"""Local annual-summary image archive; no shell, subprocess or remote service."""
from pathlib import Path
import re
import zipfile
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..app_paths import get_output_dir

router=APIRouter()
class BatchRequest(BaseModel):
    batch_id:str

@router.post("/api/offline/wrapped/zip")
def zip_wrapped_batch(request:BatchRequest):
    if not re.fullmatch(r"wb_[0-9a-f]{24}",request.batch_id):
        raise HTTPException(400,"Invalid local batch")
    root=get_output_dir()/"年度总结"
    directory=root/request.batch_id
    files=sorted(directory.glob("*.png"))
    if not files or len(files)>100 or sum(p.stat().st_size for p in files)>512*1024*1024:
        raise HTTPException(400,"Invalid batch size")
    destination=root/(request.batch_id+".zip")
    created=False
    try:
        with zipfile.ZipFile(destination,"x",compression=zipfile.ZIP_DEFLATED) as archive:
            created=True
            for p in files:
                archive.write(p,p.name)
    except BaseException:
        if created: destination.unlink(missing_ok=True)
        raise
    return {"ok":True,"path":str(destination),"count":len(files)}
