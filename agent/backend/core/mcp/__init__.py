"""MCP tools package and config helpers."""
import copy
import json
from typing import Dict, List, Any

import psycopg2.extras

from ..system import config
from ..db.dbutil import DatabaseUtil
from .pixabay_custom_mcp import pixabay_mcp
from .polyhaven_custom_mcp import polyhaven_mcp
from .lordicon_custom_mcp import lordicon_mcp
from .drawio_custom_mcp import drawio_mcp
from .kroki_custom_mcp import kroki_mcp
from .email_custom_mcp import email_mcp
from .task_custom_mcp import task_custom_mcp
from .pexels_custom_mcp import pexels_mcp
from .kbs_custom_mcp import kbs_mcp

# 数据库工具
db = DatabaseUtil()


def get_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """Return MCP server configs shared by all agents."""
    return copy.deepcopy(config.GLOBAL_MCP_SERVERS)


def get_mcp_allowed_tools() -> List[str]:
    """Return MCP tool allowlist names."""
    return config.MCP_ALLOWED_TOOLS


def get_user_mcp_servers(user_id: str) -> Dict[str, Dict[str, Any]]:
    """
    获取用户自定义的 MCP 服务器配置

    Args:
        user_id: 用户ID

    Returns:
        用户自定义的 MCP 服务器配置字典
    """
    user_mcps = {}

    try:
        conn = db._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute(
            """
            SELECT name, mcp_type, url, headers, env, command, args
            FROM mcps
            WHERE user_id = %s
            """,
            (user_id,),
        )

        rows = cursor.fetchall()

        for row in rows:
            mcp_config = {
                "type": row["mcp_type"]
            }

            # 添加类型特定的配置
            if row["url"]:
                mcp_config["url"] = row["url"]

            if row["headers"]:
                mcp_config["headers"] = json.loads(row["headers"])

            if row["env"]:
                mcp_config["env"] = json.loads(row["env"])

            if row["command"]:
                mcp_config["command"] = row["command"]

            if row["args"]:
                mcp_config["args"] = json.loads(row["args"])

            user_mcps[row["name"]] = mcp_config

        conn.close()

    except Exception as e:
        print(f"获取用户 MCP 配置失败: {e}")

    return user_mcps


def get_all_mcp_servers(user_id: str = None) -> Dict[str, Dict[str, Any]]:
    """
    获取所有 MCP 服务器配置（包括全局配置、用户自定义配置和 SDK MCP）

    Args:
        user_id: 用户ID（可选），如果提供则包含用户自定义配置

    Returns:
        所有 MCP 服务器配置字典
    """
    # 获取全局配置
    all_mcps = get_mcp_servers()

    # 如果提供了用户ID，合并用户自定义配置
    if user_id:
        user_mcps = get_user_mcp_servers(user_id)
        all_mcps.update(user_mcps)

    # 添加 SDK MCP 服务器（进程内，无需独立进程）
    all_mcps["pixabay-media"] = pixabay_mcp
    all_mcps["pexels-media"] = pexels_mcp
    all_mcps["polyhaven-3d"] = polyhaven_mcp
    all_mcps["lordicon"] = lordicon_mcp
    all_mcps["drawio-export"] = drawio_mcp
    all_mcps["kroki-render"] = kroki_mcp
    all_mcps["send"] = email_mcp
    all_mcps["task-custom"] = task_custom_mcp
    if config.KB_ENABLED:
        all_mcps["kbs-memory"] = kbs_mcp

    return all_mcps


__all__ = [
    "pixabay_mcp",
    "polyhaven_mcp",
    "pexels_mcp",
    "lordicon_mcp",
    "drawio_mcp",
    "kroki_mcp",
    "email_mcp",
    "task_custom_mcp",
    "get_mcp_servers",
    "get_mcp_allowed_tools",
    "get_user_mcp_servers",
    "get_all_mcp_servers",
]
