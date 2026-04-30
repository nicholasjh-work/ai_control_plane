# sqlglot-based SQL safety layer enforcing SELECT-only queries on allowlisted views — Nicholas Hidalgo
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Set

import sqlglot
import sqlglot.expressions as exp

_VIEWS_PATH = Path(__file__).parent.parent / "config" / "semantic_views.json"
_ALLOWED_TABLES: Set[str] = set(json.loads(_VIEWS_PATH.read_text())["allowed_tables"])

_BLOCKED_STATEMENT_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
)


@dataclass
class ValidationResult:
    allowed: bool
    reason: str


def _check_statement(statement: exp.Expression) -> ValidationResult:
    if isinstance(statement, exp.Union):
        for side in (statement.left, statement.right):
            result = _check_statement(side)
            if not result.allowed:
                return result
        return ValidationResult(allowed=True, reason="ok")

    if isinstance(statement, _BLOCKED_STATEMENT_TYPES):
        kind = type(statement).__name__.upper()
        return ValidationResult(
            allowed=False, reason=f"{kind} statements are not allowed"
        )

    if not isinstance(statement, exp.Select):
        kind = type(statement).__name__.upper()
        return ValidationResult(
            allowed=False, reason=f"{kind} statements are not allowed"
        )

    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in _ALLOWED_TABLES:
            return ValidationResult(
                allowed=False,
                reason=f"table '{name}' is not in the allowed views list",
            )

    for subquery in statement.find_all(exp.Subquery):
        inner = subquery.this
        if inner is not None:
            result = _check_statement(inner)
            if not result.allowed:
                return result

    return ValidationResult(allowed=True, reason="ok")


def validate_query(sql: str) -> ValidationResult:
    try:
        statements = sqlglot.parse(sql.strip())
    except Exception:
        return ValidationResult(allowed=False, reason="unparseable query")

    if not statements or statements[0] is None:
        return ValidationResult(allowed=False, reason="unparseable query")

    if len(statements) > 1:
        return ValidationResult(
            allowed=False, reason="multiple statements are not allowed"
        )

    return _check_statement(statements[0])
