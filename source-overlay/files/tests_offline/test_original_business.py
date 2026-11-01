"""Actual original-source readers/exporters, with the original synthetic fixture."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("synthetic_upstream_fixture",ROOT/"tests/test_chat_export_message_types_semantics.py")
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


@pytest.fixture
def account(tmp_path,monkeypatch):
    helper=fixture.TestChatExportMessageTypesSemantics()
    directory=helper._prepare_account(tmp_path,account="wxid_test",username="wxid_friend")
    monkeypatch.setenv("WECHAT_TOOL_DATA_DIR",str(tmp_path))
    monkeypatch.delenv("WECHAT_TOOL_OUTPUT_DIR",raising=False)
    return helper,directory


def test_original_api_reads_synthetic_messages_with_offline_auth(account):
    from test_offline_policy import request
    response=request("/api/chat/messages?account=wxid_test&username=wxid_friend&source=decrypted&limit=50")
    assert response.status_code==200,response.text
    payload=response.json()
    assert len(payload["messages"])==7
    assert any("普通文本消息" in str(item) for item in payload["messages"])


def test_wrapped_batch_local_zip_and_path_boundary(account,monkeypatch):
    from test_offline_policy import request
    from wechat_decrypt_tool.app_paths import get_output_dir
    batch_id="wb_"+"a"*24
    directory=get_output_dir()/"年度总结"/batch_id
    directory.mkdir(parents=True)
    (directory/"synthetic.png").write_bytes(b"synthetic-png-not-private")
    response=request("/api/offline/wrapped/zip",method="POST",data={"batch_id":batch_id})
    assert response.status_code==200,response.text
    with zipfile.ZipFile(response.json()["path"]) as archive:
        assert archive.namelist()==["synthetic.png"]
    assert request("/api/offline/wrapped/zip",method="POST",data={"batch_id":"../../private"}).status_code==400


@pytest.mark.parametrize("format_name",["json","txt","html","excel"])
def test_original_exports_complete_locally_in_all_four_formats(account,format_name):
    helper,directory=account
    module=helper._reload_export_modules()
    job=module.CHAT_EXPORT_MANAGER.create_job(account="wxid_test",source="decrypted",scope="selected",usernames=["wxid_friend"],
        export_format=format_name,start_time=None,end_time=None,include_hidden=False,include_official=False,
        include_media=True,media_kinds=["image","video","video_thumb"],message_types=[],output_dir=None,
        allow_process_key_extract=False,download_remote_media=False,privacy_mode=False,file_name=None,html_page_size=2)
    deadline=time.monotonic()+15
    while job.status not in {"done","error","cancelled"} and time.monotonic()<deadline:
        time.sleep(0.02)
    assert job.status=="done",job.error
    with zipfile.ZipFile(job.zip_path) as archive:
        names=archive.namelist()
        assert "manifest.json" in names
        assert any(name.endswith({"json":"messages.json","txt":"messages.txt","html":"messages.html","excel":"messages.xlsx"}[format_name]) for name in names),names
        if format_name=="html":
            document=archive.read(next(name for name in names if name.endswith("messages.html"))).decode()
            assert 'http-equiv="Content-Security-Policy"' in document
            assert "connect-src 'none'" in document
            assert any("pages/page-" in name for name in names)
            assert "_integrity/local-manifest.json" in names
