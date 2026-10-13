from typing import Any, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from .database_tools import DatabaseQuery


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(InputModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if "@" not in value or " " in value:
            raise ValueError("Enter a valid email address.")
        return value


class CreateUser(Credentials):
    name: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "member"] = "member"

    @field_validator("password")
    @classmethod
    def password_strength(cls, value):
        if len(value) < 12:
            raise ValueError("Use a password with at least 12 characters.")
        return value


class UpdateUser(InputModel):
    active: bool


class NewConversation(InputModel):
    title: str = Field(default="Bisedë e re", min_length=1, max_length=150)
    model: str | None = Field(default=None, max_length=100)


class ChatMessage(InputModel):
    content: str = Field(min_length=1, max_length=24000)
    model: str | None = Field(default=None, max_length=100)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank.")
        return value


class NewSource(InputModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["postgresql", "mysql", "sqlserver", "sqlite", "other"]
    description: str = Field(default="", max_length=1000)
    SQLSERVER_HOST: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    SQLSERVER_PORT: int | None = Field(default=None, ge=1, le=65535, repr=False)
    SQLSERVER_USER: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    SQLSERVER_PASSWORD: SecretStr | None = Field(default=None, max_length=1024, repr=False)
    SQLSERVER_DATABASE: str | None = Field(default=None, min_length=1, max_length=128, repr=False)

    @field_validator("SQLSERVER_HOST", "SQLSERVER_USER", "SQLSERVER_DATABASE")
    @classmethod
    def connection_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Connection fields cannot contain only spaces.")
        return value.strip() if value is not None else None

    def connection_settings(self):
        values = {}
        for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE"):
            value = getattr(self, f"SQLSERVER_{name}")
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if value is not None and value != "":
                values[f"SQLSERVER_{name}"] = str(value)
        return values


class NewDataset(InputModel):
    source_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    query_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    columns_schema: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class AnalysisOptions(InputModel):
    name: str = Field(default="Report data", min_length=1, max_length=80)
    kind: Literal["data", "trend", "breakdown", "comparison"] = "data"
    dimension: str | None = Field(default=None, max_length=100)
    measures: list[str] = Field(default_factory=list, max_length=12)
    revenue_column: str | None = Field(default=None, max_length=100)
    cost_column: str | None = Field(default=None, max_length=100)


class ReportAnalysis(AnalysisOptions):
    query: DatabaseQuery
    required: bool = False


class ReportRequest(InputModel):
    title: str = Field(min_length=1, max_length=150)
    template_id: str = "executive"
    instructions: str = Field(default="", max_length=6000)
    conversation_id: str | None = None
    dataset_id: str | None = None
    source_id: str | None = None
    query: DatabaseQuery | None = None
    analysis: AnalysisOptions = Field(default_factory=AnalysisOptions)
    analyses: list[ReportAnalysis] = Field(default_factory=list, max_length=8)
    rows: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=dict)
    model: str | None = Field(default=None, max_length=100)

    @field_validator("rows")
    @classmethod
    def scalar_rows(cls, rows):
        if rows is None:
            return rows
        for row in rows:
            if len(row) > 100:
                raise ValueError("Each row can contain at most 100 columns.")
            for key, value in row.items():
                if len(key) > 100 or not isinstance(value, (str, int, float, bool, type(None))):
                    raise ValueError(
                        "Rows must use short column names and scalar values (text, numbers, booleans, or null)."
                    )
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Numbers must be finite.")
        return rows


class ReportSection(InputModel):
    heading: str
    body: str


class ReportMetric(InputModel):
    label: str
    value: str
    explanation: str


class ReportDocument(InputModel):
    title: str
    summary: str
    sections: list[ReportSection]
    metrics: list[ReportMetric]
    limitations: list[str]


def strict_report_schema():
    schema = ReportDocument.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema
