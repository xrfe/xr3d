"""Install the default XR3D print engine in its own Python environment."""
import os
from pathlib import Path
import subprocess
import venv
from backend.services.print_engine import ROOT, ENVIRONMENT


def main():
    source = ROOT / "external" / "Kiln-main" / "kiln"
    if not (source / "pyproject.toml").is_file():
        raise SystemExit("The bundled XR3D print engine source is missing.")
    executable = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        venv.EnvBuilder(with_pip=True).create(ENVIRONMENT)
    subprocess.run([str(executable), "-m", "pip", "install", "--disable-pip-version-check",
                    "--constraint", str(Path(__file__).with_name("requirements.print.lock.txt")),
                    str(source)], cwd=ROOT, check=True)
    print("XR3D Print Engine is installed. Start the studio API with python -m backend.serve.")


if __name__ == "__main__":
    main()
