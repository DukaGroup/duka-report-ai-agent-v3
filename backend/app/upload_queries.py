"""Bounded structural analysis of uploaded tables; no SQL or code from the model."""

import math
import json
import operator
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadFilter(UploadInput):
    column: str = Field(max_length=100)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null", "not_null"] = "eq"
    value: str | int | float | bool | None = None
    values: list[str | int | float | bool] = Field(default_factory=list, max_length=100)

    @field_validator("value", "values")
    @classmethod
    def finite(cls, value):
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Filter numbers must be finite.")
            if isinstance(item, str) and len(item) > 1000:
                raise ValueError("Filter text is too long.")
        return value


class UploadMetric(UploadInput):
    function: Literal["sum", "count", "avg", "min", "max"]
    column: str | None = Field(default=None, max_length=100)
    alias: str = Field(min_length=1, max_length=100)


class UploadPeriod(UploadInput):
    column: str = Field(max_length=100)
    bucket: Literal["day", "month", "year"]
    alias: str = Field(default="period", min_length=1, max_length=100)


class UploadOrdering(UploadInput):
    column: str = Field(max_length=100)
    direction: Literal["asc", "desc"] = "asc"


class UploadQuery(UploadInput):
    columns: list[str] = Field(default_factory=list, max_length=100)
    filters: list[UploadFilter] = Field(default_factory=list, max_length=30)
    group_by: list[str] = Field(default_factory=list, max_length=5)
    metrics: list[UploadMetric] = Field(default_factory=list, max_length=20)
    period: UploadPeriod | None = None
    order_by: list[UploadOrdering] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=200, ge=1, le=500)


def decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def analyze_table(table, query: dict[str, Any], *, complete=False, max_rows=100000, max_bytes=50000000):
    q = UploadQuery.model_validate(query)
    types = {c["name"]: c["type"] for c in table["columns"]}
    numeric = {c for c, t in types.items() if t in ("number", "decimal", "integer")}
    referenced = q.columns + q.group_by + [f.column for f in q.filters] + [m.column for m in q.metrics if m.column]
    if q.period:
        referenced.append(q.period.column)
    allowed = set(types) | ({q.period.alias} if q.period else set())
    if set(referenced) - allowed:
        raise ValueError("An uploaded-table column is unavailable. Read its schema first.")
    source_refs = (
        [f.column for f in q.filters]
        + [m.column for m in q.metrics if m.column]
        + ([q.period.column] if q.period else [])
    )
    if set(source_refs) - types.keys():
        raise ValueError("Filters and metrics must use actual uploaded source columns.")
    for m in q.metrics:
        if m.function != "count" and (not m.column or m.column not in numeric):
            raise ValueError("Uploaded-file calculations require a numeric source column.")

    def matches(row, f):
        a, b = row.get(f.column), f.value
        if f.operator == "is_null":
            return a is None
        if f.operator == "not_null":
            return a is not None
        if a is None:
            return False
        if f.operator == "contains":
            return str(b or "").casefold() in str(a).casefold()
        if f.operator == "in":
            values = [decimal(v) for v in f.values] if f.column in numeric else f.values
            return (decimal(a) if f.column in numeric else a) in values
        if f.column in numeric:
            a, b = decimal(a), decimal(b)
            if a is None or b is None:
                raise ValueError("Numeric filters require numeric values.")
        try:
            return {
                "eq": operator.eq,
                "ne": operator.ne,
                "gt": operator.gt,
                "gte": operator.ge,
                "lt": operator.lt,
                "lte": operator.le,
            }[f.operator](a, b)
        except TypeError as exc:
            raise ValueError("Uploaded-file filter types do not match.") from exc

    rows = [dict(r) for r in table["rows"] if all(matches(r, f) for f in q.filters)]
    if q.period:
        if q.period.alias in types:
            raise ValueError("Period alias must not replace a source column.")
        for r in rows:
            value = r.get(q.period.column)
            try:
                d = datetime.fromisoformat(str(value)) if value is not None else None
            except ValueError as exc:
                raise ValueError("Period grouping requires ISO date values.") from exc
            r[q.period.alias] = (
                d.strftime({"day": "%Y-%m-%d", "month": "%Y-%m-01", "year": "%Y-01-01"}[q.period.bucket]) if d else None
            )
        types[q.period.alias] = "date"
    groups = q.group_by + ([q.period.alias] if q.period and q.period.alias not in q.group_by else [])
    if q.group_by and not q.metrics:
        raise ValueError("Grouping requires aggregate metrics.")
    if q.metrics:
        fields = groups + [m.alias for m in q.metrics]
        if len({f.casefold() for f in fields}) != len(fields):
            raise ValueError("Result column labels must be unique.")
        grouped = defaultdict(list)
        for row in rows:
            grouped[tuple(row.get(c) for c in groups)].append(row)
        if not groups and not rows:
            grouped[()] = []
        result = []
        with localcontext() as ctx:
            ctx.prec = 50
            for key, population in grouped.items():
                r = dict(zip(groups, key))
                for m in q.metrics:
                    values = [decimal(p.get(m.column)) for p in population] if m.column else []
                    values = [v for v in values if v is not None]
                    if m.function == "count":
                        value = sum(p.get(m.column) is not None for p in population) if m.column else len(population)
                    elif not values:
                        value = None
                    else:
                        value = {
                            "sum": lambda: sum(values),
                            "avg": lambda: sum(values) / len(values),
                            "min": lambda: min(values),
                            "max": lambda: max(values),
                        }[m.function]()
                    r[m.alias] = str(value) if isinstance(value, Decimal) else value
                result.append(r)
        columns = [{"name": f, "type": types[f]} for f in groups] + [
            {"name": m.alias, "type": "integer" if m.function == "count" else "decimal"} for m in q.metrics
        ]
    else:
        fields = q.columns or list(types)
        result = [{f: r.get(f) for f in fields} for r in rows]
        columns = [{"name": f, "type": types[f]} for f in fields]
    for ordering in reversed(q.order_by):
        if ordering.column not in fields:
            raise ValueError("Ordering must use a result column.")
        is_numeric = next(c["type"] for c in columns if c["name"] == ordering.column) in (
            "decimal",
            "number",
            "integer",
        )
        result.sort(
            key=lambda r: (
                r[ordering.column] is None,
                decimal(r[ordering.column])
                if is_numeric and r[ordering.column] is not None
                else str(r[ordering.column] or ""),
            ),
            reverse=ordering.direction == "desc",
        )
    if complete:
        if len(result) > max_rows or len(json.dumps(result, allow_nan=False).encode()) > max_bytes:
            raise ValueError(
                "The complete report exceeds the configured export limits. Ask an administrator to increase them; no partial report was generated."
            )
        bounded, truncated = result, False
    else:
        truncated = len(result) > q.limit or len(json.dumps(result[: q.limit]).encode()) > 100000
        bounded = result[: q.limit]
        while len(json.dumps(bounded).encode()) > 100000:
            bounded.pop()
    return {
        "rows": bounded,
        "columns": columns,
        "truncated": truncated,
        "result_rows": len(result),
        "matched_source_rows": len(rows),
        "query": q.model_dump(),
        "scope": f"{len(rows)} matching rows from the uploaded table; {len(table['rows'])} source rows.",
    }
