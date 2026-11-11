"""Private LAN adapters. Protocol sources and supported scope: docs/printer-adapters.md.

No automatic retries of physical commands. All methods are blocking and run off
the API event loop. Printer credentials are held only for the current request.
"""
from collections import deque
from contextlib import contextmanager
import ftplib
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import time
import uuid
import zipfile
import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class VendorError(Exception):
    """Safe-to-display message; never include raw device responses or credentials."""


class VendorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(pattern=r"^(BAMBU_LAB|FLASHFORGE)$")
    host: str
    port: int
    serialNumber: str = Field(pattern=r"^[A-Za-z0-9_-]{4,64}$")
    accessCode: SecretStr = Field(min_length=1, max_length=64)

    @field_validator("host")
    @classmethod
    def lan_address(cls, value):
        address = ipaddress.ip_address(value)
        if not any(address in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("Use the printer's private IPv4 LAN address")
        return str(address)

    @model_validator(mode="after")
    def fixed_service_port(self):
        if self.port != (8883 if self.type == "BAMBU_LAB" else 8898):
            raise ValueError("Use MQTT TLS port 8883 for Bambu or HTTP port 8898 for FLASHFORGE 5M")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.accessCode.get_secret_value()):
            raise ValueError("Invalid LAN access code")
        return self

    def identity(self):
        return self.type, self.host, self.port, self.serialNumber


def filename(value: str, suffix: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value) or not value.lower().endswith(suffix):
        raise VendorError(f"Select a printer-sliced {suffix} file with a simple filename")
    return value


def numeric(value, default=0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def snapshot(state, data, fields):
    return {"connectionState": state, "filename": str(data.get(fields[0]) or ""),
            "progressPercent": max(0, min(100, numeric(data.get(fields[1])) * fields[2])),
            "timeRemainingSeconds": max(0, int(numeric(data.get(fields[3])) * fields[4])),
            "toolActualC": numeric(data.get(fields[5])), "toolTargetC": numeric(data.get(fields[6])),
            "bedActualC": numeric(data.get(fields[7])), "bedTargetC": numeric(data.get(fields[8]))}


class FlashforgeAdapter:
    """Adventurer 5M/5M Pro HTTP LAN API, single material only."""
    def __init__(self, profile, transport=None):
        self.profile = profile
        self.client = httpx.Client(base_url=f"http://{profile.host}:{profile.port}/", timeout=60,
                                   follow_redirects=False, trust_env=False, transport=transport)

    def close(self): self.client.close()

    def request(self, endpoint, **kwargs):
        with self.client.stream("POST", endpoint, **kwargs) as response:
            if response.status_code != 200: raise VendorError("FLASHFORGE did not accept the request")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 1024 * 1024: raise VendorError("FLASHFORGE response exceeds limit")
        try:
            result = json.loads(body)
        except ValueError as error:
            raise VendorError("FLASHFORGE returned an invalid response") from error
        if not isinstance(result, dict) or type(result.get("code")) is not int or result["code"] != 0:
            raise VendorError("FLASHFORGE rejected the request. Check LAN mode, serial number, access code and printer state.")
        return result

    def auth(self):
        return {"serialNumber": self.profile.serialNumber, "checkCode": self.profile.accessCode.get_secret_value()}

    def detail(self):
        detail = self.request("detail", json=self.auth()).get("detail")
        if not isinstance(detail, dict): raise VendorError("FLASHFORGE returned no printer status")
        pid = detail.get("pid")
        try: pid = int(pid, 16) if isinstance(pid, str) else int(pid)
        except (TypeError, ValueError): raise VendorError("Cannot identify FLASHFORGE printer model")
        if pid not in (35, 36): raise VendorError("This adapter supports Adventurer 5M and 5M Pro only")
        return detail

    def status(self):
        data = self.detail()
        raw = str(data.get("status", "")).lower()
        state = {"printing": "PRINTING", "heating": "PRINTING", "pausing": "PAUSED", "pause": "PAUSED",
                 "ready": "CONNECTED", "completed": "CONNECTED", "cancel": "CONNECTED"}.get(raw, "ERROR")
        return snapshot(state, data, ("printFileName", "printProgress", 100, "estimatedTime", 1,
                                     "rightTemp", "rightTargetTemp", "platTemp", "platTargetTemp"))

    def upload(self, path, name):
        filename(name, ".gcode")
        self.detail()  # Model/auth gate before uploading any bytes.
        with path.open("rb") as source:
            if b"\x00" in source.read(8192): raise VendorError("FLASHFORGE requires plain printer-sliced G-code")
            source.seek(0)
            self.request("uploadGcode", headers={**self.auth(), "fileSize": str(path.stat().st_size),
                "printNow": "false", "levelingBeforePrint": "true", "useMatlStation": "false"},
                files={"gcodeFile": (name, source, "application/octet-stream")})
        return {"filename": name}

    def start(self, uploaded):
        if str(self.detail().get("status", "")).lower() not in ("ready", "completed", "cancel"):
            raise VendorError("FLASHFORGE is not idle; no new print was requested")
        self.request("printGcode", json={**self.auth(), "fileName": filename(uploaded["filename"], ".gcode"), "levelingBeforePrint": True})

    def action(self, action):
        expected = {"pause": "PAUSED", "resume": "PRINTING", "cancel": "CONNECTED"}[action]
        self.request("control", json={**self.auth(), "payload": {"cmd": "jobCtl_cmd", "args": {
            "jobID": "", "action": {"pause": "pause", "resume": "continue", "cancel": "cancel"}[action]}}})
        # /control reports dispatch even for ignored commands. Confirm state.
        for _ in range(12):
            if self.status()["connectionState"] == expected: return
            time.sleep(.5)
        raise VendorError("Command dispatched, but FLASHFORGE has not confirmed the requested state. Check the printer before retrying.")


def bambu_tls(profile):
    directory = os.getenv("XR3D_BAMBU_CERT_DIR", "")
    certificate = Path(directory) / f"{profile.serialNumber}.pem" if directory else None
    if certificate is None or not certificate.is_file():
        raise VendorError("Install this Bambu printer's trusted certificate in XR3D_BAMBU_CERT_DIR as SERIAL.pem")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Device certificates identify the serial, not its DHCP IP. Trust only the
    # owner's installed certificate rather than disabling certificate validation.
    context.check_hostname = False
    context.load_verify_locations(cafile=str(certificate))
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN  # Trust the pinned device leaf even if vendor-signed.
    return context


class BambuSession:
    def __init__(self, profile, context, client=None, timeout=15):
        import paho.mqtt.client as mqtt
        self.profile = profile
        self.timeout = timeout
        self.client = client or mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"xr3d-{uuid.uuid4().hex[:12]}", reconnect_on_failure=False)
        self.client.username_pw_set("bblp", profile.accessCode.get_secret_value())
        self.client.tls_set_context(context)
        self.client.tls_insecure_set(True)  # Skip IP-name matching; CERT_REQUIRED and the owner's CA file still apply.
        self.client.connect_timeout = 10
        self.ready = False; self.error = None
        self.replies = deque(maxlen=64); self.print_data = {}
        self.client.on_connect = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure: self.error = "Bambu authentication failed; check LAN mode and access code"
        else: client.subscribe(f"device/{self.profile.serialNumber}/report", qos=1)

    def on_subscribe(self, client, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons): self.error = "Bambu report subscription was rejected"
        else: self.ready = True

    def on_message(self, client, userdata, message):
        if message.topic != f"device/{self.profile.serialNumber}/report" or len(message.payload) > 1024 * 1024: return
        try: data = json.loads(message.payload).get("print")
        except (ValueError, AttributeError): return
        if isinstance(data, dict):
            self.print_data.update(data)  # Partial status pushes must retain earlier values.
            self.replies.append(data)

    def wait(self, predicate, timeout=None):
        timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error: raise VendorError(self.error)
            if predicate(): return
            if self.client.loop(timeout=.25) != 0: raise VendorError("Bambu MQTT connection was interrupted")
        raise VendorError("No Bambu acknowledgement received. Check printer state before retrying.")

    def connect(self):
        self.client.connect(self.profile.host, self.profile.port, keepalive=30)
        self.wait(lambda: self.ready)

    def close(self): self.client.disconnect()

    def publish(self, section, command, **fields):
        sequence = str(uuid.uuid4().int % 2147483646 + 1)
        result = self.client.publish(f"device/{self.profile.serialNumber}/request",
            json.dumps({section: {"sequence_id": sequence, "command": command, **fields}}), qos=1, retain=False)
        if result.rc != 0: raise VendorError("Bambu command could not be sent")
        return sequence

    def full_status(self):
        self.publish("pushing", "pushall")
        self.wait(lambda: "gcode_state" in self.print_data)
        return self.print_data

    def command(self, command, **fields):
        self.replies.clear()
        sequence = self.publish("print", command, **fields)
        def reply():
            return next((item for item in self.replies if item.get("command") == command and str(item.get("sequence_id")) == sequence), None)
        self.wait(lambda: reply() is not None)
        if str(reply().get("result", "")).upper() != "SUCCESS":
            raise VendorError("Bambu rejected the command. Check Developer Mode, printer state and the selected print file.")


class BambuFTPS(ftplib.FTP_TLS):
    """Implicit TLS and control-session reuse required by Bambu's FTPS service."""
    def connect(self, host="", port=990, timeout=60, source_address=None):
        self.host = host; self.port = port; self.timeout = timeout
        raw = socket.create_connection((host, port), timeout, source_address)
        try: self.sock = self.context.wrap_socket(raw, server_hostname=host)
        except BaseException: raw.close(); raise
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        connection, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        try:
            if self._prot_p:
                connection = self.context.wrap_socket(connection, server_hostname=self.host, session=self.sock.session)
        except BaseException: connection.close(); raise
        return connection, size


def bambu_package(path):
    try:
        with zipfile.ZipFile(path) as package:
            settings_info = package.getinfo("Metadata/project_settings.config")
            if settings_info.file_size > 1024 * 1024: raise VendorError("Invalid Bambu project settings")
            config = json.loads(package.read(settings_info))
            if not isinstance(config.get("filament_type"), list) or len(config["filament_type"]) != 1:
                raise VendorError("Only single-filament Bambu packages using the external spool are supported")
            plates = [info for info in package.infolist() if re.fullmatch(r"Metadata/plate_\d+\.gcode", info.filename)]
            if len(plates) != 1 or plates[0].filename != "Metadata/plate_1.gcode":
                raise VendorError("Export a sliced Bambu 3MF containing only plate 1")
            if plates[0].file_size > 256 * 1024 * 1024:
                raise VendorError("Bambu plate G-code exceeds size limit")
            digest = hashlib.md5()  # Device protocol checksum, not a security hash.
            with package.open(plates[0]) as source:
                head = source.read(8192)
                if not head or b"\x00" in head: raise VendorError("Package has no printable plate G-code")
                digest.update(head)
                while chunk := source.read(65536): digest.update(chunk)
            return digest.hexdigest()
    except (zipfile.BadZipFile, KeyError, ValueError, AttributeError) as error:
        raise VendorError("Select a sliced Bambu .gcode.3mf package, not a model-only 3MF") from error


class BambuAdapter:
    def __init__(self, profile):
        self.profile = profile

    def close(self): pass

    @contextmanager
    def session(self):
        session = BambuSession(self.profile, bambu_tls(self.profile))
        try:
            session.connect()
            yield session
        finally: session.close()

    def status(self):
        with self.session() as session: data = session.full_status()
        raw = str(data.get("gcode_state", "")).upper()
        state = {"IDLE": "CONNECTED", "FINISH": "CONNECTED", "RUNNING": "PRINTING", "PREPARE": "PRINTING",
                 "SLICING": "PRINTING", "PAUSE": "PAUSED", "FAILED": "ERROR"}.get(raw, "ERROR")
        return snapshot(state, data, ("gcode_file", "mc_percent", 1, "mc_remaining_time", 60,
                                     "nozzle_temper", "nozzle_target_temper", "bed_temper", "bed_target_temper"))

    def upload(self, path, name):
        filename(name, ".gcode.3mf")
        checksum = bambu_package(path)
        with BambuFTPS(context=bambu_tls(self.profile), timeout=60) as ftp:
            ftp.connect(self.profile.host, 990)
            ftp.login("bblp", self.profile.accessCode.get_secret_value())
            ftp.prot_p()
            with path.open("rb") as source: ftp.storbinary(f"STOR {name}", source, blocksize=65536)
            if ftp.size(name) != path.stat().st_size: raise VendorError("Bambu upload size was not confirmed")
        return {"filename": name, "md5": checksum}

    def start(self, uploaded):
        name = filename(uploaded["filename"], ".gcode.3mf")
        with self.session() as session:
            status = session.full_status()
            if status.get("gcode_state") not in ("IDLE", "FINISH", "FAILED"):
                raise VendorError("Bambu is not idle; no new print was requested")
            session.command("project_file", param="Metadata/plate_1.gcode", url=f"file:///sdcard/{name}",
                subtask_name=name, md5=uploaded["md5"], project_id="0", profile_id="0", task_id="0", subtask_id="0",
                bed_type="auto", timelapse=False, bed_leveling=True, flow_cali=False, vibration_cali=True,
                layer_inspect=False, use_ams=False)

    def action(self, action):
        with self.session() as session:
            session.command({"pause": "pause", "resume": "resume", "cancel": "stop"}[action], param="")


def adapter(profile):
    return BambuAdapter(profile) if profile.type == "BAMBU_LAB" else FlashforgeAdapter(profile)
