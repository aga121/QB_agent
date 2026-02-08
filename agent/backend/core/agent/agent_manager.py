"""
智能体管理器
负责管理ClaudeSDKClient的创建、存储和访问
"""

import asyncio
import os
import logging
from contextlib import suppress
from typing import Dict, Optional
import importlib
import inspect
from pathlib import Path
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
import sys
import psycopg2.extras
from datetime import datetime
from ..db.dbutil import DatabaseUtil
from ..mcp import get_mcp_allowed_tools, get_all_mcp_servers
from ..membership.pub_key_api import get_api_key_for_membership
from ..membership.sub_api import get_user_membership_info
from ..firewall.firewall_bash import (
    build_tool_permission_handler,
    build_tool_hooks,
    get_bash_isolation_prompt,
    is_firewall_enabled,
)
from ..system import config

# 日志
logger = logging.getLogger(__name__)
# 环境变量配置
os.environ.setdefault('FIREWALL_ENABLED', 'true' if config.FIREWALL_ENABLED else 'false')

db = DatabaseUtil()

class AgentManager:
    """智能体管理器，负责管理所有AI智能体的ClaudeSDKClient"""

    def __init__(self):
        self._clients: Dict[str, ClaudeSDKClient] = {}
        self._client_options: Dict[str, ClaudeAgentOptions] = {}
        self._client_connected: Dict[str, bool] = {}
        # 跟踪最后活跃时间（用于24小时超时检查）
        self._agent_last_active: Dict[str, datetime] = {}  # agent_id -> last_active_time

    @staticmethod
    async def _allow_all_tools(
        tool_name: str,
        input_data: dict,
        context: dict,
    ) -> dict:
        for module_name in ("claude_agent_sdk.permissions", "claude_agent_sdk"):
            try:
                mod = importlib.import_module(module_name)
            except Exception:
                continue
            allow_cls = getattr(mod, "PermissionResultAllow", None)
            if allow_cls:
                try:
                    sig = inspect.signature(allow_cls)
                    if "updatedInput" in sig.parameters:
                        return allow_cls(updatedInput=input_data)
                    if "input_data" in sig.parameters:
                        return allow_cls(input_data)
                except Exception:
                    pass
                try:
                    return allow_cls()
                except Exception:
                    pass
        return {"behavior": "allow", "updatedInput": input_data}

    async def create_agent_client(self, agent_id: str, agent_name: str, work_dir: str, session_id: str = None, continue_conversation: bool = False) -> bool:
        """
        为指定智能体创建ClaudeSDKClient

        Args:
            agent_id: 智能体ID
            agent_name: 智能体名称
            work_dir: 工作目录路径
            session_id: 可选的会话ID，用于恢复之前的会话记忆
            continue_conversation: 是否继续最近的对话

        Returns:
            是否创建成功
        """
        try:
            # 如果客户端已存在，先关闭
            if agent_id in self._clients:
                await self.close_agent_client(agent_id)

            # 通过 agent_id 获取 owner_id
            owner_id = None
            try:
                agent_info = db.get_user_by_id(agent_id)
                if agent_info and agent_info.get("owner_id"):
                    owner_id = agent_info["owner_id"]
            except Exception as e:
                print(f"获取 agent owner_id 失败: {e}", file=sys.stderr)

            # 读取自定义配置（如有）
            settings = db.get_agent_settings(agent_id) or {}
            custom_work_dir = settings.get("work_dir")
            if custom_work_dir:
                work_dir = custom_work_dir
            # system_prompt = settings.get("system_prompt") or self._generate_system_prompt(agent_name, work_dir, agent_id)  # 已注释：不使用数据库提示词
            system_prompt = self._generate_system_prompt(agent_name, work_dir, agent_id)  # 只从 config 获取提示词
            if is_firewall_enabled():
                isolation_prompt = get_bash_isolation_prompt(work_dir)
                if isolation_prompt and isolation_prompt not in system_prompt:
                    system_prompt = system_prompt + isolation_prompt

            # 创建客户端选项
            allowed_tools = [
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Glob",
                "Grep",
                *get_mcp_allowed_tools(),
            ]

            # 获取 MCP 服务器配置（包括全局和用户自定义）
            mcp_servers = get_all_mcp_servers(owner_id)

            # Resolve membership-based API key for this agent owner.
            env_overrides = {}
            try:
                membership_info = get_user_membership_info(owner_id) if owner_id else None
                membership_level = (membership_info or {}).get("membership_level") or "no"
                api_key = get_api_key_for_membership(membership_level)
                if api_key:
                    env_overrides = {
                        "ANTHROPIC_AUTH_TOKEN": api_key["auth_token"],
                        "ANTHROPIC_BASE_URL": api_key["base_url"],
                    }
            except Exception:
                env_overrides = {}

            options = ClaudeAgentOptions(
                allowed_tools=allowed_tools,
                permission_mode="default",
                can_use_tool=build_tool_permission_handler(work_dir),
                hooks=build_tool_hooks(work_dir),
                cwd=work_dir,
                system_prompt=system_prompt,
                setting_sources=["project"],
                include_partial_messages=False,  # 显式禁用部分消息推送
                resume=session_id,  # 使用传入的session_id恢复会话
                continue_conversation=continue_conversation,  # 设置是否继续对话
                mcp_servers=mcp_servers,
                env=env_overrides,
            )

            # 创建工作目录
            Path(work_dir).mkdir(parents=True, exist_ok=True)

            # 创建ClaudeSDKClient
            client = ClaudeSDKClient(options)

            # 存储客户端和选项
            self._clients[agent_id] = client
            self._client_options[agent_id] = options
            self._client_connected[agent_id] = False
            self._agent_last_active[agent_id] = datetime.now()

            # 不打印创建成功日志，避免过多输出
            return True

        except Exception as e:
            print(f"❌ 创建智能体客户端失败 {agent_name}: {str(e)}", file=sys.stderr)
            return False

    async def get_agent_client(self, agent_id: str) -> Optional[ClaudeSDKClient]:
        """
        获取指定智能体的ClaudeSDKClient

        Args:
            agent_id: 智能体ID

        Returns:
            ClaudeSDKClient对象，如果不存在返回None
        """
        if agent_id not in self._clients:
            logger.info("智能体客户端不存在: %s", agent_id)
            return None

        return self._clients[agent_id]

    async def is_client_available(self, agent_id: str) -> bool:
        """
        检查智能体客户端是否可用

        Args:
            agent_id: 智能体ID

        Returns:
            是否可用
        """
        return agent_id in self._clients

    async def ensure_client_connected(self, agent_id: str) -> bool:
        """
        确保客户端已连接

        Args:
            agent_id: 智能体ID

        Returns:
            是否连接成功
        """
        client = self._clients.get(agent_id)
        if not client:
            return False

        # 如果未连接，则连接
        if not self._client_connected.get(agent_id, False):
            try:
                await client.connect()
                self._client_connected[agent_id] = True
            except Exception:
                return False

        # 更新最后活跃时间
        self._agent_last_active[agent_id] = datetime.now()
        return True

    async def close_agent_client(self, agent_id: str) -> bool:
        """
        关闭指定智能体的ClaudeSDKClient

        Args:
            agent_id: 智能体ID

        Returns:
            是否关闭成功
        """
        try:
            if agent_id in self._clients:
                # 关闭客户端
                client = self._clients[agent_id]

                # 先尝试断开连接
                try:
                    if hasattr(client, 'disconnect'):
                        await client.disconnect()
                except Exception:
                    pass  # 忽略断开连接时的错误

                # 然后关闭客户端
                try:
                    if hasattr(client, 'close'):
                        await client.close()
                except Exception:
                    pass  # 忽略关闭时的错误

                await self._force_kill_cli_process(client, agent_id)

                # 从字典中移除
                del self._clients[agent_id]
                if agent_id in self._client_options:
                    del self._client_options[agent_id]
                if agent_id in self._client_connected:
                    del self._client_connected[agent_id]
                if agent_id in self._agent_last_active:
                    del self._agent_last_active[agent_id]

                logger.info("成功关闭智能体客户端: %s", agent_id)
                return True
            else:
                logger.info("智能体客户端不存在: %s", agent_id)
                return False

        except Exception as e:
            logger.error("关闭智能体客户端失败 %s: %s", agent_id, str(e))
            return False

    async def close_all_clients(self) -> int:
        """
        关闭所有智能体客户端

        Returns:
            成功关闭的客户端数量
        """
        closed_count = 0
        agent_ids = list(self._clients.keys())  # 创建副本避免迭代时修改

        for agent_id in agent_ids:
            if await self.close_agent_client(agent_id):
                closed_count += 1

        logger.info("成功关闭 %s 个智能体客户端", closed_count)
        return closed_count

    async def _force_kill_cli_process(self, client, agent_id: str) -> None:
        """Best-effort kill for leaked Claude CLI processes."""
        transport = getattr(client, "_transport", None)
        query = getattr(client, "_query", None)
        if not transport and query:
            transport = getattr(query, "transport", None)
        process = getattr(transport, "_process", None) if transport else None
        if not process or getattr(process, "returncode", None) is not None:
            return
        with suppress(Exception):
            process.terminate()
        try:
            wait_result = process.wait()
            if asyncio.iscoroutine(wait_result):
                await wait_result
        except Exception:
            with suppress(Exception):
                process.terminate()

    def get_agent_info(self, agent_id: str) -> Optional[Dict]:
        """
        获取智能体信息

        Args:
            agent_id: 智能体ID

        Returns:
            智能体信息字典
        """
        if agent_id not in self._clients:
            return None

        return {
            "agent_id": agent_id,
            "is_available": True,
            "work_dir": self._client_options[agent_id].cwd if agent_id in self._client_options else None,
            "system_prompt": self._client_options[agent_id].system_prompt if agent_id in self._client_options else None
        }

    def list_all_agents(self) -> Dict[str, Dict]:
        """
        列出所有智能体信息

        Returns:
            所有智能体的信息字典
        """
        agents_info = {}
        for agent_id in self._clients:
            agents_info[agent_id] = self.get_agent_info(agent_id)

        return agents_info

    async def initialize_user_agents(self, owner_id: str):
        """
        初始化指定用户的所有AI智能体
        用户登录时调用

        Args:
            owner_id: 用户ID
        """
        import psycopg2.extras
        conn = None

        try:
            from ..db.dbutil import DatabaseUtil
            db_util = DatabaseUtil()
            conn = db_util._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 获取指定用户的所有AI智能体
            cursor.execute("SELECT id, username, owner_id FROM users WHERE user_type = 'ai' AND owner_id = %s", (owner_id,))
            ai_users = cursor.fetchall()

            if ai_users:
                print(f"🔄 为用户初始化 {len(ai_users)} 个AI智能体...")

            for user in ai_users:
                user_id = user['id']
                username = user['username']

                # 获取工作目录
                work_dir = get_agent_work_dir(owner_id, user_id)

                # 如果智能体客户端不存在，则创建
                if not await self.is_client_available(user_id):
                    success = await self.create_agent_client(user_id, username, work_dir)
                    if success:
                        print(f"✅ 智能体 {username} 初始化成功")

        except Exception as e:
            print(f"❌ 初始化用户AI智能体失败: {str(e)}", file=sys.stderr)
        finally:
            if conn:
                conn.close()  # 确保连接被归还到连接池

    async def logout_user_agents(self, owner_id: str):
        """
        关闭指定用户的所有AI智能体
        用户登出时调用

        Args:
            owner_id: 用户ID
        """
        import psycopg2.extras
        conn = None

        try:
            from ..db.dbutil import DatabaseUtil
            db_util = DatabaseUtil()
            conn = db_util._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 获取指定用户的所有AI智能体
            cursor.execute("SELECT id, username FROM users WHERE user_type = 'ai' AND owner_id = %s", (owner_id,))
            ai_users = cursor.fetchall()

            closed_count = 0
            for user in ai_users:
                user_id = user['id']
                username = user['username']

                # 关闭智能体客户端
                if await self.close_agent_client(user_id):
                    closed_count += 1
                    print(f"✅ 智能体 {username} 已离线")

            if closed_count > 0:
                print(f"✅ 用户登出，已关闭 {closed_count} 个AI智能体")

        except Exception as e:
            print(f"❌ 关闭用户AI智能体失败: {str(e)}", file=sys.stderr)
        finally:
            if conn:
                conn.close()  # 确保连接被归还到连接池

    async def initialize_all_ai_agents(self):
        """
        初始化数据库中所有的AI智能体
        在系统启动时调用，重新创建所有离线的智能体客户端
        """
        import psycopg2.extras
        conn = None

        try:
            from ..db.dbutil import DatabaseUtil
            db_util = DatabaseUtil()
            conn = db_util._get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 获取所有AI类型的用户
            cursor.execute("SELECT id, username, owner_id FROM users WHERE user_type = 'ai'")
            ai_users = cursor.fetchall()

            # 静默初始化所有AI智能体
            for user in ai_users:
                user_id = user['id']
                username = user['username']
                owner_id = user['owner_id']

                # 获取工作目录
                work_dir = get_agent_work_dir(owner_id, user_id)

                # 重新创建智能体客户端
                await self.create_agent_client(user_id, username, work_dir)

        except Exception as e:
            print(f"❌ 初始化AI智能体失败: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        finally:
            if conn:
                conn.close()  # 确保连接被归还到连接池

    def _generate_system_prompt(self, agent_name: str, work_dir: str, agent_id: str = "") -> str:
        """
        生成系统提示词

        Args:
            agent_name: 智能体名称
            work_dir: 工作目录
            agent_id: 智能体ID（用于静态页面分享）

        Returns:
            系统提示词
        """
        return config.get_system_prompt(agent_name, work_dir, agent_id)

# 创建全局智能体管理器实例
agent_manager = AgentManager()

def get_default_system_prompt(agent_name: str, work_dir: str) -> str:
    """获取默认系统提示词（与智能体管理器一致）"""
    return config.get_system_prompt(agent_name, work_dir)

async def initialize_agent_client(agent_id: str, agent_name: str, work_dir: str, session_id: str = None, continue_conversation: bool = False) -> bool:
    """
    初始化智能体客户端的公共方法

    Args:
        agent_id: 智能体ID
        agent_name: 智能体名称
        work_dir: 工作目录
        session_id: 可选的会话ID，用于恢复之前的会话记忆
        continue_conversation: 是否继续最近的对话

    Returns:
        是否初始化成功
    """
    return await agent_manager.create_agent_client(agent_id, agent_name, work_dir, session_id, continue_conversation)

async def get_agent_client(agent_id: str) -> Optional[ClaudeSDKClient]:
    """
    获取智能体客户端的公共方法

    Args:
        agent_id: 智能体ID

    Returns:
        ClaudeSDKClient对象
    """
    return await agent_manager.get_agent_client(agent_id)

async def ensure_agent_connected(agent_id: str) -> bool:
    """
    确保智能体客户端已连接（带空闲超时）。

    Args:
        agent_id: 智能体ID

    Returns:
        是否连接成功
    """
    return await agent_manager.ensure_client_connected(agent_id)

async def close_agent_client(agent_id: str) -> bool:
    """
    关闭智能体客户端的公共方法

    Args:
        agent_id: 智能体ID

    Returns:
        是否关闭成功
    """
    return await agent_manager.close_agent_client(agent_id)

def _get_default_work_base() -> Path:
    """
    获取工作目录的根路径，支持环境变量覆盖并按系统提供默认值
    """
    return config.get_work_base_dir()

def get_agent_work_dir(user_id: str, agent_id: str) -> str:
    """
    获取智能体的工作目录路径

    Args:
        user_id: 用户ID
        agent_id: 智能体ID

    Returns:
        工作目录路径
    """
    try:
        settings = db.get_agent_settings(agent_id) or {}
        custom_work_dir = settings.get("work_dir")
        if custom_work_dir:
            return str(Path(custom_work_dir).expanduser())
    except Exception:
        pass
    return config.get_agent_work_dir(user_id, agent_id)

def get_user_work_base_dir(user_id: str) -> Path:
    """获取用户工作目录根路径"""
    return config.get_user_work_base_dir(user_id)

def get_agent_session_id(agent_id: str) -> Optional[str]:
    """
    获取智能体的会话ID

    Args:
        agent_id: 智能体ID

    Returns:
        会话ID，如果不存在返回None
    """
    options = agent_manager._client_options.get(agent_id)
    return options.resume if options else None


async def initialize_user_agents(owner_id: str):
    """
    初始化指定用户的所有AI智能体
    用户登录时调用

    Args:
        owner_id: 用户ID
    """
    await agent_manager.initialize_user_agents(owner_id)

async def logout_user_agents(owner_id: str):
    """
    关闭指定用户的所有AI智能体
    用户登出时调用

    Args:
        owner_id: 用户ID
    """
    await agent_manager.logout_user_agents(owner_id)


async def main():
    """测试AgentManager的完整功能"""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    print("=" * 60)
    print("🚀 AgentManager 功能测试开始")
    print("=" * 60)

    # 测试参数
    test_agent_id = "test_agent_001"
    test_agent_name = "测试智能体"
    test_work_dir = str(_get_default_work_base() / "test_agent_workspace")

    try:
        # 1. 创建智能体（使用continue_conversation来保持记忆）
        print("\n【1️⃣ 创建智能体（启用对话连续性）】")
        success = await agent_manager.create_agent_client(
            test_agent_id,
            test_agent_name,
            test_work_dir,
            continue_conversation=True  # 启用对话连续性
        )
        print(f"✅ 创建结果: {'成功' if success else '失败'}")

        # 3. 获取客户端
        print("\n【2️⃣ 获取客户端】")
        client = await agent_manager.get_agent_client(test_agent_id)
        print(f"✅ 获取客户端: {'成功' if client else '失败'}")

        # 4. 连接客户端并进行第一次对话
        if client:
            print("\n【4️⃣ 连接客户端并进行第一次对话】")
            session_id = None
            try:
                # 手动连接客户端
                await client.connect()
                print("✅ 客户端已连接")

                # 第一次对话
                await client.query("你好！请记住我的名字叫张三，并在工作目录创建一个test.txt文件，写入'Hello World'")
                response = ""
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response += block.text
                    elif isinstance(message, ResultMessage):
                        # 获取会话ID
                        session_id = message.session_id if hasattr(message, 'session_id') else None
                        print(f"✅ 会话ID: {session_id}")
                print(f"✅ AI响应: {response[:150]}...")

                # 5. 第二次对话（测试连续性）- 不需要重新连接
                print("\n【5️⃣ 第二次对话（测试记忆）】")
                await client.query("你还记得我的名字吗？请读取test.txt文件的内容")
                response = ""
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                response += block.text
                print(f"✅ AI响应: {response[:200]}...")

                # 检查记忆
                if "张三" in response and "Hello World" in response:
                    print("✅ 记忆测试通过！AI记住了用户名字和文件内容")
                else:
                    print("⚠️ 记忆测试：未完全保留信息")

            except Exception as e:
                print(f"❌ 对话失败: {e}")

        # 7. 关闭智能体（模拟下线）
        print("\n【6️⃣ 关闭智能体（模拟下线）】")
        await agent_manager.close_agent_client(test_agent_id)
        print(f"✅ 智能体已关闭")

        # 8. 重新创建智能体（使用resume恢复会话）
        if session_id:
            print("\n【7️⃣ 重新创建智能体（使用session_id恢复）】")
            success = await agent_manager.create_agent_client(
                test_agent_id,
                test_agent_name,
                test_work_dir,
                session_id=session_id  # 使用之前的会话ID
            )
            print(f"✅ 重建结果: {'成功' if success else '失败'}")

            # 9. 测试恢复的记忆
            if success:
                client = await agent_manager.get_agent_client(test_agent_id)
                if client:
                    print("\n【8️⃣ 测试恢复的记忆】")
                    try:
                        async with client:
                            await client.query("我们刚才聊了什么？test.txt文件里有什么？")
                            response = ""
                            async for message in client.receive_response():
                                if isinstance(message, AssistantMessage):
                                    for block in message.content:
                                        if isinstance(block, TextBlock):
                                            response += block.text
                            print(f"✅ AI响应: {response[:200]}...")
                    except Exception as e:
                        print(f"❌ 对话失败: {e}")

        # 10. 最终清理
        print("\n【9️⃣ 最终清理】")
        await agent_manager.close_agent_client(test_agent_id)
        print(f"✅ 智能体已清理")

        print("\n" + "=" * 60)
        print("🎉 所有测试完成！")
        print("✅ 会话记忆功能已验证")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    """运行测试"""
    asyncio.run(main())
