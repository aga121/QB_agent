"""
Knowledge base service layer.
Shared by HTTP API and MCP.
"""
import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import httpx
import psycopg2.extras

from ..db.dbutil import DatabaseUtil
from ..system import config

db = DatabaseUtil()

def _ensure_user_exists(user_id: str) -> None:
    if not user_id:
        raise RuntimeError("user_id 不能为空")
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        if cursor.fetchone() is None:
            raise RuntimeError("用户不存在")
    finally:
        conn.close()


async def get_embedding(text: str) -> List[float]:
    if not config.BIGMODEL_API_KEY:
        raise RuntimeError("BIGMODEL_API_KEY 未配置")
    payload = {
        "model": config.BIGMODEL_EMBEDDING_MODEL,
        "input": text,
        "dimensions": config.BIGMODEL_EMBEDDING_DIMENSIONS,
    }
    headers = {
        "Authorization": f"Bearer {config.BIGMODEL_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://open.bigmodel.cn/api/paas/v4/embeddings",
            json=payload,
            headers=headers,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"向量化失败: {resp.text}")
    data = resp.json()
    embedding = data.get("data", [{}])[0].get("embedding")
    if not embedding:
        raise RuntimeError("向量化返回为空")
    return embedding


async def add_memory(
    user_id: str,
    memory_type: str,
    content: str,
    title: Optional[str] = None,
    is_public: int = 0,
) -> Dict[str, Any]:
    _ensure_user_exists(user_id)
    embedding_str = None
    if config.KB_USE_VECTOR:
        embedding = await get_embedding(content)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    now = datetime.utcnow()
    memory_id = str(uuid.uuid4())

    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if embedding_str is not None:
            cursor.execute(
                """
                INSERT INTO memory_units
                (id, user_id, memory_type, title, content, embedding, status, is_public, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, (%s)::vector, 1, %s, %s, %s)
                RETURNING id, user_id, memory_type, title, content, status, is_public, created_at, updated_at
                """,
                (
                    memory_id,
                    user_id,
                    memory_type,
                    title,
                    content,
                    embedding_str,
                    is_public,
                    now,
                    now,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO memory_units
                (id, user_id, memory_type, title, content, embedding, status, is_public, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NULL, 1, %s, %s, %s)
                RETURNING id, user_id, memory_type, title, content, status, is_public, created_at, updated_at
                """,
                (
                    memory_id,
                    user_id,
                    memory_type,
                    title,
                    content,
                    is_public,
                    now,
                    now,
                ),
            )
        row = cursor.fetchone()
        conn.commit()
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "memory_type": row["memory_type"],
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "is_public": row["is_public"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    finally:
        conn.close()


async def update_memory(
    user_id: str,
    memory_id: str,
    memory_type: Optional[str] = None,
    title: Optional[str] = None,
    content: Optional[str] = None,
    is_public: Optional[int] = None,
    status: Optional[int] = None,
) -> Dict[str, Any]:
    _ensure_user_exists(user_id)
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute(
            "SELECT id, user_id FROM memory_units WHERE id = %s",
            (memory_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("记忆不存在")
        if row["user_id"] != user_id:
            raise RuntimeError("无权限修改该记忆")

        fields = []
        params: List[object] = []
        new_content = None
        if memory_type is not None:
            fields.append("memory_type = %s")
            params.append(memory_type)
        if title is not None:
            fields.append("title = %s")
            params.append(title)
        if content is not None:
            new_content = content
            fields.append("content = %s")
            params.append(content)
        if is_public is not None:
            fields.append("is_public = %s")
            params.append(is_public)
        if status is not None:
            fields.append("status = %s")
            params.append(status)

        if not fields and new_content is None:
            raise RuntimeError("没有可更新字段")

        if new_content is not None:
            if config.KB_USE_VECTOR:
                embedding = await get_embedding(new_content)
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                fields.append("embedding = (%s)::vector")
                params.append(embedding_str)
            else:
                fields.append("embedding = NULL")

        fields.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(memory_id)

        cursor.execute(
            f"""
            UPDATE memory_units
            SET {', '.join(fields)}
            WHERE id = %s
            RETURNING id, user_id, memory_type, title, content, status, is_public, created_at, updated_at
            """,
            tuple(params),
        )
        updated = cursor.fetchone()
        conn.commit()
        return {
            "id": updated["id"],
            "user_id": updated["user_id"],
            "memory_type": updated["memory_type"],
            "title": updated["title"],
            "content": updated["content"],
            "status": updated["status"],
            "is_public": updated["is_public"],
            "created_at": updated["created_at"].isoformat() if updated["created_at"] else None,
            "updated_at": updated["updated_at"].isoformat() if updated["updated_at"] else None,
        }
    finally:
        conn.close()


async def delete_memory(user_id: str, memory_id: str) -> None:
    _ensure_user_exists(user_id)
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute(
            "SELECT id, user_id FROM memory_units WHERE id = %s",
            (memory_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("记忆不存在")
        if row["user_id"] != user_id:
            raise RuntimeError("无权限删除该记忆")
        cursor.execute("DELETE FROM memory_units WHERE id = %s", (memory_id,))
        conn.commit()
    finally:
        conn.close()


async def query_memory(
    user_id: str,
    content: str,
    topk: int = 10,
) -> List[Dict[str, Any]]:
    _ensure_user_exists(user_id)
    topk = max(1, min(topk, 50))

    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if config.KB_USE_VECTOR:
            embedding = await get_embedding(content)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            cursor.execute(
                """
                WITH query AS (
                    SELECT (%s)::vector AS embedding,
                           plainto_tsquery('simple', %s) AS tsq
                )
                SELECT
                    m.id,
                    m.user_id,
                    m.memory_type,
                    m.title,
                    m.content,
                    m.is_public,
                    m.status,
                    m.created_at,
                    COALESCE((1 - (m.embedding <=> query.embedding)), 0) AS semantic_score,
                    ts_rank(m.content_tsv, query.tsq) AS keyword_score,
                    (0.55 * COALESCE((1 - (m.embedding <=> query.embedding)), 0) + 0.45 * ts_rank(m.content_tsv, query.tsq)) AS final_score
                FROM memory_units m, query
                WHERE m.status = 1
                  AND (m.user_id = %s OR m.is_public = 1)
                ORDER BY final_score DESC
                LIMIT %s
                """,
                (embedding_str, content, user_id, topk),
            )
        else:
            cursor.execute(
                """
                WITH query AS (
                    SELECT plainto_tsquery('simple', %s) AS tsq
                )
                SELECT
                    m.id,
                    m.user_id,
                    m.memory_type,
                    m.title,
                    m.content,
                    m.is_public,
                    m.status,
                    m.created_at,
                    0.0 AS semantic_score,
                    ts_rank(m.content_tsv, query.tsq) AS keyword_score,
                    ts_rank(m.content_tsv, query.tsq) AS final_score
                FROM memory_units m, query
                WHERE m.status = 1
                  AND (m.user_id = %s OR m.is_public = 1)
                ORDER BY final_score DESC
                LIMIT %s
                """,
                (content, user_id, topk),
            )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "memory_type": row["memory_type"],
                    "title": row["title"],
                    "content": row["content"],
                    "is_public": row["is_public"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "semantic_score": float(row["semantic_score"] or 0),
                    "keyword_score": float(row["keyword_score"] or 0),
                    "final_score": float(row["final_score"] or 0),
                }
            )
        return results
    finally:
        conn.close()


async def list_chat_fragments(user_id: str) -> List[Dict[str, Any]]:
    _ensure_user_exists(user_id)
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT id, content, created_at
            FROM memory_units
            WHERE user_id = %s
              AND status = 1
              AND memory_type = %s
              AND title = %s
            ORDER BY created_at DESC
            """,
            (user_id, "聊天碎片", "聊天碎片"),
        )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "content": row["content"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        return results
    finally:
        conn.close()


async def clear_chat_fragments(user_id: str) -> int:
    _ensure_user_exists(user_id)
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM memory_units
            WHERE user_id = %s
              AND memory_type = %s
              AND title = %s
            """,
            (user_id, "聊天碎片", "聊天碎片"),
        )
        deleted = cursor.rowcount or 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def _parse_kb_param_content(content: Optional[str]) -> Dict[str, Any]:
    if not content:
        return {}
    text = content.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError("进度参数必须是 JSON 格式") from exc
    if not isinstance(data, dict):
        raise RuntimeError("进度参数必须是 JSON 对象")
    last_created_at = data.get("last_created_at")
    if not isinstance(last_created_at, str) or not last_created_at.strip():
        raise RuntimeError("进度参数必须包含 last_created_at 字符串")
    try:
        data["last_created_at"] = datetime.fromisoformat(last_created_at)
    except Exception as exc:
        raise RuntimeError("last_created_at 不是合法的 ISO 时间字符串") from exc
    return data


async def dump_unprocessed_chat_records(user_id: str, output_dir: str) -> Tuple[str, int]:
    _ensure_user_exists(user_id)
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT content, updated_at
            FROM memory_units
            WHERE user_id = %s
              AND status = 1
              AND memory_type = %s
              AND title = %s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (user_id, "参数", "已整理记忆参数"),
        )
        param_row = cursor.fetchone()
        params = _parse_kb_param_content(param_row["content"] if param_row else None)

        last_created_at = params.get("last_created_at")
        if last_created_at:
            cursor.execute(
                """
                SELECT m.id, m.session_id, m.sequence_number, m.sender_type, m.content, m.created_at
                FROM chat_messages m
                JOIN chat_sessions s ON s.id = m.session_id
                WHERE s.user_id = %s
                  AND m.created_at > %s
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 500
                """,
                (user_id, last_created_at),
            )
        else:
            cursor.execute(
                """
                SELECT m.id, m.session_id, m.sequence_number, m.sender_type, m.content, m.created_at
                FROM chat_messages m
                JOIN chat_sessions s ON s.id = m.session_id
                WHERE s.user_id = %s
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 500
                """,
                (user_id,),
            )
        rows = cursor.fetchall()
    finally:
        conn.close()

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"unprocessed_chat_records_{user_id}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.txt"
    file_path = str(Path(output_dir) / filename)

    lines: List[str] = ["当前未处理聊天记录："]
    if params:
        lines.append(f"进度参数: {params}")
    if not rows:
        lines.append("无未处理记录")
    else:
        current_session = None
        for row in rows:
            session_id = row.get("session_id") or ""
            if session_id != current_session:
                current_session = session_id
                lines.append(f"\n会话 {session_id}:")
            lines.append(
                f"- {row.get('sequence_number')} | {row.get('sender_type')} | {row.get('created_at')}\n"
                f"  {row.get('content') or ''}"
            )

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return file_path, len(rows)


async def set_memory_progress_now(user_id: str) -> Dict[str, Any]:
    _ensure_user_exists(user_id)
    payload = {"last_created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    content = json.dumps(payload, ensure_ascii=False)

    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT id FROM memory_units
            WHERE user_id = %s
              AND memory_type = %s
              AND title = %s
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (user_id, "参数", "已整理记忆参数"),
        )
        row = cursor.fetchone()
        now = datetime.utcnow()
        if row:
            cursor.execute(
                """
                UPDATE memory_units
                SET content = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING id, content, updated_at
                """,
                (content, now, row["id"]),
            )
            updated = cursor.fetchone()
            conn.commit()
            return {
                "id": updated["id"],
                "content": updated["content"],
                "updated_at": updated["updated_at"].isoformat() if updated["updated_at"] else None,
            }
        memory_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO memory_units
            (id, user_id, memory_type, title, content, embedding, status, is_public, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NULL, 1, 0, %s, %s)
            RETURNING id, content, updated_at
            """,
            (memory_id, user_id, "参数", "已整理记忆参数", content, now, now),
        )
        created = cursor.fetchone()
        conn.commit()
        return {
            "id": created["id"],
            "content": created["content"],
            "updated_at": created["updated_at"].isoformat() if created["updated_at"] else None,
        }
    finally:
        conn.close()


async def add_memory_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for item in items:
        try:
            row = await add_memory(
                user_id=(item.get("user_id") or "").strip(),
                memory_type=(item.get("memory_type") or "").strip(),
                title=item.get("title"),
                content=(item.get("content") or "").strip(),
                is_public=int(item.get("is_public") or 0),
            )
            results.append({"ok": True, "id": row.get("id")})
        except Exception as exc:
            results.append({"ok": False, "error": str(exc)})
    return results


async def update_memory_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for item in items:
        try:
            row = await update_memory(
                user_id=(item.get("user_id") or "").strip(),
                memory_id=(item.get("memory_id") or "").strip(),
                memory_type=item.get("memory_type"),
                title=item.get("title"),
                content=item.get("content"),
                is_public=int(item.get("is_public")) if item.get("is_public") is not None else None,
                status=int(item.get("status")) if item.get("status") is not None else None,
            )
            results.append({"ok": True, "id": row.get("id")})
        except Exception as exc:
            results.append({"ok": False, "error": str(exc)})
    return results


async def delete_memory_batch(user_id: str, memory_ids: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for memory_id in memory_ids:
        try:
            await delete_memory(user_id=user_id, memory_id=(memory_id or "").strip())
            results.append({"ok": True, "id": memory_id})
        except Exception as exc:
            results.append({"ok": False, "id": memory_id, "error": str(exc)})
    return results


async def query_memory_batch(user_id: str, queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for query in queries:
        content = (query.get("content") or "").strip()
        topk = int(query.get("topk") or 10)
        try:
            rows = await query_memory(user_id=user_id, content=content, topk=topk)
            results.append({"ok": True, "content": content, "results": rows})
        except Exception as exc:
            results.append({"ok": False, "content": content, "error": str(exc)})
    return results
