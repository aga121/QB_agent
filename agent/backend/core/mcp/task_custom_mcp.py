"""
定时任务 MCP
"""
import json
import logging
import re
import uuid
from datetime import datetime
from typing import List

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..db.dbutil import DatabaseUtil
from .do_mcp_task import schedule_task, cancel_task

db = DatabaseUtil()
logger = logging.getLogger(__name__)


def _normalize_schedule_type(value: str) -> str:
    schedule_type = (value or "cron").strip().lower()
    if schedule_type not in {"cron", "date"}:
        schedule_type = "cron"
    return schedule_type


def _parse_run_at(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _has_timezone_suffix(value: str) -> bool:
    if not value:
        return False
    return value.endswith("Z") or bool(re.search(r"[+-]\d{2}:\d{2}$", value))


@tool(
    name="add_task",
    description=(
        "任务必须前提条件调用先获取当前系统时间mcp__22222222222222__now-time_info"
        "创建定时任务（批量）。输入 cron 或 date 计划，任务触发时会调用 /api/v1/chat/send 执行。"
        "参数：tasks(数组；每项包含 task_name, task_message, schedule_type[cron/date], "
        "cron_expr(仅cron), run_at(仅date, ISO), current_time(仅date, ISO), agent_id(必填)。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_name": {"type": "string"},
                        "task_description": {"type": "string"},
                        "task_message": {"type": "string"},
                        "schedule_type": {"type": "string"},
                        "cron_expr": {"type": "string"},
                        "run_at": {"type": "string"},
                        "current_time": {"type": "string"},
                        "agent_id": {"type": "string"},
                    },
                    "required": ["task_name", "agent_id"],
                },
            }
        },
        "required": ["tasks"],
    },
)
async def add_task(args: dict) -> dict:
    tasks = args.get("tasks") or []
    if not tasks:
        return {"content": [{"type": "text", "text": "tasks 不能为空"}]}

    created_ids: List[str] = []
    for task in tasks:
        task_id = str(uuid.uuid4())
        schedule_type = _normalize_schedule_type(task.get("schedule_type"))
        cron_expr = (task.get("cron_expr") or "").strip()
        run_at_raw = (task.get("run_at") or "").strip()
        current_time_raw = (task.get("current_time") or "").strip()
        run_at = _parse_run_at(run_at_raw)
        current_time = _parse_run_at(current_time_raw)
        if schedule_type == "cron" and not cron_expr:
            return {"content": [{"type": "text", "text": "cron 任务必须提供 cron_expr"}]}
        if schedule_type == "date" and not run_at:
            return {"content": [{"type": "text", "text": "date 任务必须提供 run_at(ISO格式)"}]}
        if schedule_type == "date":
            if not current_time:
                return {"content": [{"type": "text", "text": "date 任务必须提供 current_time(ISO格式)"}]}
            if not _has_timezone_suffix(run_at_raw) or not _has_timezone_suffix(current_time_raw):
                return {"content": [{"type": "text", "text": "run_at/current_time 必须包含时区偏移（如 2026-01-14T19:30:00+08:00），请先获取当前系统时间再设置"}]}
            if current_time.tzinfo is None:
                return {"content": [{"type": "text", "text": "current_time 必须包含时区信息"}]}
            now = datetime.now(current_time.tzinfo)
            if abs((now - current_time).total_seconds()) > 120:
                return {"content": [{"type": "text", "text": "current_time 与系统时间偏差过大，请先获取当前系统时间再设置"}]}

        agent_id = (task.get("agent_id") or "").strip()
        session_id = (task.get("session_id") or "").strip()

        if not agent_id:
            return {"content": [{"type": "text", "text": "agent_id 必填"}]}
        row = db.execute_query(
            """
            SELECT
                u.owner_id AS user_id,
                (
                    SELECT id
                    FROM chat_sessions
                    WHERE user_id = u.owner_id AND ai_agent_id = %s
                    ORDER BY COALESCE(last_message_at, updated_at) DESC NULLS LAST
                    LIMIT 1
                ) AS session_id
            FROM users u
            WHERE u.id = %s
            """,
            (agent_id, agent_id),
            fetch="one",
        )
        user_id = row.get("user_id") if row else ""
        if not user_id:
            return {"content": [{"type": "text", "text": "无法确定 user_id"}]}
        session_id = row.get("session_id") if row else ""
        if not session_id:
            return {"content": [{"type": "text", "text": "缺少 session_id，且无法自动匹配会话"}]}

        logger.info(
            "task_mcp:add_task resolved agent_id=%s session_id=%s schedule_type=%s",
            agent_id,
            session_id,
            schedule_type,
        )
        db.execute_query(
            """
            INSERT INTO task_custom_mcp (
                id, user_id, agent_id, session_id, task_name, task_description,
                task_message, schedule_type, cron_expr, run_at, status, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                task_id,
                user_id,
                agent_id,
                session_id,
                task.get("task_name"),
                task.get("task_description") or "",
                task.get("task_message") or "",
                schedule_type,
                cron_expr if schedule_type == "cron" else None,
                run_at if schedule_type == "date" else None,
            ),
            fetch=None,
        )
        schedule_task(task_id)
        created_ids.append(task_id)
        logger.info("task_mcp:add_task scheduled task_id=%s", task_id)

    return {"content": [{"type": "text", "text": json.dumps({"task_ids": created_ids}, ensure_ascii=True)}]}


@tool(
    name="list_tasks",
    description="查询定时任务列表。参数：user_id(必填)、status(可选)、include_completed(可选)",
    input_schema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "status": {"type": "string"},
            "include_completed": {"type": "boolean"},
        },
        "required": ["user_id"],
    },
)
async def list_tasks(args: dict) -> dict:
    user_id = args.get("user_id")
    status = (args.get("status") or "").strip()
    include_completed = bool(args.get("include_completed"))
    where = ["user_id = %s"]
    params = [user_id]
    if status:
        where.append("status = %s")
        params.append(status)
    elif not include_completed:
        where.append("status NOT IN ('completed', 'cancelled')")

    rows = db.execute_query(
        f"""
        SELECT id, task_name, task_description, task_message, schedule_type,
               cron_expr, run_at, status, last_run_at, next_run_at, created_at, updated_at
        FROM task_custom_mcp
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        """,
        tuple(params),
    ) or []

    return {"content": [{"type": "text", "text": json.dumps({"tasks": rows}, ensure_ascii=True, default=str)}]}


@tool(
    name="cancel_task",
    description="取消定时任务（停止调度并标记为 cancelled）。参数：task_id",
    input_schema={"task_id": str},
)
async def cancel_task_tool(args: dict) -> dict:
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return {"content": [{"type": "text", "text": "task_id 不能为空"}]}
    cancel_task(task_id)
    db.execute_query(
        """
        UPDATE task_custom_mcp
        SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (task_id,),
        fetch=None,
    )
    return {"content": [{"type": "text", "text": json.dumps({"task_id": task_id, "status": "cancelled"}, ensure_ascii=True)}]}


@tool(
    name="update_task",
    description=(
        "更新定时任务并重新调度。参数：task_id、task_name、task_description、task_message、"
        "schedule_type、cron_expr、run_at"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "task_name": {"type": "string"},
            "task_description": {"type": "string"},
            "task_message": {"type": "string"},
            "schedule_type": {"type": "string"},
            "cron_expr": {"type": "string"},
            "run_at": {"type": "string"},
        },
        "required": ["task_id"],
    },
)
async def update_task(args: dict) -> dict:
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return {"content": [{"type": "text", "text": "task_id 不能为空"}]}

    schedule_type = args.get("schedule_type")
    cron_expr = args.get("cron_expr")
    run_at = args.get("run_at")
    updates = []
    params = []

    if args.get("task_name") is not None:
        updates.append("task_name = %s")
        params.append(args.get("task_name"))
    if args.get("task_description") is not None:
        updates.append("task_description = %s")
        params.append(args.get("task_description"))
    if args.get("task_message") is not None:
        updates.append("task_message = %s")
        params.append(args.get("task_message"))
    if schedule_type is not None:
        schedule_type = _normalize_schedule_type(schedule_type)
        updates.append("schedule_type = %s")
        params.append(schedule_type)
    if cron_expr is not None:
        updates.append("cron_expr = %s")
        params.append(cron_expr)
    if run_at is not None:
        parsed = _parse_run_at(run_at)
        updates.append("run_at = %s")
        params.append(parsed)

    if not updates:
        return {"content": [{"type": "text", "text": "没有更新字段"}]}

    params.append(task_id)
    db.execute_query(
        f"""
        UPDATE task_custom_mcp
        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        tuple(params),
        fetch=None,
    )
    schedule_task(task_id)
    return {"content": [{"type": "text", "text": json.dumps({"task_id": task_id, "status": "updated"}, ensure_ascii=True)}]}


task_custom_mcp = create_sdk_mcp_server(
    name="task-custom",
    version="1.0.0",
    tools=[
        add_task,
        list_tasks,
        cancel_task_tool,
        update_task,
    ],
)
