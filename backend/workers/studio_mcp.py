"""The XR3D-branded local MCP tools call the authenticated studio API."""
import json
import os
from pathlib import Path
from typing import Any
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

server = MCPServer("XR3D", title="XR3D Studio", instructions="Inspect models and read printer status from your XR3D studio.")
read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
max_model_bytes = 24 * 1024 * 1024


def request(method, path, **kwargs):
    try:
        with httpx.Client(base_url=os.environ["XR3D_MCP_API"], timeout=70, trust_env=False, follow_redirects=False,
                          headers={"Authorization": f"Bearer {os.environ['XR3D_MCP_TOKEN']}"}) as client:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as error:
        raise ToolError(f"XR3D API returned HTTP {error.response.status_code}.") from None
    except (httpx.HTTPError, ValueError):
        raise ToolError("Could not read the XR3D API response.") from None


@server.tool(annotations=read_only, structured_output=True)
def discover_printers() -> list[dict[str, Any]]:
    """Find printers advertising on the XR3D server's local network."""
    return request("GET", "print-engine/discover")


@server.tool(annotations=read_only, structured_output=True)
def printer_status(name: str) -> dict[str, Any]:
    """Read the status of a printer listed in the owner's XR3D MCP configuration."""
    configured = os.getenv("XR3D_MCP_PRINTERS")
    if not configured:
        raise ToolError("Configure a named printer file when launching XR3D MCP.")
    try:
        with Path(configured).open("rb") as stream:
            profiles = json.loads(stream.read(65_536))
        profile = profiles[name]
        if not isinstance(profile, dict):
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError):
        raise ToolError("No valid XR3D printer profile was found for that name.") from None
    return request("POST", "printers/vendor/status", json=profile)


@server.tool(annotations=read_only, structured_output=True)
def inspect_stl(filename: str, nozzle_mm: float = 0.4) -> dict[str, Any]:
    """Analyze an STL saved inside the model directory shared with XR3D MCP."""
    root = Path(os.environ["XR3D_MCP_MODELS"])
    source = (root / filename).resolve()
    if not source.is_relative_to(root) or source.suffix.lower() != ".stl" or not source.is_file():
        raise ToolError("Select an STL inside the configured XR3D model directory.")
    if not 1 <= source.stat().st_size <= max_model_bytes:
        raise ToolError("The STL must be nonempty and no larger than 24 MB.")
    if not 0.1 <= nozzle_mm <= 2:
        raise ToolError("Use a nozzle diameter between 0.1 and 2 mm.")
    with source.open("rb") as model:
        return request("POST", "print-engine/inspect", files={"model": (source.name, model, "application/octet-stream")},
                       data={"config": json.dumps({"nozzleMm": nozzle_mm})})


if __name__ == "__main__":
    server.run("stdio")
