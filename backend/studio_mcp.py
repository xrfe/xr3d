"""Start the local XR3D MCP server over standard input and output."""
import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from dotenv import load_dotenv
from backend.services.print_engine import ROOT, python_path, worker_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "backend-data" / "mcp-models")
    parser.add_argument("--printers", type=Path, help="JSON file of named printer profiles owned by this server")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    token = os.getenv("XR3D_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("Configure the XR3D API access token first.")
    api = urlsplit(args.api)
    if (api.scheme not in {"http", "https"} or not api.hostname or api.username or api.password or
            api.query or api.fragment or api.scheme == "http" and api.hostname not in {"127.0.0.1", "::1", "localhost"}):
        raise SystemExit("Use a loopback HTTP URL or an HTTPS XR3D API URL.")
    python = python_path()
    if not python.is_file():
        raise SystemExit("Install the XR3D print engine with python -m backend.install_print_engine.")
    environment = worker_environment()
    environment.update(XR3D_MCP_API=args.api.rstrip("/"), XR3D_MCP_TOKEN=token,
                       XR3D_MCP_MODELS=str(args.model_dir.resolve()))
    if args.printers:
        environment["XR3D_MCP_PRINTERS"] = str(args.printers.resolve())
    worker = ROOT / "backend" / "workers" / "studio_mcp.py"
    raise SystemExit(subprocess.run([str(python), "-I", str(worker)], env=environment, check=False).returncode)


if __name__ == "__main__":
    main()
