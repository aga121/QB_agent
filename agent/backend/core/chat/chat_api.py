"""
聊天API模块
处理用户与AI智能体之间的聊天交互
"""

import uuid
import json
import psycopg2.extras
import asyncio
import sys
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from ..agent.agent_manager import agent_manager, get_agent_client, close_agent_client, get_agent_work_dir
from ..auth.auth_filter import get_current_user_id
from ..db.dbutil import DatabaseUtil
from ..system import config
from ..membership.sub_api import check_user_message_quota
from ..firewall.firewall_bash import check_user_storage_quota
from ..kbs import service as kbs_service

# 创建路由器
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# 数据库工具
db = DatabaseUtil()
logger = logging.getLogger(__name__)

# 预览文件缓存（用于检测新增可预览文件）
_preview_cache_lock = asyncio.Lock()
_preview_file_cache: Dict[str, Dict[str, float]] = {}
_preview_snapshot_cache: Dict[str, Dict[str, Any]] = {}
PREVIEWABLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".html", ".htm"}

# 针对同一智能体的并发请求加锁，避免底层传输状态冲突
agent_locks: Dict[str, asyncio.Lock] = {}
def get_agent_lock(agent_id: str) -> asyncio.Lock:
    lock = agent_locks.get(agent_id)
    if lock is None:
        lock = asyncio.Lock()
        agent_locks[agent_id] = lock
    return lock

# 针对同一会话的发送队列，允许把短时间内的多条消息合并后再请求Claude
pending_message_queues: Dict[str, List[str]] = {}
queue_processing_flags: Dict[str, bool] = {}
def _queue_key(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"

async def _build_kb_context(user_id: str, message: str, topk: int = 10) -> Optional[str]:
    if not config.KB_ENABLED:
        return None
    if not message or not message.strip():
        return None
    try:
        rows = await kbs_service.query_memory(user_id=user_id, content=message, topk=topk)
    except Exception as exc:
        logger.warning("KB query failed: %s", exc)
        return None
    if not rows:
        return None
    lines: List[str] = []
    for row in rows:
        memory_type = row.get("memory_type") or ""
        title = row.get("title") or ""
        content = (row.get("content") or "").strip()
        if len(content) > 500:
            content = content[:500].rstrip() + "..."
        header = f"- {memory_type}"
        if title:
            header = f"{header} | {title}"
        lines.append(f"{header}\n  {content}")
    return "\n".join(lines)

async def _record_chat_fragment(user_id: str, message: str) -> None:
    if not config.KB_ENABLED:
        return
    if not message:
        return
    content = message.strip()
    if len(content) <= 5:
        return
    try:
        await kbs_service.add_memory(
            user_id=user_id,
            memory_type="聊天碎片",
            title="聊天碎片",
            content=content,
            is_public=0,
        )
    except Exception as exc:
        logger.warning("KB add_memory failed: %s", exc)

# Pydantic模型定义
class ChatMessageRequest(BaseModel):
    """发送消息请求模型"""
    session_id: Optional[str] = None  # 会话ID，可选
    ai_agent_id: str  # AI智能体ID
    message: str  # 消息内容
    message_type: str = "text"  # 消息类型：text, image, file
    metadata: Optional[str] = None  # 元数据（JSON字符串）

class ChatMessageResponse(BaseModel):
    """发送消息响应模型"""
    success: bool
    message: str
    session_id: str
    timestamp: datetime
    client_missing: Optional[bool] = None

class ChatMessageRecord(BaseModel):
    """聊天记录模型"""
    id: str
    session_id: str
    sender_id: str
    sender_type: str
    sender_name: Optional[str] = None
    content: str
    message_type: str
    metadata: Optional[str]
    created_at: datetime

class ChatSession(BaseModel):
    """聊天会话模型"""
    id: str
    user_id: str
    ai_agent_id: str
    title: Optional[str]


@router.get("/ui-config")
async def get_chat_ui_config() -> Dict[str, Any]:
    return {
        "extensions_enabled": config.CHAT_EXTENSION_ENABLED,
        "public_base_url": config.PUBLIC_BASE_URL,
    }
    is_active: bool
    last_message_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

def create_session(user_id: str, ai_agent_id: str, session_claude_id: Optional[str] = None) -> str:
    """
    创建新的聊天会话

    Args:
        user_id: 用户ID
        ai_agent_id: AI智能体ID
        session_claude_id: Claude SDK的会话ID

    Returns:
        会话ID
    """
    session_id = str(uuid.uuid4())
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        allowed, used_bytes, quota_bytes = check_user_storage_quota(user_id)
        if not allowed:
            used_mb = round(used_bytes / 1024 / 1024, 1)
            quota_mb = round(quota_bytes / 1024 / 1024, 1)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"storage_exceeded:用户存储已超过限制（{used_mb}MB / {quota_mb}MB），请清理后再继续。"
            )
        cursor.execute('''
            INSERT INTO chat_sessions
            (id, user_id, ai_agent_id, session_claude_id)
            VALUES (%s, %s, %s, %s)
        ''', (session_id, user_id, ai_agent_id, session_claude_id))

        conn.commit()
        return session_id
    finally:
        conn.close()

def get_or_create_session(user_id: str, ai_agent_id: str, session_id: Optional[str] = None) -> tuple:
    """
    获取或创建聊天会话

    Args:
        user_id: 用户ID
        ai_agent_id: AI智能体ID
        session_id: 会话ID（可选）

    Returns:
        (session_id, is_new_session)
    """
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if session_id:
            # 检查会话是否存在
            cursor.execute('''
                SELECT id FROM chat_sessions
                WHERE id = %s AND user_id = %s AND ai_agent_id = %s
            ''', (session_id, user_id, ai_agent_id))

            if cursor.fetchone():
                return session_id, False

        # 创建新会话
        new_session_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO chat_sessions
            (id, user_id, ai_agent_id)
            VALUES (%s, %s, %s)
        ''', (new_session_id, user_id, ai_agent_id))

        conn.commit()
        return new_session_id, True
    finally:
        conn.close()

def save_message(session_id: str, sender_id: str, sender_type: str,
                  content: str, message_type: str = "text", metadata: Optional[str] = None):
    """
    保存聊天消息

    Args:
        session_id: 会话ID
        sender_id: 发送者ID
        sender_type: 发送者类型（human/ai）
        content: 消息内容
        message_type: 消息类型
        metadata: 元数据
    """
    message_id = str(uuid.uuid4())
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 获取当前会话的最大序号
        cursor.execute('''
            SELECT COALESCE(MAX(sequence_number), 0) as max_seq
            FROM chat_messages
            WHERE session_id = %s
        ''', (session_id,))

        result = cursor.fetchone()
        next_sequence = result['max_seq'] + 1 if result else 1

        cursor.execute('''
            INSERT INTO chat_messages
            (id, session_id, sequence_number, sender_id, sender_type, content, message_type, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (message_id, session_id, next_sequence, sender_id, sender_type, content, message_type, metadata))

        # 更新会话的最后消息时间
        cursor.execute('''
            UPDATE chat_sessions
            SET last_message_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (session_id,))

        conn.commit()

        # 更新 Redis 缓存：增加该会话的消息计数
        try:
            cursor.execute('''
                SELECT user_id FROM chat_sessions WHERE id = %s
            ''', (session_id,))
            session = cursor.fetchone()
            if session and session.get('user_id'):
                from ..cache.redis_cache import increment_sync_count
                if increment_sync_count(session['user_id'], session_id):
                    logger.info("📈 Redis 缓存已更新: user_id=%s, session_id=%s", session['user_id'], session_id)
        except Exception as e:
            logger.warning("更新 Redis 缓存失败: %s", str(e))
    finally:
        conn.close()

def update_session_claude_id(session_id: str, session_claude_id: str):
    """更新会话的Claude SDK ID"""
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute('''
            UPDATE chat_sessions
            SET session_claude_id = %s
            WHERE id = %s
        ''', (session_claude_id, session_id))

        conn.commit()
    finally:
        conn.close()

def _collect_workdir_info(user_id: str, agent_id: str) -> Dict[str, Any]:
    """
    收集工作目录的轻量级快照，用于前端检测是否需要刷新文件树

    优化：
    - 只遍历到第2层（减少开销）
    - 排除常见的依赖包目录（.git, venv, node_modules等）
    """
    from pathlib import Path
    base = Path(get_agent_work_dir(user_id, agent_id)).resolve()

    # 需要排除的目录名（依赖包、版本控制等）
    IGNORED_DIRS = {
        '.git', '.svn', '.hg',  # 版本控制
        'venv', '.venv', 'env', '.env', 'virtualenv',  # Python虚拟环境
        'node_modules',  # Node.js依赖
        '__pycache__', '.pytest_cache', '.mypy_cache',  # Python缓存
        'dist', 'build', '*.egg-info',  # 构建产物
        '.next', '.nuxt',  # Next.js
        'target', 'bin', 'obj',  # 其他构建产物
    }

    info: Dict[str, Any] = {
        "path": str(base),
        "exists": base.exists(),
        "file_count": 0,
        "dir_count": 0,
        "latest_mtime": None,
    }

    if not base.exists():
        return info

    latest_mtime = None
    try:
        # 只遍历到第2层：base/* 和 base/*/*
        for level0 in base.iterdir():
            if level0.name in IGNORED_DIRS:
                continue

            try:
                stat_res = level0.stat()
            except Exception:
                continue

            if level0.is_dir():
                info["dir_count"] += 1
                mtime = stat_res.st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime

                # 第2层
                try:
                    for level1 in level0.iterdir():
                        if level1.name in IGNORED_DIRS:
                            continue

                        try:
                            stat_res1 = level1.stat()
                        except Exception:
                            continue

                        if level1.is_dir():
                            info["dir_count"] += 1
                        else:
                            info["file_count"] += 1

                        mtime = stat_res1.st_mtime
                        if latest_mtime is None or mtime > latest_mtime:
                            latest_mtime = mtime
                except Exception:
                    pass
            else:
                info["file_count"] += 1
                mtime = stat_res.st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime

        if latest_mtime is not None:
            info["latest_mtime"] = datetime.fromtimestamp(latest_mtime).isoformat()
    except Exception as exc:
        print(f"收集工作目录信息失败: {exc}", file=sys.stderr)

    return info


def _collect_previewable_files(base: Path, max_depth: int = 4) -> Dict[str, float]:
    """
    收集可预览文件（png/jpg/svg/html等）的相对路径与mtime。
    为避免开销，仅遍历到指定深度。
    """
    IGNORED_DIRS = {
        '.git', '.svn', '.hg',
        'venv', '.venv', 'env', '.env', 'virtualenv',
        'node_modules',
        '__pycache__', '.pytest_cache', '.mypy_cache',
        'dist', 'build', '*.egg-info',
        '.next', '.nuxt',
        'target', 'bin', 'obj',
    }

    files: Dict[str, float] = {}
    if not base.exists():
        return files

    def add_file(path: Path) -> None:
        ext = path.suffix.lower()
        if ext not in PREVIEWABLE_EXTENSIONS:
            return
        try:
            rel = str(path.relative_to(base))
            files[rel] = path.stat().st_mtime
        except Exception:
            return

    try:
        base_depth = len(base.parts)
        for root, dirs, filenames in os.walk(base):
            current_depth = len(Path(root).parts) - base_depth
            # 超过深度就不再下钻
            if current_depth >= max_depth:
                dirs[:] = []
                continue

            # 过滤忽略目录
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

            for name in filenames:
                if name in IGNORED_DIRS:
                    continue
                add_file(Path(root) / name)
    except Exception:
        pass

    return files


async def _maybe_emit_preview_messages(
    user_id: str,
    session_id: str,
    agent_id: str,
    snapshot: Dict[str, Any]
) -> None:
    """
    当检测到工作目录变化时，找出新增可预览文件并写入聊天记录。
    初次建立缓存时不推送，避免启动时刷屏。
    """
    if not session_id or not agent_id or not snapshot or not snapshot.get("exists"):
        return

    async with _preview_cache_lock:
        previous_snapshot = _preview_snapshot_cache.get(session_id)
        if previous_snapshot:
            if (
                previous_snapshot.get("latest_mtime") == snapshot.get("latest_mtime")
                and previous_snapshot.get("file_count") == snapshot.get("file_count")
                and previous_snapshot.get("dir_count") == snapshot.get("dir_count")
            ):
                return

        work_dir = Path(get_agent_work_dir(user_id, agent_id)).resolve()
        current_files = _collect_previewable_files(work_dir)
        previous_files = _preview_file_cache.get(session_id)

        # 首次缓存：只记录，不推送
        if previous_files is None:
            _preview_file_cache[session_id] = current_files
            _preview_snapshot_cache[session_id] = snapshot
            return

        new_paths = [path for path in current_files.keys() if path not in previous_files]
        if new_paths:
            new_paths.sort(key=lambda p: current_files.get(p, 0))
            for rel_path in new_paths:
                payload = {
                    "agent_id": agent_id,
                    "path": rel_path,
                    "name": Path(rel_path).name,
                }
                marker = json.dumps(payload, ensure_ascii=True)
                content = f"新增可预览文件：`{rel_path}`\n<!--preview-file:{marker}-->"
                metadata = json.dumps({"path": rel_path, "preview": True, "agent_id": agent_id}, ensure_ascii=True)
                try:
                    save_message(session_id, agent_id, "ai", content, "file", metadata)
                except Exception as exc:
                    logger.warning("写入预览消息失败: %s", str(exc))

        _preview_file_cache[session_id] = current_files
        _preview_snapshot_cache[session_id] = snapshot

async def _ensure_agent_client(agent_id: str, user_id: str, session_claude_id: Optional[str]):
    """
    获取可用的AI客户端；如果已有客户端但会话ID不一致则重建以确保记忆延续
    """
    from ..agent.agent_manager import get_agent_work_dir, initialize_agent_client
    # 调试：观察当前已缓存的客户端列表
    try:
        cached_ids = list(agent_manager._clients.keys())
        logger.info("======== [chat/send] cached_clients=%s", cached_ids)
    except Exception:
        pass
    client = await get_agent_client(agent_id)
    current_resume = None
    options = agent_manager._client_options.get(agent_id)
    if options:
        current_resume = getattr(options, "resume", None)

    # 如果已有客户端但resume与持久化的session不匹配，则重建
    if client:
        need_rebuild = False
        rebuild_reasons = []
        try:
            settings = db.get_agent_settings(agent_id) or {}
            desired_prompt = settings.get("system_prompt")
            desired_work_dir = settings.get("work_dir")
            current_prompt = getattr(options, "system_prompt", None) if options else None
            current_work_dir = getattr(options, "cwd", None) if options else None
            if desired_prompt:
                try:
                    from ..firewall.firewall_bash import get_bash_isolation_prompt
                    isolation_prompt = get_bash_isolation_prompt(current_work_dir)
                    if isolation_prompt and isolation_prompt not in desired_prompt:
                        desired_prompt = desired_prompt + isolation_prompt
                except Exception:
                    pass
            # system_prompt 变更不再触发重建，避免频繁断开连接
            if desired_work_dir and desired_work_dir != current_work_dir:
                need_rebuild = True
                rebuild_reasons.append("work_dir_mismatch")
        except Exception:
            pass
        if session_claude_id and session_claude_id != current_resume:
            if current_resume:
                # 已有 resume 但与DB不一致，重建
                need_rebuild = True
                rebuild_reasons.append("resume_mismatch")
            else:
                # 客户端存在但未记录 resume，直接更新选项以复用实例
                try:
                    agent_manager._client_options[agent_id].resume = session_claude_id  # type: ignore[attr-defined]
                    current_resume = session_claude_id
                except Exception:
                    need_rebuild = True
        elif session_claude_id is None and current_resume:
            # 当前请求未绑定Claude会话，但客户端仍携带旧会话，保持复用以避免反复重建
            pass

        if need_rebuild:
            logger.info(
                "======== [chat/send] rebuild agent=%s reasons=%s",
                agent_id,
                rebuild_reasons,
            )
            await close_agent_client(agent_id)
            client = None

    # 如无客户端则按最新session创建
    if not client:
        work_dir = get_agent_work_dir(user_id, agent_id)
        agent_name = f"AI_{agent_id[:8]}"
        try:
            info = db.get_user_by_id(agent_id)
            if info and info.get("username"):
                agent_name = info.get("username")
        except Exception:
            pass
        init_start = datetime.now()
        success = await initialize_agent_client(
            agent_id,
            agent_name,
            work_dir,
            session_claude_id,
            continue_conversation=bool(session_claude_id)
        )
        init_cost_ms = int((datetime.now() - init_start).total_seconds() * 1000)
        logger.info(
            "======== [chat/send] init agent=%s cost=%sms resume=%s",
            agent_id,
            init_cost_ms,
            session_claude_id,
        )
        if not success:
            return None
        client = await get_agent_client(agent_id)

    return client

async def _process_ai_response(session_id: str, agent_id: str, message: str, _retry: bool = False):
    """
    异步处理AI回复（后台任务）

    Args:
        session_id: 会话ID
        agent_id: AI智能体ID
        message: 用户消息
    """
    try:
        # 获取会话信息以找到 user_id
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('''
            SELECT user_id, session_claude_id FROM chat_sessions WHERE id = %s
        ''', (session_id,))
        session_info = cursor.fetchone()
        conn.close()

        if not session_info:
            logger.warning("Session not found: %s", session_id)
            return

        user_id = session_info["user_id"]
        session_claude_id = session_info["session_claude_id"]

        kb_context = await _build_kb_context(user_id, message)
        if kb_context:
            message = f"{message}\n==========\n根据用户消息查到的知识库片段：\n{kb_context}"

        # 3. 获取AI客户端，确保绑定正确的会话ID以保持记忆
        client = await _ensure_agent_client(agent_id, user_id, session_claude_id)

        # 4. 发送消息给AI（加锁避免并发写入同一传输流）
        if not client:
            logger.warning("AI agent not available: %s", agent_id)
            return

        lock = get_agent_lock(agent_id)
        ai_response = ""
        text_logged = False
        overall_start = datetime.now()
        async with lock:
            # 仅在未连接或超过空闲阈值时重连
            connect_start = datetime.now()
            try:
                from ..agent.agent_manager import ensure_agent_connected
                await ensure_agent_connected(agent_id)
            except Exception:
                pass
            connect_cost_ms = int((datetime.now() - connect_start).total_seconds() * 1000)

            query_start = datetime.now()
            await client.query(message)
            query_cost_ms = int((datetime.now() - query_start).total_seconds() * 1000)
            # 记录调用耗时，便于定位延迟来源
            logger.info(
                "======== [chat/send] agent=%s connect=%sms query=%sms",
                agent_id,
                connect_cost_ms,
                query_cost_ms,
            )

            # 5. 接收AI回复并实时保存进度
            from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage, ToolUseBlock, ToolResultBlock, ThinkingBlock
            recv_start = datetime.now()
            text_block_count = 0
            first_block_ms: Optional[int] = None

            def log_progress(content: str, subtype: Optional[str] = None):
                if not content:
                    return
                save_message(
                    session_id,
                    agent_id,
                    "ai",
                    content,
                    "text",
                    json.dumps({"subtype": subtype}) if subtype else None
                )

            # 提示用户：AI 正在处理
            log_progress("正在深度思考中", "thinking")

            # 使用与 demo 一致的 receive_response，避免额外等待
            async for msg in client.receive_response():
                # 记录 Claude 会话ID
                msg_session_id = getattr(msg, 'session_id', None)
                if msg_session_id and msg_session_id != session_claude_id:
                    update_session_claude_id(session_id, msg_session_id)
                    session_claude_id = msg_session_id

                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, ThinkingBlock):
                            # AI 思考过程（可选显示）
                            thinking_content = getattr(block, "thinking", "")
                            if thinking_content and len(thinking_content) < 500:  # 只显示短思考
                                log_progress(f"💭 {thinking_content[:200]}...", "thinking")
                        elif isinstance(block, ToolUseBlock):
                            tool_name = block.name or "未知工具"
                            detail = ""
                            if hasattr(block, "input") and isinstance(block.input, dict):
                                path = block.input.get("file_path") or block.input.get("path") or ""
                                if path:
                                    # 只显示文件名，不显示完整路径
                                    filename = path.split("/")[-1]
                                    detail = f" -> {filename}"
                            log_progress(f"正在拼命使用工具 {tool_name}{detail}", "tool_use")
                        elif isinstance(block, ToolResultBlock):
                            tool_name = (
                                getattr(block, "name", None)
                                or getattr(block, "tool_name", None)
                                or "工具"
                            )
                            summary = ""
                            output = getattr(block, "output", None) or getattr(block, "result", None)
                            if output:
                                text_out = str(output)
                                summary = f" 结果: {text_out[:200]}" if text_out else ""
                            log_progress(f"✅ 工具 {tool_name} 执行完成{summary}", "tool_result")
                        elif isinstance(block, TextBlock):
                            chunk = block.text or ""
                            ai_response += chunk
                            text_block_count += 1
                            if first_block_ms is None:
                                first_block_ms = int((datetime.now() - recv_start).total_seconds() * 1000)
                            if chunk.strip():
                                log_progress(f"{chunk}", "text_block")
                                text_logged = True

                elif isinstance(msg, ResultMessage):
                    # 结果消息标记结束
                    status = getattr(msg, "subtype", None) or "success"
                    result_text = getattr(msg, "result", None)
                    if status == "error":
                        log_progress(f"❌ 任务失败: {result_text}", "error")
                    # 任务完成不显示，由 AI 的回复内容自然结束
                    break
            recv_cost_ms = int((datetime.now() - recv_start).total_seconds() * 1000)
            total_cost_ms = int((datetime.now() - overall_start).total_seconds() * 1000)
            logger.info(
                "======== [chat/send] agent=%s recv=%sms blocks=%s first_block=%sms total=%sms",
                agent_id,
                recv_cost_ms,
                text_block_count,
                first_block_ms,
                total_cost_ms,
            )

        # 保存完整AI回复（汇总）
        if ai_response and not text_logged:
            save_message(
                session_id,
                agent_id,
                "ai",
                ai_response,
                "text"
            )

    except Exception as e:
        err_msg = str(e)
        logger.exception("Error in _process_ai_response: %s", err_msg)
        if not _retry and (
            "terminated process" in err_msg.lower()
            or "message reader" in err_msg.lower()
            or "exit code" in err_msg.lower()
            or "cannot write to terminated process" in err_msg.lower()
        ):
            try:
                await close_agent_client(agent_id)
                update_session_claude_id(session_id, None)
                await _ensure_agent_client(agent_id, user_id, None)
                await _process_ai_response(session_id, agent_id, message, _retry=True)
                return
            except Exception:
                logger.exception("Failed to reinitialize agent after fatal CLI error (agent_id=%s)", agent_id)
        # 保存错误消息
        save_message(
            session_id,
            agent_id,
            "ai",
            "抱歉，处理您的消息时出现了错误,请重新登陆系统方可解决",
            "text",
            json.dumps({"error": True})
        )


async def _process_queue(agent_id: str, session_id: str, key: str):
    """处理同一会话的消息队列，将积累的消息合并后再请求Claude"""
    try:
        while pending_message_queues.get(key):
            # 把当前队列的消息取出并清空队列
            messages = pending_message_queues.get(key, [])
            pending_message_queues[key] = []
            if not messages:
                break
            combined_message = "\n".join(messages)
            await _process_ai_response(session_id, agent_id, combined_message)
    finally:
        queue_processing_flags[key] = False


# API端点实现
@router.post("/send", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    发送消息给AI智能体

    处理流程：
    1. 获取或创建会话
    2. 保存用户消息
    3. 立即返回成功响应
    4. 异步处理AI回复（不阻塞响应）
    """

    try:
        # 0. 检查会员配额并计数（只要调用接口就计数）
        quota = check_user_message_quota(user_id, increment=True)
        if not quota['allowed']:
            # 非会员超过配额限制（使用动态配置）
            limit_msg = f"{config.NON_MEMBER_LIMIT_HOURS}小时{config.NON_MEMBER_LIMIT_MAX}次"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"quota_exceeded:{limit_msg}:您已超过免费使用次数限制，请订阅会员继续使用"
            )

        # 1. 获取或创建会话
        session_id, is_new_session = get_or_create_session(
            user_id,
            request.ai_agent_id,
            request.session_id
        )

        # 2. 保存用户消息
        save_message(
            session_id,
            user_id,
            "human",
            request.message,
            request.message_type,
            request.metadata
        )
        await _record_chat_fragment(user_id, request.message)

        # 3. 立即返回成功响应
        client_missing = False
        try:
            from ..agent.agent_manager import agent_manager
            client_missing = (
                request.ai_agent_id not in agent_manager._clients
                or not agent_manager._client_connected.get(request.ai_agent_id, False)
            )
        except Exception:
            client_missing = False

        response = ChatMessageResponse(
            success=True,
            message="Message sent successfully",
            session_id=session_id,
            timestamp=datetime.now(),
            client_missing=client_missing
        )

        # 4. 异步处理AI回复（不阻塞响应）
        # 将消息入队，同一会话的多条消息会自动合并后再请求Claude
        key = _queue_key(request.ai_agent_id, session_id)
        if key not in pending_message_queues:
            pending_message_queues[key] = []
        pending_message_queues[key].append(request.message)

        if not queue_processing_flags.get(key):
            queue_processing_flags[key] = True
            asyncio.create_task(_process_queue(request.ai_agent_id, session_id, key))

        return response

    except HTTPException:
        # HTTPException 直接向上传播（不要转换成 500）
        raise
    except Exception as e:
        logger.error("Error in send_message: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions/{user_id}", response_model=List[ChatSession])
async def get_user_sessions(
    user_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    获取用户的所有聊天会话
    """
    # 确保只能查看自己的会话
    if current_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute('''
            SELECT * FROM chat_sessions
            WHERE user_id = %s
            ORDER BY last_message_at DESC, created_at DESC
        ''', (user_id,))

        sessions = []
        for row in cursor.fetchall():
            sessions.append(ChatSession(**dict(row)))

        return sessions
    finally:
        conn.close()

@router.get("/messages/{session_id}", response_model=List[ChatMessageRecord])
async def get_session_messages(
    session_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    获取指定会话的所有聊天记录
    """
    # 验证会话属于当前用户
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cursor.execute('''
            SELECT user_id FROM chat_sessions
            WHERE id = %s
        ''', (session_id,))

        session = cursor.fetchone()
        if not session or session["user_id"] != current_user_id:
            raise HTTPException(status_code=404, detail="Session not found or access denied")

        # 获取消息
        cursor.execute('''
            SELECT * FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 100
        ''', (session_id,))

        messages = []
        rows = cursor.fetchall()
        for row in reversed(rows):
            messages.append(ChatMessageRecord(**dict(row)))

        return messages
    finally:
        conn.close()

@router.post("/sessions/{session_id}/title")
async def update_session_title(
    session_id: str,
    title: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    更新会话标题
    """
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 验证会话所有权
        cursor.execute('''
            SELECT user_id FROM chat_sessions
            WHERE id = %s
        ''', (session_id,))

        session = cursor.fetchone()
        if not session or session["user_id"] != current_user_id:
            raise HTTPException(status_code=404, detail="Session not found or access denied")

        # 更新标题
        cursor.execute('''
            UPDATE chat_sessions
            SET title = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (title, session_id))

        conn.commit()

        return {"success": True, "message": "Title updated successfully"}
    finally:
        conn.close()

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    删除聊天会话（软删除，标记为非活跃）
    """
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 验证会话所有权
        cursor.execute('''
            SELECT user_id FROM chat_sessions
            WHERE id = %s
        ''', (session_id,))

        session = cursor.fetchone()
        if not session or session["user_id"] != current_user_id:
            raise HTTPException(status_code=404, detail="Session not found or access denied")

        # 软删除会话
        cursor.execute('''
            UPDATE chat_sessions
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (session_id,))

        conn.commit()

        return {"success": True, "message": "Session deleted successfully"}
    finally:
        conn.close()

@router.delete("/sessions/{session_id}/messages")
async def clear_session_messages(
    session_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    清空会话的所有消息（保留会话，仅删除消息）
    """
    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # 验证会话所有权
        cursor.execute('''
            SELECT user_id FROM chat_sessions
            WHERE id = %s
        ''', (session_id,))

        session = cursor.fetchone()
        if not session or session["user_id"] != current_user_id:
            raise HTTPException(status_code=404, detail="Session not found or access denied")

        # 删除该会话的所有消息
        cursor.execute('''
            DELETE FROM chat_messages
            WHERE session_id = %s
        ''', (session_id,))

        # 重置会话的最后消息时间
        cursor.execute('''
            UPDATE chat_sessions
            SET last_message_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (session_id,))

        conn.commit()

        # 清理 Redis 缓存中该用户的所有计数（强制从数据库重新查询）
        # 注意：必须完全删除缓存，而不是只删除单个session，否则increment_sync_count会继续累加错误的值
        try:
            from ..cache.redis_cache import invalidate_sync_cache
            invalidate_sync_cache(current_user_id)
            logger.info("🗑️ 已清除用户的Redis缓存: user_id=%s, session_id=%s", current_user_id[:8], session_id[:8])
        except Exception as e:
            logger.warning("清理Redis缓存失败: %s", str(e))

        return {"success": True, "message": "Messages cleared successfully"}
    finally:
        conn.close()



class SyncCountsRequest(BaseModel):
    """客户端同步请求，携带各会话已知聊天count（基于最大序号）"""
    known_counts: Dict[str, int] = {}
    include_inactive: bool = False
    current_session_id: Optional[str] = None
    limit_per_session: int = 10  # 每会话最多返回的增量消息条数（默认前10条）


class SyncCountsResponse(BaseModel):
    """同步响应：返回各会话当前数量和差异消息"""
    success: bool
    counts: Dict[str, int]
    deltas: Dict[str, List[ChatMessageRecord]]
    workdirs: Dict[str, Dict[str, Any]] = {}


@router.post("/sessions/{user_id}/sync", response_model=SyncCountsResponse)
async def sync_messages(
    user_id: str,
    request: SyncCountsRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    增量同步聊天记录：
    - 统计当前用户所有（可选包含非活跃）会话的消息数量。
    - 若与客户端提供的 `known_counts` 存在差异，则返回相应会话的新增消息（基于 sequence_number）。

    请求体示例：
    {
      "known_counts": {"<session_id>": 10, "<session_id2>": 5},
      "include_inactive": false,
      "limit_per_session": 100
    }
    """
    # 权限校验：仅允许查询当前登录用户自己的会话
    if current_user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    include_inactive = request.include_inactive
    limit_per_session = max(1, min(request.limit_per_session, 100))

    conn = db.get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # 1) 尝试从 Redis 缓存读取 counts 和 agents
        from ..cache.redis_cache import get_sync_counts, set_sync_counts, get_sync_agents, set_sync_agents
        counts: Dict[str, int] = {}
        session_agent_map: Dict[str, str] = {}

        cached_counts = get_sync_counts(user_id)
        cached_agents = get_sync_agents(user_id)

        if cached_counts is not None:
            # Redis 缓存命中
            counts = cached_counts
            session_agent_map = cached_agents or {}
        else:
            # Redis 缓存未命中，查询数据库
            if include_inactive:
                cursor.execute(
                    '''
                    SELECT cs.id AS session_id, cs.ai_agent_id, COALESCE(MAX(cm.sequence_number), 0) AS max_seq
                    FROM chat_sessions cs
                    LEFT JOIN chat_messages cm ON cm.session_id = cs.id
                    WHERE cs.user_id = %s
                    GROUP BY cs.id, cs.ai_agent_id
                    ''',
                    (user_id,)
                )
            else:
                cursor.execute(
                    '''
                    SELECT cs.id AS session_id, cs.ai_agent_id, COALESCE(MAX(cm.sequence_number), 0) AS max_seq
                    FROM chat_sessions cs
                    LEFT JOIN chat_messages cm ON cm.session_id = cs.id
                    WHERE cs.user_id = %s AND cs.is_active = TRUE
                    GROUP BY cs.id, cs.ai_agent_id
                    ''',
                    (user_id,)
                )

            rows = cursor.fetchall()
            counts = {row['session_id']: int(row['max_seq']) for row in rows}
            session_agent_map = {row['session_id']: row['ai_agent_id'] for row in rows}

            # 写入 Redis 缓存（counts 和 agents 都缓存）
            # 空字典会跳过写入（新用户无会话是正常状态）
            if counts:
                set_sync_counts(user_id, counts)
                set_sync_agents(user_id, session_agent_map)
                logger.info("💾 已写入 Redis 缓存: user_id=%s, sessions=%d", user_id, len(counts))

        # 2) 仅对有差异的会话拉取增量（最前N条）；优先当前会话
        deltas: Dict[str, List[ChatMessageRecord]] = {}

        # 先处理当前会话，确保实时消息优先返回
        prioritized_ids = []
        if request.current_session_id and request.current_session_id in counts:
            prioritized_ids.append(request.current_session_id)
        # 其余会话按需处理
        other_ids = [sid for sid in counts.keys() if sid not in prioritized_ids]
        ordered_ids = prioritized_ids + other_ids

        for sid in ordered_ids:
            server_max = counts.get(sid, 0)
            client_known = int(request.known_counts.get(sid, 0))

            if server_max > client_known:
                # 基于联合索引 (session_id, sequence_number) 获取增量，限制条数
                msgs: List[ChatMessageRecord] = []
                if sid == request.current_session_id:
                    cursor.execute(
                        '''SELECT * FROM chat_messages
                           WHERE session_id = %s
                           ORDER BY sequence_number DESC
                           LIMIT %s''',
                        (sid, limit_per_session)
                    )
                    rows = list(reversed(cursor.fetchall()))
                else:
                    cursor.execute(
                        '''SELECT * FROM chat_messages
                           WHERE session_id = %s AND sequence_number > %s
                           ORDER BY sequence_number ASC
                           LIMIT %s''',
                        (sid, client_known, limit_per_session)
                    )
                    rows = cursor.fetchall()
                for row in rows:
                    msgs.append(ChatMessageRecord(**dict(row)))
                if msgs:
                    deltas[sid] = msgs

        # 3) 当前会话的工作目录快照（仅当前会话以降低开销）
        workdirs: Dict[str, Dict[str, Any]] = {}
        if request.current_session_id:
            agent_id = None
            if request.current_session_id in session_agent_map:
                agent_id = session_agent_map[request.current_session_id]
            else:
                # session 不在缓存中，从数据库查询
                logger.info("🔍 [sync] current_session_id 不在缓存中，从数据库查询: %s", request.current_session_id)
                cursor.execute(
                    "SELECT ai_agent_id FROM chat_sessions WHERE id = %s AND user_id = %s",
                    (request.current_session_id, user_id)
                )
                row = cursor.fetchone()
                if row:
                    agent_id = row['ai_agent_id']
                    # 更新缓存
                    session_agent_map[request.current_session_id] = agent_id
                    set_sync_agents(user_id, session_agent_map)
                    logger.info("✅ [sync] 从数据库找到 agent_id=%s", agent_id)
                else:
                    logger.warning("⚠️ [sync] 数据库中也找不到 session: %s", request.current_session_id)

            if agent_id:
                info = _collect_workdir_info(user_id, agent_id)
                workdirs[request.current_session_id] = info
                await _maybe_emit_preview_messages(
                    user_id,
                    request.current_session_id,
                    agent_id,
                    info,
                )

        return SyncCountsResponse(success=True, counts=counts, deltas=deltas, workdirs=workdirs)
    except Exception as e:
        logger.error("Error in sync_messages: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
