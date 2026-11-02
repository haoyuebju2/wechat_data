from fastapi import APIRouter
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
