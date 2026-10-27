"""Small, hash-checked edits to immutable model-authored scripts."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field


def script_hash(source):
    return hashlib.sha256(source.encode()).hexdigest()


class ScriptEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(min_length=1, max_length=65536)
    after: str = Field(max_length=65536)
    occurrences: int = Field(default=1, ge=1, le=100)


class ScriptReuse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=128, pattern=r"^(calculation|report):[A-Za-z0-9-]+$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    edits: list[ScriptEdit] = Field(default_factory=list, max_length=20)


def apply_reuse(source, reuse):
    if script_hash(source) != reuse.sha256:
        raise ValueError("Saved script changed; read its current hash before reusing it.")
    for edit in reuse.edits:
        if source.count(edit.before) != edit.occurrences:
            raise ValueError("Script edit must match exactly the declared number of occurrences; read the script again.")
        source = source.replace(edit.before, edit.after)
        if len(source.encode()) > 65536:
            raise ValueError("Edited script exceeds the 64 KB limit.")
    return source
