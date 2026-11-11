"""Protocol fixtures only: no tests contact a physical printer or cloud service."""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import socket
import ssl
import threading
import zipfile
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.routes import printers as routes
from backend.services import vendor_printers as vendors


def profile(kind="FLASHFORGE"):
    return vendors.VendorProfile(type=kind, host="192.168.1.20", port=8898 if kind == "FLASHFORGE" else 8883,
        serialNumber="XR3DTEST123", accessCode="12345678")


def package_bytes(filaments=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Metadata/project_settings.config", json.dumps({"filament_type": filaments or ["PLA"]}))
        archive.writestr("Metadata/plate_1.gcode", "; printer-sliced test fixture\nG1 X1 Y2 E1\n")
    return output.getvalue()


def detail(state="ready", **changes):
    result = {"pid": "23", "status": state, "printFileName": "part.gcode", "printProgress": .25,
              "estimatedTime": 120, "rightTemp": 205, "rightTargetTemp": 210, "platTemp": 59, "platTargetTemp": 60}
    result.update(changes)
    return {"code": 0, "detail": result}


def test_flashforge_authenticated_http_upload_start_control_and_telemetry(tmp_path):
    calls = []; state = "ready"
    def serve(request):
        nonlocal state
        calls.append(request)
        if request.url.path == "/uploadGcode":
            assert request.headers["checkcode"] == "12345678" and request.headers["printnow"] == "false"
            assert b'name="gcodeFile"' in request.content and b"G1 X1" in request.content
            return httpx.Response(200, json={"code": 0})
        data = json.loads(request.content)
        assert data["serialNumber"] == "XR3DTEST123" and data["checkCode"] == "12345678"
        if request.url.path == "/detail": return httpx.Response(200, json=detail(state))
        if request.url.path == "/printGcode":
            assert data["fileName"] == "part.gcode" and data["levelingBeforePrint"] is True
            state = "printing"
        elif request.url.path == "/control":
            assert data["payload"]["cmd"] == "jobCtl_cmd"
            state = {"pause": "pause", "continue": "printing", "cancel": "ready"}[data["payload"]["args"]["action"]]
        else: pytest.fail("Unexpected vendor endpoint")
        return httpx.Response(200, json={"code": 0})
    adapter = vendors.FlashforgeAdapter(profile(), httpx.MockTransport(serve))
    source = tmp_path / "part.gcode"; source.write_text("G1 X1 Y2 E1\n")
    uploaded = adapter.upload(source, source.name)
    assert len([r for r in calls if r.url.path == "/printGcode"]) == 0
    adapter.start(uploaded)
    status = adapter.status()
    assert status["connectionState"] == "PRINTING" and status["progressPercent"] == 25
    assert status["timeRemainingSeconds"] == 120 and status["toolActualC"] == 205
    for action in ("pause", "resume", "cancel"): adapter.action(action)
    assert adapter.status()["connectionState"] == "CONNECTED"
    adapter.close()


@pytest.mark.parametrize("response", [{"code": 1}, {"code": False}, {"detail": {}}, {"code": 0, "detail": {"pid": "26"}}])
def test_flashforge_auth_or_wrong_model_never_reports_success(response):
    adapter = vendors.FlashforgeAdapter(profile(), httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    with pytest.raises(vendors.VendorError): adapter.status()
    adapter.close()


def test_flashforge_unknown_state_is_not_ready():
    adapter = vendors.FlashforgeAdapter(profile(), httpx.MockTransport(lambda _: httpx.Response(200,json=detail("unknown"))))
    assert adapter.status()["connectionState"] == "ERROR"
    adapter.close()


def test_bambu_package_rejects_model_only_and_multi_filament(tmp_path):
    source = tmp_path / "part.gcode.3mf"; source.write_bytes(package_bytes())
    assert len(vendors.bambu_package(source)) == 32
    source.write_bytes(package_bytes(["PLA", "PETG"]))
    with pytest.raises(vendors.VendorError, match="single-filament"): vendors.bambu_package(source)
    source.write_bytes(b"not a sliced package")
    with pytest.raises(vendors.VendorError, match="sliced Bambu"): vendors.bambu_package(source)


def read_packet(connection):
    def read(count):
        result = b""
        while len(result) < count:
            chunk = connection.recv(count - len(result))
            if not chunk: raise EOFError("MQTT connection ended")
            result += chunk
        return result
    header = read(1)[0]; length = 0; multiplier = 1
    for _ in range(4):
        value = read(1)[0]; length += (value & 127) * multiplier
        if not value & 128: return header, read(length)
        multiplier *= 128
    raise ValueError("Malformed MQTT length")


def mqtt_publish(connection, serial, data):
    topic = f"device/{serial}/report".encode()
    payload = len(topic).to_bytes(2,"big") + topic + json.dumps({"print": data}).encode()
    length = len(payload); encoded = b""
    while True:
        digit = length % 128; length //= 128
        encoded += bytes([digit | (128 if length else 0)])
        if not length: break
    connection.sendall(b"\x30" + encoded + payload)


@contextmanager
def mqtt_fixture(reject=False, command_result="SUCCESS"):
    cert = Path(__file__).parent / "fixtures/lan-test-cert.pem"
    key = cert.with_name("lan-test-key.pem")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert,key)
    listener = socket.socket(); listener.bind(("127.0.0.1",0)); listener.listen(); listener.settimeout(5)
    errors = []; commands = []
    def serve():
        try:
            with listener.accept()[0] as raw:
                with tls.wrap_socket(raw,server_side=True) as connection:
                    connection.settimeout(5)
                    header, body = read_packet(connection)
                    assert header == 0x10 and b"bblp" in body and b"12345678" in body
                    connection.sendall(b"\x20\x02\x00" + (b"\x05" if reject else b"\x00"))
                    if reject: return
                    header, body = read_packet(connection); assert header == 0x82
                    connection.sendall(b"\x90\x03" + body[:2] + b"\x01")
                    while True:
                        header, body = read_packet(connection)
                        if header == 0xe0: return
                        if header >> 4 != 3: continue
                        topic_size = int.from_bytes(body[:2],"big")
                        assert body[2:2+topic_size] == b"device/XR3DTEST123/request"
                        offset = 2 + topic_size
                        if (header >> 1) & 3:
                            connection.sendall(b"\x40\x02" + body[offset:offset+2]); offset += 2
                        payload = json.loads(body[offset:]); commands.append(payload)
                        if "pushing" in payload:
                            mqtt_publish(connection,"XR3DTEST123",{"nozzle_temper":205})
                            mqtt_publish(connection,"XR3DTEST123",{"gcode_state":"IDLE","bed_temper":60})
                        else:
                            command = payload["print"]
                            # An unrelated stale success must not acknowledge the current command.
                            mqtt_publish(connection,"XR3DTEST123",{"command":command["command"],"sequence_id":"old","result":"SUCCESS"})
                            if command_result is not None:
                                mqtt_publish(connection,"XR3DTEST123",{"command":command["command"],"sequence_id":command["sequence_id"],"result":command_result})
        except (EOFError, ssl.SSLEOFError): pass
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=serve,daemon=True); thread.start()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); context.check_hostname=False; context.load_verify_locations(cert)
    target = profile("BAMBU_LAB").model_copy(update={"host":"127.0.0.1","port":listener.getsockname()[1]})
    try: yield target, context, commands
    finally:
        thread.join(6); listener.close()
        assert not thread.is_alive() and not errors, errors


def test_bambu_real_mqtt_tls_handshake_partial_status_and_correlated_ack():
    with mqtt_fixture() as (target, context, commands):
        session = vendors.BambuSession(target,context,timeout=3)
        try:
            session.connect()
            status = session.full_status()
            assert status["nozzle_temper"] == 205 and status["bed_temper"] == 60
            session.command("pause",param="")
        finally: session.close()
        assert commands[0]["pushing"]["command"] == "pushall"
        assert commands[1]["print"]["command"] == "pause"


def test_bambu_rejected_mqtt_credentials_fail():
    with mqtt_fixture(reject=True) as (target,context,_):
        session = vendors.BambuSession(target,context,timeout=3)
        try:
            with pytest.raises(vendors.VendorError): session.connect()
        finally: session.close()


def test_bambu_negative_command_ack_is_not_success():
    with mqtt_fixture(command_result="FAIL") as (target,context,_):
        session = vendors.BambuSession(target,context,timeout=3)
        try:
            session.connect()
            with pytest.raises(vendors.VendorError,match="rejected"): session.command("resume",param="")
        finally: session.close()


def test_bambu_requires_owner_trusted_certificate(monkeypatch):
    monkeypatch.delenv("XR3D_BAMBU_CERT_DIR",raising=False)
    with pytest.raises(vendors.VendorError,match="trusted certificate"): vendors.bambu_tls(profile("BAMBU_LAB"))


def test_stale_acknowledgement_does_not_report_command_success():
    with mqtt_fixture(command_result=None) as (target,context,_):
        session=vendors.BambuSession(target,context,timeout=.5)
        try:
            session.connect()
            with pytest.raises(vendors.VendorError,match="acknowledgement"): session.command("pause",param="")
        finally: session.close()


def test_pairing_checks_fingerprint_and_never_overwrites_trust(tmp_path):
    import hashlib
    from backend.printer_certificate import install
    pem=(Path(__file__).parent/"fixtures/lan-test-cert.pem").read_text()
    der=ssl.PEM_cert_to_DER_cert(pem)
    with pytest.raises(ValueError): install(der,"XR3DTEST123","0"*64,tmp_path)
    assert not list(tmp_path.iterdir())
    fingerprint=hashlib.sha256(der).hexdigest()
    path=install(der,"XR3DTEST123",fingerprint,tmp_path)
    assert ssl.PEM_cert_to_DER_cert(path.read_text())==der
    with pytest.raises(FileExistsError): install(der,"XR3DTEST123",fingerprint,tmp_path)


def test_bambu_upload_confirms_size_and_keeps_tls_verification(tmp_path,monkeypatch):
    source=tmp_path/"part.gcode.3mf"; source.write_bytes(package_bytes())
    cert=(Path(__file__).parent/"fixtures/lan-test-cert.pem").read_bytes()
    (tmp_path/"XR3DTEST123.pem").write_bytes(cert)
    monkeypatch.setenv("XR3D_BAMBU_CERT_DIR",str(tmp_path))
    operations=[]
    class FTP:
        def __init__(self,context,timeout): assert context.verify_mode==ssl.CERT_REQUIRED
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def connect(self,host,port): assert port==990
        def login(self,user,password): assert user=="bblp" and password=="12345678"
        def prot_p(self): operations.append("encrypted-data")
        def storbinary(self,command,stream,blocksize):
            assert operations==["encrypted-data"] and command=="STOR part.gcode.3mf"
            assert stream.read()==source.read_bytes(); operations.append("uploaded")
        def size(self,name): return 0
    monkeypatch.setattr(vendors,"BambuFTPS",FTP)
    with pytest.raises(vendors.VendorError,match="size"): vendors.BambuAdapter(profile("BAMBU_LAB")).upload(source,source.name)
    assert operations==["encrypted-data","uploaded"]


def test_bambu_start_requires_real_ack_and_uses_uploaded_plate_checksum(monkeypatch):
    with mqtt_fixture() as (target,context,commands):
        monkeypatch.setattr(vendors,"bambu_tls",lambda _:context)
        adapter=vendors.BambuAdapter(target)
        adapter.start({"filename":"part.gcode.3mf","md5":"a"*32})
        start=commands[-1]["print"]
        assert start["command"]=="project_file" and start["param"]=="Metadata/plate_1.gcode"
        assert start["url"]=="file:///sdcard/part.gcode.3mf" and start["md5"]=="a"*32
        assert start["use_ams"] is False and start["bed_leveling"] is True


def test_bambu_ftps_implicit_tls_encrypted_data_and_session_reuse():
    cert=Path(__file__).parent/"fixtures/lan-test-cert.pem"; key=cert.with_name("lan-test-key.pem")
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.maximum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert,key)
    listener=socket.socket(); listener.bind(("127.0.0.1",0)); listener.listen(); listener.settimeout(5)
    errors=[]; transferred=[]; reused=[]
    def serve():
        passive=None
        try:
            with listener.accept()[0] as raw:
                with tls.wrap_socket(raw,server_side=True) as control:
                    control.settimeout(5); stream=control.makefile("rb")
                    control.sendall(b"220 FTPS fixture\r\n")
                    while True:
                        line=stream.readline().decode().strip()
                        if not line: break
                        command,_,arg=line.partition(" ")
                        if command=="USER":
                            assert arg=="bblp"; control.sendall(b"331 Password\r\n")
                        elif command=="PASS":
                            assert arg=="12345678"; control.sendall(b"230 Logged in\r\n")
                        elif command in ("PBSZ","PROT","TYPE"):
                            control.sendall(b"200 Accepted\r\n")
                        elif command=="PASV":
                            passive=socket.socket(); passive.bind(("127.0.0.1",0)); passive.listen(); passive.settimeout(5)
                            port=passive.getsockname()[1]
                            control.sendall(f"227 Passive (127,0,0,1,{port//256},{port%256})\r\n".encode())
                        elif command=="STOR":
                            assert arg=="part.gcode.3mf"
                            control.sendall(b"150 Send data\r\n")
                            with passive.accept()[0] as data_raw:
                                data_raw.settimeout(5)
                                with tls.wrap_socket(data_raw,server_side=True) as data:
                                    reused.append(data.session_reused)
                                    chunks=[]
                                    while chunk:=data.recv(4096): chunks.append(chunk)
                                    transferred.append(b"".join(chunks)); data.unwrap()
                            passive.close(); passive=None
                            control.sendall(b"226 Transfer complete\r\n")
                        elif command=="SIZE": control.sendall(f"213 {len(transferred[0])}\r\n".encode())
                        elif command=="QUIT":
                            control.sendall(b"221 Bye\r\n"); break
                        else: raise AssertionError(f"Unexpected FTPS command {command}")
        except Exception as error: errors.append(error)
        finally:
            if passive: passive.close()
    thread=threading.Thread(target=serve,daemon=True); thread.start()
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); context.check_hostname=False
    context.load_verify_locations(cert); context.maximum_version=ssl.TLSVersion.TLSv1_2
    payload=package_bytes()
    try:
        with vendors.BambuFTPS(context=context,timeout=5) as ftp:
            ftp.connect("127.0.0.1",listener.getsockname()[1],timeout=5)
            ftp.login("bblp","12345678"); ftp.prot_p()
            ftp.storbinary("STOR part.gcode.3mf",io.BytesIO(payload))
            assert ftp.size("part.gcode.3mf")==len(payload)
    finally:
        thread.join(6); listener.close()
        assert not thread.is_alive() and not errors, errors
    assert transferred==[payload] and reused==[True]


def test_bridge_auth_redaction_upload_receipt_and_no_replay(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"API_TOKEN","test-token"); monkeypatch.setattr(settings,"DATA_DIR",tmp_path)
    routes.receipts.clear(); routes.device_locks.clear()
    calls = []
    class Adapter:
        def close(self): pass
        def status(self): return {"connectionState":"CONNECTED"}
        def upload(self,path,name):
            assert path.read_bytes() == b"G1 X1\n"; calls.append("upload")
            return {"filename":name}
        def start(self,item): calls.append("start")
        def action(self,action): calls.append(action)
    monkeypatch.setattr(routes,"adapter",lambda _:Adapter())
    client=TestClient(app)
    raw = profile().model_dump(mode="json"); raw["accessCode"]="12345678"
    assert client.post("/api/v1/printers/vendor/status",json=raw).status_code==401
    client.headers["Authorization"]="Bearer test-token"
    wrong={**raw,"port":1}
    response=client.post("/api/v1/printers/vendor/status",json=wrong)
    assert response.status_code==422 and "12345678" not in response.text
    response=client.post("/api/v1/printers/vendor/upload",data={"profile":json.dumps(raw)},files={"file":("part.gcode",b"G1 X1\n")})
    assert response.status_code==200
    receipt=response.json()["receipt"]; assert calls==["upload"]
    assert client.post("/api/v1/printers/vendor/start",json={"profile":{**raw,"host":"192.168.1.21"},"receipt":receipt}).status_code==409
    assert client.post("/api/v1/printers/vendor/start",json={"profile":raw,"receipt":receipt}).status_code==200
    assert client.post("/api/v1/printers/vendor/start",json={"profile":raw,"receipt":receipt}).status_code==409
    assert calls==["upload","start"] and not list(tmp_path.glob("printer-*"))
    assert "12345678" not in repr(routes.receipts)
    client.close()
