"""Observable chat activity only; never return reasoning text or tool arguments."""

import json

TOOLS = {
    "WebSearch": "Kërkim në internet", "WebFetch": "Lexim i faqes në internet",
    "read_handoff_context": "Lexim i kontekstit të bisedës",
    "discover_databases": "Zbulim i databazave", "list_databases": "Lexim i databazave",
    "resolve_company_access": "Kontroll i qasjes te kompanitë",
    "discover_sales": "Zbulim i të dhënave të shitjeve",
    "list_sources": "Lexim i burimeve të të dhënave",
    "list_schemas": "Lexim i skemave",
    "list_tables": "Lexim i tabelave", "describe_table": "Kontroll i kolonave",
    "inspect_sap_context": "Kontroll i strukturës SAP",
    "query_database": "Lexim i të dhënave", "fetch_dataset": "Lexim i dataset-it",
    "list_attachments": "Kontroll i skedarëve",
    "read_attachment": "Lexim i skedarit",
    "query_attachment": "Analizë e skedarit",
    "create_attachment_report": "Përgatitje e raportit nga skedari",
    "find_calculation_scripts": "Kërkim i llogaritjeve të mëparshme",
    "read_calculation_script": "Lexim i llogaritjes së mëparshme",
    "calculate_data": "Llogaritje e rezultateve", "create_report": "Përgatitje e raportit",
    "create_calculation_report": "Përgatitje e raportit nga llogaritjet",
    "create_database_report": "Përgatitje e raportit nga databaza",
    "list_datasets": "Kontroll i burimeve të të dhënave",
}
PHASES = {"thinking": "Përgatitje e përgjigjes", "reasoning": "Arsyetim",
          "recovering": "Rifillim i punës", "switching": "Kalimi te abonimi tjetër",
          "refreshing": "Përditësim i kontekstit të bisedës"}

CONFIGURATION_PHASES = frozenset(("switching", "refreshing", "recovering"))
CONFIGURATION_TOOLS = frozenset(("read_handoff_context",))


def configuration_event(event):
    return (
        event.get("type") in ("activity", "snapshot") and event.get("activity") in CONFIGURATION_PHASES
        or event.get("type") == "tool" and event.get("name") in CONFIGURATION_TOOLS
    )


def viewer_event(event, technical=False):
    """Keep public activity while reserving step details for Devs."""
    if technical:
        return event
    shown = {key: value for key, value in event.items()
             if key not in ("step_id", "step_label", "step_kind")}
    if not configuration_event(event):
        return shown
    # Snapshot text still resets an unfinished answer during failover. Dropping
    # the event would leave stale text in a member's chat after reconnecting.
    shown = {key: value for key, value in shown.items()
             if key not in ("name", "provider", "from_provider", "model")}
    return {**shown, "type": "snapshot" if event.get("type") == "snapshot" else "activity", "activity": "thinking"}


def public_step(event, technical=True):
    if not technical and configuration_event(event):
        return None
    kind = event.get("type")
    if kind == "tool":
        label = TOOLS.get(event.get("name"), "Kontroll i të dhënave")
        return {"label": label, "kind": "tool"}
    if kind in ("activity", "snapshot") and event.get("activity") in PHASES:
        return {"label": PHASES[event["activity"]], "kind": "activity"}
    if kind == "started":
        return {"label": "Puna filloi", "kind": "activity"}
    if kind == "done":
        return {"label": "Përgjigjja përfundoi" if event.get("status") == "completed" else "Puna u ndërpre", "kind": "done"}
    if kind == "error":
        return {"label": "Puna nuk përfundoi", "kind": "error"}
    return None


def conversation_progress(db, conversation, technical=True):
    if not technical:
        return {}
    rows = db.all(
        "SELECT e.run_id,e.seq,e.event_json FROM chat_run_events e JOIN messages m ON m.id=e.run_id "
        "WHERE m.conversation_id=? AND json_extract(e.event_json,'$.type') "
        "IN ('tool','activity','snapshot','started','done','error') ORDER BY e.seq", (conversation,))
    result = {}
    for row in rows:
        event = json.loads(row["event_json"])
        step = public_step(event, technical=technical)
        if step:
            result.setdefault(row["run_id"], []).append({"id": event.get("step_id", str(row["seq"])), **step})
    return result
