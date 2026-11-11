import secrets
from fastapi import Header, HTTPException
from backend.config import settings

def require_token(authorization: str | None = Header(default=None)):
    if not settings.API_TOKEN:
        raise HTTPException(503, "Set XR3D_API_TOKEN on the server before using the API")
    if not secrets.compare_digest(authorization or "", f"Bearer {settings.API_TOKEN}"):
        raise HTTPException(401, "Invalid server access token", headers={"WWW-Authenticate": "Bearer"})
