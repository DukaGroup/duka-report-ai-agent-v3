"""Private uploads exposed through owner-checked, bounded backend tools."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from fastapi import HTTPException
from .db import now, uid
from .upload_queries import analyze_table

MAX_UPLOAD = 12 * 1024 * 1024
EXTENSIONS = {".xlsx", ".csv", ".pdf", ".docx", ".txt"}


class AttachmentStore:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db
        self.directory = settings.data_dir / "uploads"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.semaphore = asyncio.Semaphore(2)

    def owned(self, user_id, identifier, conversation_id=None):
        row = self.db.one("SELECT * FROM attachments WHERE id=? AND user_id=?", (identifier, user_id))
        if not row or (conversation_id is not None and row["conversation_id"] != conversation_id):
            raise HTTPException(404, "Attachment not found.")
        return row

    def parsed(self, row):
        return json.loads((self.directory / (row["id"] + ".json")).read_text())

    def metadata(self, row):
        parsed = self.parsed(row)
        return {
            "id": row["id"],
            "name": row["name"],
            "size": row["size"],
            "kind": row["extension"].lstrip("."),
            "purpose": row["purpose"],
            "created_at": row["created_at"],
            "warnings": parsed["warnings"],
            "tables": [{k: v for k, v in t.items() if k != "rows"} for t in parsed["tables"]],
            "text_length": len(parsed["text"]),
            "text_truncated": parsed["text_truncated"],
            "format": parsed["format"],
        }

    def manifest(self, row):
        metadata = self.metadata(row)
        metadata["tables"] = [
            {"id": t["id"], "name": t["name"], "row_count": t["row_count"], "column_count": len(t["columns"])}
            for t in metadata["tables"]
        ]
        return metadata

    async def upload(self, user_id, conversation_id, file):
        name = re.sub(r"[\x00-\x1f\x7f]", "", (file.filename or "upload").replace("\\", "/").split("/")[-1])[:180]
        extension = Path(name).suffix.lower()
        if extension not in EXTENSIONS:
            raise HTTPException(422, "Upload Excel (.xlsx), CSV, PDF, Word (.docx), or text files.")
        if (
            self.db.one(
                "SELECT count(*) AS n FROM attachments WHERE user_id=? AND conversation_id=?",
                (user_id, conversation_id),
            )["n"]
            >= 50
        ):
            raise HTTPException(413, "This conversation has reached its upload limit. Start a new conversation.")
        total = self.db.one("SELECT coalesce(sum(size),0) AS total FROM attachments WHERE user_id=?", (user_id,))[
            "total"
        ]
        identifier, size = uid(), 0
        path, parsed_path = self.directory / (identifier + extension), self.directory / (identifier + ".json")
        try:
            with path.open("xb") as output:
                path.chmod(0o600)
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Uploads must be smaller than 12 MB.")
                    if total + size > 250 * 1024 * 1024:
                        raise HTTPException(413, "Your private upload storage limit has been reached.")
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "The uploaded file is empty.")
            async with self.semaphore:
                env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "PYTHONPATH")}
                env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
                env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "app.attachment_reader",
                    str(path),
                    extension,
                    str(parsed_path),
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(process.wait(), 25)
                except TimeoutError as exc:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise HTTPException(422, "The upload exceeded parsing limits or could not be read.") from exc
                except BaseException:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise
            if not parsed_path.exists():
                raise HTTPException(422, "The upload exceeded parsing limits or could not be read.")
            parsed_path.chmod(0o600)
            result = json.loads(parsed_path.read_text())
            if result.get("error"):
                raise HTTPException(422, result["error"])
            self.db.execute(
                "INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?)",
                (identifier, user_id, conversation_id, name, extension, size, "analysis", now()),
            )
            self.db.audit(user_id, "attachment.uploaded", identifier, {"kind": extension, "bytes": size})
            return self.metadata(self.owned(user_id, identifier))
        except BaseException:
            path.unlink(missing_ok=True)
            parsed_path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    def message_files(self, user_id, conversation_id, identifiers):
        if len(set(identifiers)) != len(identifiers):
            raise HTTPException(422, "Attachment IDs must be unique.")
        return [self.manifest(self.owned(user_id, identifier, conversation_id)) for identifier in identifiers]

    def sent_files(self, user_id, conversation_id, before_message_id=None):
        rows = self.db.all(
            "SELECT DISTINCT a.* FROM attachments a JOIN message_attachments ma ON ma.attachment_id=a.id JOIN messages m ON m.id=ma.message_id WHERE a.user_id=? AND a.conversation_id=? AND m.status='completed' AND (? IS NULL OR (m.created_at,m.rowid)<(SELECT created_at,rowid FROM messages WHERE id=? AND conversation_id=?)) ORDER BY a.created_at",
            (user_id, conversation_id, before_message_id, before_message_id, conversation_id),
        )
        return [self.manifest(r) for r in rows]

    def read(self, user_id, identifier, conversation_id, table_id=None, offset=0, limit=100):
        row = self.owned(user_id, identifier, conversation_id)
        parsed = self.parsed(row)
        if not 0 <= offset <= 200000 or not 1 <= limit <= 200:
            raise ValueError("Attachment pagination is outside its limits.")
        if table_id:
            t = next((t for t in parsed["tables"] if t["id"] == table_id), None)
            if not t:
                raise ValueError("Uploaded table not found. Use list_attachments first.")
            result = {k: v for k, v in t.items() if k != "rows"}
            rows = t["rows"][offset : offset + limit]
            while len(json.dumps(rows).encode()) > 60000:
                rows.pop()
            if not rows and offset < len(t["rows"]):
                raise ValueError("A row exceeds the attachment preview limit. Query selected columns instead.")
            result.update(
                rows=rows,
                next_offset=offset + len(rows) if offset + len(rows) < len(t["rows"]) else None,
                truncated=offset > 0 or offset + len(rows) < len(t["rows"]),
            )
        else:
            text = parsed["text"][offset : offset + 12000]
            result = {
                "text": text,
                "next_offset": offset + len(text) if offset + len(text) < len(parsed["text"]) else None,
                "text_truncated": parsed["text_truncated"],
                "warnings": parsed["warnings"],
                "tables": [{k: v for k, v in t.items() if k != "rows"} for t in parsed["tables"]],
                "format": parsed["format"],
            }
        return {"attachment_id": identifier, "name": row["name"], "untrusted_document": True, **result}

    def query(self, user_id, identifier, conversation_id, table_id, query, *, complete=False):
        row = self.owned(user_id, identifier, conversation_id)
        parsed = self.parsed(row)
        if table_id == "text" or not parsed["tables"]:
            if parsed["text_truncated"]:
                raise ValueError("The text is a preview. Use complete uploaded tables for reports.")
            t = {
                "columns": [{"name": "segment", "type": "integer"}, {"name": "text", "type": "text"}],
                "rows": [
                    {"segment": i + 1, "text": parsed["text"][start : start + 3000]}
                    for i, start in enumerate(range(0, len(parsed["text"]), 3000))
                ],
            }
        else:
            t = next((t for t in parsed["tables"] if t["id"] == table_id), None)
            if not t:
                raise ValueError("Uploaded table not found. Use list_attachments first.")
        return analyze_table(
            t,
            query,
            complete=complete,
            max_rows=self.settings.report_max_rows,
            max_bytes=self.settings.report_max_bytes,
        )

    def format_reference(self, user_id, identifier, conversation_id):
        row = self.owned(user_id, identifier, conversation_id)
        parsed = self.parsed(row)
        if row["extension"] != ".xlsx" or not parsed["format"]:
            raise ValueError("Use an Excel file with a formatted table as the format reference.")
        return {"attachment_id": identifier, "name": row["name"], **parsed["format"]}
