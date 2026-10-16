"""Standalone worker; imports trusted libraries before applying kernel restrictions."""

import json
import gc
import os
import sys
from pathlib import Path

# -I ignores user site packages, PYTHONPATH and the current directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.script_sandbox import isolate, limit_resources, SandboxUnavailable
from app.workbook_script import run_script
from app.workbooks import excel_report, ReportDataError
# Resolve trusted lazy renderer imports before filesystem access is restricted.
import app.layout_renderer  # noqa: F401
import app.balance_workbook  # noqa: F401
import app.balance_exports  # noqa: F401


def main():
    directory = Path(sys.argv[1]).resolve()
    os.umask(0o077)
    limit_resources(int(sys.argv[2]), int(sys.argv[3]))
    # Only these two output handles survive into script execution. Seccomp
    # forbids opening ANY file afterward, including anonymous /proc/*/fd paths.
    document = json.loads((directory / "document.json").read_text())
    snapshot = {"rows_json": (directory / "rows.json").read_text(),
                "provenance_json": (directory / "provenance.json").read_text(),
                "captured_at": json.loads((directory / "capture.json").read_text())}
    output = (directory / "report.xlsx").open("wb")
    status = (directory / "result.json").open("w")
    try:
        isolate(str(directory), int(sys.argv[2]), int(sys.argv[3]))
        layout = run_script(document["workbook"]["python_script"], document, snapshot)
        # LayoutSheet/report helper cycles can retain a second decoded snapshot.
        gc.collect()
        checks = []
        report = {"content_json": json.dumps(document)}
        content = excel_report(report, snapshot, layout, checks)
        output.write(content)
        result = {"ok": True, "custom": layout is not None, "checks": checks}
    except SandboxUnavailable:
        result = {"ok": False, "kind": "sandbox", "error": "Workbook script isolation is unavailable. Check Linux Landlock and seccomp support."}
    except ReportDataError as exc:
        result = {"ok": False, "kind": "script", "error": str(exc)}
    except Exception as exc:
        # Never send source values, tracebacks, paths or environment into repairs.
        result = {"ok": False, "kind": "script", "error": f"Workbook script failed with {type(exc).__name__}. Use the documented report helpers."}
    status.write(json.dumps(result))
    output.close()
    status.close()


if __name__ == "__main__":
    main()
