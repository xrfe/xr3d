import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config import settings

server_token = HTTPBearer(scheme_name="XR3D Server Token", auto_error=False,
                          description="Enter the XR3D server access token.")


def require_token(authorization: Annotated[HTTPAuthorizationCredentials | None, Security(server_token)]):
    if not settings.API_TOKEN:
        raise HTTPException(503, "Set XR3D_API_TOKEN on the server before using the API")
    header = f"{authorization.scheme} {authorization.credentials}" if authorization else ""
    if not secrets.compare_digest(header, f"Bearer {settings.API_TOKEN}"):
        raise HTTPException(401, "Invalid server access token", headers={"WWW-Authenticate": "Bearer"})
