from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
import random
import string
from typing import Optional
from pathlib import Path
import sys
import uuid
from ..db.dbutil import DatabaseUtil
from ..auth.auth_utils import generate_token, verify_token
from ..agent.agent_manager import (
    initialize_agent_client,
    initialize_user_agents,
    logout_user_agents,
    get_user_work_base_dir,
    get_agent_work_dir,
    get_default_system_prompt,
)
from ..firewall.firewall_bash import ensure_user_firewall, ensure_user_settings
from ..auth.auth_filter import get_current_user_id
from ..system import config
from . import relationship_api
from ..auth.sms_api import send_verification_code, verify_login_code
from ..membership.sub_api import create_free_trial_subscription, get_user_membership_info

router = APIRouter()

# 初始化数据库
db = DatabaseUtil()

class UserLogin(BaseModel):
    phone: str
    code: str

class UserRegister(BaseModel):
    username: str
    password: str
    email: Optional[str] = None  # 改为普通的可选字符串
    full_name: Optional[str] = None

class SendCodeRequest(BaseModel):
    phone: str

def _random_username(length: int = 4) -> str:
    """生成随机用户名"""
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(length))

class UserResponse(BaseModel):
    id: str  # UUID
    username: str
    email: Optional[str]
    full_name: Optional[str]
    created_at: str

class CreateAiAssistantRequest(BaseModel):
    username: str
    system_prompt: Optional[str] = None

class DefaultPromptRequest(BaseModel):
    username: Optional[str] = None

@router.post("/auth/login")
async def login(user: UserLogin, request: Request):
    """用户登录接口"""
    try:
        # 验证验证码
        verify_result = verify_login_code(user.phone, user.code)
        if not verify_result['success']:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=verify_result['message']
            )

        user_data = db.get_user_by_phone(user.phone)
        if not user_data:
            username = _random_username()
            while db.get_user_by_username(username):
                username = _random_username()

            # 获取客户端和服务器IP地址
            client_ip = request.client.host if request.client else None
            import socket
            try:
                server_ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                server_ip = "127.0.0.1"

            user_id = db.create_user(
                username=username,
                password=user.code,
                email=None,
                full_name=None,
                user_type='human',
                owner_id=None,
                client_ip=client_ip,
                server_ip=server_ip,
                phone=user.phone
            )
            user_data = db.get_user_by_id(user_id)

            # 首次登录，创建7天免费会员
            try:
                create_free_trial_subscription(user_id, user.phone)
                print(f"✅ 为新用户 {username} 创建7天免费会员")
            except Exception as e:
                print(f"创建免费会员失败: {str(e)}", file=sys.stderr)

        # 生成token
        token = generate_token(user_data['id'], user_data['username'])

        # 初始化用户设置（端口范围等）
        try:
            ensure_user_settings(user_data['id'])
        except Exception as e:
            print(f"初始化用户设置失败: {str(e)}", file=sys.stderr)

        # 初始化用户的AI智能体（如果还没有初始化）
        await initialize_user_agents(user_data['id'])

        # 检查用户是否已有AI智能体，如果没有则自动创建
        try:
            existing_agents = db.get_ai_agents_by_owner(user_data['id'])

            if len(existing_agents) == 0:
                await ensure_user_firewall(user_data['id'])
                # 用户没有AI智能体，需要创建三个默认智能体
                from ..system import config

                # 获取客户端和服务器IP地址
                client_ip = request.client.host if request.client else None
                import socket
                try:
                    server_ip = socket.gethostbyname(socket.gethostname())
                except:
                    server_ip = "127.0.0.1"

                # 创建基础工作目录
                base_work_dir = get_user_work_base_dir(user_data['id'])
                base_work_dir.mkdir(parents=True, exist_ok=True)

                created_agents = []
                for i, agent_config in enumerate(config.DEFAULT_AI_AGENTS):
                    # 生成智能体用户名和名称
                    agent_number = i + 1
                    agent_username = f"{user_data['username']}AI{agent_number}"
                    agent_full_name = f"{user_data.get('full_name', user_data['username'])}的{agent_config['description']}"

                    # 创建AI智能体记录，使用与用户相同的密码
                    agent_id = db.create_user(
                        username=agent_username,
                        password=user_data['password'],  # 使用用户的密码
                        email=None,
                        full_name=agent_full_name,
                        user_type='ai',
                        owner_id=user_data['id'],
                        client_ip=client_ip,
                        server_ip=server_ip
                    )

                    # 创建智能体专用工作目录
                    agent_work_dir = Path(get_agent_work_dir(user_data['id'], agent_id))
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
                        "description": agent_config['description'],
                        "agent_number": agent_number
                    })

                print(f"为用户 {user_data['username']} 自动创建了 {len(created_agents)} 个AI智能体")

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
                            cursor.execute(friendship_query, (friendship_id, user_data['id'], agent['id']))
                            conn.commit()
                            conn.close()  # 自动归还到连接池
                            print(f"✅ 用户与AI智能体 {agent['username']} 已建立好友关系")

                    except Exception as e:
                        print(f"建立好友关系失败: {str(e)}", file=sys.stderr)

        except Exception as e:
            # 智能体初始化失败不应该影响登录，只记录错误
            print(f"自动初始化AI智能体失败: {str(e)}", file=sys.stderr)

        # 登录成功
        return {
            "status": "success",
            "message": "登录成功",
            "token": token,
            "user": {
                "id": user_data['id'],
                "username": user_data['username'],
                "email": user_data['email'],
                "full_name": user_data['full_name']
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"登录错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )

@router.post("/auth/logout")
async def logout(request: Request):
    """用户登出接口"""
    try:
        # 从请求头获取token
        token = request.headers.get("Authorization", "").replace("Bearer ", "")

        if token:
            # 验证token并获取用户信息
            user_info = verify_token(token)
            if user_info:
                # 关闭该用户的所有AI智能体
                await logout_user_agents(user_info['user_id'])
                print(f"✅ 用户 {user_info['username']} 登出，智能体已关闭")

        return {"success": True, "message": "登出成功"}

    except Exception as e:
        print(f"登出错误: {str(e)}", file=sys.stderr)
        return {"success": True, "message": "登出成功"}  # 即使出错也返回成功

@router.post("/auth/send_code")
async def send_code(payload: SendCodeRequest, request: Request):
    """发送验证码"""
    phone = (payload.phone or "").strip()
    if not phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号不能为空")

    # 获取客户端信息
    fingerprint = request.headers.get("x-client-fingerprint", "") or ""
    user_agent = request.headers.get("user-agent", "") or "unknown"
    client_ip = request.client.host if request.client else "unknown"

    # 调用短信模块发送验证码
    result = await send_verification_code(
        phone=phone,
        client_ip=client_ip,
        user_agent=user_agent,
        fingerprint=fingerprint
    )

    if not result['success']:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS if "频繁" in result['message'] else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result['message']
        )

    return {
        "status": "success",
        "message": result['message'],
        "expires_at": result.get('expires_at')
    }

@router.post("/auth/register")
async def register(user: UserRegister, request: Request):
    """用户注册接口"""
    try:
        # 检查用户名是否已存在
        if db.get_user_by_username(user.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 如果提供了邮箱，检查邮箱是否已存在
        if user.email and db.get_user_by_email(user.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被注册"
            )

        # 获取客户端IP地址
        client_ip = request.client.host if request.client else None

        # 获取服务器IP地址
        import socket
        try:
            # 获取本机IP地址
            server_ip = socket.gethostbyname(socket.gethostname())
        except:
            server_ip = "127.0.0.1"

        # 创建用户
        user_id = db.create_user(
            username=user.username,
            password=user.password,
            email=user.email,
            full_name=user.full_name,
            client_ip=client_ip,
            server_ip=server_ip
        )

        return {
            "status": "success",
            "message": "注册成功",
            "user_id": user_id
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"注册错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )

@router.post("/ai_agents")
async def create_ai_assistant(
    payload: CreateAiAssistantRequest,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
):
    """新建AI智能体"""
    try:
        username = (payload.username or "").strip()
        if not username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI名字不能为空"
            )

        # 检查用户名是否重复
        if db.get_user_by_username(username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI名字已存在，请更换"
            )

        # 检查会员状态和AI数量限制
        membership_info = get_user_membership_info(current_user_id)
        is_member = membership_info is not None

        # 获取用户已有的AI助手数量
        query = """
            SELECT COUNT(*) as count FROM users
            WHERE owner_id = %s AND user_type = 'ai'
        """
        result = db.execute_query(query, (current_user_id,), "one")
        ai_count = result['count'] if result else 0

        max_ai_count = config.MAX_AI_ASSISTANTS_MEMBER if is_member else config.MAX_AI_ASSISTANTS_NON_MEMBER

        if ai_count >= max_ai_count:
            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"非会员无法创建AI助手，请订阅会员后使用（会员最多可创建{config.MAX_AI_ASSISTANTS_MEMBER}个AI助手）"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"您已达到AI助手创建上限（{max_ai_count}个）"
                )

        # 获取当前用户信息
        owner = db.get_user_by_id(current_user_id)
        if not owner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        client_ip = request.client.host if request.client else None
        import socket
        try:
            server_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            server_ip = "127.0.0.1"

        agent_id = db.create_user(
            username=username,
            password=owner['password'],
            email=None,
            full_name=username,
            user_type='ai',
            owner_id=current_user_id,
            client_ip=client_ip,
            server_ip=server_ip
        )

        # 处理工作目录（自动生成）
        work_dir = get_agent_work_dir(current_user_id, agent_id)
        Path(work_dir).mkdir(parents=True, exist_ok=True)

        system_prompt = (payload.system_prompt or "").strip()
        if not system_prompt:
            system_prompt = get_default_system_prompt(username, work_dir)
        if system_prompt:
            system_prompt = system_prompt.replace("{{AGENT_NAME}}", username)
            system_prompt = system_prompt.replace("{{WORK_DIR}}", work_dir)
            system_prompt = system_prompt.replace("系统默认工作目录", work_dir)
        if system_prompt:
            db.upsert_agent_settings(
                agent_id,
                system_prompt=system_prompt if system_prompt else None,
                work_dir=work_dir,
            )

        # 初始化智能体客户端
        await initialize_agent_client(
            agent_id=agent_id,
            agent_name=username,
            work_dir=work_dir
        )

        return {
            "status": "success",
            "message": "AI助手创建成功",
            "agent": {
                "id": agent_id,
                "username": username,
                "work_dir": work_dir,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"创建AI智能体失败: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建AI智能体失败"
        )

@router.post("/ai_agents/default_prompt")
async def get_ai_default_prompt(
    payload: DefaultPromptRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    """获取默认system_prompt"""
    name = (payload.username or "").strip() or "AI助手"
    system_prompt = get_default_system_prompt(name, "系统默认工作目录")
    return {"status": "success", "system_prompt": system_prompt}

@router.get("/auth/verify")
async def verify_user_token(request: Request):
    """验证用户token"""
    try:
        # 从请求头获取token
        authorization = request.headers.get("authorization")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少认证token"
            )

        token = authorization.split(" ")[1]
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期"
            )

        return {
            "status": "success",
            "message": "token有效",
            "user_id": token_data.get('user_id'),
            "username": token_data.get('username')
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Token验证错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token验证失败"
        )

@router.get("/friends")
async def get_friends(request: Request):
    """获取用户的好友和群组列表"""
    try:
        # 从请求头获取token
        authorization = request.headers.get("authorization")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少认证token"
            )

        token = authorization.split(" ")[1]
        token_data = verify_token(token)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的token或token已过期"
            )

        user_id = token_data.get('user_id')

        # 获取好友列表
        friends = relationship_api.get_users_by_relationship(user_id, 'parent')  # 父级（好友）

        # 获取AI智能体列表
        agents = db.get_ai_agents_by_owner(user_id)

        # 构建返回数据
        contacts = []

        # 添加人类好友
        for friend in friends:
            contacts.append({
                "id": friend['id'],
                "name": friend['username'],
                "type": "friend",  # human类型都标记为friend
                "avatar": friend.get('avatar_url', ''),
                "status": "online",  # 好友状态
                "description": f"人类用户 - {friend.get('full_name', friend['username'])}",
                "user_type": friend.get('user_type', 'human'),
                "created_at": friend.get('created_at', '').isoformat() if friend.get('created_at') else '',
                "updated_at": friend.get('updated_at', '').isoformat() if friend.get('updated_at') else ''
            })

        # 添加AI智能体
        for agent in agents:
            contacts.append({
                "id": agent['id'],
                "name": agent['username'],
                "type": "agent",
                "avatar": agent.get('avatar_url', ''),
                "description": f"AI智能体 - {agent.get('full_name', agent['username'])}",
                "user_type": agent.get('user_type', 'ai'),
                "created_at": agent.get('created_at', '').isoformat() if agent.get('created_at') else '',
                "updated_at": agent.get('updated_at', '').isoformat() if agent.get('updated_at') else ''
            })

        
        return {
            "status": "success",
            "contacts": contacts
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"获取好友列表错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )

@router.get("/auth/users")
async def get_users():
    """获取所有用户列表（管理员功能）"""
    try:
        users = db.get_all_users()
        return {
            "status": "success",
            "users": users
        }
    except Exception as e:
        print(f"获取用户列表错误: {str(e)}", file=sys.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务器内部错误"
        )
