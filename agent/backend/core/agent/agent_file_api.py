"""
会话工作目录文件浏览 API
"""

import sys
import mimetypes
import os
import shutil
import subprocess
import hashlib
import re
import json
import tempfile
import zipfile
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body, File, UploadFile, Query
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from .agent_manager import get_agent_work_dir, get_user_work_base_dir
from ..auth.auth_filter import get_current_user_id
from ..auth.auth_utils import verify_token
from ..db.dbutil import DatabaseUtil
from ..system import config
from ..firewall.firewall_bash import check_user_storage_quota

router = APIRouter(prefix="/api/v1/chat", tags=["agent_files"])

# 初始化数据库工具
db = DatabaseUtil()

OFFICE_EXTENSIONS = config.OFFICE_EXTENSIONS
_LIBREOFFICE_CACHE: Dict[str, str] = {}

def _get_session_workdir(session_id: str, user_id: str) -> Dict[str, Any]:
    """获取单聊会话工作目录"""
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


def _resolve_context(session_id: str, user_id: str) -> Dict[str, Any]:
    return _get_session_workdir(session_id, user_id)

def _resolve_path(base: Path, relative_path: str) -> Path:
    """在工作目录下安全解析相对路径"""
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

def _get_user_id_from_token(token: str) -> str:
    token_data = verify_token(token)
    if not token_data or not token_data.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的token或token已过期",
        )
    return token_data["user_id"]

def _find_libreoffice_cmd() -> Optional[str]:
    """查找LibreOffice可执行文件"""
    cached = _LIBREOFFICE_CACHE.get("cmd")
    if cached is not None:
        return cached or None

    env_path = os.getenv("LIBREOFFICE_PATH")
    if env_path and Path(env_path).exists():
        _LIBREOFFICE_CACHE["cmd"] = env_path
        return env_path

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            _LIBREOFFICE_CACHE["cmd"] = found
            return found

    if os.name == "nt":
        for path in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(path).exists():
                _LIBREOFFICE_CACHE["cmd"] = path
                return path

    _LIBREOFFICE_CACHE["cmd"] = ""
    return None

def _cache_pdf_path(target: Path, cache_root: Path) -> Path:
    stat_res = target.stat()
    signature = f"{target.as_posix()}|{stat_res.st_mtime}|{stat_res.st_size}"
    hash_key = hashlib.sha1(signature.encode("utf-8")).hexdigest()
    cache_dir = cache_root / hash_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{target.stem}.pdf"

def _convert_office_to_pdf(target: Path, cache_root: Path) -> Path:
    pdf_path = _cache_pdf_path(target, cache_root)
    if pdf_path.exists():
        return pdf_path

    cmd = _find_libreoffice_cmd()
    if not cmd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未检测到 LibreOffice，无法在线预览，请下载后查看",
        )

    out_dir = pdf_path.parent
    args = [
        cmd,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(target),
    ]

    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **kwargs)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="文件转换超时")
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else "文件转换失败"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)

    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="转换失败，未生成PDF")
    return pdf_path

def _get_archive_root(work_dir: Path) -> Path:
    return work_dir.parent / "svn"

def _list_archives(archive_root: Path) -> List[str]:
    if not archive_root.exists():
        return []
    numeric = []
    others = []
    for p in archive_root.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if name.isdigit():
            numeric.append(int(name))
        else:
            others.append(name)
    numeric_sorted = sorted(numeric, reverse=True)
    others_sorted = sorted(others, reverse=True)
    return [str(n) for n in numeric_sorted] + others_sorted

def _copy_tree(src: Path, dst: Path) -> None:
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in {".preview_cache"}:
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

def _clear_directory(path: Path) -> None:
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except FileNotFoundError:
                pass


def _has_children(path: Path) -> bool:
    try:
        return any(entry for entry in path.iterdir() if not entry.is_symlink())
    except Exception:
        return False


def _build_file_tree(current_path: Path, base_path: Path, depth: int) -> List[Dict[str, Any]]:
    """递归构建文件树（按深度）"""
    items: List[Dict[str, Any]] = []
    skills_items: List[Dict[str, Any]] = []

    try:
        entries_with_stat = []
        for entry in current_path.iterdir():
            if entry.is_symlink():
                continue
            try:
                stat_result = entry.stat()
            except Exception:
                continue
            entries_with_stat.append((entry, stat_result))
        entries_with_stat.sort(
            key=lambda item: (-item[1].st_mtime, item[0].is_file(), item[0].name.lower())
        )
    except FileNotFoundError:
        return items
    except Exception as exc:
        print(f"读取目录失败 {current_path}: {exc}", file=sys.stderr)
        return items

    for entry, stat_result in entries_with_stat:

        # 特殊处理：如果是 .claude 目录，检查其子目录并提升
        if entry.is_dir() and entry.name == ".claude":
            # 尝试找到 skills 目录并提升到当前层级
            skills_dir = entry / "skills"
            if skills_dir.exists() and skills_dir.is_dir():
                # 将 skills 目录提升到当前层级，显示为"技能包"
                relative_path = skills_dir.relative_to(base_path).as_posix()
                item: Dict[str, Any] = {
                    "name": config.SKILL_PACKAGE_DISPLAY_NAME,  # "技能包"
                    "path": relative_path,
                    "type": "directory",
                    "display_name": config.SKILL_PACKAGE_DISPLAY_NAME,
                    "is_skills_package": True,
                    "modified_at": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
                    "has_children": _has_children(skills_dir),
                }
                if depth > 0:
                    item["children"] = _build_file_tree(skills_dir, base_path, depth - 1)
                skills_items.append(item)
            # 跳过 .claude 目录本身，不显示
            continue

        relative_path = entry.relative_to(base_path).as_posix()
        item: Dict[str, Any] = {
            "name": entry.name,
            "path": relative_path,
            "type": "directory" if entry.is_dir() else "file",
            "modified_at": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
        }

        if entry.is_dir():
            item["has_children"] = _has_children(entry)
            if depth > 0:
                item["children"] = _build_file_tree(entry, base_path, depth - 1)
        else:
            item["size"] = stat_result.st_size

        items.append(item)

    return skills_items + items


@router.get("/sessions/{session_id}/files")
async def get_session_files(
    session_id: str,
    user_id: str,
        path: str = None,
    depth: int = 3,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    获取指定会话的工作目录文件列表
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    try:
        session_info = _resolve_context(session_id, user_id)
        work_dir = session_info["work_dir"]
        agent_id = session_info["agent_id"]

        depth = max(0, min(int(depth), 3))
        target_dir = work_dir
        if path:
            target_dir = _resolve_path(work_dir, path)
            if not target_dir.exists() or not target_dir.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="目录不存在",
                )
        files = _build_file_tree(target_dir, work_dir, depth)

        return {
            "success": True,
            "session_id": session_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "work_dir": str(work_dir),
            "files": files,
        }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"获取会话工作目录失败: {exc}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取会话文件失败",
        )


@router.get("/sessions/{session_id}/file")
async def read_file(
    session_id: str,
    path: str,
    user_id: str,
        current_user_id: str = Depends(get_current_user_id),
):
    """
    读取指定会话工作目录下的文件内容
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    allowed, used_bytes, quota_bytes = check_user_storage_quota(user_id)
    if not allowed:
        used_mb = round(used_bytes / 1024 / 1024, 1)
        quota_mb = round(quota_bytes / 1024 / 1024, 1)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"storage_exceeded:用户存储已超过限制（{used_mb}MB / {quota_mb}MB），请清理后再上传。"
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    data = target.read_bytes()
    is_binary = False
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        content = data.decode("utf-8", errors="replace")
        is_binary = True

    stat_res = target.stat()
    return {
        "success": True,
        "path": path,
        "is_binary": is_binary,
        "content": content,
        "size": stat_res.st_size,
        "modified_at": datetime.fromtimestamp(stat_res.st_mtime).isoformat(),
    }


@router.post("/sessions/{session_id}/files")
async def write_file(
    session_id: str,
    user_id: str,
        body: Dict[str, Any] = Body(..., examples={"default": {"summary": "写文件", "value": {"path": "notes.txt", "content": "hello"}}}),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    创建或覆盖文件
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    rel_path = body.get("path")
    content = body.get("content", "")

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, rel_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {"success": True, "path": rel_path}


@router.post("/sessions/{session_id}/folders")
async def create_folder(
    session_id: str,
    user_id: str,
        body: Dict[str, Any] = Body(..., examples={"default": {"summary": "创建文件夹", "value": {"path": "docs"}}}),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    创建文件夹（递归创建父目录）
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    rel_path = body.get("path")
    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, rel_path)
    target.mkdir(parents=True, exist_ok=True)

    return {"success": True, "path": rel_path, "type": "directory"}


@router.delete("/sessions/{session_id}/files")
async def delete_entry(
    session_id: str,
    user_id: str,
        body: Dict[str, Any] = Body(..., examples={"default": {"summary": "删除文件/文件夹", "value": {"path": "old.txt", "recursive": False}}}),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    删除文件或文件夹（文件夹默认要求为空，除非 recursive=True）
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    rel_path = body.get("path")
    recursive = bool(body.get("recursive", False))

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, rel_path)

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="目标不存在",
        )

    if target.is_dir():
        if recursive:
            try:
                shutil.rmtree(target)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"递归删除失败: {str(exc)}",
                )
        else:
            try:
                target.rmdir()
            except OSError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="目录非空，若需递归删除请传 recursive=True",
                )
    else:
        target.unlink(missing_ok=True)

    return {"success": True, "path": rel_path}


@router.delete("/sessions/{session_id}/files/all")
async def clear_all_files(
    session_id: str,
    user_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    批量删除工作目录中的所有文件和文件夹（保留技能包目录）
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]

    if not work_dir.exists():
        return {"success": True, "deleted_count": 0}

    deleted_count = 0
    try:
        # 仅保留 .claude，其余顶层目录/文件直接删除
        for item in sorted(work_dir.iterdir(), reverse=True):
            if item.name == ".claude":
                continue
            try:
                if item.is_file():
                    item.unlink(missing_ok=True)
                    deleted_count += 1
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                # 跳过无法删除的文件
                pass

        return {"success": True, "deleted_count": deleted_count}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清空文件失败: {str(e)}"
        )


@router.post("/sessions/{session_id}/rename")
async def rename_entry(
    session_id: str,
    user_id: str,
        body: Dict[str, Any] = Body(..., examples={"default": {"summary": "重命名/移动", "value": {"old_path": "old.txt", "new_path": "new.txt"}}}),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    重命名/移动文件或文件夹（限工作目录内）
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    old_rel = body.get("old_path")
    new_rel = body.get("new_path")
    if not old_rel or not new_rel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="old_path/new_path 不能为空",
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    old_target = _resolve_path(work_dir, old_rel)
    new_target = _resolve_path(work_dir, new_rel)

    if not old_target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="源路径不存在",
        )

    new_target.parent.mkdir(parents=True, exist_ok=True)
    old_target.rename(new_target)

    return {"success": True, "old_path": old_rel, "new_path": new_rel}


@router.get("/sessions/{session_id}/download")
async def download_file(
    session_id: str,
    user_id: str,
    path: str,
        current_user_id: str = Depends(get_current_user_id),
):
    """
    下载/直接打开文件（需带 Authorization 头）。
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    if target.is_dir():
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp_path = Path(tmp_file.name)
        tmp_file.close()
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in target.rglob("*"):
                if file_path.is_file():
                    rel = file_path.relative_to(target)
                    zf.write(file_path, arcname=f"{target.name}/{rel}")
        safe_name = quote(f"{target.name}.zip")
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"
        }
        return FileResponse(
            path=str(tmp_path),
            media_type="application/zip",
            filename=None,
            headers=headers,
            background=BackgroundTask(lambda: tmp_path.unlink(missing_ok=True)),
        )

    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    media_type, _ = mimetypes.guess_type(target.name)
    media_type = media_type or "application/octet-stream"

    safe_name = quote(target.name)
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}"
    }

    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=None,
        headers=headers,
    )


@router.post("/sessions/{session_id}/upload")
async def upload_files(
    session_id: str,
    user_id: str = Query(...),
        files: List[UploadFile] = File(...),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    上传文件/文件夹到会话工作目录（支持相对路径）。
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]

    saved = []
    for upload in files:
        rel_path = (upload.filename or "").replace("\\", "/").lstrip("/")
        if not rel_path:
            continue
        target = _resolve_path(work_dir, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        saved.append(rel_path)

    return {"success": True, "files": saved}


@router.get("/sessions/{session_id}/archives")
async def list_archives(
    session_id: str,
    user_id: str,
        current_user_id: str = Depends(get_current_user_id),
):
    """
    获取归档列表。
    """
    if current_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户身份验证失败")

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    archive_root = _get_archive_root(work_dir)
    return {"success": True, "archives": _list_archives(archive_root)}


@router.post("/sessions/{session_id}/archives")
async def create_archive(
    session_id: str,
    user_id: str = Query(...),
        current_user_id: str = Depends(get_current_user_id),
):
    """
    创建归档，最多保留10个。
    """
    if current_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户身份验证失败")

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    if not work_dir.exists():
        work_dir.mkdir(parents=True, exist_ok=True)

    archive_root = _get_archive_root(work_dir)
    archive_root.mkdir(parents=True, exist_ok=True)
    archives = _list_archives(archive_root)
    numeric = [int(name) for name in archives if name.isdigit()]
    stamp = str(max(numeric) + 1) if numeric else "1"
    dest = archive_root / stamp
    _copy_tree(work_dir, dest)

    archives = _list_archives(archive_root)
    if len(archives) > 10:
        for old_name in archives[10:]:
            shutil.rmtree(archive_root / old_name, ignore_errors=True)

    return {"success": True, "archive": stamp}


@router.post("/sessions/{session_id}/archives/{archive_name}/restore")
async def restore_archive(
    session_id: str,
    archive_name: str,
    user_id: str = Query(...),
        current_user_id: str = Depends(get_current_user_id),
):
    """
    恢复归档到当前工作目录。
    """
    if current_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户身份验证失败")

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    archive_root = _get_archive_root(work_dir)
    source = archive_root / archive_name
    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="归档不存在")

    if not work_dir.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory(work_dir)
    _copy_tree(source, work_dir)

    return {"success": True, "archive": archive_name}


@router.delete("/sessions/{session_id}/archives")
async def clear_archives(
    session_id: str,
    user_id: str = Query(...),
        current_user_id: str = Depends(get_current_user_id),
):
    """
    清空所有归档。
    """
    if current_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户身份验证失败")

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    archive_root = _get_archive_root(work_dir)
    if archive_root.exists():
        shutil.rmtree(archive_root, ignore_errors=True)
        archive_root.mkdir(parents=True, exist_ok=True)
    return {"success": True}


@router.get("/sessions/{session_id}/preview")
async def preview_file(
    session_id: str,
    user_id: str,
    path: str,
        current_user_id: str = Depends(get_current_user_id),
):
    """
    预览Office文件（服务端转换为PDF）。
    """
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    suffix = target.suffix.lower()
    if suffix in OFFICE_EXTENSIONS:
        cache_root = get_user_work_base_dir(user_id) / ".preview_cache"
        pdf_path = _convert_office_to_pdf(target, cache_root)
        safe_name = quote(f"{target.stem}.pdf")
        headers = {"Content-Disposition": f"inline; filename*=UTF-8''{safe_name}"}
        return FileResponse(path=str(pdf_path), media_type="application/pdf", filename=None, headers=headers)

    if suffix == ".pdf":
        safe_name = quote(target.name)
        headers = {"Content-Disposition": f"inline; filename*=UTF-8''{safe_name}"}
        return FileResponse(path=str(target), media_type="application/pdf", filename=None, headers=headers)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="当前文件类型不支持在线预览",
    )


@router.get("/sessions/{session_id}/preview_html")
async def preview_html(
    session_id: str,
    path: str,
    token: str,
    ):
    """
    预览HTML文件（注入base以支持相对资源）。
    """
    user_id = _get_user_id_from_token(token)
    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    base_href = f"/api/v1/chat/sessions/{session_id}/assets/{token}/"

    try:
        html = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = target.read_text(encoding="utf-8", errors="replace")
    base_tag = f'<base href="{base_href}">'

    # 移除已有 base
    html = re.sub(r"<base\\b[^>]*>", "", html, flags=re.IGNORECASE)
    # 修正 file:///.../work/ 形式的本地绝对路径为相对路径
    html = re.sub(r'file:///[^"\'\\s]*?/work/', '', html, flags=re.IGNORECASE)
    if re.search(r"<head\\b[^>]*>", html, flags=re.IGNORECASE):
        html = re.sub(r"(<head\\b[^>]*>)", r"\\1" + base_tag, html, count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html

    anchor_fix_script = (
        "<script>"
        "document.addEventListener('click',function(e){"
        "var a=e.target&&e.target.closest?e.target.closest('a'):null;"
        "if(!a){return;}"
        "var href=a.getAttribute('href');"
        "if(href&&href.charAt(0)==='#'){"
        "e.preventDefault();"
        "if(href.length>1){location.hash=href;}else{location.hash='';}"
        "}"
        "});"
        "</script>"
    )
    height_report_script = (
        "<script>"
        "function __qbReportHeight(){"
        "var h=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);"
        "try{parent.postMessage({type:'previewHeight',path:" + json.dumps(path) + ",height:h},'*');}catch(e){}"
        "}"
        "window.addEventListener('load',__qbReportHeight);"
        "window.addEventListener('resize',__qbReportHeight);"
        "setTimeout(__qbReportHeight,100);"
        "setTimeout(__qbReportHeight,500);"
        "</script>"
    )
    if re.search(r"</body>", html, flags=re.IGNORECASE):
        html = re.sub(r"</body>", anchor_fix_script + height_report_script + "</body>", html, count=1, flags=re.IGNORECASE)
    else:
        html += anchor_fix_script + height_report_script
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/sessions/{session_id}/assets/{token}/{asset_path:path}")
async def preview_asset(
    session_id: str,
    token: str,
    asset_path: str,
):
    """
    预览HTML资源文件（通过token鉴权）。
    """
    user_id = _get_user_id_from_token(token)
    session_info = _resolve_context(session_id, user_id)
    work_dir = session_info["work_dir"]
    target = _resolve_path(work_dir, asset_path)

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    media_type, _ = mimetypes.guess_type(target.name)
    media_type = media_type or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type, filename=None)
