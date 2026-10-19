"""Stop an owned native process without waiting for a network control reply."""

import asyncio
import contextlib
import os
import signal


def request_process_stop(process, *, group=False):
    if process is None or process.returncode is not None:
        return

    def send(sig):
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                if group:
                    os.killpg(process.pid, sig)
                elif sig == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()

    send(signal.SIGTERM)
    # A short flush grace, then escalation even if provider cleanup is blocked.
    # The process object guards against signalling a reaped/reused PID.
    asyncio.get_running_loop().call_later(0.25, send, signal.SIGKILL)
