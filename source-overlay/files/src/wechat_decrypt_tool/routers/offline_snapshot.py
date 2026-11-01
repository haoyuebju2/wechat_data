import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..offline_snapshot import SNAPSHOTS

router = APIRouter()

class RefreshRequest(BaseModel):
    account: str

@router.get("/api/offline/snapshot/status")
def snapshot_status(account: str):
    try:
        return SNAPSHOTS.status(account)
    except ValueError:
        raise HTTPException(400, "Invalid account") from None

@router.post("/api/offline/snapshot/refresh")
def snapshot_refresh(request: RefreshRequest):
    try:
        return SNAPSHOTS.request(request.account)
    except ValueError:
        raise HTTPException(400, "Invalid account") from None

@router.get("/api/offline/snapshot/events")
async def snapshot_events(request: Request, account: str):
    try:
        initial = SNAPSHOTS.status(account)
    except ValueError:
        raise HTTPException(400, "Invalid account") from None
    async def events():
        status = initial
        yield "retry: 1000\n\n"
        while not SNAPSHOTS.stopped and not await request.is_disconnected():
            yield "data: " + json.dumps(status, ensure_ascii=False) + "\n\n"
            status = await asyncio.to_thread(SNAPSHOTS.wait_status, account, status["revision"])
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
