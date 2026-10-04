"""Static safety checks for LLM-generated SQL (spec: SQL safety).

validate_sql returns a list of human-readable errors; an empty list means the SQL may run.
The errors are fed back to the LLM so it can repair its query.
See docs/SQLValidator using SQLGlot.md for a walkthrough.
"""
from collections import deque

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from agent.schema import COLUMNS, CONTRACT_KEYS, FOREIGN_KEYS, TABLE_NAMES
from governance.policy import load_policy

ALLOWED_TABLES = TABLE_NAMES
BLOCKED_COLUMNS = load_policy().restricted_column_names
ALLOWED_PARAMS = {"contract_id", "as_of_date"}
BLOCKED_FUNCTIONS = {"openrowset", "openquery", "opendatasource", "openxml"}
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create,
    exp.Alter, exp.Command, exp.Into, exp.TruncateTable,
)


def used_params(sql: str) -> set[str]:
    """Names of the :placeholders in a statement (empty if it does not parse)."""
    try:
        tree = sqlglot.parse_one(sql, read="tsql")
    except sqlglot.errors.ParseError:
        return set()
    return {p.name for p in tree.find_all(exp.Placeholder)}


def validate_sql(sql: str) -> list[str]:
    if not sql or not sql.strip():
        return ["The query is empty."]
    try:
        statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
    except sqlglot.errors.ParseError as err:
        return [f"The query does not parse as T-SQL: {err}"]

    if len(statements) != 1:
        return ["Exactly one statement is allowed; do not chain statements with ';'."]
    tree = statements[0]

    errors: list[str] = []
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        errors.append("Only SELECT queries are allowed.")
    for node in tree.find_all(*FORBIDDEN_NODES):
        errors.append(f"{node.key.upper()} is not allowed; the query must be a plain SELECT.")
        break

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if table.catalog or (table.db and table.db.lower() != "dbo"):
            errors.append(f"Table {table.sql('tsql')} is outside dbo; only dbo tables are allowed.")
        elif name not in ALLOWED_TABLES:
            errors.append(f"Table '{table.name}' is not in the allowed schema.")

    for column in tree.find_all(exp.Column):
        if column.name.lower() in BLOCKED_COLUMNS:
            errors.append(f"Column '{column.name}' is restricted and may never be selected.")
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            errors.append("SELECT * is not allowed; list the columns you need.")
            break

    for func in tree.find_all(exp.Anonymous):
        if str(func.name).lower() in BLOCKED_FUNCTIONS:
            errors.append(f"Function {func.name} is not allowed.")
    if tree.find(exp.Or):
        errors.append("OR is not allowed (it can widen the contract filter); use IN (...) instead.")

    params = {p.name for p in tree.find_all(exp.Placeholder)}
    unknown = params - ALLOWED_PARAMS
    if unknown:
        errors.append(f"Unknown parameters {sorted(unknown)}; only :contract_id and :as_of_date exist.")

    if not errors:                      # scope analysis needs a structurally sound query
        errors += _contract_scope_errors(tree)
    return errors


# --- contract scoping ----------------------------------------------------------------
#
# Every SELECT (each UNION branch, subquery and CTE body separately) that reads a table must:
#   1. compare a contract key column (Contracts.Id, LeaseFinances.ContractId,
#      LoanFinances.ContractId or Receivables.EntityId) with :contract_id using '=' in its own
#      WHERE / JOIN ... ON, not under NOT;
#   2. reach every other table it reads through foreign-key joins from that anchor;
#   3. filter any Receivables it reads with EntityType = 'CT'.
# Anything else could return rows, and PII, belonging to other contracts.

def _contract_scope_errors(tree: exp.Expression) -> list[str]:
    try:
        scopes = traverse_scope(tree)
    except Exception as err:
        return [f"Could not analyse the query structure ({err}); simplify the query."]

    errors: list[str] = []
    for scope in scopes:
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue
        tables = {alias.lower(): source.name.lower()
                  for alias, source in scope.sources.items() if isinstance(source, exp.Table)}
        if not tables:
            continue                    # reads only CTEs/subqueries, which are checked as scopes

        anchors: set[str] = set()
        ct_filtered: set[str] = set()
        edges: list[tuple[str, str]] = []
        for eq in _own_equalities(select):
            for col, other in ((eq.this, eq.expression), (eq.expression, eq.this)):
                if not isinstance(col, exp.Column):
                    continue
                ref = _resolve(col, tables)
                if ref is None:
                    continue
                alias, table, column = ref
                if isinstance(other, exp.Placeholder) and other.name == "contract_id" \
                        and (table, column) in CONTRACT_KEYS:
                    anchors.add(alias)
                if isinstance(other, exp.Literal) and other.is_string and other.this.upper() == "CT" \
                        and (table, column) == ("receivables", "entitytype"):
                    ct_filtered.add(alias)
            if isinstance(eq.this, exp.Column) and isinstance(eq.expression, exp.Column):
                left, right = _resolve(eq.this, tables), _resolve(eq.expression, tables)
                if left and right and frozenset({left[1:], right[1:]}) in FOREIGN_KEYS:
                    edges.append((left[0], right[0]))

        read = ", ".join(sorted(set(tables.values())))
        if {a for a, t in tables.items() if t == "receivables"} - ct_filtered:
            errors.append("Receivables must be filtered with EntityType = 'CT'.")
        if not anchors:
            errors.append(
                f"The SELECT reading {read} is not limited to the current contract. Add a filter like "
                "Contracts.Id = :contract_id, LeaseFinances.ContractId = :contract_id, "
                "LoanFinances.ContractId = :contract_id or Receivables.EntityId = :contract_id "
                "(qualify columns with table aliases).")
            continue
        unreached = set(tables) - _reachable(anchors, edges)
        if unreached:
            names = ", ".join(sorted({tables[a] for a in unreached}))
            errors.append(
                f"Table(s) {names} are not joined to the contract through key relationships "
                "(e.g. LeaseFinances.CustomerId = Customers.Id, ReceivableDetails.ReceivableId = Receivables.Id).")
    return errors


def _own_equalities(select: exp.Select):
    """'=' predicates in this SELECT's own WHERE and JOIN ... ON (not nested queries, not under NOT)."""
    clauses = [select.args.get("where")] + [join.args.get("on") for join in select.args.get("joins") or []]
    for clause in filter(None, clauses):
        for eq in clause.find_all(exp.EQ):
            if eq.find_ancestor(exp.Select) is not select:
                continue
            node, negated = eq.parent, False
            while node is not None and node is not clause:
                if isinstance(node, exp.Not):
                    negated = True
                    break
                node = node.parent
            if not negated:
                yield eq


def _resolve(column: exp.Column, tables: dict[str, str]) -> tuple[str, str, str] | None:
    """(alias, table, column) for a column reference, or None if it cannot be pinned down."""
    name = column.name.lower()
    if column.table:
        alias = column.table.lower()
        return (alias, tables[alias], name) if alias in tables else None
    owners = [alias for alias, table in tables.items() if name in COLUMNS.get(table, set())]
    return (owners[0], tables[owners[0]], name) if len(owners) == 1 else None


def _reachable(anchors: set[str], edges: list[tuple[str, str]]) -> set[str]:
    seen, queue = set(anchors), deque(anchors)
    while queue:
        current = queue.popleft()
        for a, b in edges:
            for nxt in ((b,) if a == current else ()) + ((a,) if b == current else ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return seen
