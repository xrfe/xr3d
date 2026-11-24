"""Start the private studio API: python -m backend.serve [--host 0.0.0.0]."""
import argparse
from contextlib import ExitStack
from ipaddress import IPv4Address
import logging
import os
from pathlib import Path
import re
import secrets
import socket
from dotenv import load_dotenv


def lan_addresses(host):
    from backend.routes.pairing import is_lan_address

    if host != "0.0.0.0":
        return [IPv4Address(host)] if is_lan_address(host) else []
    from ifaddr import get_adapters

    return sorted({IPv4Address(interface.ip) for adapter in get_adapters()
                   for interface in adapter.ips if interface.is_IPv4 and is_lan_address(interface.ip)})


def advertise_lan(stack, app, host, port):
    from backend.routes.pairing import LanPairing, SERVICE_TYPE

    try:
        addresses = lan_addresses(host)
    except OSError:
        addresses = []
    if not addresses:
        return
    pairing = LanPairing()
    app.state.lan_pairing = pairing
    stack.callback(delattr, app.state, "lan_pairing")
    print("On your phone, open XR3D Settings > Find XR3D Server.", flush=True)
    print(f"One-time setup code (valid for 10 minutes): {pairing.display_code}", flush=True)
    for address in addresses:
        print(f"  http://{address}:{port}", flush=True)
    print("If discovery is unavailable, enter one of the addresses above in Find XR3D Server.", flush=True)
    try:
        from zeroconf import IPVersion, ServiceInfo, Zeroconf

        name = re.sub(r"[^a-zA-Z0-9-]", "-", socket.gethostname())[:32].strip("-") or "PC"
        service = ServiceInfo(SERVICE_TYPE, f"XR3D Server - {name}.{SERVICE_TYPE}",
                              addresses=[address.packed for address in addresses], port=port,
                              properties={"version": "1"}, server=f"{name}-xr3d.local.")
        zeroconf = stack.enter_context(Zeroconf(interfaces=[str(address) for address in addresses],
                                               ip_version=IPVersion.V4Only))
        zeroconf.register_service(service, allow_name_change=True)
        stack.callback(zeroconf.unregister_service, service)
    except Exception as error:
        logging.getLogger(__name__).warning("LAN discovery could not start (%s). Use a server address.",
                                            type(error).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    env_path = Path(".env")
    load_dotenv(env_path)
    if not os.getenv("XR3D_API_TOKEN"):
        token = secrets.token_urlsafe(32)
        with env_path.open("a", encoding="utf-8") as stream:
            stream.write(f"\nXR3D_API_TOKEN={token}\n")
        os.environ["XR3D_API_TOKEN"] = token
        print("A server access token was saved to .env for manual setup.")
    if not (os.getenv("XR3D_LOCAL_COMMAND") or os.getenv("FAL_KEY") or os.getenv("MESHY_API_KEY")):
        print("No server inference key/runtime configured. Set XR3D_LOCAL_COMMAND, FAL_KEY, or MESHY_API_KEY; Meshy users can also supply their own key in the app.")
    from backend.services.print_engine import EngineError, run_engine
    try:
        run_engine("health", timeout=10)
        print("XR3D Print Engine is ready for server discovery, model checks, and printer fallback.")
    except EngineError:
        print("XR3D Print Engine is unavailable. Run Install XR3D Server to set it up.")
    from backend.services.fem import fem_dependencies_available, solver_executable
    if fem_dependencies_available() and solver_executable():
        print("FEM is ready. Open a model in XR3D and select FEA XR.", flush=True)
    else:
        print("FEM setup is incomplete. Run Install XR3D Server and check CalculiX availability.", flush=True)
    import uvicorn
    from backend.main import app

    with ExitStack() as stack:
        advertise_lan(stack, app, args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, workers=1)

if __name__ == "__main__":
    main()
