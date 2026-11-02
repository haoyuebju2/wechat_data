from fastapi import APIRouter,Query,Request,HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import json
from pydantic import BaseModel,Field
from typing import Literal
from .. import local_cdn
from ..offline_originals import AUTO_ORIGINALS
from ..media_helpers import _resolve_account_dir

router=APIRouter(prefix='/api/offline/originals')

class Settings(BaseModel):
    enabled:bool=False
    auto_mode:Literal['off','all','selected']|None=None
    conversations:dict[str,list[str]]|None=None

class Original(BaseModel):
    account:str=Field(min_length=1,max_length=160)
    server_id:int=Field(ge=-(2**63),lt=2**64)
    username:str=Field(min_length=1,max_length=256)
    md5:str=Field(default='',max_length=32)

class HistorySeen(BaseModel):
    through:dict[str,int]=Field(max_length=32)

@router.get('/history/summary')
def history_summary():
    return AUTO_ORIGINALS.history_summary()

@router.get('/history')
def history(limit:int=Query(default=50,ge=1,le=100),cursor:str|None=Query(default=None,max_length=2048)):
    try:return AUTO_ORIGINALS.history(limit,cursor)
    except ValueError:raise HTTPException(status_code=400,detail='Invalid history cursor') from None

@router.post('/history/seen')
def history_seen(request:HistorySeen):
    if any(value<0 or value>2**63-1 for value in request.through.values()):
        raise HTTPException(status_code=400,detail='Invalid history boundary')
    return AUTO_ORIGINALS.mark_history_seen(request.through)

@router.delete('/history')
def clear_history():
    return AUTO_ORIGINALS.clear_history()

@router.get('/history/events')
async def history_events(request:Request):
    async def events():
        revision=AUTO_ORIGINALS.history_revision()
        yield 'data: '+json.dumps({'revision':revision})+'\n\n'
        while not await request.is_disconnected() and not AUTO_ORIGINALS._stop.is_set():
            changed=await asyncio.to_thread(AUTO_ORIGINALS.wait_history,revision,10)
            if changed!=revision:
                revision=changed
                yield 'data: '+json.dumps({'revision':revision})+'\n\n'
            else:yield ': keepalive\n\n'
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

@router.get('/settings')
def settings():
    return {**local_cdn.settings(),'queue':AUTO_ORIGINALS.summary()}

@router.put('/settings')
def save_settings(request:Settings):
    from fastapi import HTTPException
    try:return local_cdn.save_settings(request.enabled,request.auto_mode,request.conversations)
    except ValueError:raise HTTPException(status_code=400,detail='Invalid original-image scope') from None

@router.post('/image')
def original(request:Original):
    try:
        return local_cdn.original(_resolve_account_dir(request.account),request.server_id,request.username,request.md5)
    except Exception:
        return {'ok':False,'status':'unavailable','message':'原图暂不可用，正在显示本地图片'}
