from app.reports import numeric_summary
from app.schemas import strict_report_schema


def test_financial_sums_use_decimal_and_ignore_nonfinite():
    result = numeric_summary(
        [{"revenue": 0.1, "active": True}, {"revenue": 0.2, "active": False}, {"other": float("inf")}]
    )
    assert result["numeric_column_sums"] == {"revenue": "0.3"}
    assert result["row_count"] == 3


def test_structured_report_schema_rejects_extra_properties():
    schema = strict_report_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    for value in schema["$defs"].values():
        assert value["additionalProperties"] is False
