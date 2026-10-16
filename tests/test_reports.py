from app.reports import data_metadata
from app.schemas import strict_report_schema


def test_transport_metadata_does_not_calculate_or_interpret_numeric_columns():
    rows = [{"id": 100, "amount": "0.10", "rate": "0.2"}, {"id": 200, "amount": "0.20", "rate": "0.5"}]
    columns = [{"name": "amount", "type": "decimal"}]
    result = data_metadata(rows, columns)
    assert result["row_count"] == 2 and result["columns"] == columns
    assert set(result) == {"row_count", "row_count_meaning", "columns", "calculation_policy"}
    assert "numeric_column_sums" not in result


def test_structured_report_schema_rejects_extra_properties():
    schema = strict_report_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    for value in schema["$defs"].values():
        assert value["additionalProperties"] is False
