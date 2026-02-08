"""
API Key utilities for selecting model credentials by membership level.
"""

import uuid
from typing import Dict, Optional, List, Any

import psycopg2.extras

from ..db.dbutil import DatabaseUtil

db = DatabaseUtil()


def _next_priority(membership_type: str) -> int:
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            """
            SELECT COALESCE(MAX(priority), 0) AS max_priority
            FROM api_keys
            WHERE membership_type = %s
            """,
            (membership_type,),
        )
        row = cursor.fetchone()
        max_priority = row["max_priority"] if row else 0
        return int(max_priority) + 1
    finally:
        conn.close()


def create_api_key(
    membership_type: str,
    base_url: str,
    auth_token: str,
    description: Optional[str] = None,
    model_name: Optional[str] = None,
    status: str = "active",
    error: Optional[str] = None,
) -> str:
    """
    Create a new API key record. Each creation increments priority by 1.
    """
    key_id = str(uuid.uuid4())
    priority = _next_priority(membership_type)
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api_keys
            (id, membership_type, base_url, auth_token, description, model_name, priority, status, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                key_id,
                membership_type,
                base_url,
                auth_token,
                description,
                model_name,
                priority,
                status,
                error,
            ),
        )
        conn.commit()
        return key_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_api_key_for_membership(membership_type: str) -> Optional[Dict[str, Any]]:
    """
    Fetch an active API key for a membership type (lowest priority first).
    Keys with membership_type 'all' are also eligible.
    Each fetch bumps the selected key's priority to the end for simple rotation.
    """
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            """
            WITH picked AS (
                SELECT id
                FROM api_keys
                WHERE membership_type IN (%s, 'all') AND status = 'active'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                FOR UPDATE
            )
            UPDATE api_keys
            SET priority = (
                SELECT COALESCE(MAX(priority), 0) + 1
                FROM api_keys
                WHERE membership_type IN (%s, 'all')
            )
            WHERE id IN (SELECT id FROM picked)
            RETURNING id, membership_type, base_url, auth_token, model_name, priority
            """,
            (membership_type, membership_type),
        )
        row = cursor.fetchone()
        conn.commit()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_api_keys(membership_type: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if membership_type:
            cursor.execute(
                """
                SELECT id, membership_type, base_url, model_name, priority, status, error, created_at
                FROM api_keys
                WHERE membership_type = %s
                ORDER BY priority DESC, created_at DESC
                """,
                (membership_type,),
            )
        else:
            cursor.execute(
                """
                SELECT id, membership_type, base_url, model_name, priority, status, error, created_at
                FROM api_keys
                ORDER BY membership_type, priority DESC, created_at DESC
                """
            )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_api_key_status(key_id: str, status: str, error: Optional[str] = None) -> None:
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE api_keys
            SET status = %s, error = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, error, key_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
