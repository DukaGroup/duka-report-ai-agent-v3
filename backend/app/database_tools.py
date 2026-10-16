"""Schema discovery and structural SELECT planning. No arbitrary SQL from the model."""

from typing import Annotated, Literal
import math

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def output_label(value):
    value = value.strip()
    if not value:
        raise ValueError("A result column label cannot be blank.")
    return value


# Result labels are display names, not SQL expressions. They are always bracket-quoted.
OutputLabel = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"), AfterValidator(output_label)
]


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Table(QueryInput):
    schema_name: str = Field(alias="schema", default="dbo", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    alias: str = Field(default="t", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,29}$")


class Selection(QueryInput):
    column: str = Field(min_length=1, max_length=160)
    alias: OutputLabel | None = None
    bucket: Literal["day", "month", "year"] | None = None


class Metric(QueryInput):
    function: Literal["sum", "avg", "min", "max", "count", "count_distinct"]
    column: str | None = Field(default=None, max_length=160)
    alias: OutputLabel


class Join(QueryInput):
    left: str = Field(max_length=160)
    right: str = Field(max_length=160)
    kind: Literal["inner", "left"] = "inner"


class Filter(QueryInput):
    column: str = Field(max_length=160)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "like", "in", "is_null", "not_null"]
    value: str | int | float | bool | None = None
    values: list[str | int | float | bool] = Field(default_factory=list, max_length=100)

    @field_validator("value", "values")
    @classmethod
    def bounded_values(cls, value):
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and len(item) > 1000:
                raise ValueError("Filter values must be at most 1000 characters.")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Filter numbers must be finite.")
        return value


class Ordering(QueryInput):
    column: str = Field(max_length=160)
    direction: Literal["asc", "desc"] = "asc"


class DatabaseQuery(QueryInput):
    tables: list[Table] = Field(min_length=1, max_length=4)
    select: list[Selection] = Field(default_factory=list, max_length=60)
    metrics: list[Metric] = Field(default_factory=list, max_length=20)
    joins: list[Join] = Field(default_factory=list, max_length=3)
    filters: list[Filter] = Field(default_factory=list, max_length=30)
    group_by: list[str] = Field(default_factory=list, max_length=20)
    order_by: list[Ordering] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=100, ge=1, le=500)


def quote(name):
    return "[" + name.replace("]", "]]") + "]"


def compile_select(query: DatabaseQuery, descriptions, *, complete=False, dialect="sqlserver"):
    """Compile only metadata-verified identifiers and bound scalar filter values."""
    if dialect not in ("sqlserver", "hana"):
        raise ValueError("Unsupported database dialect.")
    def quoted(name):
        return '"' + name.replace('"', '""') + '"' if dialect == "hana" else quote(name)

    def placeholder(key):
        return "?" if dialect == "hana" else f"%({key})s"

    tables = {t.alias: t for t in query.tables}
    if len(tables) != len(query.tables):
        raise ValueError("Table aliases must be unique.")
    if len(query.joins) != len(query.tables) - 1:
        raise ValueError("Each additional table requires one join.")
    metadata = {alias: {c["name"]: c for c in descriptions[alias]["columns"]} for alias in tables}

    def column(ref):
        alias, separator, name = ref.partition(".")
        if not separator or alias not in metadata or name not in metadata[alias]:
            raise ValueError("Unknown column. Use alias.column from describe_table results.")
        return f"{quoted(alias)}.{quoted(name)}", metadata[alias][name]

    output, columns, labels, folded_labels = [], [], set(), set()
    selections = query.select
    if not selections and not query.metrics:
        alias = query.tables[0].alias
        selections = [Selection(column=f"{alias}.{name}") for name in list(metadata[alias])[:60]]
    selection_sql = {}
    for item in selections:
        sql, info = column(item.column)
        if item.bucket:
            if info["type"] not in ("date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"):
                raise ValueError("Date buckets require a date/time column.")
            sql = (
                f"CAST({sql} AS date)"
                if item.bucket == "day"
                else f"DATEFROMPARTS(YEAR({sql}), {'MONTH(' + sql + ')' if item.bucket == 'month' else '1'}, 1)"
            )
            if dialect == "hana":
                original, _ = column(item.column)
                sql = (f"CAST({original} AS DATE)" if item.bucket == "day" else
                       f"TO_DATE(TO_NVARCHAR({original}, 'YYYY-MM') || '-01', 'YYYY-MM-DD')" if item.bucket == "month" else
                       f"TO_DATE(TO_NVARCHAR(YEAR({original})) || '-01-01', 'YYYY-MM-DD')")
        selection_sql[item.alias or info["name"]] = sql

    def group_column(ref):
        return selection_sql[ref] if ref in selection_sql else column(ref)[0]

    grouped = {group_column(ref) for ref in query.group_by}

    def add(sql, name, kind):
        if name.casefold() in folded_labels or len(name) > 100:
            raise ValueError("Result column names must be unique and at most 100 characters; use aliases.")
        labels.add(name)
        folded_labels.add(name.casefold())
        output.append(f"{sql} AS {quoted(name)}")
        columns.append({"name": name, "type": kind})

    for item in selections:
        _, info = column(item.column)
        sql = selection_sql[item.alias or info["name"]]
        if (query.metrics or grouped) and sql not in grouped:
            raise ValueError("Selected non-aggregate columns must be included in group_by.")
        add(sql, item.alias or info["name"], "date" if item.bucket else info["type"])
    for item in query.metrics:
        if item.column:
            sql, info = column(item.column)
        elif item.function == "count":
            sql, info = "*", {"type": "integer"}
        else:
            raise ValueError("This aggregate needs a column.")
        numeric = {"int", "bigint", "smallint", "tinyint", "float", "real", "decimal", "numeric", "money", "smallmoney"}
        if item.function in ("sum", "avg") and info["type"] not in numeric:
            raise ValueError("SUM and AVG require a numeric column.")
        function = ("COUNT" if dialect == "hana" else "COUNT_BIG") if item.function in ("count", "count_distinct") else item.function.upper()
        expression = "DISTINCT " + sql if item.function == "count_distinct" else sql
        add(
            f"{function}({expression})",
            item.alias,
            "integer" if item.function in ("count", "count_distinct") else "decimal" if item.function in ("sum", "avg") else info["type"],
        )
    if not output:
        raise ValueError("Choose columns or aggregates to read.")

    first = query.tables[0]
    from_sql = f"{quoted(first.schema_name)}.{quoted(first.name)} AS {quoted(first.alias)}"
    seen = {first.alias}
    for table, join in zip(query.tables[1:], query.joins):
        left, _ = column(join.left)
        right, _ = column(join.right)
        a, b = join.left.partition(".")[0], join.right.partition(".")[0]
        if not ((a in seen and b == table.alias) or (b in seen and a == table.alias)):
            raise ValueError("Each join must connect the new table to a previous table.")
        from_sql += f" {join.kind.upper()} JOIN {quoted(table.schema_name)}.{quoted(table.name)} AS {quoted(table.alias)} ON {left} = {right}"
        seen.add(table.alias)
    params, predicates = {}, []
    for index, condition in enumerate(query.filters):
        sql, _ = column(condition.column)
        key = f"f{index}"
        if condition.operator in ("is_null", "not_null"):
            predicates.append(f"{sql} IS {'NOT ' if condition.operator == 'not_null' else ''}NULL")
        elif condition.operator == "in":
            if not condition.values:
                raise ValueError("IN requires at least one value.")
            keys = [f"{key}_{i}" for i in range(len(condition.values))]
            params.update(zip(keys, condition.values))
            predicates.append(f"{sql} IN ({', '.join(placeholder(k) for k in keys)})")
        elif condition.value is None:
            if condition.operator not in ("eq", "ne"):
                raise ValueError("Use is_null/not_null to filter NULL values.")
            predicates.append(f"{sql} IS {'NOT ' if condition.operator == 'ne' else ''}NULL")
        else:
            operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "like": "LIKE"}[
                condition.operator
            ]
            params[key] = condition.value
            predicates.append(f"{sql} {operator} {placeholder(key)}")
    # Fetch one extra row to detect limited results, never present previews as complete data.
    prefix = "SELECT" if complete or dialect == "hana" else f"SELECT TOP ({query.limit + 1})"
    sql = f"{prefix} {', '.join(output)} FROM {from_sql}"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if grouped:
        sql += " GROUP BY " + ", ".join(group_column(ref) for ref in query.group_by)
    ordering = []
    for item in query.order_by:
        ref = quoted(item.column) if item.column in labels else column(item.column)[0]
        if (query.metrics or grouped) and item.column not in labels and ref not in grouped:
            raise ValueError("Sort grouped results by a group column or metric alias.")
        ordering.append(f"{ref} {item.direction.upper()}")
    if ordering:
        sql += " ORDER BY " + ", ".join(ordering)
    if dialect == "hana" and not complete:
        sql += f" LIMIT {query.limit + 1}"
    return sql, params, columns
