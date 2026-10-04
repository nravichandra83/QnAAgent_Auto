"""Classify query output columns by tracing them back to source columns (sqlglot lineage).

    SELECT cu.FirstName + ' ' + cu.LastName AS CustomerName ...  ->  {"CustomerName": "PERSON"}

Works through aliases, expressions, subqueries and CTEs, so masking does not depend on the
LLM keeping original column names.
"""
import logging

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage

from agent.schema import lineage_schema
from governance.policy import Policy

log = logging.getLogger(__name__)
_SCHEMA = lineage_schema()


def classify_output_columns(sql: str, policy: Policy) -> dict[str, str] | None:
    """Output column name -> entity type, for columns derived from classified source columns.
    Returns None if lineage cannot be computed; callers then rely on value scanning only."""
    try:
        tree = sqlglot.parse_one(sql, read="tsql")
        if not isinstance(tree, exp.Query):
            return None                             # unknown shape: classification unknown, not "no PII"
        result: dict[str, str] = {}
        for projection in tree.selects:
            name = projection.alias_or_name
            if not name:
                continue
            node = lineage(name, tree, schema=_SCHEMA, dialect="tsql")
            types = []
            for leaf in node.walk():
                if leaf.downstream or not isinstance(leaf.source, exp.Table):
                    continue
                table = leaf.source.name.lower()
                column = leaf.name.split(".")[-1].lower()
                entity = policy.columns.get((table, column))
                if entity:
                    types.append(entity)
            if types:
                # A restricted type wins (e.g. SSN mixed into an expression)
                restricted = [t for t in types if not policy.reveal.get(t, False)]
                result[name] = (restricted or types)[0]
        return result
    except Exception as err:  # lineage is best effort; masking falls back to value scanning
        log.warning("Lineage failed, falling back to value scanning: %s", err)
        return None
