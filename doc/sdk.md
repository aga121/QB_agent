Agent SDK
Agent SDK 参考 - Python
￼
￼
￼
￼
Copy page
￼
Python Agent SDK 的完整 API 参考，包括所有函数、类型和类。
Copy link to clipboard
安装
pip install claude-agent-sdk
￼
Copy link to clipboard
在 query() 和 ClaudeSDKClient 之间选择
Python SDK 提供了两种与 Claude Code 交互的方式：
Copy link to clipboard
快速比较
功能
query()
ClaudeSDKClient
会话
每次创建新会话
重用同一会话
对话
单次交换
同一上下文中的多次交换
连接
自动管理
手动控制
流式输入
✅ 支持
✅ 支持
中断
❌ 不支持
✅ 支持
钩子
❌ 不支持
✅ 支持
自定义工具
❌ 不支持
✅ 支持
继续聊天
❌ 每次新会话
✅ 维持对话
用例
一次性任务
连续对话
Copy link to clipboard
何时使用 query()（每次新建会话）
最适合：
•
不需要对话历史的一次性问题
•
不需要来自之前交换的上下文的独立任务
•
简单的自动化脚本
•
当您想每次都重新开始时
Copy link to clipboard
何时使用 ClaudeSDKClient（连续对话）
最适合：
•
继续对话 - 当您需要 Claude 记住上下文时
•
后续问题 - 基于之前的回应进行构建
•
交互式应用程序 - 聊天界面、REPL
•
响应驱动的逻辑 - 当下一步操作取决于 Claude 的响应时
•
会话控制 - 显式管理对话生命周期
Copy link to clipboard
函数
Copy link to clipboard
query()
为每次与 Claude Code 的交互创建一个新会话。返回一个异步迭代器，在消息到达时产生消息。每次调用 query()都会重新开始，不记得之前的交互。
async def query(
    *,
    prompt: str | AsyncIterable[dict[str, Any]],
    options: ClaudeAgentOptions | None = None
) -> AsyncIterator[Message]
￼
Copy link to clipboard
参数
参数
类型
描述
prompt
str | AsyncIterable[dict]
输入提示，可以是字符串或异步可迭代对象（用于流式模式）
options
ClaudeAgentOptions | None
可选配置对象（如果为 None，默认为 ClaudeAgentOptions()）
Copy link to clipboard
返回
返回一个 AsyncIterator[Message]，从对话中产生消息。
Copy link to clipboard
示例 - 带选项
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are an expert Python developer",
        permission_mode='acceptEdits',
        cwd="/home/user/project"
    )

    async for message in query(
        prompt="Create a Python web server",
        options=options
    ):
        print(message)


asyncio.run(main())
￼
Copy link to clipboard
tool()
用于定义具有类型安全的 MCP 工具的装饰器。
def tool(
    name: str,
    description: str,
    input_schema: type | dict[str, Any]
) -> Callable[[Callable[[Any], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]
￼
Copy link to clipboard
参数
参数
类型
描述
name
str
工具的唯一标识符
description
str
工具功能的人类可读描述
input_schema
type | dict[str, Any]
定义工具输入参数的架构（见下文）
Copy link to clipboard
输入架构选项
1.
简单类型映射（推荐）：
{"text": str, "count": int, "enabled": bool}
￼
2.
JSON Schema 格式（用于复杂验证）：
{
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "count": {"type": "integer", "minimum": 0}
    },
    "required": ["text"]
}
￼
Copy link to clipboard
返回
一个装饰器函数，包装工具实现并返回一个 SdkMcpTool 实例。
Copy link to clipboard
示例
from claude_agent_sdk import tool
from typing import Any

@tool("greet", "Greet a user", {"name": str})
async def greet(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{
            "type": "text",
            "text": f"Hello, {args['name']}!"
        }]
    }
￼
Copy link to clipboard
create_sdk_mcp_server()
创建在 Python 应用程序内运行的进程内 MCP 服务器。
def create_sdk_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: list[SdkMcpTool[Any]] | None = None
) -> McpSdkServerConfig
￼
Copy link to clipboard
参数
参数
类型
默认值
描述
name
str
-
服务器的唯一标识符
version
str
"1.0.0"
服务器版本字符串
tools
list[SdkMcpTool[Any]] | None
None
使用 @tool 装饰器创建的工具函数列表
Copy link to clipboard
返回
返回一个 McpSdkServerConfig 对象，可以传递给 ClaudeAgentOptions.mcp_servers。
Copy link to clipboard
示例
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("add", "Add two numbers", {"a": float, "b": float})
async def add(args):
    return {
        "content": [{
            "type": "text",
            "text": f"Sum: {args['a'] + args['b']}"
        }]
    }

@tool("multiply", "Multiply two numbers", {"a": float, "b": float})
async def multiply(args):
    return {
        "content": [{
            "type": "text",
            "text": f"Product: {args['a'] * args['b']}"
        }]
    }

calculator = create_sdk_mcp_server(
    name="calculator",
    version="2.0.0",
    tools=[add, multiply]  # Pass decorated functions
)

# Use with Claude
options = ClaudeAgentOptions(
    mcp_servers={"calc": calculator},
    allowed_tools=["mcp__calc__add", "mcp__calc__multiply"]
)
￼
Copy link to clipboard
类
Copy link to clipboard
ClaudeSDKClient
在多次交换中维持对话会话。 这是 TypeScript SDK 的 query() 函数内部工作方式的 Python 等效物 - 它创建一个可以继续对话的客户端对象。
Copy link to clipboard
关键特性
•
会话连续性：在多个 query() 调用中维持对话上下文
•
同一对话：Claude 记住会话中的之前消息
•
中断支持：可以在 Claude 执行中途停止
•
显式生命周期：您控制会话何时开始和结束
•
响应驱动流：可以对响应做出反应并发送后续消息
•
自定义工具和钩子：支持自定义工具（使用 @tool 装饰器创建）和钩子
class ClaudeSDKClient:
    def __init__(self, options: ClaudeAgentOptions | None = None)
    async def connect(self, prompt: str | AsyncIterable[dict] | None = None) -> None
    async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None
    async def receive_messages(self) -> AsyncIterator[Message]
    async def receive_response(self) -> AsyncIterator[Message]
    async def interrupt(self) -> None
    async def disconnect(self) -> None
￼
Copy link to clipboard
方法
方法
描述
__init__(options)
使用可选配置初始化客户端
connect(prompt)
连接到 Claude，可选初始提示或消息流
query(prompt, session_id)
以流式模式发送新请求
receive_messages()
以异步迭代器形式接收来自 Claude 的所有消息
receive_response()
接收消息直到并包括 ResultMessage
interrupt()
发送中断信号（仅在流式模式下工作）
disconnect()
从 Claude 断开连接
Copy link to clipboard
上下文管理器支持
客户端可以用作异步上下文管理器以实现自动连接管理：
async with ClaudeSDKClient() as client:
    await client.query("Hello Claude")
    async for message in client.receive_response():
        print(message)
￼
重要： 在迭代消息时，避免使用 break 提前退出，因为这可能导致 asyncio 清理问题。相反，让迭代自然完成或使用标志来跟踪何时找到所需内容。
Copy link to clipboard
示例 - 继续对话
import asyncio
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage

async def main():
    async with ClaudeSDKClient() as client:
        # First question
        await client.query("What's the capital of France?")

        # Process response
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")

        # Follow-up question - Claude remembers the previous context
        await client.query("What's the population of that city?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")

        # Another follow-up - still in the same conversation
        await client.query("What are some famous landmarks there?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")

asyncio.run(main())
￼
Copy link to clipboard
示例 - 使用 ClaudeSDKClient 进行流式输入
import asyncio
from claude_agent_sdk import ClaudeSDKClient

async def message_stream():
    """Generate messages dynamically."""
    yield {"type": "text", "text": "Analyze the following data:"}
    await asyncio.sleep(0.5)
    yield {"type": "text", "text": "Temperature: 25°C"}
    await asyncio.sleep(0.5)
    yield {"type": "text", "text": "Humidity: 60%"}
    await asyncio.sleep(0.5)
    yield {"type": "text", "text": "What patterns do you see?"}

async def main():
    async with ClaudeSDKClient() as client:
        # Stream input to Claude
        await client.query(message_stream())

        # Process response
        async for message in client.receive_response():
            print(message)

        # Follow-up in same session
        await client.query("Should we be concerned about these readings?")

        async for message in client.receive_response():
            print(message)

asyncio.run(main())
￼
Copy link to clipboard
示例 - 使用中断
import asyncio
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async def interruptible_task():
    options = ClaudeAgentOptions(
        allowed_tools=["Bash"],
        permission_mode="acceptEdits"
    )

    async with ClaudeSDKClient(options=options) as client:
        # Start a long-running task
        await client.query("Count from 1 to 100 slowly")

        # Let it run for a bit
        await asyncio.sleep(2)

        # Interrupt the task
        await client.interrupt()
        print("Task interrupted!")

        # Send a new command
        await client.query("Just say hello instead")

        async for message in client.receive_response():
            # Process the new response
            pass

asyncio.run(interruptible_task())
￼
Copy link to clipboard
示例 - 高级权限控制
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions
)

async def custom_permission_handler(
    tool_name: str,
    input_data: dict,
    context: dict
):
    """Custom logic for tool permissions."""

    # Block writes to system directories
    if tool_name == "Write" and input_data.get("file_path", "").startswith("/system/"):
        return {
            "behavior": "deny",
            "message": "System directory write not allowed",
            "interrupt": True
        }

    # Redirect sensitive file operations
    if tool_name in ["Write", "Edit"] and "config" in input_data.get("file_path", ""):
        safe_path = f"./sandbox/{input_data['file_path']}"
        return {
            "behavior": "allow",
            "updatedInput": {**input_data, "file_path": safe_path}
        }

    # Allow everything else
    return {
        "behavior": "allow",
        "updatedInput": input_data
    }

async def main():
    options = ClaudeAgentOptions(
        can_use_tool=custom_permission_handler,
        allowed_tools=["Read", "Write", "Edit"]
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Update the system config file")

        async for message in client.receive_response():
            # Will use sandbox path instead
            print(message)

asyncio.run(main())
￼
Copy link to clipboard
类型
Copy link to clipboard
SdkMcpTool
使用 @tool 装饰器创建的 SDK MCP 工具的定义。
@dataclass
class SdkMcpTool(Generic[T]):
    name: str
    description: str
    input_schema: type[T] | dict[str, Any]
    handler: Callable[[T], Awaitable[dict[str, Any]]]
￼
属性
类型
描述
name
str
工具的唯一标识符
description
str
人类可读的描述
input_schema
type[T] | dict[str, Any]
输入验证的架构
handler
Callable[[T], Awaitable[dict[str, Any]]]
处理工具执行的异步函数
Copy link to clipboard
ClaudeAgentOptions
Claude Code 查询的配置数据类。
@dataclass
class ClaudeAgentOptions:
    allowed_tools: list[str] = field(default_factory=list)
    system_prompt: str | SystemPromptPreset | None = None
    mcp_servers: dict[str, McpServerConfig] | str | Path = field(default_factory=dict)
    permission_mode: PermissionMode | None = None
    continue_conversation: bool = False
    resume: str | None = None
    max_turns: int | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    output_format: OutputFormat | None = None
    permission_prompt_tool_name: str | None = None
    cwd: str | Path | None = None
    settings: str | None = None
    add_dirs: list[str | Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    extra_args: dict[str, str | None] = field(default_factory=dict)
    max_buffer_size: int | None = None
    debug_stderr: Any = sys.stderr  # Deprecated
    stderr: Callable[[str], None] | None = None
    can_use_tool: CanUseTool | None = None
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    user: str | None = None
    include_partial_messages: bool = False
    fork_session: bool = False
    agents: dict[str, AgentDefinition] | None = None
    setting_sources: list[SettingSource] | None = None
￼
属性
类型
默认值
描述
allowed_tools
list[str]
[]
允许的工具名称列表
system_prompt
str | SystemPromptPreset | None
None
系统提示配置。传递字符串以获得自定义提示，或使用 {"type": "preset", "preset": "claude_code"} 获得 Claude Code 的系统提示。添加 "append" 以扩展预设
mcp_servers
dict[str, McpServerConfig] | str | Path
{}
MCP 服务器配置或配置文件路径
permission_mode
PermissionMode | None
None
工具使用的权限模式
continue_conversation
bool
False
继续最近的对话
resume
str | None
None
要恢复的会话 ID
max_turns
int | None
None
最大对话轮数
disallowed_tools
list[str]
[]
不允许的工具名称列表
model
str | None
None
要使用的 Claude 模型
output_format
OutputFormat | None
None
定义代理结果的输出格式。有关详细信息，请参阅结构化输出
permission_prompt_tool_name
str | None
None
权限提示的 MCP 工具名称
cwd
str | Path | None
None
当前工作目录
settings
str | None
None
设置文件的路径
add_dirs
list[str | Path]
[]
Claude 可以访问的其他目录
env
dict[str, str]
{}
环境变量
extra_args
dict[str, str | None]
{}
直接传递给 CLI 的其他 CLI 参数
max_buffer_size
int | None
None
缓冲 CLI stdout 时的最大字节数
debug_stderr
Any
sys.stderr
已弃用 - 用于调试输出的类文件对象。改用 stderr 回调
stderr
Callable[[str], None] | None
None
来自 CLI 的 stderr 输出的回调函数
can_use_tool
CanUseTool | None
None
工具权限回调函数
hooks
dict[HookEvent, list[HookMatcher]] | None
None
用于拦截事件的钩子配置
user
str | None
None
用户标识符
include_partial_messages
bool
False
包括部分消息流事件
fork_session
bool
False
使用 resume 恢复时，分叉到新会话 ID 而不是继续原始会话
agents
dict[str, AgentDefinition] | None
None
以编程方式定义的子代理
plugins
list[SdkPluginConfig]
[]
从本地路径加载自定义插件。有关详细信息，请参阅插件
setting_sources
list[SettingSource] | None
None（无设置）
控制要加载哪些文件系统设置。省略时，不加载任何设置。注意： 必须包括 "project" 以加载 CLAUDE.md 文件
Copy link to clipboard
OutputFormat
结构化输出验证的配置。
class OutputFormat(TypedDict):
    type: Literal["json_schema"]
    schema: dict[str, Any]
￼
字段
必需
描述
type
是
必须是 "json_schema" 以进行 JSON Schema 验证
schema
是
输出验证的 JSON Schema 定义
Copy link to clipboard
SystemPromptPreset
使用 Claude Code 预设系统提示和可选添加的配置。
class SystemPromptPreset(TypedDict):
    type: Literal["preset"]
    preset: Literal["claude_code"]
    append: NotRequired[str]
￼
字段
必需
描述
type
是
必须是 "preset" 以使用预设系统提示
preset
是
必须是 "claude_code" 以使用 Claude Code 的系统提示
append
否
要附加到预设系统提示的其他说明
Copy link to clipboard
SettingSource
控制 SDK 从哪些基于文件系统的配置源加载设置。
SettingSource = Literal["user", "project", "local"]
￼
值
描述
位置
"user"
全局用户设置
~/.claude/settings.json
"project"
共享项目设置（版本控制）
.claude/settings.json
"local"
本地项目设置（gitignored）
.claude/settings.local.json
Copy link to clipboard
默认行为
当 setting_sources 省略或为 None 时，SDK 不加载任何文件系统设置。这为 SDK 应用程序提供了隔离。
Copy link to clipboard
为什么使用 setting_sources？
加载所有文件系统设置（旧版行为）：
# Load all settings like SDK v0.0.x did
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Analyze this code",
    options=ClaudeAgentOptions(
        setting_sources=["user", "project", "local"]  # Load all settings
    )
):
    print(message)
￼
仅加载特定设置源：
# Load only project settings, ignore user and local
async for message in query(
    prompt="Run CI checks",
    options=ClaudeAgentOptions(
        setting_sources=["project"]  # Only .claude/settings.json
    )
):
    print(message)
￼
测试和 CI 环境：
# Ensure consistent behavior in CI by excluding local settings
async for message in query(
    prompt="Run tests",
    options=ClaudeAgentOptions(
        setting_sources=["project"],  # Only team-shared settings
        permission_mode="bypassPermissions"
    )
):
    print(message)
￼
仅 SDK 应用程序：
# Define everything programmatically (default behavior)
# No filesystem dependencies - setting_sources defaults to None
async for message in query(
    prompt="Review this PR",
    options=ClaudeAgentOptions(
        # setting_sources=None is the default, no need to specify
        agents={ /* ... */ },
        mcp_servers={ /* ... */ },
        allowed_tools=["Read", "Grep", "Glob"]
    )
):
    print(message)
￼
加载 CLAUDE.md 项目说明：
# Load project settings to include CLAUDE.md files
async for message in query(
    prompt="Add a new feature following project conventions",
    options=ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code"  # Use Claude Code's system prompt
        },
        setting_sources=["project"],  # Required to load CLAUDE.md from project
        allowed_tools=["Read", "Write", "Edit"]
    )
):
    print(message)
￼
Copy link to clipboard
设置优先级
加载多个源时，设置按此优先级合并（从高到低）：
1.
本地设置（.claude/settings.local.json）
2.
项目设置（.claude/settings.json）
3.
用户设置（~/.claude/settings.json）
编程选项（如 agents、allowed_tools）始终覆盖文件系统设置。
Copy link to clipboard
AgentDefinition
以编程方式定义的子代理的配置。
@dataclass
class AgentDefinition:
    description: str
    prompt: str
    tools: list[str] | None = None
    model: Literal["sonnet", "opus", "haiku", "inherit"] | None = None
￼
字段
必需
描述
description
是
何时使用此代理的自然语言描述
tools
否
允许的工具名称数组。如果省略，继承所有工具
prompt
是
代理的系统提示
model
否
此代理的模型覆盖。如果省略，使用主模型
Copy link to clipboard
PermissionMode
用于控制工具执行的权限模式。
PermissionMode = Literal[
    "default",           # Standard permission behavior
    "acceptEdits",       # Auto-accept file edits
    "plan",              # Planning mode - no execution
    "bypassPermissions"  # Bypass all permission checks (use with caution)
]
￼
Copy link to clipboard
McpSdkServerConfig
使用 create_sdk_mcp_server() 创建的 SDK MCP 服务器的配置。
class McpSdkServerConfig(TypedDict):
    type: Literal["sdk"]
    name: str
    instance: Any  # MCP Server instance
￼
Copy link to clipboard
McpServerConfig
MCP 服务器配置的联合类型。
McpServerConfig = McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig
￼
Copy link to clipboard
McpStdioServerConfig
class McpStdioServerConfig(TypedDict):
    type: NotRequired[Literal["stdio"]]  # Optional for backwards compatibility
    command: str
    args: NotRequired[list[str]]
    env: NotRequired[dict[str, str]]
￼
Copy link to clipboard
McpSSEServerConfig
class McpSSEServerConfig(TypedDict):
    type: Literal["sse"]
    url: str
    headers: NotRequired[dict[str, str]]
￼
Copy link to clipboard
McpHttpServerConfig
class McpHttpServerConfig(TypedDict):
    type: Literal["http"]
    url: str
    headers: NotRequired[dict[str, str]]
￼
Copy link to clipboard
SdkPluginConfig
SDK 中加载插件的配置。
class SdkPluginConfig(TypedDict):
    type: Literal["local"]
    path: str
￼
字段
类型
描述
type
Literal["local"]
必须是 "local"（目前仅支持本地插件）
path
str
插件目录的绝对或相对路径
示例：
plugins=[
    {"type": "local", "path": "./my-plugin"},
    {"type": "local", "path": "/absolute/path/to/plugin"}
]
￼
有关创建和使用插件的完整信息，请参阅插件。
Copy link to clipboard
消息类型
Copy link to clipboard
Message
所有可能消息的联合类型。
Message = UserMessage | AssistantMessage | SystemMessage | ResultMessage
￼
Copy link to clipboard
UserMessage
用户输入消息。
@dataclass
class UserMessage:
    content: str | list[ContentBlock]
￼
Copy link to clipboard
AssistantMessage
带有内容块的助手响应消息。
@dataclass
class AssistantMessage:
    content: list[ContentBlock]
    model: str
￼
Copy link to clipboard
SystemMessage
带有元数据的系统消息。
@dataclass
class SystemMessage:
    subtype: str
    data: dict[str, Any]
￼
Copy link to clipboard
ResultMessage
带有成本和使用信息的最终结果消息。
@dataclass
class ResultMessage:
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
￼
Copy link to clipboard
内容块类型
Copy link to clipboard
ContentBlock
所有内容块的联合类型。
ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock
￼
Copy link to clipboard
TextBlock
文本内容块。
@dataclass
class TextBlock:
    text: str
￼
Copy link to clipboard
ThinkingBlock
思考内容块（用于具有思考能力的模型）。
@dataclass
class ThinkingBlock:
    thinking: str
    signature: str
￼
Copy link to clipboard
ToolUseBlock
工具使用请求块。
@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
￼
Copy link to clipboard
ToolResultBlock
工具执行结果块。
@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None
￼
Copy link to clipboard
错误类型
Copy link to clipboard
ClaudeSDKError
所有 SDK 错误的基础异常类。
class ClaudeSDKError(Exception):
    """Base error for Claude SDK."""
￼
Copy link to clipboard
CLINotFoundError
当 Claude Code CLI 未安装或找不到时引发。
class CLINotFoundError(CLIConnectionError):
    def __init__(self, message: str = "Claude Code not found", cli_path: str | None = None):
        """
        Args:
            message: Error message (default: "Claude Code not found")
            cli_path: Optional path to the CLI that was not found
        """
￼
Copy link to clipboard
CLIConnectionError
当连接到 Claude Code 失败时引发。
class CLIConnectionError(ClaudeSDKError):
    """Failed to connect to Claude Code."""
￼
Copy link to clipboard
ProcessError
当 Claude Code 进程失败时引发。
class ProcessError(ClaudeSDKError):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None):
        self.exit_code = exit_code
        self.stderr = stderr
￼
Copy link to clipboard
CLIJSONDecodeError
当 JSON 解析失败时引发。
class CLIJSONDecodeError(ClaudeSDKError):
    def __init__(self, line: str, original_error: Exception):
        """
        Args:
            line: The line that failed to parse
            original_error: The original JSON decode exception
        """
        self.line = line
        self.original_error = original_error
￼
Copy link to clipboard
钩子类型
Copy link to clipboard
HookEvent
支持的钩子事件类型。请注意，由于设置限制，Python SDK 不支持 SessionStart、SessionEnd 和 Notification 钩子。
HookEvent = Literal[
    "PreToolUse",      # Called before tool execution
    "PostToolUse",     # Called after tool execution
    "UserPromptSubmit", # Called when user submits a prompt
    "Stop",            # Called when stopping execution
    "SubagentStop",    # Called when a subagent stops
    "PreCompact"       # Called before message compaction
]
￼
Copy link to clipboard
HookCallback
钩子回调函数的类型定义。
HookCallback = Callable[
    [dict[str, Any], str | None, HookContext],
    Awaitable[dict[str, Any]]
]
￼
参数：
•
input_data：钩子特定的输入数据（请参阅钩子文档）
•
tool_use_id：可选的工具使用标识符（用于工具相关钩子）
•
context：带有其他信息的钩子上下文
返回一个可能包含以下内容的字典：
•
decision："block" 以阻止操作
•
systemMessage：要添加到记录的系统消息
•
hookSpecificOutput：钩子特定的输出数据
Copy link to clipboard
HookContext
传递给钩子回调的上下文信息。
@dataclass
class HookContext:
    signal: Any | None = None  # Future: abort signal support
￼
Copy link to clipboard
HookMatcher
用于将钩子匹配到特定事件或工具的配置。
@dataclass
class HookMatcher:
    matcher: str | None = None        # Tool name or pattern to match (e.g., "Bash", "Write|Edit")
    hooks: list[HookCallback] = field(default_factory=list)  # List of callbacks to execute
￼
Copy link to clipboard
钩子使用示例
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher, HookContext
from typing import Any

async def validate_bash_command(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Validate and potentially block dangerous bash commands."""
    if input_data['tool_name'] == 'Bash':
        command = input_data['tool_input'].get('command', '')
        if 'rm -rf /' in command:
            return {
                'hookSpecificOutput': {
                    'hookEventName': 'PreToolUse',
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': 'Dangerous command blocked'
                }
            }
    return {}

async def log_tool_use(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Log all tool usage for auditing."""
    print(f"Tool used: {input_data.get('tool_name')}")
    return {}

options = ClaudeAgentOptions(
    hooks={
        'PreToolUse': [
            HookMatcher(matcher='Bash', hooks=[validate_bash_command]),
            HookMatcher(hooks=[log_tool_use])  # Applies to all tools
        ],
        'PostToolUse': [
            HookMatcher(hooks=[log_tool_use])
        ]
    }
)

async for message in query(
    prompt="Analyze this codebase",
    options=options
):
    print(message)
￼
Copy link to clipboard
工具输入/输出类型
所有内置 Claude Code 工具的输入/输出架构文档。虽然 Python SDK 不将这些导出为类型，但它们代表消息中工具输入和输出的结构。
Copy link to clipboard
Task
工具名称： Task
输入：
{
    "description": str,      # A short (3-5 word) description of the task
    "prompt": str,           # The task for the agent to perform
    "subagent_type": str     # The type of specialized agent to use
}
￼
输出：
{
    "result": str,                    # Final result from the subagent
    "usage": dict | None,             # Token usage statistics
    "total_cost_usd": float | None,  # Total cost in USD
    "duration_ms": int | None         # Execution duration in milliseconds
}
￼
Copy link to clipboard
Bash
工具名称： Bash
输入：
{
    "command": str,                  # The command to execute
    "timeout": int | None,           # Optional timeout in milliseconds (max 600000)
    "description": str | None,       # Clear, concise description (5-10 words)
    "run_in_background": bool | None # Set to true to run in background
}
￼
输出：
{
    "output": str,              # Combined stdout and stderr output
    "exitCode": int,            # Exit code of the command
    "killed": bool | None,      # Whether command was killed due to timeout
    "shellId": str | None       # Shell ID for background processes
}
￼
Copy link to clipboard
Edit
工具名称： Edit
输入：
{
    "file_path": str,           # The absolute path to the file to modify
    "old_string": str,          # The text to replace
    "new_string": str,          # The text to replace it with
    "replace_all": bool | None  # Replace all occurrences (default False)
}
￼
输出：
{
    "message": str,      # Confirmation message
    "replacements": int, # Number of replacements made
    "file_path": str     # File path that was edited
}
￼
Copy link to clipboard
Read
工具名称： Read
输入：
{
    "file_path": str,       # The absolute path to the file to read
    "offset": int | None,   # The line number to start reading from
    "limit": int | None     # The number of lines to read
}
￼
输出（文本文件）：
{
    "content": str,         # File contents with line numbers
    "total_lines": int,     # Total number of lines in file
    "lines_returned": int   # Lines actually returned
}
￼
输出（图像）：
{
    "image": str,       # Base64 encoded image data
    "mime_type": str,   # Image MIME type
    "file_size": int    # File size in bytes
}
￼
Copy link to clipboard
Write
工具名称： Write
输入：
{
    "file_path": str,  # The absolute path to the file to write
    "content": str     # The content to write to the file
}
￼
输出：
{
    "message": str,        # Success message
    "bytes_written": int,  # Number of bytes written
    "file_path": str       # File path that was written
}
￼
Copy link to clipboard
Glob
工具名称： Glob
输入：
{
    "pattern": str,       # The glob pattern to match files against
    "path": str | None    # The directory to search in (defaults to cwd)
}
￼
输出：
{
    "matches": list[str],  # Array of matching file paths
    "count": int,          # Number of matches found
    "search_path": str     # Search directory used
}
￼
Copy link to clipboard
Grep
工具名称： Grep
输入：
{
    "pattern": str,                    # The regular expression pattern
    "path": str | None,                # File or directory to search in
    "glob": str | None,                # Glob pattern to filter files
    "type": str | None,                # File type to search
    "output_mode": str | None,         # "content", "files_with_matches", or "count"
    "-i": bool | None,                 # Case insensitive search
    "-n": bool | None,                 # Show line numbers
    "-B": int | None,                  # Lines to show before each match
    "-A": int | None,                  # Lines to show after each match
    "-C": int | None,                  # Lines to show before and after
    "head_limit": int | None,          # Limit output to first N lines/entries
    "multiline": bool | None           # Enable multiline mode
}
￼
输出（内容模式）：
{
    "matches": [
        {
            "file": str,
            "line_number": int | None,
            "line": str,
            "before_context": list[str] | None,
            "after_context": list[str] | None
        }
    ],
    "total_matches": int
}
￼
输出（files_with_matches 模式）：
{
    "files": list[str],  # Files containing matches
    "count": int         # Number of files with matches
}
￼
Copy link to clipboard
NotebookEdit
工具名称： NotebookEdit
输入：
{
    "notebook_path": str,                     # Absolute path to the Jupyter notebook
    "cell_id": str | None,                    # The ID of the cell to edit
    "new_source": str,                        # The new source for the cell
    "cell_type": "code" | "markdown" | None,  # The type of the cell
    "edit_mode": "replace" | "insert" | "delete" | None  # Edit operation type
}
￼
输出：
{
    "message": str, # Success message
    "edit_type": "replaced" | "inserted" | "deleted",  # Type of edit performed
    "cell_id": str | None,                       # Cell ID that was affected
    "total_cells": int                           # Total cells in notebook after edit
}
￼
Copy link to clipboard
WebFetch
工具名称： WebFetch
输入：
{
    "url": str,     # The URL to fetch content from
    "prompt": str   # The prompt to run on the fetched content
}
￼
输出：
{
    "response": str,           # AI model's response to the prompt
    "url": str,                # URL that was fetched
    "final_url": str | None,   # Final URL after redirects
    "status_code": int | None  # HTTP status code
}
￼
Copy link to clipboard
WebSearch
工具名称： WebSearch
输入：
{
    "query": str,                        # The search query to use
    "allowed_domains": list[str] | None, # Only include results from these domains
    "blocked_domains": list[str] | None  # Never include results from these domains
}
￼
输出：
{
    "results": [
        {
            "title": str,
            "url": str,
            "snippet": str,
            "metadata": dict | None
        }
    ],
    "total_results": int,
    "query": str
}
￼
Copy link to clipboard
TodoWrite
工具名称： TodoWrite
输入：
{
    "todos": [
        {
            "content": str, # The task description
            "status": "pending" | "in_progress" | "completed",  # Task status
            "activeForm": str                            # Active form of the description
        }
    ]
}
￼
输出：
{
    "message": str,  # Success message
    "stats": {
        "total": int,
        "pending": int,
        "in_progress": int,
        "completed": int
    }
}
￼
Copy link to clipboard
BashOutput
工具名称： BashOutput
输入：
{
    "bash_id": str,       # The ID of the background shell
    "filter": str | None  # Optional regex to filter output lines
}
￼
输出：
{
    "output": str, # New output since last check
    "status": "running" | "completed" | "failed",       # Current shell status
    "exitCode": int | None # Exit code when completed
}
￼
Copy link to clipboard
KillBash
工具名称： KillBash
输入：
{
    "shell_id": str  # The ID of the background shell to kill
}
￼
输出：
{
    "message": str,  # Success message
    "shell_id": str  # ID of the killed shell
}
￼
Copy link to clipboard
ExitPlanMode
工具名称： ExitPlanMode
输入：
{
    "plan": str  # The plan to run by the user for approval
}
￼
输出：
{
    "message": str,          # Confirmation message
    "approved": bool | None  # Whether user approved the plan
}
￼
Copy link to clipboard
ListMcpResources
工具名称： ListMcpResources
输入：
{
    "server": str | None  # Optional server name to filter resources by
}
￼
输出：
{
    "resources": [
        {
            "uri": str,
            "name": str,
            "description": str | None,
            "mimeType": str | None,
            "server": str
        }
    ],
    "total": int
}
￼
Copy link to clipboard
ReadMcpResource
工具名称： ReadMcpResource
输入：
{
    "server": str,  # The MCP server name
    "uri": str      # The resource URI to read
}
￼
输出：
{
    "contents": [
        {
            "uri": str,
            "mimeType": str | None,
            "text": str | None,
            "blob": str | None
        }
    ],
    "server": str
}
￼
Copy link to clipboard
ClaudeSDKClient 的高级功能
Copy link to clipboard
构建连续对话界面
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, TextBlock
import asyncio

class ConversationSession:
    """Maintains a single conversation session with Claude."""

    def __init__(self, options: ClaudeAgentOptions = None):
        self.client = ClaudeSDKClient(options)
        self.turn_count = 0

    async def start(self):
        await self.client.connect()
        print("Starting conversation session. Claude will remember context.")
        print("Commands: 'exit' to quit, 'interrupt' to stop current task, 'new' for new session")

        while True:
            user_input = input(f"\n[Turn {self.turn_count + 1}] You: ")

            if user_input.lower() == 'exit':
                break
            elif user_input.lower() == 'interrupt':
                await self.client.interrupt()
                print("Task interrupted!")
                continue
            elif user_input.lower() == 'new':
                # Disconnect and reconnect for a fresh session
                await self.client.disconnect()
                await self.client.connect()
                self.turn_count = 0
                print("Started new conversation session (previous context cleared)")
                continue

            # Send message - Claude remembers all previous messages in this session
            await self.client.query(user_input)
            self.turn_count += 1

            # Process response
            print(f"[Turn {self.turn_count}] Claude: ", end="")
            async for message in self.client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            print(block.text, end="")
            print()  # New line after response

        await self.client.disconnect()
        print(f"Conversation ended after {self.turn_count} turns.")

async def main():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash"],
        permission_mode="acceptEdits"
    )
    session = ConversationSession(options)
    await session.start()

# Example conversation:
# Turn 1 - You: "Create a file called hello.py"
# Turn 1 - Claude: "I'll create a hello.py file for you..."
# Turn 2 - You: "What's in that file?"
# Turn 2 - Claude: "The hello.py file I just created contains..." (remembers!)
# Turn 3 - You: "Add a main function to it"
# Turn 3 - Claude: "I'll add a main function to hello.py..." (knows which file!)

asyncio.run(main())
￼
Copy link to clipboard
使用钩子进行行为修改
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    HookContext
)
import asyncio
from typing import Any

async def pre_tool_logger(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Log all tool usage before execution."""
    tool_name = input_data.get('tool_name', 'unknown')
    print(f"[PRE-TOOL] About to use: {tool_name}")

    # You can modify or block the tool execution here
    if tool_name == "Bash" and "rm -rf" in str(input_data.get('tool_input', {})):
        return {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': 'Dangerous command blocked'
            }
        }
    return {}

async def post_tool_logger(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Log results after tool execution."""
    tool_name = input_data.get('tool_name', 'unknown')
    print(f"[POST-TOOL] Completed: {tool_name}")
    return {}

async def user_prompt_modifier(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: HookContext
) -> dict[str, Any]:
    """Add context to user prompts."""
    original_prompt = input_data.get('prompt', '')

    # Add timestamp to all prompts
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'updatedPrompt': f"[{timestamp}] {original_prompt}"
        }
    }

async def main():
    options = ClaudeAgentOptions(
        hooks={
            'PreToolUse': [
                HookMatcher(hooks=[pre_tool_logger]),
                HookMatcher(matcher='Bash', hooks=[pre_tool_logger])
            ],
            'PostToolUse': [
                HookMatcher(hooks=[post_tool_logger])
            ],
            'UserPromptSubmit': [
                HookMatcher(hooks=[user_prompt_modifier])
            ]
        },
        allowed_tools=["Read", "Write", "Bash"]
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query("List files in current directory")

        async for message in client.receive_response():
            # Hooks will automatically log tool usage
            pass

asyncio.run(main())
￼
Copy link to clipboard
实时进度监控
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ToolUseBlock,
    ToolResultBlock,
    TextBlock
)
import asyncio

async def monitor_progress():
    options = ClaudeAgentOptions(
        allowed_tools=["Write", "Bash"],
        permission_mode="acceptEdits"
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "Create 5 Python files with different sorting algorithms"
        )

        # Monitor progress in real-time
        files_created = []
        async for message in client.receive_messages():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        if block.name == "Write":
                            file_path = block.input.get("file_path", "")
                            print(f"🔨 Creating: {file_path}")
                    elif isinstance(block, ToolResultBlock):
                        print(f"✅ Completed tool execution")
                    elif isinstance(block, TextBlock):
                        print(f"💭 Claude says: {block.text[:100]}...")

            # Check if we've received the final result
            if hasattr(message, 'subtype') and message.subtype in ['success', 'error']:
                print(f"\n🎯 Task completed!")
                break

asyncio.run(monitor_progress())
￼
Copy link to clipboard
使用示例
Copy link to clipboard
基本文件操作（使用 query）
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ToolUseBlock
import asyncio

async def create_project():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Bash"],
        permission_mode='acceptEdits',
        cwd="/home/user/project"
    )

    async for message in query(
        prompt="Create a Python project structure with setup.py",
        options=options
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    print(f"Using tool: {block.name}")

asyncio.run(create_project())
￼
Copy link to clipboard
错误处理
from claude_agent_sdk import (
    query,
    CLINotFoundError,
    ProcessError,
    CLIJSONDecodeError
)

try:
    async for message in query(prompt="Hello"):
        print(message)
except CLINotFoundError:
    print("Please install Claude Code: npm install -g @anthropic-ai/claude-code")
except ProcessError as e:
    print(f"Process failed with exit code: {e.exit_code}")
except CLIJSONDecodeError as e:
    print(f"Failed to parse response: {e}")
￼
Copy link to clipboard
使用客户端的流式模式
from claude_agent_sdk import ClaudeSDKClient
import asyncio

async def interactive_session():
    async with ClaudeSDKClient() as client:
        # Send initial message
        await client.query("What's the weather like?")

        # Process responses
        async for msg in client.receive_response():
            print(msg)

        # Send follow-up
        await client.query("Tell me more about that")

        # Process follow-up response
        async for msg in client.receive_response():
            print(msg)

asyncio.run(interactive_session())
￼
Copy link to clipboard
使用 ClaudeSDKClient 的自定义工具
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server,
    AssistantMessage,
    TextBlock
)
import asyncio
from typing import Any

# Define custom tools with @tool decorator
@tool("calculate", "Perform mathematical calculations", {"expression": str})
async def calculate(args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = eval(args["expression"], {"__builtins__": {}})
        return {
            "content": [{
                "type": "text",
                "text": f"Result: {result}"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error: {str(e)}"
            }],
            "is_error": True
        }

@tool("get_time", "Get current time", {})
async def get_time(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "content": [{
            "type": "text",
            "text": f"Current time: {current_time}"
        }]
    }

async def main():
    # Create SDK MCP server with custom tools
    my_server = create_sdk_mcp_server(
        name="utilities",
        version="1.0.0",
        tools=[calculate, get_time]
    )

    # Configure options with the server
    options = ClaudeAgentOptions(
        mcp_servers={"utils": my_server},
        allowed_tools=[
            "mcp__utils__calculate",
            "mcp__utils__get_time"
        ]
    )

    # Use ClaudeSDKClient for interactive tool usage
    async with ClaudeSDKClient(options=options) as client:
        await client.query("What's 123 * 456?")

        # Process calculation response
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Calculation: {block.text}")

        # Follow up with time query
        await client.query("What time is it now?")

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Time: {block.text}")

asyncio.run(main())
￼
Copy link to clipboard
另请参阅
•
Python SDK 指南 - 教程和示例
•
SDK 概述 - 常规 SDK 概念
•
TypeScript SDK 参考 - TypeScript SDK 文档
•
CLI 参考 - 命令行界面
•
常见工作流 - 分步指南