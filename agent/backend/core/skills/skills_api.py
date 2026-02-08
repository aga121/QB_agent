"""
技能发布与管理 API
"""

import os
import shutil
import uuid
import json
import psycopg2.extras
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Query, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse

from ..agent.agent_file_api import _resolve_context
from ..agent.agent_manager import get_user_work_base_dir, get_agent_work_dir
from ..auth.auth_filter import get_current_user_id
from ..auth.auth_utils import verify_token
from ..db.dbutil import DatabaseUtil
from ..system import config

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])
db = DatabaseUtil()


def _get_table_columns(cursor, table_name: str) -> set:
    """获取表的所有列名（PostgreSQL）"""
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        AND table_schema = 'public'
    """, (table_name,))
    return {row['column_name'] for row in cursor.fetchall()}

def _ensure_skill_installs_table(cursor) -> None:
    """确保技能安装映射表存在"""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_installs (
            id TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(skill_id, agent_id, user_id),
            FOREIGN KEY (skill_id) REFERENCES skills (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_installs_agent ON skill_installs(agent_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_installs_user ON skill_installs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill_installs_skill ON skill_installs(skill_id)")


class InstallSkillRequest(BaseModel):
    skill_id: str
    agent_id: str


class SkillReactionRequest(BaseModel):
    action: str


def _safe_category_id(name: str) -> str:
    return name.strip()

def _resolve_public_dir(skill_id: str, public_path: Optional[str], user_id: str) -> Path:
    if public_path:
        return Path(public_path).resolve()
    return get_user_work_base_dir(user_id).parent / "skills_public" / skill_id

def _list_images(public_dir: Path) -> List[str]:
    image_dir = public_dir / "image"
    if not image_dir.exists():
        return []
    files = sorted([p.name for p in image_dir.iterdir() if p.is_file()])
    return files


def _resolve_skill_source(public_dir: Path, skill_name: str) -> Path:
    candidate = (public_dir / skill_name).resolve()
    if candidate.exists() and candidate.is_dir():
        return candidate
    # fallback: pick first directory that is not image
    for entry in public_dir.iterdir():
        if entry.is_dir() and entry.name != "image":
            return entry.resolve()
    return candidate


def _next_skill_name(target_root: Path, base_name: str) -> str:
    if not (target_root / base_name).exists():
        return base_name
    index = 1
    while True:
        name = f"{base_name}V{index}"
        if not (target_root / name).exists():
            return name
        index += 1

@router.get("/categories")
async def list_skill_categories(current_user_id: str = Depends(get_current_user_id)):
    rows = db.execute_query("SELECT name FROM skill_categories ORDER BY name ASC")
    return {
        "success": True,
        "categories": [row["name"] for row in rows] if rows else [],
    }

@router.get("/list")
async def list_skills(
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    mine: Optional[bool] = Query(False),
    current_user_id: str = Depends(get_current_user_id),
):
    params = []
    where = ["1=1"]
    if category:
        where.append("s.category = %s")
        params.append(category)
    if q:
        where.append("(s.name LIKE %s OR s.description LIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if mine:
        where.append("s.author_id = %s")
        params.append(current_user_id)

    rows = db.execute_query(
        f"""
        SELECT s.id, s.name, s.description, s.category, s.images_json, s.public_path,
               s.like_count, s.dislike_count,
               s.author_id, u.username AS author_name, s.created_at
        FROM skills s
        LEFT JOIN users u ON s.author_id = u.id
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(s.like_count, 0) DESC, s.created_at DESC
        """,
        tuple(params) if params else None,
    )
    skills = []
    for row in rows or []:
        data = dict(row)
        public_dir = _resolve_public_dir(data["id"], data.get("public_path"), current_user_id)
        images = []
        if data.get("images_json"):
            try:
                images = json.loads(data["images_json"]) or []
            except Exception:
                images = []
        if not images:
            images = _list_images(public_dir)
        skills.append({
            "id": data["id"],
            "name": data["name"],
            "description": data.get("description") or "",
            "category": data.get("category") or "",
            "author_name": data.get("author_name") or "匿名",
            "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
            "like_count": data.get("like_count", 0),
            "dislike_count": data.get("dislike_count", 0),
            "images": [f"/skills_public/{data['id']}/image/{name}" for name in images],
        })
    return {"success": True, "skills": skills}

@router.get("/agent/{agent_id}")
async def list_agent_skills(
    agent_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    if not agent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少agent_id")
    agents = db.get_ai_agents_by_owner(current_user_id)
    agent_ids = {agent["id"] for agent in agents}
    if agent_id not in agent_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限查看该智能体技能")

    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_skill_installs_table(cursor)
        conn.commit()
        cursor.execute(
            """
            SELECT DISTINCT
                s.id,
                s.name,
                s.content,
                s.created_at,
                si.installed_at,
                COALESCE(si.installed_at, s.created_at) AS sort_at
            FROM skills s
            LEFT JOIN skill_installs si
              ON s.id = si.skill_id
             AND si.user_id = %s
             AND si.agent_id = %s
            WHERE si.id IS NOT NULL
               OR s.author_id = %s
            ORDER BY sort_at DESC
            """,
            (current_user_id, agent_id, current_user_id),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    skills = []
    for row in rows or []:
        data = dict(row)
        skills.append({
            "id": data["id"],
            "name": data.get("name") or "",
            "content": data.get("content") or "",
        })
    return {"success": True, "skills": skills}

@router.get("/{skill_id}")
async def get_skill_detail(
    skill_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    row = db.execute_query(
        """
        SELECT s.id, s.name, s.description, s.content, s.category, s.images_json, s.public_path,
               s.like_count, s.dislike_count,
               s.author_id, u.username AS author_name, s.created_at
        FROM skills s
        LEFT JOIN users u ON s.author_id = u.id
        WHERE s.id = %s
        """,
        (skill_id,),
        fetch="one",
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
    data = dict(row)
    public_dir = _resolve_public_dir(data["id"], data.get("public_path"), current_user_id)
    images = []
    if data.get("images_json"):
        try:
            images = json.loads(data["images_json"]) or []
        except Exception:
            images = []
    if not images:
        images = _list_images(public_dir)
    reaction = db.execute_query(
        "SELECT action FROM skill_reactions WHERE skill_id = %s AND user_id = %s",
        (skill_id, current_user_id),
        fetch="one",
    )
    return {
        "success": True,
        "skill": {
            "id": data["id"],
            "name": data["name"],
            "description": data.get("description") or "",
            "content": data.get("content") or "",
            "category": data.get("category") or "",
            "author_id": data.get("author_id"),
            "author_name": data.get("author_name") or "匿名",
            "created_at": data.get("created_at").isoformat() if data.get("created_at") else None,
            "like_count": data.get("like_count", 0),
            "dislike_count": data.get("dislike_count", 0),
            "user_action": reaction["action"] if reaction else None,
            "images": [f"/skills_public/{data['id']}/image/{name}" for name in images],
        },
    }

@router.get("/{skill_id}/assets/{asset_path:path}")
async def get_skill_asset(
    skill_id: str,
    asset_path: str,
    request: Request,
    token: Optional[str] = Query(None),
):
    if token:
        token_data = verify_token(token)
        if not token_data or not token_data.get("user_id"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的token")
        current_user_id = token_data["user_id"]
    else:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_value = auth_header.split(" ", 1)[1].strip()
            token_data = verify_token(token_value)
            if not token_data or not token_data.get("user_id"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的token")
            current_user_id = token_data["user_id"]
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未授权")
    row = db.execute_query(
        "SELECT public_path FROM skills WHERE id = %s",
        (skill_id,),
        fetch="one",
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
    public_dir = _resolve_public_dir(skill_id, row["public_path"] if row else None, current_user_id)
    target = (public_dir / asset_path).resolve()
    try:
        target.relative_to(public_dir)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="路径非法")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源不存在")
    return FileResponse(target)

def _ensure_skill_columns(cursor) -> None:
    existing = _get_table_columns(cursor, "skills")
    if "skill_path" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN skill_path TEXT")
    if "public_path" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN public_path TEXT")
    if "category" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN category TEXT")
    if "images_json" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN images_json TEXT")
    if "content" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN content TEXT")
    if "like_count" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN like_count INTEGER DEFAULT 0")
    if "dislike_count" not in existing:
        cursor.execute("ALTER TABLE skills ADD COLUMN dislike_count INTEGER DEFAULT 0")

    cat_existing = _get_table_columns(cursor, "skill_categories")
    if not cat_existing:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS skill_categories (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL)"
        )

    reactions_existing = _get_table_columns(cursor, "skill_reactions")
    if not reactions_existing:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_reactions (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('like', 'dislike')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(skill_id, user_id)
            )
            """
        )


@router.post("/publish")
async def publish_skill(
    session_id: str = Form(...),
    skill_folder: str = Form(...),
    description: str = Form(""),
    content: str = Form(""),
    category: str = Form(""),
    images: List[UploadFile] = File(default_factory=list),
    current_user_id: str = Depends(get_current_user_id),
):
    """发布技能：复制技能包文件夹到公开目录，并记录元数据"""
    if not session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少会话ID")
    if not skill_folder:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少技能文件夹")

    session_info = _resolve_context(session_id, current_user_id)
    work_dir = Path(session_info["work_dir"]).resolve()
    agent_id = session_info["agent_id"]

    skill_root = (work_dir / config.SKILL_PACKAGE_DIR).resolve()
    skill_path = (skill_root / skill_folder).resolve()
    try:
        skill_path.relative_to(skill_root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="技能路径非法")
    if not skill_path.exists() or not skill_path.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能文件夹不存在")

    public_root = get_user_work_base_dir(current_user_id).parent / "skills_public"
    public_root.mkdir(parents=True, exist_ok=True)
    skill_id = str(uuid.uuid4())
    dest_dir = (public_root / skill_id).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_skill_dir = dest_dir / skill_path.name
    if dest_skill_dir.exists():
        shutil.rmtree(dest_skill_dir)
    shutil.copytree(skill_path, dest_skill_dir)

    # 保存上传的图片到 image 目录
    image_dir = dest_dir / "image"
    image_dir.mkdir(parents=True, exist_ok=True)
    saved_images = []
    for idx, upload in enumerate(images or []):
        if not upload or not upload.filename:
            continue
        # 获取文件扩展名
        ext = Path(upload.filename).suffix or ".png"
        # 生成唯一文件名：使用 UUID 避免重复
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}{ext}"
        target = image_dir / filename
        with target.open("wb") as f:
            f.write(await upload.read())
        saved_images.append(filename)

    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_skill_columns(cursor)
        cursor.execute(
            """
            INSERT INTO skills (
                id, name, description, content, skill_path, public_path, category, images_json,
                like_count, dislike_count, author_id, agent_id, session_id, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                skill_id,
                skill_path.name,
                description,
                content,
                str(Path(config.SKILL_PACKAGE_DIR) / skill_path.name),
                str(dest_dir),
                _safe_category_id(category) if category else "",
                json.dumps(saved_images) if saved_images else None,
                current_user_id,
                agent_id,
                session_id,
            ),
        )

        if category:
            category_name = _safe_category_id(category)
            cursor.execute(
                "INSERT INTO skill_categories (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (str(uuid.uuid4()), category_name),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "success": True,
        "skill_id": skill_id,
        "name": skill_path.name,
        "category": category,
        "created_at": datetime.utcnow().isoformat(),
    }


@router.post("/install")
async def install_skill(
    payload: InstallSkillRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    skill_id = (payload.skill_id or "").strip()
    agent_id = (payload.agent_id or "").strip()
    if not skill_id or not agent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少必要参数")

    agents = db.get_ai_agents_by_owner(current_user_id)
    agent_ids = {agent["id"] for agent in agents}
    if agent_id != "all" and agent_id not in agent_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限安装到该智能体")

    row = db.execute_query(
        "SELECT name, skill_path, public_path FROM skills WHERE id = %s",
        (skill_id,),
        fetch="one",
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
    row_data = dict(row)
    skill_name = row_data.get("name") or Path(row_data.get("skill_path") or "").name
    if not skill_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="技能信息缺失")

    public_dir = _resolve_public_dir(skill_id, row_data.get("public_path"), current_user_id)
    if not public_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能文件不存在")

    source_dir = _resolve_skill_source(public_dir, skill_name)
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能目录不存在")

    target_ids = agent_ids if agent_id == "all" else {agent_id}
    results = []
    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_skill_installs_table(cursor)
        for target_agent_id in target_ids:
            target_work_dir = Path(get_agent_work_dir(current_user_id, target_agent_id)).resolve()
            target_skill_root = (target_work_dir / config.SKILL_PACKAGE_DIR).resolve()
            target_skill_root.mkdir(parents=True, exist_ok=True)
            target_name = _next_skill_name(target_skill_root, source_dir.name)
            target_dir = (target_skill_root / target_name).resolve()
            try:
                target_dir.relative_to(target_skill_root)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目标路径非法")
            shutil.copytree(source_dir, target_dir)
            cursor.execute(
                """
                INSERT INTO skill_installs (id, skill_id, agent_id, user_id, installed_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (skill_id, agent_id, user_id) DO NOTHING
                """,
                (str(uuid.uuid4()), skill_id, target_agent_id, current_user_id),
            )
            results.append({"agent_id": target_agent_id, "installed_name": target_name})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "success": True,
        "skill_id": skill_id,
        "agent_id": agent_id,
        "results": results,
    }


@router.post("/{skill_id}/reaction")
async def react_skill(
    skill_id: str,
    payload: SkillReactionRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    action = (payload.action or "").strip().lower()
    if action not in {"like", "dislike"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的操作")
    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_skill_columns(cursor)
        cursor.execute("SELECT id FROM skills WHERE id = %s", (skill_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
        cursor.execute(
            "SELECT action FROM skill_reactions WHERE skill_id = %s AND user_id = %s",
            (skill_id, current_user_id),
        )
        existing = cursor.fetchone()
        if existing and existing["action"] == action:
            column = "like_count" if action == "like" else "dislike_count"
            cursor.execute(
                f"UPDATE skills SET {column} = MAX(COALESCE({column}, 0) - 1, 0), updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (skill_id,),
            )
            cursor.execute(
                "DELETE FROM skill_reactions WHERE skill_id = %s AND user_id = %s",
                (skill_id, current_user_id),
            )
            new_action = None
        else:
            if existing and existing["action"] in {"like", "dislike"}:
                prev_column = "like_count" if existing["action"] == "like" else "dislike_count"
                cursor.execute(
                    f"UPDATE skills SET {prev_column} = MAX(COALESCE({prev_column}, 0) - 1, 0) WHERE id = %s",
                    (skill_id,),
                )
            column = "like_count" if action == "like" else "dislike_count"
            cursor.execute(
                f"UPDATE skills SET {column} = COALESCE({column}, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (skill_id,),
            )
            cursor.execute(
                """
                INSERT INTO skill_reactions (id, skill_id, user_id, action, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(skill_id, user_id) DO UPDATE SET
                    action = excluded.action,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(uuid.uuid4()), skill_id, current_user_id, action),
            )
            new_action = action
        cursor.execute("SELECT like_count, dislike_count FROM skills WHERE id = %s", (skill_id,))
        counts = cursor.fetchone()
        conn.commit()
        return {
            "success": True,
            "like_count": counts["like_count"] if counts else 0,
            "dislike_count": counts["dislike_count"] if counts else 0,
            "action": new_action,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    row = db.execute_query(
        "SELECT author_id, public_path FROM skills WHERE id = %s",
        (skill_id,),
        fetch="one",
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
    if row["author_id"] != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限删除该技能")

    public_dir = _resolve_public_dir(skill_id, row["public_path"], current_user_id)
    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("DELETE FROM skill_reactions WHERE skill_id = %s", (skill_id,))
        cursor.execute("DELETE FROM skills WHERE id = %s", (skill_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if public_dir.exists():
        shutil.rmtree(public_dir, ignore_errors=True)

    return {"success": True}


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    description: str = Form(""),
    content: str = Form(""),
    category: str = Form(""),
    images: List[UploadFile] = File(default_factory=list),
    current_user_id: str = Depends(get_current_user_id),
):
    """编辑技能：更新描述、内容、分类与附加图片"""
    row = db.execute_query(
        "SELECT author_id, public_path, images_json FROM skills WHERE id = %s",
        (skill_id,),
        fetch="one",
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="技能不存在")
    if row["author_id"] != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限编辑该技能")

    public_dir = _resolve_public_dir(skill_id, row["public_path"], current_user_id)
    public_dir.mkdir(parents=True, exist_ok=True)
    image_dir = public_dir / "image"
    image_dir.mkdir(parents=True, exist_ok=True)

    saved_images = []
    for upload in images or []:
        if not upload or not upload.filename:
            continue
        ext = Path(upload.filename).suffix or ".png"
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}{ext}"
        target = image_dir / filename
        with target.open("wb") as f:
            f.write(await upload.read())
        saved_images.append(filename)

    images_list = []
    if row.get("images_json"):
        try:
            images_list = json.loads(row["images_json"]) or []
        except Exception:
            images_list = []
    if saved_images:
        images_list.extend(saved_images)

    conn = db._get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_skill_columns(cursor)
        cursor.execute(
            """
            UPDATE skills
            SET description = %s,
                content = %s,
                category = %s,
                images_json = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                description,
                content,
                _safe_category_id(category) if category else "",
                json.dumps(images_list) if images_list else None,
                skill_id,
            ),
        )
        if category:
            category_name = _safe_category_id(category)
            cursor.execute(
                "INSERT INTO skill_categories (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (str(uuid.uuid4()), category_name),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"success": True, "skill_id": skill_id}
