"""
Agent local service proxy.
Maps /agent/<username>-<port> to http://127.0.0.1:<port>.
Static HTML file serving: /html-page/<user_id>/<filename>.html
"""

from __future__ import annotations

from typing import Optional
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from ..system.config import get_agent_work_dir

router = APIRouter()

# 安全验证：filename 只允许字母、数字、中文、下划线、连字符和点
SAFE_FILENAME_PATTERN = re.compile(r'^[\w\u4e00-\u9fff.\-]+$')

# 允许的静态文件类型
ALLOWED_HTML_PAGE_EXTENSIONS = {
    ".html",
    ".png",
    ".svg",
    ".jpg",
    ".jpeg",
    ".js",
    ".css",
    ".json",
}

CONTENT_TYPE_BY_EXT = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _extract_port(slug: str) -> Optional[int]:
    if not slug:
        return None
    if "-" in slug:
        _, port_str = slug.rsplit("-", 1)
    else:
        port_str = slug
    if not port_str.isdigit():
        return None
    port = int(port_str)
    return port if 1 <= port <= 65535 else None


def _filter_headers(headers: dict) -> dict:
    excluded = {
        "content-encoding",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
    return {k: v for k, v in headers.items() if k.lower() not in excluded}


@router.api_route("/agent/{slug}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@router.api_route("/agent/{slug}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_agent_service(slug: str, path: str = "", request: Request = None) -> Response:
    port = _extract_port(slug)
    if not port:
        raise HTTPException(status_code=400, detail="invalid agent port")

    target_url = f"http://127.0.0.1:{port}"
    if path:
        target_url = f"{target_url}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = _filter_headers(dict(request.headers))
    headers.pop("host", None)

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=await request.body(),
                follow_redirects=False,
            )
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="upstream service unavailable")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=_filter_headers(dict(resp.headers)),
    )


@router.get("/html-page/{agent_id}/{file_path:path}")
async def serve_static_html(agent_id: str, file_path: str):
    """
    安全地提供 agent 工作目录中的静态 HTML 文件
    路径格式：/html-page/{agent_id}/{filename}

    安全机制：
    1. 只允许白名单扩展名
    2. 防止路径遍历攻击（..）
    3. 只允许安全字符（字母、数字、中文、下划线、连字符、点）
    """
    # 兼容处理：自动去掉 agentid_ 前缀（如果用户误加）
    if agent_id.startswith("agentid_"):
        agent_id = agent_id[8:]

    # 安全检查 1：防止路径遍历
    if ".." in file_path or "\\" in file_path:
        raise HTTPException(status_code=400, detail="invalid filename")

    # 安全检查 2：只允许白名单扩展名
    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_HTML_PAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="file type not allowed")

    # 安全检查 3：文件名格式验证（逐段检查）
    parts = [p for p in file_path.split("/") if p]
    if not parts or any(not SAFE_FILENAME_PATTERN.match(p) for p in parts):
        raise HTTPException(status_code=400, detail="invalid filename format")

    # 通过 agent_id 获取工作目录
    from ..system.config import get_agent_work_dir
    from ..db.dbutil import DatabaseUtil
    import psycopg2.extras
    import logging

    logger = logging.getLogger(__name__)
    db = DatabaseUtil()
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute('''
            SELECT owner_id FROM users WHERE id = %s AND user_type = 'ai'
        ''', (agent_id,))
        agent_info = cursor.fetchone()
        conn.close()

        logger.debug(f"[html-page] agent_id={agent_id}, agent_info={agent_info}")

        if not agent_info:
            raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")

        owner_id = agent_info.get("owner_id")
        if not owner_id:
            raise HTTPException(status_code=404, detail=f"agent has no owner_id: {agent_id}")

        work_dir = get_agent_work_dir(owner_id, agent_id)
        file_path = Path(work_dir) / file_path

        logger.debug(f"[html-page] work_dir={work_dir}, file_path={file_path}, exists={file_path.exists()}")

        # 安全检查：确保文件在工作目录内
        if not str(file_path.resolve()).startswith(str(Path(work_dir).resolve())):
            raise HTTPException(status_code=403, detail="access denied")

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {file_path}")

    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.close()
        logger.error(f"[html-page] error: {e}")
        raise HTTPException(status_code=500, detail=f"error: {str(e)}")

    # 读取并返回文件内容
    try:
        content = file_path.read_bytes()
        return Response(
            content=content,
            media_type=CONTENT_TYPE_BY_EXT.get(ext, "application/octet-stream")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"error reading file: {str(e)}")
