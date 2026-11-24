"""Bounded calls to the print worker in the backend's Python environment."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend" / "workers" / "print_engine.py"
SUPPORTED_PRINTERS = frozenset({"OCTOPRINT", "MOONRAKER_KLIPPER", "PRUSA_LINK", "DUET"})


class EngineError(RuntimeError):
    pass


class EngineUnavailable(EngineError):
    pass


class EngineTimeout(EngineError):
    pass


def python_path():
    # Keep the executable's venv path even when it is a symlink.
    return Path(sys.executable)


def worker_environment():
    # The worker does not receive the studio's tokens, AI keys, proxy credentials or vendor account settings.
    inherited = {"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in inherited}
    data = Path(os.getenv("XR3D_DATA_DIR") or (ROOT / "backend-data")).resolve() / "print-engine"
    data.mkdir(parents=True, exist_ok=True)
    environment.update({"HOME": str(data), "USERPROFILE": str(data), "APPDATA": str(data),
                        "LOCALAPPDATA": str(data), "XDG_CONFIG_HOME": str(data), "XDG_DATA_HOME": str(data),
                        "XDG_CACHE_HOME": str(data)})
    return environment


def run_engine(operation, *, timeout=30, **parameters):
    executable = python_path()
    if not executable.is_file():
        raise EngineUnavailable("Run Install XR3D Server to set up the XR3D Print Engine.")
    request = json.dumps({"operation": operation, **parameters}, allow_nan=False).encode("utf-8")
    try:
        process = subprocess.run([str(executable), "-I", str(WORKER)], input=request, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, cwd=ROOT, env=worker_environment(), timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise EngineTimeout("The XR3D print engine timed out. Check printer status before retrying a command.") from error
    except OSError as error:
        raise EngineUnavailable("Could not launch the XR3D print engine.") from error
    if process.returncode or len(process.stdout) > 1_048_576:
        raise EngineUnavailable("The XR3D print engine failed to start or returned an incomplete response.")
    try:
        reply = json.loads(process.stdout)
        if not isinstance(reply, dict):
            raise ValueError
    except (ValueError, UnicodeError) as error:
        raise EngineError("Invalid response from the XR3D print engine.") from error
    if reply.get("ok") is True:
        return reply["result"]
    if reply.get("error") == "unavailable":
        raise EngineUnavailable("The XR3D print engine installation is incomplete.")
    messages = {
        "not_idle": "The printer is not idle. No print was requested.",
        "upload": "The printer did not confirm the upload.",
        "command": "The printer did not confirm the command. Check printer status before retrying.",
        "input": "Provide a valid printable STL model and print settings.",
        "transport": "Could not reach or authenticate to the printer from the XR3D server.",
    }
    raise EngineError(messages.get(reply.get("error"), "The XR3D print engine could not complete the request."))
