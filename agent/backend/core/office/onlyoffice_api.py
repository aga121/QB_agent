"""
OnlyOffice 在线预览与编辑接口
"""

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse

from ..system import config
from ..agent.agent_manager import get_agent_work_dir
from ..auth.auth_utils import verify_token
from ..db.dbutil import DatabaseUtil

router = APIRouter(prefix="/api/v1/onlyoffice", tags=["onlyoffice"])
db = DatabaseUtil()


def _get_user_id_from_token(token: str) -> str:
    token_data = verify_token(token)
    if not token_data or not token_data.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的token或token已过期",
        )
    return token_data["user_id"]


def _get_session_workdir(session_id: str, user_id: str) -> Dict[str, Any]:
    session_row = db.execute_query(
        """
        SELECT id, user_id, ai_agent_id
        FROM chat_sessions
        WHERE id = %s
        """,
        (session_id,),
        fetch="one",
    )

    if not session_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    session = dict(session_row)
    if session["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该会话",
        )

    agent_id = session["ai_agent_id"]
    work_dir = Path(get_agent_work_dir(user_id, agent_id)).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return {"work_dir": work_dir, "agent_id": agent_id}


def _resolve_path(base: Path, relative_path: str) -> Path:
    if not relative_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="path 不能为空",
        )
    target = (base / relative_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="路径越界，禁止访问工作目录之外的文件",
        )
    return target


def _get_base_url(request: Request) -> str:
    if config.ONLYOFFICE_PUBLIC_BASE_URL:
        return f"{config.ONLYOFFICE_PUBLIC_BASE_URL}/"
    return str(request.base_url)


def _build_doc_key(target: Path) -> str:
    stat_res = target.stat()
    signature = f"{target.as_posix()}|{stat_res.st_mtime}|{stat_res.st_size}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


@router.get("/settings")
async def onlyoffice_settings() -> Dict[str, str]:
    return {
        "mode": config.OFFICE_PREVIEW_MODE,
        "onlyoffice_server_url": config.ONLYOFFICE_SERVER_URL,
    }


@router.get("/editor")
async def onlyoffice_editor(
    session_id: str,
    path: str,
    token: str,
    request: Request,
    mode: str = "edit",
):
    if config.OFFICE_PREVIEW_MODE != "onlyoffice":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OnlyOffice 未启用",
        )

    user_id = _get_user_id_from_token(token)
    session_info = _get_session_workdir(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    suffix = target.suffix.lower()
    if suffix not in config.OFFICE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前文件类型不支持 OnlyOffice",
        )

    if mode not in {"view", "edit"}:
        mode = "edit"

    base_url = _get_base_url(request)
    file_url = (
        f"{base_url}api/v1/onlyoffice/file?session_id={quote(session_id)}"
        f"&path={quote(path)}&token={quote(token)}"
    )
    callback_url = (
        f"{base_url}api/v1/onlyoffice/callback?session_id={quote(session_id)}"
        f"&path={quote(path)}&token={quote(token)}"
    )

    doc_config = {
        "document": {
            "fileType": suffix.lstrip("."),
            "key": _build_doc_key(target),
            "title": target.name,
            "url": file_url,
        },
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": mode,
            "user": {
                "id": user_id,
                "name": user_id,
            },
            "customization": {
                "uiTheme": config.ONLYOFFICE_UI_THEME,
            },
        },
        "height": "100%",
        "width": "100%",
    }
    if config.ONLYOFFICE_JWT_SECRET:
        token = jwt.encode(doc_config, config.ONLYOFFICE_JWT_SECRET, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        doc_config["token"] = token

    api_url = f"{config.ONLYOFFICE_SERVER_URL}/web-apps/apps/api/documents/api.js"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{target.name}</title>
  <style>
    html, body, #onlyoffice-editor {{
      height: 100%;
      width: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #fff;
    }}
  </style>
</head>
<body>
  <div id="onlyoffice-editor"></div>
  <script src="{api_url}"></script>
  <script>
    const config = {json.dumps(doc_config, ensure_ascii=False)};
    new DocsAPI.DocEditor("onlyoffice-editor", config);
  </script>
</body>
</html>"""
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/file")
async def onlyoffice_file(
    session_id: str,
    path: str,
    token: str,
):
    user_id = _get_user_id_from_token(token)
    session_info = _get_session_workdir(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    media_type, _ = mimetypes.guess_type(target.name)
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type, filename=None)


@router.post("/callback")
async def onlyoffice_callback(
    session_id: str,
    path: str,
    token: str,
    request: Request,
):
    user_id = _get_user_id_from_token(token)
    session_info = _get_session_workdir(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    try:
        payload = await request.json()
    except Exception:
        return {"error": 1}

    status_code = payload.get("status")
    if status_code in (2, 6):
        file_url = payload.get("url")
        if not file_url:
            return {"error": 1}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(file_url)
                resp.raise_for_status()
                data = resp.content
        except Exception:
            return {"error": 1}

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    return {"error": 0}
