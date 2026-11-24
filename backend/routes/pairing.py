"""One-time setup for a phone on the studio's local network."""
from ipaddress import IPv4Address, IPv4Network
import secrets
from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.config import settings

SERVICE_TYPE = "_xr3d._tcp.local."
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LAN_NETWORKS = tuple(map(IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
router = APIRouter(tags=["Server setup"])


def is_lan_address(host: str, *, loopback: bool = False) -> bool:
    try:
        address = IPv4Address(host)
    except ValueError:
        return False
    return (loopback and address.is_loopback) or any(address in network for network in LAN_NETWORKS)


class LanPairing:
    def __init__(self):
        self.code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        self.expires = monotonic() + 600
        self.attempts = 12
        self.lock = Lock()

    @property
    def display_code(self):
        return "-".join(self.code[index:index + 4] for index in range(0, len(self.code), 4))

    def claim(self, code):
        normalized = code.replace("-", "").replace(" ", "").upper()
        with self.lock:
            if self.attempts <= 0 or monotonic() >= self.expires:
                return False
            self.attempts -= 1
            if not normalized.isascii() or not secrets.compare_digest(normalized, self.code):
                return False
            self.attempts = 0
            return True


class PairingRequest(BaseModel):
    code: str = Field(min_length=1, max_length=24)


@router.post("/pair")
async def pair(request: Request, setup: PairingRequest, response: Response):
    pairing = getattr(request.app.state, "lan_pairing", None)
    if pairing is None or not request.client or not is_lan_address(request.client.host, loopback=True):
        raise HTTPException(404, "Server setup is unavailable. Open Start XR3D Server on the PC.")
    if not settings.API_TOKEN or not pairing.claim(setup.code):
        raise HTTPException(403, "Check the setup code. If it expired or was used, restart XR3D Server for a new code.")
    response.headers["Cache-Control"] = "no-store"
    return {"serverToken": settings.API_TOKEN}
