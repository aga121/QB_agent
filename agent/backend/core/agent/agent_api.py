from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import os
import uuid
from pathlib import Path
from ..db.dbutil import DatabaseUtil
from ..auth.auth_utils import verify_token
from ..auth.auth_filter import get_current_user_id, get_current_user_data
from .agent_manager import initialize_agent_client, get_agent_client, get_agent_work_dir, get_user_work_base_dir, get_default_system_prompt
from ..system import config

router = APIRouter()

# 初始化数据库
db = DatabaseUtil()

# 全局字典存储智能体客户端
# 格式: {agent_id: ClaudeSDKClient}
agent_clients: Dict[str, Any] = {}

class AgentInitRequest(BaseModel):
    """智能体初始化请求模型"""
    user_id: str

class AgentResponse(BaseModel):
    """智能体响应模型"""
    id: str
    username: str
    full_name: Optional[str]
    description: str
    agent_type: str

@router.post("/agent_init")
async def agent_init(req: AgentInitRequest, request: Request, current_user_id: str = Depends(get_current_user_id)):
    """
    智能体初始化接口（现在主要用于手动初始化）

    功能：
    1. 检查用户是否已有AI智能体
    2. 如果没有，默认创建三个AI智能体
    3. 初始化每个智能体的工作目录和ClaudeSDKClient

    注意：现在登录接口会自动初始化，此接口主要用于手动重新初始化
    """
    try:
        # 验证用户ID与认证用户ID是否匹配
        if current_user_id != req.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户身份验证失败"
            )

        # 获取用户信息
        user_data = db.get_user_by_id(req.user_id)
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 检查用户是否已有AI智能体
        existing_agents = db.get_ai_agents_by_owner(req.user_id)

        if len(existing_agents) == 0:
            # 用户没有AI智能体，需要创建三个默认智能体
            created_agents = []

            # 获取客户端和服务器IP地址
            client_ip = request.client.host if request.client else None
            import socket
            try:
                server_ip = socket.gethostbyname(socket.gethostname())
            except:
                server_ip = "127.0.0.1"

            # 创建基础工作目录
            base_work_dir = get_user_work_base_dir(req.user_id)
            base_work_dir.mkdir(parents=True, exist_ok=True)

            for i, agent_config in enumerate(config.DEFAULT_AI_AGENTS):
                # 生成智能体用户名和名称
                suffix = f"AI-{i + 1}"
                agent_username = f"{user_data['username']}({suffix})"
                agent_full_name = f"{user_data.get('full_name', user_data['username'])}的{agent_config['description']}"

                # 创建AI智能体记录，使用与用户相同的密码
                agent_id = db.create_user(
                    username=agent_username,
                    password=user_data['password'],  # 使用用户的密码
                    email=None,
                    full_name=agent_full_name,
                    user_type='ai',
                    owner_id=req.user_id,
                    client_ip=client_ip,
                    server_ip=server_ip
                )

                # 创建智能体专用工作目录
                agent_work_dir = Path(get_agent_work_dir(req.user_id, agent_id))
                agent_work_dir.mkdir(parents=True, exist_ok=True)

                # 创建技能包目录（.claude/skills）
                skills_dir = agent_work_dir / config.SKILL_PACKAGE_DIR
                skills_dir.mkdir(parents=True, exist_ok=True)
                print(f"✅ 为智能体 {agent_username} 创建技能包目录: {skills_dir}")

                default_prompt = get_default_system_prompt(agent_username, str(agent_work_dir))
                db.upsert_agent_settings(agent_id, system_prompt=default_prompt, work_dir=str(agent_work_dir))

                # 初始化ClaudeSDKClient
                success = await initialize_agent_client(
                    agent_id=agent_id,
                    agent_name=agent_username,
                    work_dir=str(agent_work_dir)
                )

                if not success:
                    print(f"警告: 智能体 {agent_username} 客户端初始化失败", file=sys.stderr)
                else:
                    print(f"✅ 智能体 {agent_username} 客户端初始化成功")

                created_agents.append({
                    "id": agent_id,
                    "username": agent_username,
                    "full_name": agent_full_name,
                    "description": agent_config['description'],
                    "agent_type": suffix
                })

            # 建立与AI智能体的好友关系
            if created_agents:
                try:
                    for agent in created_agents:
                        # 直接创建已接受的好友关系
                        friendship_id = str(uuid.uuid4())
                        friendship_query = '''
                            INSERT INTO friendships (id, user_id, friend_id, status)
                            VALUES (%s, %s, %s, 'accepted')
                        '''
                        conn = db.get_connection()  # 使用包装器连接
                        cursor = conn.cursor()
                        cursor.execute(friendship_query, (friendship_id, req.user_id, agent['id']))
                        conn.commit()
                        conn.close()  # 自动归还到连接池

                except Exception as e:
                    print(f"建立好友关系失败: {str(e)}", file=sys.stderr)

            return {
                "status": "success",
                "message": "智能体初始化成功",
                "created": True,
                "agents": created_agents,
                "total_agents": len(created_agents)
            }
        else:
            # 用户已有AI智能体，返回现有智能体列表
            existing_agents_data = []
            for agent in existing_agents:
                agent_type = "AI-1"
                if "AI-2" in agent['username']:
                    agent_type = "AI-2"
                elif "AI-3" in agent['username']:
                    agent_type = "AI-3"

                existing_agents_data.append({
                    "id": agent['id'],
                    "username": agent['username'],
                    "full_name": agent['full_name'],
                    "description": _get_agent_description_by_full_name(agent.get('full_name')),
                    "agent_type": agent_type
                })

            return {
                "status": "success",
                "message": "智能体已存在",
                "created": False,
                "agents": existing_agents_data,
                "total_agents": len(existing_agents_data)
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"智能体初始化错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="智能体初始化失败"
        )

@router.get("/agent_list")
async def get_agent_list(user_id: str, current_user_id: str = Depends(get_current_user_id)):
    """
    获取用户的AI智能体列表

    Args:
        user_id: 用户ID
        current_user_id: 通过认证过滤器获取的当前用户ID

    Returns:
        用户的所有AI智能体列表
    """
    try:
        # 验证用户ID与认证用户ID是否匹配
        if current_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户身份验证失败"
            )

        # 获取用户的AI智能体
        agents = db.get_ai_agents_by_owner(user_id)

        if len(agents) == 0:
            return {
                "status": "success",
                "message": "用户暂无AI智能体，请先调用初始化接口",
                "agents": [],
                "total_agents": 0
            }

        # 格式化智能体数据
        agents_data = []
        for agent in agents:
            agent_type = "AI-1"
            if "AI-2" in agent['username']:
                agent_type = "AI-2"
            elif "AI-3" in agent['username']:
                agent_type = "AI-3"

            agents_data.append({
                "id": agent['id'],
                "username": agent['username'],
                "full_name": agent['full_name'],
                "description": _get_agent_description_by_full_name(agent.get('full_name')),
                "agent_type": agent_type,
                "created_at": agent['created_at'].isoformat() if agent.get('created_at') else None
            })

        return {
            "status": "success",
            "message": "获取智能体列表成功",
            "agents": agents_data,
            "total_agents": len(agents_data)
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"获取智能体列表错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取智能体列表失败"
        )

def _get_agent_description_by_full_name(full_name: Optional[str]) -> str:
    """从用户表 full_name 中提取智能体描述"""
    if not full_name:
        return "通用AI智能体"
    marker = "的"
    if marker in full_name:
        return full_name.split(marker, 1)[1] or "通用AI智能体"
    return full_name

# get_agent_work_dir 函数已在 agent_manager 中定义，这里直接导入使用

async def get_and_verify_agent_client(agent_id: str) -> Optional[Any]:
    """
    获取并验证智能体客户端的公共方法

    Args:
        agent_id: 智能体ID

    Returns:
        ClaudeSDKClient对象，如果不存在或无效返回None
    """
    try:
        client = await get_agent_client(agent_id)
        if not client:
            print(f"智能体客户端不存在: {agent_id}", file=sys.stderr)
            return None

        # 这里可以添加更多验证逻辑
        # 比如检查客户端是否仍然连接正常等

        return client
    except Exception as e:
        print(f"获取智能体客户端失败 {agent_id}: {str(e)}", file=sys.stderr)
        return None
