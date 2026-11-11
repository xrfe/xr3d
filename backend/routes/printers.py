"""Authenticated, bounded LAN bridge. Credentials never persist in the server."""
import asyncio
import ftplib
import httpx
from collections import OrderedDict
import tempfile
from pathlib import Path
import time
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from backend.config import settings
from backend.security import require_token
from backend.services.vendor_printers import VendorProfile, VendorError, adapter, filename

router = APIRouter(prefix="/printers/vendor", tags=["Vendor printers"], dependencies=[Depends(require_token)])
capacity = asyncio.Semaphore(4)
# Receipts contain only target identity + remote filename/checksum, never credentials.
receipts = OrderedDict()
device_locks = {}


class StartRequest(BaseModel):
    profile: VendorProfile
    receipt: str


class ActionRequest(BaseModel):
    profile: VendorProfile
    action: Literal["pause", "resume", "cancel"]


async def perform(profile, operation):
    # A per-target lock prevents polling and physical commands racing each other.
    key = profile.identity()
    if key not in device_locks and len(device_locks) >= 32:
        raise HTTPException(429, "Printer bridge target limit reached; restart the private server to clear it")
    lock = device_locks.setdefault(key, asyncio.Lock())
    def run():
        device = adapter(profile)
        try: return operation(device)
        finally: device.close()
    try:
        async with capacity, lock:
            # Thread work must finish before releasing its device lock, including
            # when a phone disconnects. Never retry a command automatically.
            task = asyncio.create_task(asyncio.to_thread(run))
            try: return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
    except VendorError as error:
        raise HTTPException(502, str(error)) from error
    except (OSError, ValueError, RuntimeError, ftplib.Error, httpx.HTTPError) as error:
        raise HTTPException(502, "Printer transport failed. Check LAN connectivity, credentials, certificate and printer state before retrying.") from error


@router.post("/status")
async def status(profile: VendorProfile):
    return await perform(profile, lambda device: device.status())


@router.post("/upload")
async def upload(profile: str = Form(...), file: UploadFile = File(...)):
    try:
        try: target = VendorProfile.model_validate_json(profile)
        except ValidationError as error: raise HTTPException(422, "Invalid vendor printer configuration") from error
        suffix = ".gcode.3mf" if target.type == "BAMBU_LAB" else ".gcode"
        try: filename(file.filename or "", suffix)
        except VendorError as error: raise HTTPException(422, str(error)) from error
        now = time.monotonic()
        for key in list(receipts):
            if receipts[key][0] < now: receipts.pop(key)
        if len(receipts) >= 128: raise HTTPException(429, "Too many pending printer uploads; start a job or wait for receipts to expire")
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="printer-", dir=settings.DATA_DIR) as folder:
            source = Path(folder) / ("input" + suffix)
            size = 0
            with source.open("wb") as output:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > settings.MAX_MODEL_BYTES: raise HTTPException(413, "Printer file exceeds 256 MB")
                    output.write(chunk)
            if not size: raise HTTPException(422, "Printer file is empty")
            remote_name = f"xr3d_{uuid.uuid4().hex}{suffix}"
            uploaded = await perform(target, lambda device: device.upload(source, remote_name))
        receipt = uuid.uuid4().hex
        receipts[receipt] = (time.monotonic() + 3600, target.identity(), uploaded)
        return {"receipt": receipt, "filename": uploaded["filename"]}
    finally: await file.close()


@router.post("/start")
async def start(request: StartRequest):
    item = receipts.get(request.receipt)
    if item is None or item[0] < time.monotonic() or item[1] != request.profile.identity():
        raise HTTPException(409, "Upload receipt expired or belongs to another printer; upload the file again")
    # Consume before contacting the printer: an ambiguous timeout cannot later
    # replay the same physical command. Check printer state before uploading again.
    receipts.pop(request.receipt)
    await perform(request.profile, lambda device: device.start(item[2]))
    return {"accepted": True}


@router.post("/action")
async def action(request: ActionRequest):
    await perform(request.profile, lambda device: device.action(request.action))
    return {"accepted": True}
