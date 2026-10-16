"""No credentials, source connections or general filesystem access during calculations."""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.calculation_script import run_script
from app.script_sandbox import isolate, limit_resources, SandboxUnavailable


def main():
    directory = Path(sys.argv[1]).resolve()
    memory, seconds = int(sys.argv[2]), int(sys.argv[3])
    os.umask(0o077)
    limit_resources(memory, seconds)
    request = json.loads((directory / "input.json").read_text())
    with (directory / "result.json").open("w") as output:
        try:
            isolate(str(directory), memory, seconds)
            result = run_script(request["script"], request["tables"])
            # Strings preserve Decimal values exactly across the process boundary.
            encoded = json.dumps({"ok": True, "result": result}, allow_nan=False,
                                 default=lambda v: str(v) if isinstance(v, Decimal) else unsupported())
            if len(encoded.encode()) > request["max_bytes"]:
                raise ValueError("Calculation output exceeds the configured size limit.")
        except SandboxUnavailable:
            encoded = json.dumps({"ok": False, "error": "Calculation isolation is unavailable; no calculation was executed."})
        except Exception as exc:
            # Source contents, paths and tracebacks never become tool errors.
            encoded = json.dumps({"ok": False, "error": f"Calculation failed with {type(exc).__name__}. Check the documented helpers, field names, missing values and numeric operations."})
        output.write(encoded)


def unsupported():
    raise ValueError("Calculation outputs must contain scalar table values.")


if __name__ == "__main__":
    main()
