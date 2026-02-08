"""
MCP 配置管理 API
"""

import uuid
import json
import psycopg2.extras
import sys
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.auth_filter import get_current_user_id
from ..db.dbutil import DatabaseUtil
from ..system import config

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])
db = DatabaseUtil()


class MCPResponse(BaseModel):
    """MCP 响应模型"""
    id: str
    name: str
    url: str
    mcp_type: str
    created_at: str


class MCPServersResponse(BaseModel):
    """MCP 服务器列表响应模型"""
    mcps: List[MCPResponse]


class InstallMCPRequest(BaseModel):
    """安装 MCP 请求模型"""
    url: str
    name: str


@router.get("/installed", response_model=MCPServersResponse)
async def get_installed_mcps(user_id: str = Depends(get_current_user_id)):
    """
    获取用户已安装的 MCP 列表

    Args:
        user_id: 当前用户ID

    Returns:
        用户已安装的 MCP 列表
    """
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute('''
            SELECT id, name, url, mcp_type, created_at
            FROM mcps
            WHERE user_id = %s
            ORDER BY created_at DESC
        ''', (user_id,))

        rows = cursor.fetchall()

        mcps = []
        for row in rows:
            mcps.append({
                "id": row["id"],
                "name": row["name"],
                "url": row["url"],
                "mcp_type": row["mcp_type"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            })

        return {"mcps": mcps}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取 MCP 列表失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()  # 确保连接被归还到连接池



@router.post("/install")
async def install_mcp(
    request: InstallMCPRequest,
    user_id: str = Depends(get_current_user_id)
):
    """
    安装新的 MCP 服务器

    Args:
        request: 包含 url 和 name 的请求体
        user_id: 当前用户ID

    Returns:
        安装结果
    """
    # 验证 URL 格式
    if not request.url or "mcpmarket.cn/mcp/" not in request.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请输入有效的 MCP URL"
        )

    # 验证名称
    if not request.name or not request.name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请输入 MCP 名称"
        )

    name = request.name.strip()

    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 检查是否已存在同名 MCP
        cursor.execute('''
            SELECT id FROM mcps
            WHERE user_id = %s AND name = %s
        ''', (user_id, name))

        existing = cursor.fetchone()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"已存在名为 '{name}' 的 MCP 配置"
            )

        # 生成新的 MCP ID
        mcp_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        # 插入数据库（HTTP 类型，只存储 URL）
        cursor.execute('''
            INSERT INTO mcps (id, user_id, name, mcp_type, url, created_at, updated_at)
            VALUES (%s, %s, %s, 'http', %s, %s, %s)
        ''', (mcp_id, user_id, name, request.url, created_at, created_at))

        conn.commit()

        # 重启用户的所有智能体以应用新的 MCP 配置
        from ..agent.agent_manager import agent_manager
        try:
            await agent_manager.logout_user_agents(user_id)
            await agent_manager.initialize_user_agents(user_id)
        except Exception as e:
            print(f"重启智能体失败: {e}", file=sys.stderr)

        return {
            "success": True,
            "message": "MCP 安装成功，已重启智能体",
            "mcp_id": mcp_id
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"安装 MCP 失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()  # 确保连接被归还到连接池



@router.delete("/{mcp_id}")
async def remove_mcp(
    mcp_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    删除已安装的 MCP 服务器

    Args:
        mcp_id: MCP ID
        user_id: 当前用户ID

    Returns:
        删除结果
    """
    conn = None
    mcp_name = None

    try:
        conn = db.get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 检查 MCP 是否存在且属于当前用户
        cursor.execute('''
            SELECT name FROM mcps
            WHERE id = %s AND user_id = %s
        ''', (mcp_id, user_id))

        mcp = cursor.fetchone()
        if not mcp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MCP 不存在或无权删除"
            )

        mcp_name = mcp['name']

        # 删除 MCP
        cursor.execute('''
            DELETE FROM mcps
            WHERE id = %s AND user_id = %s
        ''', (mcp_id, user_id))

        conn.commit()

        # 重启用户的所有智能体以应用新的 MCP 配置
        from ..agent.agent_manager import agent_manager
        try:
            await agent_manager.logout_user_agents(user_id)
            await agent_manager.initialize_user_agents(user_id)
        except Exception as e:
            print(f"重启智能体失败: {e}", file=sys.stderr)

        return {
            "success": True,
            "message": f"MCP '{mcp_name}' 已删除，已重启智能体"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除 MCP 失败: {str(e)}"
        )
    finally:
        if conn:
            conn.close()  # 确保连接被归还到连接池
