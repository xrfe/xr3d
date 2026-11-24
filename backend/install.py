"""Install XR3D and its workers into the current Python 3.12 virtual environment."""
import argparse
from hashlib import file_digest
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CALCULIX_URL = "https://www.dhondt.de/calculix_2.24_4win.zip"
CALCULIX_SHA256 = "8c22c627a2e134b988121a9028a4b0c20fa9aa834448c94040c5cefadee49905"
CALCULIX_MEMBER = "calculix_2.24_4win/ccx_i4_static.exe"


def install_python():
    if sys.prefix == sys.base_prefix or sys.version_info[:2] != (3, 12):
        raise SystemExit("Run the XR3D installer with Python 3.12 inside a virtual environment.")
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
    # Source builds can invoke `python` by name even when the venv was not activated.
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), env.get("PATH", "")))
    subprocess.run([*pip, "install", "--require-virtualenv", "-r", str(ROOT / "backend/requirements.lock.txt")],
                   cwd=ROOT, env=env, check=True)
    subprocess.run([*pip, "check"], cwd=ROOT, check=True)


def install_calculix(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    print("Installing CalculiX 2.24 from its upstream Windows release…", flush=True)
    with TemporaryDirectory(dir=target.parent) as directory:
        archive_path = Path(directory) / "calculix.zip"
        with urlopen(CALCULIX_URL, timeout=45) as response, archive_path.open("wb") as archive:
            total = 0
            while chunk := response.read(65_536):
                total += len(chunk)
                if total > 64 * 1024 * 1024:
                    raise ValueError("CalculiX download exceeded the expected archive size")
                archive.write(chunk)
        with archive_path.open("rb") as archive:
            if file_digest(archive, "sha256").hexdigest() != CALCULIX_SHA256:
                raise ValueError("CalculiX download failed checksum verification")
        executable = Path(directory) / target.name
        with ZipFile(archive_path) as archive, archive.open(CALCULIX_MEMBER) as source, executable.open("wb") as output:
            shutil.copyfileobj(source, output)
        executable.replace(target)


def configure_runtime():
    from dotenv import load_dotenv
    from backend.services.fem import managed_solver_path, solver_executable

    config = ROOT / ".env"
    if not config.exists():
        template = (ROOT / ".env.example").read_bytes()
        try:
            with config.open("xb") as output:
                output.write(template)
        except FileExistsError:
            pass
    load_dotenv(config)

    if solver_executable() is None and sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}:
        install_calculix(managed_solver_path())
    if solver_executable() is None:
        print("FEM needs CalculiX. Install ccx and put it on PATH or set XR3D_CCX_EXECUTABLE in .env.")
        if sys.platform.startswith("linux"):
            print("On Debian or Ubuntu, run sudo apt install calculix-ccx libglu1-mesa.")
    else:
        try:
            import gmsh  # noqa: F401
        except (ImportError, OSError):
            print("Gmsh could not load. On Debian or Ubuntu, install the system package libglu1-mesa.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-only", action="store_true", help="Install the shared Python packages only")
    args = parser.parse_args()
    try:
        install_python()
        if not args.python_only:
            configure_runtime()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"XR3D setup stopped: {error}") from error
    print("XR3D setup complete. Open Start XR3D Server to launch the backend.")


if __name__ == "__main__":
    main()
