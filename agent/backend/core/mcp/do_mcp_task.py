"""
定时任务执行器
负责调度并触发 MCP 任务执行
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from ..system import config
from ..auth.auth_utils import generate_token
from ..db.dbutil import DatabaseUtil

logger = logging.getLogger(__name__)
db = DatabaseUtil()

_scheduler: Optional[AsyncIOScheduler] = None


def _get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=config.TASK_TIMEZONE)
    return _scheduler


def start_task_scheduler() -> None:
    scheduler = _get_scheduler()
    if scheduler.running:
        return
    scheduler.start()
    _load_and_schedule_tasks()
    logger.info("✅ 定时任务调度器已启动")


async def stop_task_scheduler() -> None:
    scheduler = _get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 定时任务调度器已停止")


def _load_and_schedule_tasks() -> None:
    rows = db.execute_query(
        """
        SELECT id FROM task_custom_mcp
        WHERE status IN ('pending', 'active')
        """,
        fetch="all",
    ) or []
    for row in rows:
        task_id = row.get("id")
        if task_id:
            schedule_task(task_id)


def schedule_task(task_id: str) -> None:
    task = db.execute_query(
        "SELECT * FROM task_custom_mcp WHERE id = %s",
        (task_id,),
        fetch="one",
    )
    if not task:
        logger.warning("task_scheduler: task not found (task_id=%s)", task_id)
        return
    if task.get("status") in {"cancelled", "completed", "failed"}:
        logger.info(
            "task_scheduler: skip task status=%s (task_id=%s)",
            task.get("status"),
            task_id,
        )
        return

    scheduler = _get_scheduler()
    try:
        trigger = _build_trigger(task)
    except Exception as exc:
        logger.error("task_scheduler: trigger error (task_id=%s) %s", task_id, exc)
        _mark_task_failed(task_id, f"trigger_error:{exc}")
        return

    scheduler.add_job(
        _execute_task,
        trigger=trigger,
        args=[task_id],
        id=task_id,
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )
    _refresh_next_run(task_id)
    logger.info(
        "task_scheduler: scheduled task_id=%s type=%s",
        task_id,
        task.get("schedule_type"),
    )


def cancel_task(task_id: str) -> None:
    scheduler = _get_scheduler()
    try:
        scheduler.remove_job(task_id)
        logger.info("task_scheduler: cancelled task_id=%s", task_id)
    except Exception:
        pass


def _build_trigger(task: dict):
    schedule_type = (task.get("schedule_type") or "cron").lower()
    if schedule_type == "date":
        run_at = task.get("run_at")
        if not run_at:
            raise ValueError("missing run_at")
        return DateTrigger(run_date=run_at)
    cron_expr = task.get("cron_expr") or ""
    if not cron_expr:
        raise ValueError("missing cron_expr")
    return CronTrigger.from_crontab(cron_expr, timezone=config.TASK_TIMEZONE)


def _refresh_next_run(task_id: str) -> None:
    scheduler = _get_scheduler()
    job = scheduler.get_job(task_id)
    next_run = job.next_run_time if job else None
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE task_custom_mcp
            SET next_run_at = %s,
                updated_at = CURRENT_TIMESTAMP,
                status = 'active'
            WHERE id = %s
            """,
            (next_run, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("task_scheduler: next_run updated task_id=%s next_run=%s", task_id, next_run)


def _mark_task_failed(task_id: str, reason: str) -> None:
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE task_custom_mcp
            SET status = 'failed',
                last_error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (reason, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    logger.warning("task_scheduler: task failed task_id=%s reason=%s", task_id, reason)


async def _execute_task(task_id: str) -> None:
    task = db.execute_query(
        "SELECT * FROM task_custom_mcp WHERE id = %s",
        (task_id,),
        fetch="one",
    )
    if not task:
        logger.warning("task_executor: task not found (task_id=%s)", task_id)
        return
    if task.get("status") in {"cancelled", "completed", "failed"}:
        logger.info(
            "task_executor: skip task status=%s (task_id=%s)",
            task.get("status"),
            task_id,
        )
        return

    schedule_type = (task.get("schedule_type") or "cron").lower()
    if schedule_type == "cron" and _is_cron_too_frequent(task):
        logger.info("任务触发频率过高，跳过执行: %s", task_id)
        _refresh_next_run(task_id)
        return

    _update_status(task_id, "running")
    try:
        logger.info("task_executor: executing task_id=%s", task_id)
        await _dispatch_task(task)
        if schedule_type == "date":
            _update_status(task_id, "completed")
            cancel_task(task_id)
        else:
            _update_status(task_id, "active")
            _refresh_next_run(task_id)
        logger.info("task_executor: completed task_id=%s", task_id)
    except Exception as exc:
        _mark_task_failed(task_id, f"dispatch_error:{exc}")


async def _dispatch_task(task: dict) -> None:
    user_id = task.get("user_id")
    agent_id = task.get("agent_id")
    session_id = task.get("session_id")
    message = task.get("task_message") or task.get("task_description") or ""
    if not (user_id and agent_id and session_id and message):
        raise ValueError("missing required fields")

    user = db.get_user_by_id(user_id)
    if not user or not user.get("username"):
        raise ValueError("user not found")

    token = generate_token(user_id, user["username"])
    task_prefix = "[TASK] 这是系统定时任务，请直接执行任务内容，不要对用户提问或对话。\n"
    payload = {
        "ai_agent_id": agent_id,
        "message": f"{task_prefix}{message}",
        "session_id": session_id,
    }
    url = f"{config.TASK_DISPATCH_BASE_URL}/api/v1/chat/send"
    headers = {"Authorization": f"Bearer {token}"}

    logger.info(
        "task_executor: dispatch task_id=%s agent_id=%s session_id=%s",
        task.get("id"),
        agent_id,
        session_id,
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    logger.info("task_executor: dispatch success task_id=%s", task.get("id"))


def _update_status(task_id: str, status: str) -> None:
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE task_custom_mcp
            SET status = %s,
                last_run_at = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, datetime.now(), task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _is_cron_too_frequent(task: dict) -> bool:
    min_interval = config.TASK_CRON_MIN_INTERVAL_SECONDS
    if min_interval <= 0:
        return False
    last_run = task.get("last_run_at")
    if not last_run:
        return False
    delta = datetime.now() - last_run
    return delta.total_seconds() < min_interval
