from fastapi import HTTPException


def saved_effort(db, conversation_id):
    row = db.one("SELECT reasoning_effort FROM conversation_settings WHERE conversation_id=?", (conversation_id,)) if conversation_id else None
    return row["reasoning_effort"] if row else None


async def validate_effort(runtime, model, effort):
    if effort is None:
        return
    catalog = await runtime.models()
    selected = next((m for m in catalog if (model in (m.get("id"), m.get("model")) if model else m.get("isDefault"))), None)
    if not selected or effort not in selected.get("supported_reasoning_efforts", []):
        raise HTTPException(422, "This model does not support the selected reasoning effort. Choose another level or automatic.")
