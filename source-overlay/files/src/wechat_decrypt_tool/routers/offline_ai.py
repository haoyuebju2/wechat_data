from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .. import offline_ai as ai

router = APIRouter(prefix="/api/offline/ai")

class Settings(BaseModel):
    enabled: bool = False
    base_url: str = Field(max_length=200)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=2048)

class Message(BaseModel):
    role: str = Field(max_length=20)
    content: str = Field(max_length=100000)

class Conversation(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)

class Grant(BaseModel):
    text: str = Field(max_length=ai.MAX_TEXT)
    cloud_ack: bool = False

def guarded(operation):
    try:
        return operation()
    except Exception:
        # Never echo provider errors, private payloads, keys or file paths.
        raise HTTPException(400, "操作未完成：请检查本机模型配置、授权状态或输入内容。") from None

@router.get("/settings")
def settings():
    return guarded(ai.public_settings)

@router.put("/settings")
def save(request: Settings):
    return guarded(lambda: ai.save_settings(**request.model_dump()))

@router.post("/chat")
def chat(request: Conversation):
    return guarded(lambda: {"content": ai.local_completion([item.model_dump() for item in request.messages])})

@router.get("/grant")
def grant_status():
    return guarded(ai.grant_status)

@router.post("/grant")
def grant(request: Grant):
    return guarded(lambda: ai.create_grant(request.text, request.cloud_ack))

@router.delete("/grant")
def revoke():
    return guarded(ai.revoke_grant)
