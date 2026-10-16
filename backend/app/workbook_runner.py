"""Cancellable private subprocess jobs, then independent workbook read-back validation."""

import asyncio
import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path

from .workbooks import excel_report, ReportDataError
from .workbook_validation import validate_workbook
from .report_exports import public_snapshot


class WorkbookSandboxUnavailable(ReportDataError):
    pass


class WorkbookRunner:
    def __init__(self, settings):
        self.settings = settings
        self.capacity = asyncio.Semaphore(4)

    async def build(self, report, snapshot, phase=None):
        traffic = getattr(self,'traffic',None)
        started = time.perf_counter()
        identifier = report.get('id')
        if traffic:
            document = json.loads(report['content_json'])
            traffic.record('backend-excel','workbook/build','started',correlation_id=identifier,user_id=report.get('user_id'),
                           payload={'report_id':identifier,'python_script':(document.get('workbook') or {}).get('python_script')})
        try:
            content,verified = await self._build(report,snapshot,phase)
            if traffic:
                traffic.record('excel-backend','workbook/validation','ok',correlation_id=identifier,user_id=report.get('user_id'),
                               size=len(content),duration_ms=round((time.perf_counter()-started)*1000,2),payload=verified)
            return content,verified
        except BaseException as exc:
            if traffic:
                traffic.record('excel-backend','workbook/validation','interrupted' if isinstance(exc,asyncio.CancelledError) else 'error',
                               correlation_id=identifier,user_id=report.get('user_id'),duration_ms=round((time.perf_counter()-started)*1000,2),
                               payload={'report_id':identifier,'error':str(exc) if isinstance(exc,ReportDataError) else type(exc).__name__})
            raise

    async def _build(self, report, snapshot, phase=None):
        from .balance_workbook import balance_contract
        await asyncio.to_thread(balance_contract, snapshot)
        worker_snapshot = public_snapshot(snapshot)
        document = json.loads(report["content_json"])
        script = (document.get("workbook") or {}).get("python_script")
        if not script:
            raise ReportDataError("Workbook script is missing. Generate build(report) using the report helpers.")
        root = self.settings.data_dir / "excel-jobs"
        root.mkdir(exist_ok=True, mode=0o700)
        async with self.capacity:
            with tempfile.TemporaryDirectory(prefix="job-", dir=root) as temporary:
                directory = Path(temporary)
                def prepare_input():
                    # Snapshot JSON is already immutable and serialized. Avoid
                    # re-encoding huge row arrays in the HTTP event loop.
                    (directory / "document.json").write_text(json.dumps(document, ensure_ascii=False))
                    (directory / "rows.json").write_text(worker_snapshot["rows_json"])
                    (directory / "provenance.json").write_text(worker_snapshot["provenance_json"])
                    (directory / "capture.json").write_text(json.dumps(snapshot["captured_at"]))

                preparation = asyncio.create_task(asyncio.to_thread(prepare_input))
                try:
                    await asyncio.shield(preparation)
                except asyncio.CancelledError:
                    await preparation
                    raise
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-I", "-B", str(Path(__file__).with_name("workbook_worker.py")), str(directory),
                    str(self.settings.workbook_memory_mb), str(self.settings.workbook_timeout), cwd=directory,
                    env={"LANG": "C.UTF-8", "TMPDIR": str(directory)}, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, close_fds=True,
                )
                try:
                    await asyncio.wait_for(process.wait(), self.settings.workbook_timeout)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                    raise ReportDataError("Workbook script exceeded its execution time limit.") from None
                except BaseException:
                    if process.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            process.kill()
                        await process.wait()
                    raise
                if process.returncode != 0 or not (directory / "result.json").exists():
                    raise ReportDataError("Workbook worker stopped before completion. Check script complexity and resource limits.")
                result = json.loads((directory / "result.json").read_text())
                if not result["ok"]:
                    if result["kind"] == "sandbox":
                        raise WorkbookSandboxUnavailable(result["error"])
                    raise ReportDataError(result["error"])
                if phase:
                    await phase("validating")
                content = await asyncio.to_thread((directory / "report.xlsx").read_bytes)
                verified = await asyncio.to_thread(validate_workbook, content, document, snapshot, result["checks"], result["custom"])
                return content, verified


async def rebuild_excel(manager, report, snapshot):
    document = json.loads(report["content_json"])
    if (document.get("workbook") or {}).get("python_script"):
        return (await manager.workbook_runner.build(report, snapshot))[0]
    # Historic saved reports remain readable without regenerating model content.
    return await asyncio.to_thread(excel_report, report, snapshot)
