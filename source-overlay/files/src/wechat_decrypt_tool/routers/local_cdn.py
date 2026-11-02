from fastapi import APIRouter
from pydantic import BaseModel,Field
from .. import local_cdn
from ..media_helpers import _resolve_account_dir

router=APIRouter(prefix='/api/offline/originals')

class Settings(BaseModel):
    enabled:bool=False

class Original(BaseModel):
    account:str=Field(min_length=1,max_length=160)
    server_id:int=Field(ge=-(2**63),lt=2**64)
    username:str=Field(min_length=1,max_length=256)
    md5:str=Field(default='',max_length=32)

@router.get('/settings')
def settings():
    return local_cdn.settings()

@router.put('/settings')
def save_settings(request:Settings):
    return local_cdn.save_settings(request.enabled)

@router.post('/image')
def original(request:Original):
    try:
        return local_cdn.original(_resolve_account_dir(request.account),request.server_id,request.username,request.md5)
    except Exception:
        return {'ok':False,'status':'unavailable','message':'原图暂不可用，正在显示本地图片'}
