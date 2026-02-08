"""
后台任务管理
用简单的 asyncio 任务替代复杂的调度器
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Set
from ..system import config
from ..agent.agent_manager import agent_manager
from ..mcp.do_mcp_task import start_task_scheduler, stop_task_scheduler

logger = logging.getLogger(__name__)

# 存储所有运行中的后台任务
_running_tasks: Set[asyncio.Task] = set()


async def _idle_agent_cleanup_task():
    """
    定期清理超时的空闲agent
    从配置文件读取检查间隔和超时时间
    """
    interval_seconds = config.IDLE_AGENT_CLEANUP_INTERVAL
    timeout_seconds = config.IDLE_TIMEOUT_SECONDS

    logger.info(f"🧹 启动空闲agent清理任务，间隔: {interval_seconds}秒，超时: {timeout_seconds}秒")

    while True:
        try:
            await asyncio.sleep(interval_seconds)

            closed_count = 0
            now = datetime.now()
            timeout_threshold = timedelta(seconds=timeout_seconds)

            # 获取所有已连接的agent
            agent_ids = list(agent_manager._clients.keys())

            for agent_id in agent_ids:
                last_active = agent_manager._agent_last_active.get(agent_id)
                if not last_active:
                    continue

                idle_time = now - last_active
                if idle_time > timeout_threshold:
                    try:
                        logger.info(
                            f"🧹 清理超时空闲agent: {agent_id}, 空闲时间: {int(idle_time.total_seconds())}秒"
                        )
                        await agent_manager.close_agent_client(agent_id)
                        closed_count += 1
                    except Exception as e:
                        logger.error(f"清理agent失败 {agent_id}: {e}")

            if closed_count > 0:
                logger.info(f"✅ 清理完成: 共关闭 {closed_count} 个超时空闲agent")

        except asyncio.CancelledError:
            logger.info("🛑 空闲agent清理任务已停止")
            break
        except Exception as e:
            logger.error(f"❌ 空闲agent清理任务异常: {e}")
            # 异常后等待30秒再继续
            await asyncio.sleep(30)


def start_background_tasks():
    """启动所有后台任务"""
    logger.info("🚀 启动后台任务...")

    # 启动空闲agent清理任务
    task = asyncio.create_task(_idle_agent_cleanup_task())
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)

    # 启动定时任务调度器（常驻）
    start_task_scheduler()

    logger.info(f"✅ 后台任务已启动，共 {len(_running_tasks)} 个任务运行中")


async def stop_background_tasks():
    """停止所有后台任务"""
    logger.info("🛑 正在停止后台任务...")

    for task in list(_running_tasks):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    _running_tasks.clear()
    await stop_task_scheduler()
    logger.info("✅ 所有后台任务已停止")


def get_background_tasks_status() -> dict:
    """获取后台任务状态"""
    interval = config.IDLE_AGENT_CLEANUP_INTERVAL
    timeout = config.IDLE_TIMEOUT_SECONDS

    return {
        "running_count": len(_running_tasks),
        "tasks": [
            {
                "name": "idle_agent_cleanup",
                "description": "清理超时的空闲agent",
                "interval": f"{interval}秒 ({interval//60}分钟)",
                "timeout": f"{timeout}秒 ({timeout//3600}小时)"
            }
        ]
    }
