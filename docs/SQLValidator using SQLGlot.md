# SQLValidator using SQLGlot

How `agent/validator.py` uses [SQLGlot](https://github.com/tobymao/sqlglot) to decide whether SQL written by the LLM
is safe to run against the contract database.

## Where it sits in the agent

Only ad-hoc questions use LLM-written SQL; the four core questions use vetted templates and skip validation.

```
classify_intent --adhoc--> generate_sql --> validate_sql --valid--> execute_sql
                                ^               |
                                +----retry------+   (errors fed back to the LLM, max 2 retries, then give_up)
```

`validate_sql(sql) -> list[str]` returns human-readable errors. An empty list means the query may run. A non-empty
list goes back into the `generate_sql` prompt so the LLM can repair its own query.

It is one of three layers. The others are the read-only `agent_ro` login (no writes, `Customers.SSN` denied) and
the runtime limits in `agent/db.py` (5-second timeout, 200-row cap).

## Why SQLGlot instead of regex

SQLGlot is a pure-Python SQL parser. It turns a query into an **abstract syntax tree (AST)** of typed nodes, so the
validator inspects structure rather than text. Formatting, casing, comments and aliases cannot hide a table or column
from it, and the same keyword in a string literal is not mistaken for a command.

`read="tsql"` selects the SQL Server dialect, so `TOP n`, `[bracketed]` names and T-SQL functions parse correctly.

```python
import sqlglot
tree = sqlglot.parse_one("SELECT Status FROM dbo.Contracts WHERE Id = :contract_id", read="tsql")
print(repr(tree))
```

```
Select(
  expressions=[Column(this=Identifier(this=Status))],
  from_=From(this=Table(this=Identifier(this=Contracts), db=Identifier(this=dbo))),
  where=Where(this=EQ(this=Column(this=Identifier(this=Id)),
                      expression=Placeholder(this=contract_id))))
```

Every check in the validator is a question asked of this tree.

## SQLGlot API used

| API | What it does | Used for |
| --- | --- | --- |
| `sqlglot.parse(sql, read="tsql")` | Parses all statements; returns a list | Counting statements |
| `sqlglot.parse_one(sql, read="tsql")` | Parses a single statement | `used_params()` |
| `sqlglot.errors.ParseError` | Raised on invalid SQL | Reporting unparseable queries |
| `tree.find_all(NodeType, ...)` | Yields every node of the given types, at any depth | Tables, columns, stars, placeholders, forbidden nodes |
| `tree.find(NodeType)` | First match or `None` | Detecting `OR` |
| `node.parent` | The node's parent in the tree | `COUNT(*)` exception; `= :contract_id` check |
| `exp.Table` `.catalog` / `.db` / `.name` | Database / schema / table parts of a name | Allow-listing `dbo` tables |
| `exp.CTE.alias_or_name` | Name defined in a `WITH` clause | Exempting CTE names from the table allow-list |
| `exp.Placeholder.name` | Name of a `:param` | Parameter checks |
| `node.key` | Lower-case node type name, e.g. `into` | Error messages |

Node classes checked: `exp.Select`, `exp.SetOperation` (UNION / INTERSECT / EXCEPT), `exp.Insert`, `exp.Update`,
`exp.Delete`, `exp.Merge`, `exp.Drop`, `exp.Create`, `exp.Alter`, `exp.Command`, `exp.Into`, `exp.TruncateTable`,
`exp.Table`, `exp.Column`, `exp.Star`, `exp.Count`, `exp.Anonymous`, `exp.Or`, `exp.EQ`, `exp.Placeholder`.

## The checks

All checks run and their errors are collected, so the LLM can fix everything in one retry. Only a parse failure or a
wrong statement count returns early, because there is no single tree to inspect.

### 1. Not empty, and parses as T-SQL

```python
statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
# ParseError -> "The query does not parse as T-SQL: ..."
```

### 2. Exactly one statement

```python
if len(statements) != 1:
    return ["Exactly one statement is allowed; do not chain statements with ';'."]
```

Rejects `SELECT ... ; DROP TABLE dbo.Contracts`. SQLGlot returns one tree per statement, so a chained statement
cannot hide behind a harmless one.

### 3. The top level is a query

```python
if not isinstance(tree, (exp.Select, exp.SetOperation)):
    errors.append("Only SELECT queries are allowed.")
```

`UPDATE` parses to `exp.Update` and `EXEC xp_cmdshell 'dir'` to `exp.Execute`, so both fail here.

### 4. No forbidden nodes anywhere

```python
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create,
                   exp.Alter, exp.Command, exp.Into, exp.TruncateTable)
for node in tree.find_all(*FORBIDDEN_NODES): ...
```

Check 3 only looks at the root; this searches the whole tree. Its main catch is `SELECT ... INTO dbo.Stolen`, which
is a SELECT at the root but creates a table (`exp.Into`).

### 5. Only the eight allowed `dbo` tables

```python
cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
for table in tree.find_all(exp.Table):
    if table.name.lower() in cte_names: continue          # WITH-clause names are not real tables
    if table.catalog or (table.db and table.db.lower() != "dbo"): ...   # other database or schema
    elif table.name.lower() not in ALLOWED_TABLES: ...
```

| Query references | `catalog` | `db` | Result |
| --- | --- | --- | --- |
| `dbo.Contracts` | `''` | `dbo` | allowed |
| `Contracts` | `''` | `''` | allowed |
| `sys.tables` | `''` | `sys` | rejected: outside dbo |
| `OtherDb.dbo.Contracts` | `OtherDb` | `dbo` | rejected: outside dbo |
| `dbo.Users` | `''` | `dbo` | rejected: not in the allowed schema |

Because `find_all` walks the whole tree, tables inside subqueries, joins and CTE bodies are all checked.

### 6. No restricted columns

```python
for column in tree.find_all(exp.Column):
    if column.name.lower() in BLOCKED_COLUMNS: ...       # {"ssn"}, from restricted_columns in governance/policy.yaml
```

`cu.SSN`, `[SSN]` and `Customers.ssn` all parse to a `Column` named `SSN`. The database also denies the column to
`agent_ro`, so this is a defence in depth.

### 7. No `SELECT *`, except `COUNT(*)`

```python
for star in tree.find_all(exp.Star):
    if not isinstance(star.parent, exp.Count): ...
```

`*` would return every column of `Customers`, including SSN. In `COUNT(*)` the star's parent is a `Count` node, so
it is allowed.

### 8. No external-data functions

```python
BLOCKED_FUNCTIONS = {"openrowset", "openquery", "opendatasource", "openxml"}
for func in tree.find_all(exp.Anonymous): ...
```

SQLGlot represents functions it has no dedicated class for as `exp.Anonymous`; these four reach other servers or files.

### 9. No `OR`

```python
if tree.find(exp.Or): ...
```

`WHERE Id = :contract_id OR 1 = 1` is the classic way to widen a filter. The error message suggests `IN (...)`, which
covers the legitimate uses.

### 10. Only known parameters

```python
params = {p.name for p in tree.find_all(exp.Placeholder)}
unknown = params - {"contract_id", "as_of_date"}
```

Only these two values are ever bound; any other `:name` would fail at execution.

### 11. Scoped to the current contract (per SELECT scope)

Runs only when checks 1–10 pass. This check matters most for PII: a query that escapes the contract could read
*other* customers' names and emails, which the session vault does not know about and so could not mask.

SQLGlot's optimizer splits the query into **scopes**: one per SELECT, so each UNION branch, subquery and CTE body is
analysed on its own.

```python
from sqlglot.optimizer.scope import traverse_scope

for scope in traverse_scope(tree):
    tables = {alias: source.name for alias, source in scope.sources.items() if isinstance(source, exp.Table)}
    ...
```

`scope.sources` maps each alias in the scope's FROM/JOIN to either an `exp.Table` (a real table) or another scope (a
CTE or derived table, which is checked separately). For every scope that reads a real table:

1. **Anchor.** Its own WHERE or JOIN ... ON must contain `<contract key> = :contract_id`. The contract keys are
   `Contracts.Id`, `LeaseFinances.ContractId`, `LoanFinances.ContractId` and `Receivables.EntityId` (`agent/schema.py`).
   The left side must be a real `exp.Column` resolved to one of those, so `:contract_id = :contract_id` or
   `Customers.Id = :contract_id` do not count.
2. **Own predicates only.** An `=` counts only if its nearest `exp.Select` ancestor is this scope's SELECT
   (`eq.find_ancestor(exp.Select) is select`) and it is not under `exp.Not`. A filter inside an `EXISTS` subquery
   does not scope the outer query.
3. **Foreign-key joins.** Every other table in the scope must be reachable from the anchor through `=` joins listed
   in `FOREIGN_KEYS`, for example `LeaseFinances.CustomerId = Customers.Id`. A comma join or `ON cu.Id = c.Id` does
   not connect.
4. **Receivables** also need `EntityType = 'CT'`, otherwise sundry receivables with the same EntityId would be included.

Column references resolve through the scope's aliases. An unqualified column resolves only if exactly one table in the
scope has it; otherwise it cannot anchor, and the error asks the LLM to qualify columns.

## `used_params(sql)`

```python
def used_params(sql: str) -> set[str]:
    tree = sqlglot.parse_one(sql, read="tsql")
    return {p.name for p in tree.find_all(exp.Placeholder)}
```

`execute_sql` binds only the parameters the query uses, so extra parameters are never passed to the driver.

## Queries check 11 rejects

The first version of this check only confirmed that `= :contract_id` appeared somewhere. All of these passed it and
would have returned other contracts' data. All are now rejected, and each is a test case:

```sql
-- parameter compared with itself
SELECT SequenceNumber FROM dbo.Contracts WHERE :contract_id = :contract_id
-- filter inside a subquery; outer query unfiltered
SELECT SequenceNumber FROM dbo.Contracts WHERE EXISTS (SELECT 1 FROM dbo.Contracts c WHERE c.Id = :contract_id)
-- only one half of the UNION is filtered
SELECT SequenceNumber FROM dbo.Contracts WHERE Id = :contract_id UNION SELECT SequenceNumber FROM dbo.Contracts
-- contract id used as a customer id: returns an unrelated customer
SELECT FirstName FROM dbo.Customers WHERE Id = :contract_id
-- cross join, and a join on the wrong keys
SELECT cu.FirstName FROM dbo.Contracts c, dbo.Customers cu WHERE c.Id = :contract_id
SELECT cu.FirstName FROM dbo.Contracts c JOIN dbo.Customers cu ON cu.Id = c.Id WHERE c.Id = :contract_id
-- negated filter
SELECT c.SequenceNumber FROM dbo.Contracts c WHERE NOT (c.Id = :contract_id)
-- unscoped CTE
WITH x AS (SELECT cu.Email FROM dbo.Customers cu) SELECT x.Email FROM x
```

The check fails closed: when a query is too unusual to analyse, it is rejected and the LLM is asked to simplify it.
A database-side control (contract-scoped views or row-level security) would add an independent layer.

## Related: SQLGlot lineage for PII masking

`governance/lineage.py` uses `sqlglot.lineage.lineage()` on the same queries to trace each output column back to its
source columns, so `cu.FirstName + ' ' + cu.LastName AS CustomerName` is classified as `PERSON` and masked before any
LLM sees it.

## Tests

`tests/test_validator.py`:

- `test_vetted_queries_pass`: every core template and every few-shot example in the prompt must pass, so the prompt
  never teaches the LLM a query the validator would reject.
- `test_unsafe_queries_rejected`: 26 unsafe queries, including the scoping cases above, each with the expected error text.
- `test_properly_scoped_queries_pass`: UNION over both finance tables, scoped CTEs, key joins.
- `test_count_star_allowed`, `test_used_params`, `test_restricted_columns_come_from_policy`.

```powershell
.\.venv\Scripts\python -m pytest tests\test_validator.py
```

## Extending the validator

| Change | Where |
| --- | --- |
| Allow a new table | Add it to `TABLES` (and its keys to `FOREIGN_KEYS`) in `agent/schema.py`, and to the schema card in `agent/prompts.py` |
| Block another column | Add it to `restricted_columns` in `governance/policy.yaml`; also `DENY SELECT` it to `agent_ro` |
| Allow a new parameter | Add it to `ALLOWED_PARAMS` and to `_bind_params()` in `agent/nodes.py` |
| Add a rule | Append to `errors` with a message that tells the LLM how to fix the query, then add a rejection test |
