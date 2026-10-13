import json

import pytest
from jsonschema import ValidationError

from app.connectors import ConnectorRegistry, SourceNotConfigured


class RecordingConnector:
    def __init__(self):
        self.calls = []

    async def fetch(self, key, parameters):
        self.calls.append((key, parameters))
        return [{"revenue": 42}]


async def test_unconfigured_source_never_fetches():
    registry = ConnectorRegistry()
    with pytest.raises(SourceNotConfigured):
        await registry.fetch({"source_id": "missing", "enabled": 0}, {})


async def test_parameters_are_validated_before_query_dispatch():
    registry, connector = ConnectorRegistry(), RecordingConnector()
    registry.register("source", connector)
    dataset = {
        "source_id": "source",
        "enabled": 1,
        "query_key": "sales_summary",
        "parameters_schema_json": json.dumps(
            {
                "type": "object",
                "properties": {"month": {"type": "integer", "minimum": 1, "maximum": 12}},
                "required": ["month"],
                "additionalProperties": False,
            }
        ),
    }
    with pytest.raises(ValidationError):
        await registry.fetch(dataset, {"month": "DROP TABLE"})
    assert connector.calls == []
    assert await registry.fetch(dataset, {"month": 9}) == [{"revenue": 42}]
    assert connector.calls == [("sales_summary", {"month": 9})]
