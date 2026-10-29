"""Answers describe business results, never the databases or tables behind them."""

import json

import pytest

from app.db import now
from app.provider import BASE_INSTRUCTIONS, CodexRuntime
from app.source_privacy import PLACEHOLDER, Redactor, SourceTerms, tidy, tool_terms
from conftest import HEADERS
from test_chat_controls import claude, prepare, post  # noqa: F401


def stream(redactor, chunks):
    return "".join(redactor.feed(chunk) for chunk in chunks) + redactor.flush()


def test_identifiers_split_across_chunks_are_hidden():
    text = "Shitjet dje për Gotech ishin 1,200 ALL (databaza GoTechBC15MG, tabela `dbo`.`OINV`)."
    terms = {"GoTechBC15MG", "dbo", "OINV"}
    expected = Redactor(terms).redact(text)
    assert "GoTechBC15MG" not in expected and "OINV" not in expected
    assert PLACEHOLDER in expected and "1,200 ALL" in expected
    for size in (1, 2, 3, 5, 7, 11, len(text)):
        chunks = [text[i:i + size] for i in range(0, len(text), size)]
        streamed = stream(Redactor(terms), chunks)
        assert not any(term in streamed for term in terms)
        # Chunks may keep cosmetic punctuation; the final saved answer is tidied as a whole.
        assert tidy(streamed) == expected


def test_plain_text_is_not_held_back_and_partial_words_are_not_hidden():
    redactor = Redactor({"GoTechBC15MG", "OINV"})
    assert redactor.feed("Checkpointed partial answer") == "Checkpointed partial answer"
    # "OINVX" is a different word; "Go" may still become a private name.
    assert redactor.feed(" OINVX Go") == " OINVX "
    assert redactor.feed("od.") == "Good."
    assert redactor.flush() == ""


def test_user_typed_names_company_names_and_assistant_name_stay_visible():
    redactor = Redactor({"GOTECH", "HANA", "Finance Server"}, keep={"Gotech"},
                        visible_text="sa ishin shitjet ne gotech?")
    out = redactor.redact("Hana: shitjet e GOTECH nga Finance Server dhe HANA.")
    assert out == f"Hana: shitjet e GOTECH nga {PLACEHOLDER} dhe HANA."


def test_tool_terms_cover_queries_business_central_tables_and_discovery():
    arguments = {"source_id": "src-1", "database": "GoTechBC15MG", "query": {
        "tables": [{"schema": "dbo", "name": "Gotech Live$Sales Invoice Header", "alias": "h"}]}}
    terms = tool_terms("query_database", arguments, {"database": "GoTechBC15MG", "schemas": [{"schema_name": "SBO_GOTECH"}]})
    assert {"src-1", "GoTechBC15MG", "dbo", "Gotech Live$Sales Invoice Header", "Sales Invoice Header", "SBO_GOTECH"} <= terms
    # The company part of a table prefix is a business name, not a private identifier.
    assert "Gotech Live" not in terms
    # Ordinary words and SAP client numbers are never treated as identifiers.
    assert not tool_terms("describe_table", {"schema": "400", "table": "Sales"}, None)


def test_seeded_terms_include_sources_grants_and_earlier_tool_calls(client, admin):
    db = client.app.state.db
    user = db.one("SELECT id FROM users LIMIT 1")["id"]
    db.execute("INSERT INTO data_sources(id,name,kind,status,created_at) VALUES('src-9','Finance Server','saphana','connected',?)", (now(),))
    db.execute("INSERT INTO database_grants VALUES(?,?,?,?,?)", (user, "src-9", "HDB_FINANCE", 1, "[]"))
    terms, _ = SourceTerms(db).scope(user, "conversation")
    assert {"src-9", "Finance Server", "HDB_FINANCE"} <= terms


def test_instructions_forbid_source_details_for_every_model():
    assert "SOURCE_CONFIDENTIALITY" in BASE_INSTRUCTIONS
    assert "I took this from database X and table Y" in BASE_INSTRUCTIONS
    assert "show technical table/field names only when they help" not in BASE_INSTRUCTIONS
    assert "company/database/client" not in BASE_INSTRUCTIONS


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_chat_answer_never_shows_identifiers_seen_by_tools(client, admin, claude, monkeypatch, provider):  # noqa: F811
    from app.claude_provider import ClaudeRuntime

    chat = prepare(client, provider)
    db = client.app.state.db
    user = db.one("SELECT user_id FROM conversations WHERE id=?", (chat,))["user_id"]
    terms = client.app.state.manager.source_terms
    answer = "Shitjet e djeshme: 5,000 ALL. Burimi: databaza HDB_SALES, skema SBO_GOTECH, tabela OINV."

    async def answer_stream(self, thread, content, model=None, *args, **kwargs):
        # A tool call during the turn exposed these identifiers to the model.
        terms.observe(user, chat, "query_database",
                      {"source_id": "src", "database": "HDB_SALES",
                       "query": {"tables": [{"schema": "SBO_GOTECH", "name": "OINV", "alias": "i"}]}},
                      {"contentItems": [{"text": json.dumps({"database": "HDB_SALES"})}]})
        for index in range(0, len(answer), 4):
            yield {"type": "delta", "text": answer[index:index + 4]}
        yield {"type": "done", "status": "completed", "text": answer}

    monkeypatch.setattr(CodexRuntime if provider == "chatgpt" else ClaudeRuntime, "stream", answer_stream)
    events = post(client, chat, content="Sa ishin shitjet dje?").text
    saved = db.one("SELECT content FROM messages WHERE conversation_id=? AND role='assistant'", (chat,))["content"]
    for private in ("HDB_SALES", "SBO_GOTECH", "OINV"):
        assert private not in events and private not in saved
    assert "5,000 ALL" in saved and PLACEHOLDER in saved
    streamed = "".join(json.loads(line).get("text", "") for line in events.splitlines()
                       if json.loads(line)["type"] == "delta")
    assert streamed.startswith("Shitjet e djeshme: 5,000 ALL.")
    assert client.get(f"/api/conversations/{chat}", headers=HEADERS).status_code == 200
