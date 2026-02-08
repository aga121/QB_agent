"""
提示词模板 API
"""
import uuid
from datetime import datetime
from typing import Optional, List

import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel

from ..auth.auth_filter import get_current_user_id
from ..db.dbutil import DatabaseUtil


router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])
db = DatabaseUtil()


class PromptItem(BaseModel):
    id: str
    name: str
    content: str
    tags: Optional[str] = None
    is_official: bool = False
    usage_count: int = 0
    like_count: int = 0
    dislike_count: int = 0
    last_used_at: Optional[str] = None
    owner_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PromptListResponse(BaseModel):
    prompts: List[PromptItem]


class PromptCreateRequest(BaseModel):
    name: str
    content: str
    tags: Optional[str] = None


class PromptUpdateRequest(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None


def _format_ts(value):
    return value.isoformat() if value else None


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    scope: str = Query("all"),
    q: Optional[str] = Query(None),
    sort: str = Query("recent"),
    user_id: str = Depends(get_current_user_id),
):
    """
    获取提示词列表

    scope: all/my/official
    sort: recent/usage/name
    """
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where_clauses = []
        params: List[object] = []

        if scope == "my":
            where_clauses.append("owner_id = %s")
            params.append(user_id)
        elif scope == "official":
            where_clauses.append("is_official = TRUE")
        else:
            where_clauses.append("(is_official = TRUE OR owner_id = %s)")
            params.append(user_id)

        if q:
            where_clauses.append("(name ILIKE %s OR content ILIKE %s OR tags ILIKE %s)")
            like_val = f"%{q}%"
            params.extend([like_val, like_val, like_val])

        order_by = "last_used_at DESC NULLS LAST"
        if sort == "usage":
            order_by = "usage_count DESC, updated_at DESC"
        elif sort == "name":
            order_by = "name ASC"
        elif sort == "recent":
            order_by = "last_used_at DESC NULLS LAST"

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
        cursor.execute(
            f"""
            SELECT id, name, content, tags, is_official, usage_count, like_count, dislike_count,
                   last_used_at, owner_id, created_at, updated_at
            FROM prompt_templates
            WHERE {where_sql}
            ORDER BY {order_by}
            """,
            tuple(params),
        )

        rows = cursor.fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "content": row["content"],
                    "tags": row.get("tags"),
                    "is_official": bool(row.get("is_official")),
                    "usage_count": row.get("usage_count", 0),
                    "like_count": row.get("like_count", 0),
                    "dislike_count": row.get("dislike_count", 0),
                    "last_used_at": _format_ts(row.get("last_used_at")),
                    "owner_id": row.get("owner_id"),
                    "created_at": _format_ts(row.get("created_at")),
                    "updated_at": _format_ts(row.get("updated_at")),
                }
            )

        return {"prompts": items}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取提示词失败: {exc}",
        )
    finally:
        if conn:
            conn.close()


@router.post("", response_model=PromptItem)
async def create_prompt(
    payload: PromptCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not payload.name.strip() or not payload.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="提示词名称和内容不能为空",
        )

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        prompt_id = str(uuid.uuid4())
        now = datetime.utcnow()
        cursor.execute(
            """
            INSERT INTO prompt_templates
            (id, owner_id, name, content, tags, is_official, usage_count, like_count, dislike_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, FALSE, 0, 0, 0, %s, %s)
            RETURNING id, name, content, tags, is_official, usage_count, like_count, dislike_count,
                      last_used_at, owner_id, created_at, updated_at
            """,
            (
                prompt_id,
                user_id,
                payload.name.strip(),
                payload.content,
                payload.tags,
                now,
                now,
            ),
        )
        row = cursor.fetchone()
        conn.commit()
        return {
            "id": row["id"],
            "name": row["name"],
            "content": row["content"],
            "tags": row.get("tags"),
            "is_official": bool(row.get("is_official")),
            "usage_count": row.get("usage_count", 0),
            "like_count": row.get("like_count", 0),
            "dislike_count": row.get("dislike_count", 0),
            "last_used_at": _format_ts(row.get("last_used_at")),
            "owner_id": row.get("owner_id"),
            "created_at": _format_ts(row.get("created_at")),
            "updated_at": _format_ts(row.get("updated_at")),
        }
    except Exception as exc:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建提示词失败: {exc}",
        )
    finally:
        if conn:
            conn.close()


@router.put("/{prompt_id}", response_model=PromptItem)
async def update_prompt(
    prompt_id: str,
    payload: PromptUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT id, owner_id, is_official FROM prompt_templates WHERE id = %s",
            (prompt_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提示词不存在")
        if row.get("is_official"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="官方提示词不可修改")
        if row.get("owner_id") != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限修改该提示词")

        fields = []
        params: List[object] = []
        if payload.name is not None:
            fields.append("name = %s")
            params.append(payload.name.strip())
        if payload.content is not None:
            fields.append("content = %s")
            params.append(payload.content)
        if payload.tags is not None:
            fields.append("tags = %s")
            params.append(payload.tags)
        if not fields:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可更新的字段")

        fields.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(prompt_id)
        cursor.execute(
            f"""
            UPDATE prompt_templates
            SET {', '.join(fields)}
            WHERE id = %s
            RETURNING id, name, content, tags, is_official, usage_count, like_count, dislike_count,
                      last_used_at, owner_id, created_at, updated_at
            """,
            tuple(params),
        )
        updated = cursor.fetchone()
        conn.commit()
        return {
            "id": updated["id"],
            "name": updated["name"],
            "content": updated["content"],
            "tags": updated.get("tags"),
            "is_official": bool(updated.get("is_official")),
            "usage_count": updated.get("usage_count", 0),
            "like_count": updated.get("like_count", 0),
            "dislike_count": updated.get("dislike_count", 0),
            "last_used_at": _format_ts(updated.get("last_used_at")),
            "owner_id": updated.get("owner_id"),
            "created_at": _format_ts(updated.get("created_at")),
            "updated_at": _format_ts(updated.get("updated_at")),
        }
    except HTTPException:
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新提示词失败: {exc}",
        )
    finally:
        if conn:
            conn.close()


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    user_id: str = Depends(get_current_user_id),
):
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT id, owner_id, is_official FROM prompt_templates WHERE id = %s",
            (prompt_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提示词不存在")
        if row.get("is_official"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="官方提示词不可删除")
        if row.get("owner_id") != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限删除该提示词")

        cursor.execute("DELETE FROM prompt_templates WHERE id = %s", (prompt_id,))
        conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除提示词失败: {exc}",
        )
    finally:
        if conn:
            conn.close()


@router.post("/{prompt_id}/use")
async def use_prompt(
    prompt_id: str,
    user_id: str = Depends(get_current_user_id),
):
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            """
            UPDATE prompt_templates
            SET usage_count = usage_count + 1,
                last_used_at = %s,
                updated_at = %s
            WHERE id = %s AND (is_official = TRUE OR owner_id = %s)
            RETURNING id
            """,
            (datetime.utcnow(), datetime.utcnow(), prompt_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提示词不存在")
        conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新使用次数失败: {exc}",
        )
    finally:
        if conn:
            conn.close()
