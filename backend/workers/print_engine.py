"""Private JSON worker built on the open-source print engine's Python APIs."""
from contextlib import contextmanager, redirect_stdout
from importlib.metadata import version
from ipaddress import ip_address, ip_network
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

NETWORKS = tuple(map(ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
DISCOVERY_TYPES = {"octoprint": "OCTOPRINT", "moonraker": "MOONRAKER_KLIPPER", "creality": "MOONRAKER_KLIPPER",
                   "prusalink": "PRUSA_LINK", "bambu": "BAMBU_LAB", "duet": "DUET"}
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.gcode", re.ASCII)


class Refusal(Exception):
    pass


def lan_host(value):
    try:
        address = ip_address(value)
    except (ValueError, TypeError):
        return None
    return str(address) if any(address in network for network in NETWORKS) else None


def number(value, maximum):
    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
        return min(maximum, max(0, value))
    return 0


def discover():
    from kiln.discovery import discover_printers

    printers = {}
    for found in discover_printers(timeout=7, methods=["mdns", "ssdp"]):
        host = lan_host(found.host)
        kind = DISCOVERY_TYPES.get(found.printer_type)
        if host and kind and 1 <= found.port <= 65535:
            name = "".join(character for character in found.name[:100] if character.isprintable()) or host
            serial = found.serial if re.fullmatch(r"[A-Za-z0-9_-]{4,64}", found.serial or "") else None
            printers.setdefault((kind, host, found.port), {"type": kind, "name": name, "ipAddress": host,
                "port": found.port, "serialNumber": serial})
    return sorted(printers.values(), key=lambda printer: printer["name"].casefold())[:64]


def inspect_model(request):
    from kiln.printability import analyze_printability

    try:
        report = analyze_printability(request["path"], nozzle_diameter=request["nozzle"],
            build_volume=tuple(request["build_volume"]) if request.get("build_volume") else None,
            include_hole_detection=False)
    except (ValueError, OSError) as error:
        raise Refusal("input") from error
    return {"printable": report.printable, "score": report.score, "grade": report.grade,
            "triangleCount": report.triangle_count,
            "dimensionsMm": {key: number(value, 1_000_000) for key, value in report.dimensions_mm.items()},
            "recommendations": [text.replace("Kiln", "XR3D")[:300] for text in report.recommendations[:20]
                                if not any(phrase in text.lower() for phrase in ("kiln pro", "kiln3d.com", "kiln sign-in"))]}


@contextmanager
def device_for(profile):
    host = lan_host(profile["host"])
    port = profile["port"]
    scheme = profile.get("scheme", "http")
    if not host or not 1 <= port <= 65535 or scheme not in {"http", "https"}:
        raise Refusal("transport")
    base = f"{scheme}://{host}:{port}"
    credential = profile["accessCode"]
    match profile["type"]:
        case "OCTOPRINT":
            from kiln.printers.octoprint import OctoPrintAdapter
            device = OctoPrintAdapter(base, credential, timeout=6, retries=1)
        case "MOONRAKER_KLIPPER":
            from kiln.printers.moonraker import MoonrakerAdapter
            device = MoonrakerAdapter(base, credential, timeout=6, retries=1)
        case "PRUSA_LINK":
            from kiln.printers.prusalink import PrusaLinkAdapter
            device = PrusaLinkAdapter(base, credential, timeout=6, retries=1)
        case "DUET":
            from kiln.printers.duet import DuetAdapter
            device = DuetAdapter(base, password=credential or "reprap", timeout=6, retries=1)
        case _:
            raise Refusal("transport")
    session = device._session
    session.trust_env = False
    original_request = session.request

    def request(method, url, **kwargs):
        destination = urlsplit(url)
        if (destination.scheme, destination.hostname, destination.port or (443 if scheme == "https" else 80)) != (scheme, host, port):
            raise Refusal("transport")
        kwargs["allow_redirects"] = False
        response = original_request(method, url, **kwargs)
        if response.is_redirect:
            response.close()
            raise Refusal("transport")
        return response

    session.request = request
    try:
        yield device
    finally:
        try:
            disconnect = getattr(device, "disconnect", None)
            if disconnect is not None:
                disconnect()
        finally:
            session.close()


def printer_status(device):
    from kiln.printers.base import read_status

    condition, job = read_status(device)
    state = {"idle": "CONNECTED", "printing": "PRINTING", "paused": "PAUSED", "busy": "PRINTING",
             "cancelling": "PRINTING"}.get(condition.state.value, "ERROR") if condition.connected else "ERROR"
    return {"connectionState": state, "filename": (job.file_name or "")[:255],
            "progressPercent": number(job.completion, 100), "timeRemainingSeconds": number(job.print_time_left_seconds, 31_536_000),
            "toolActualC": number(condition.tool_temp_actual, 500), "toolTargetC": number(condition.tool_temp_target, 500),
            "bedActualC": number(condition.bed_temp_actual, 500), "bedTargetC": number(condition.bed_temp_target, 500)}


def printer_operation(operation, request):
    with device_for(request["profile"]) as device:
        if operation == "status":
            return printer_status(device)
        if operation == "upload":
            path = Path(request["path"])
            if not FILE_NAME.fullmatch(path.name):
                raise Refusal("upload")
            result = device.upload_file(str(path))
            if not result.success or not FILE_NAME.fullmatch(result.file_name):
                raise Refusal("upload")
            return {"filename": result.file_name}
        if operation == "start":
            filename = request["filename"]
            state = device.get_state()
            if not FILE_NAME.fullmatch(filename) or not state.connected or state.state.value != "idle":
                raise Refusal("not_idle")
            from kiln import print_signoff

            target = request["profile"]["host"]
            print_signoff.require_signoff(device)
            # Only the XR3D start endpoint calls this operation, after consuming the target's one-use upload receipt.
            device._kiln_registered_name = target
            print_signoff.grant("start_print", filename, target, source=print_signoff.SOURCE_PRIOR_APPROVAL, door="XR3D")
            try:
                result = device.start_print(filename)
            finally:
                print_signoff.clear()
        else:
            action = {"pause": device.pause_print, "resume": device.resume_print, "cancel": device.cancel_print}
            result = action[request["action"]]()
        if not result.success:
            raise Refusal("command")
        return {"accepted": True}


def execute(request):
    operation = request["operation"]
    if operation == "health":
        return {"name": "XR3D Print Engine", "version": version("kiln3d")}
    if operation == "discover":
        return discover()
    if operation == "inspect":
        return inspect_model(request)
    if operation in {"status", "upload", "start", "action"}:
        return printer_operation(operation, request)
    raise Refusal("input")


def main():
    operation = None
    try:
        with redirect_stdout(sys.stderr):
            request = json.load(sys.stdin)
            operation = request.get("operation")
            result = execute(request)
        output = json.dumps({"ok": True, "result": result}, ensure_ascii=True, allow_nan=False)
    except Refusal as error:
        output = json.dumps({"error": str(error)})
    except ImportError:
        output = json.dumps({"error": "unavailable"})
    except Exception:
        output = json.dumps({"error": "transport" if operation in {"status", "upload", "start", "action"} else "input"})
    print(output)


if __name__ == "__main__":
    main()
