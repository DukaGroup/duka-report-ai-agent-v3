from typing import Any, Literal
import math
import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from .database_tools import DatabaseQuery
from .upload_queries import UploadQuery
from .balance_reconciliation import BalanceRequest


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


class DatabaseAccessGrant(InputModel):
    source_id: str = Field(min_length=1, max_length=100)
    database: str = Field(min_length=1, max_length=128)
    all_companies: bool = True
    company_ids: list[str] = Field(default_factory=list, max_length=5000)


class MemberDataAccess(InputModel):
    databases: list[DatabaseAccessGrant] = Field(default_factory=list, max_length=1000)
    preserve_legacy_source_ids: list[str] = Field(default_factory=list, max_length=100)


class CreateUser(Credentials):
    database_access: MemberDataAccess | None = None
    name: str = Field(min_length=1, max_length=100)
    role: Literal["devs", "president", "manager"] = "manager"

    @field_validator("password")
    @classmethod
    def password_strength(cls, value):
        if len(value) < 12:
            raise ValueError("Use a password with at least 12 characters.")
        return value


class UpdateUser(InputModel):
    active: bool


class UpdateAccount(InputModel):
    database_access: MemberDataAccess | None = None
    active: bool | None = None
    role: Literal["devs", "president", "manager"] | None = None


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class NewConversation(InputModel):
    reasoning_effort: ReasoningEffort | None = None
    title: str = Field(default="Bisedë e re", min_length=1, max_length=150)
    model: str | None = Field(default=None, max_length=100)


class ChatStop(InputModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=100)


class ChatMessage(InputModel):
    interrupt_current: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=100)
    reasoning_effort: ReasoningEffort | None = None
    retry_message_id: str | None = Field(default=None, min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=24000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    model: str | None = Field(default=None, max_length=100)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank.")
        return value


class ProviderChoice(InputModel):
    provider: Literal["chatgpt", "claude"]


class SubscriptionLoginCode(InputModel):
    login_id: str = Field(min_length=1, max_length=100)
    code: SecretStr = Field(min_length=1, max_length=4096)


class NewSource(InputModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["postgresql", "mysql", "sqlserver", "saphana", "sqlite", "other"]
    description: str = Field(default="", max_length=1000)
    SQLSERVER_HOST: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    SQLSERVER_PORT: int | None = Field(default=None, ge=1, le=65535, repr=False)
    SQLSERVER_USER: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    SQLSERVER_PASSWORD: SecretStr | None = Field(default=None, max_length=1024, repr=False)
    SQLSERVER_DATABASE: str | None = Field(default=None, max_length=128, repr=False)
    HANA_HOST: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    HANA_PORT: int | None = Field(default=None, ge=1, le=65535, repr=False)
    HANA_USER: str | None = Field(default=None, min_length=1, max_length=255, repr=False)
    HANA_PASSWORD: SecretStr | None = Field(default=None, max_length=1024, repr=False)
    HANA_DATABASE: str | None = Field(default=None, max_length=128, repr=False)
    HANA_ENCRYPT: bool | None = None
    HANA_VALIDATE_CERTIFICATE: bool | None = None
    HANA_TLS_CA_CERTIFICATE: SecretStr | None = Field(default=None, max_length=65536, repr=False)
    HANA_TLS_SERVER_NAME: str | None = Field(default=None, max_length=253, repr=False)

    @field_validator("HANA_TLS_CA_CERTIFICATE")
    @classmethod
    def hana_ca_certificate(cls, value):
        from .hana_tls import validate_ca
        if value is not None:
            validate_ca(value.get_secret_value())
        return value

    @field_validator("HANA_TLS_SERVER_NAME")
    @classmethod
    def hana_server_name(cls, value):
        if value and not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value):
            raise ValueError("Use the DNS server name from the HANA certificate, without a scheme, port or path.")
        return value

    @field_validator("SQLSERVER_HOST", "SQLSERVER_USER", "HANA_HOST", "HANA_USER")
    @classmethod
    def connection_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Connection fields cannot contain only spaces.")
        return value.strip() if value is not None else None

    @field_validator("SQLSERVER_DATABASE", "HANA_DATABASE")
    @classmethod
    def optional_database(cls, value):
        return value.strip() if value is not None else None

    def connection_settings(self):
        values = {}
        prefix = "HANA" if self.kind == "saphana" else "SQLSERVER"
        other = "SQLSERVER" if prefix == "HANA" else "HANA"
        if any(key.startswith(other + "_") for key in self.model_fields_set):
            raise ValueError("Connection fields must match the selected database type.")
        for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE"):
            value = getattr(self, f"{prefix}_{name}")
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if value is not None and value != "":
                values[f"{prefix}_{name}"] = str(value)
        if prefix + "_DATABASE" in self.model_fields_set:
            values[prefix + "_DATABASE"] = getattr(self, prefix + "_DATABASE") or ""
        if prefix == "HANA":
            for name in ("TLS_CA_CERTIFICATE", "TLS_SERVER_NAME"):
                if "HANA_" + name in self.model_fields_set:
                    value = getattr(self, "HANA_" + name)
                    values["HANA_" + name] = value.get_secret_value() if isinstance(value, SecretStr) else value or ""
            for name in ("ENCRYPT", "VALIDATE_CERTIFICATE"):
                value = getattr(self, "HANA_" + name)
                if value is not None:
                    values["HANA_" + name] = str(value).lower()
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
    source_id: str | None = None
    database: str | None = Field(default=None, min_length=1, max_length=128)
    query: DatabaseQuery
    required: bool = False


class UploadAnalysis(AnalysisOptions):
    attachment_id: str | None = None
    table_id: str = Field(max_length=100)
    query: UploadQuery


class ReportRequest(InputModel):
    reasoning_effort: ReasoningEffort | None = None
    title: str = Field(min_length=1, max_length=150)
    template_id: str = "executive"
    instructions: str = Field(default="", max_length=6000)
    conversation_id: str | None = None
    dataset_id: str | None = None
    source_id: str | None = None
    database: str | None = Field(default=None, min_length=1, max_length=128)
    attachment_id: str | None = None
    attachment_table: str = Field(default="text", max_length=100)
    attachment_query: UploadQuery | None = None
    attachment_analyses: list[UploadAnalysis] = Field(default_factory=list, max_length=8)
    template_attachment_id: str | None = None
    use_template: bool = True
    query: DatabaseQuery | None = None
    balance_reconciliation: BalanceRequest | None = Field(
        default=None, json_schema_extra={"deprecated": True},
        description="Retired fixed-calculator input. New requests are rejected; use a model-authored calculation_id instead.",
    )
    calculation_id: str | None = Field(default=None, max_length=100)
    calculation_datasets: list[str] = Field(default_factory=list, max_length=8)
    analysis: AnalysisOptions = Field(default_factory=AnalysisOptions)
    analyses: list[ReportAnalysis] = Field(default_factory=list, max_length=8)
    rows: list[dict[str, Any]] | None = Field(default=None, max_length=1000000)
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
    workbook: "WorkbookPresentation | None" = None


class WorkbookLabel(InputModel):
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=1200)


class ColumnLabel(InputModel):
    column: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)


class AnalysisLabels(InputModel):
    index: int = Field(ge=0, le=10)
    name: str = Field(min_length=1, max_length=100)
    columns: list[ColumnLabel] = Field(default_factory=list, max_length=100)
    column_order: list[str] = Field(default_factory=list, max_length=100)
    scope: str = Field(default="", max_length=1200)
    query_explanation: str = Field(default="", max_length=1200)


class WorkbookPresentation(InputModel):
    language: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)?$")
    labels: list[WorkbookLabel] = Field(default_factory=list, max_length=120)
    analyses: list[AnalysisLabels] = Field(default_factory=list, max_length=11)
    python_script: str | None = Field(default=None, max_length=65536)


class WorkbookScriptRepair(InputModel):
    python_script: str = Field(min_length=1, max_length=65536)


ReportDocument.model_rebuild()


def strict_report_schema(model=ReportDocument):
    schema = model.model_json_schema()

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
