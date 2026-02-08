import logging
import os
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
# 临时添加项目根目录到sys.path
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agent.backend.core.user.user_api import router as user_router
from agent.backend.core.agent.agent_api import router as agent_router
from agent.backend.core.user.relationship_api import router as relationship_router
from agent.backend.core.chat.chat_api import router as chat_router
from agent.backend.core.agent.agent_file_api import router as agent_file_router
from agent.backend.core.skills.skills_api import router as skills_router
from agent.backend.core.prompts.prompts_api import router as prompts_router
from agent.backend.core.kbs.kbs_api import router as kbs_router
from agent.backend.core.mcp.mcp_api import router as mcp_router
from agent.backend.core.resoure_panel.resoure_panel import router as resource_panel_router
from agent.backend.core.membership.sub_api import router as sub_router
from agent.backend.core.agent.agent_proxy_api import router as agent_proxy_router
from agent.backend.core.office.onlyoffice_api import router as onlyoffice_router
from agent.backend.core.system.logging_setup import setup_logging

setup_logging()
from agent.backend.core.db.init_db import check_and_init
from agent.backend.core.agent.agent_manager import get_user_work_base_dir
from agent.backend.core.scheduler import background_tasks

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print("正在检查数据库...")
    check_and_init()
    print("数据库检查完成！")

    print("正在启动后台任务...")
    background_tasks.start_background_tasks()
    print("后台任务已启动！")

    yield

    # 关闭时执行
    print("正在停止后台任务...")
    await background_tasks.stop_background_tasks()
    print("后台任务已停止")

    # 关闭数据库连接池
    from agent.backend.core.db.dbutil import DatabaseUtil
    print("正在关闭数据库连接池...")
    DatabaseUtil.close_all()
    print("数据库连接池已关闭")

class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=1200")
        return response


app = FastAPI(
    title="Queen Bee API",
    version="1.0.0",
    description="Queen Bee AI 智能体平台 API",
    lifespan=lifespan
)

# Suppress noisy access logs for chat sync polling to keep console clean.
sync_path_pattern = re.compile(r"/api/v1/chat/sessions/.+/sync")
resource_status_pattern = re.compile(r"/api/v1/resource_panel/status")


class _UvicornAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if sync_path_pattern.search(msg):
                return False
            if resource_status_pattern.search(msg):
                return False
        except Exception:
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(_UvicornAccessFilter())
# 关闭 uvicorn access 日志，避免刷屏
logging.getLogger("uvicorn.access").disabled = True

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 包含 API 路由
app.include_router(user_router, prefix="/api/v1")
app.include_router(chat_router)
app.include_router(agent_router, prefix="/api/v1/chat")
app.include_router(relationship_router, prefix="/api/v1/relationship")
# 单独添加群组路由，使其可以直接访问
app.include_router(relationship_router, prefix="/api/v1")
app.include_router(agent_file_router)
app.include_router(skills_router)
app.include_router(prompts_router)
app.include_router(kbs_router)
app.include_router(mcp_router)
app.include_router(resource_panel_router)
app.include_router(sub_router, prefix="/api/v1")
app.include_router(agent_proxy_router)
app.include_router(onlyoffice_router)

# 先定义路由，再挂载静态文件
# 这样路由优先级更高

# 根路径重定向到登录页面
@app.get("/")
async def root():
    """根路径，返回登录页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    login_path = os.path.join(ui_path, "login", "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"error": "Login page not found"}

# 登录页面路由
@app.get("/login")
async def login_page():
    """登录页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    login_path = os.path.join(ui_path, "login", "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"error": "Login page not found"}

# 聊天页面路由
@app.get("/chat")
async def chat_page():
    """聊天页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    chat_path = os.path.join(ui_path, "chat", "chat.html")
    if os.path.exists(chat_path):
        return FileResponse(chat_path)
    return {"error": "Chat page not found"}

# 技能页面路由
@app.get("/skills")
async def skills_page():
    """技能页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    skills_path = os.path.join(ui_path, "skills", "skills.html")
    if os.path.exists(skills_path):
        return FileResponse(skills_path)
    return {"error": "Skills page not found"}

# MCP 页面路由
@app.get("/mcp")
async def mcp_page():
    """MCP 管理页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    mcp_path = os.path.join(ui_path, "mcp", "mcp.html")
    if os.path.exists(mcp_path):
        return FileResponse(mcp_path)
    return {"error": "MCP page not found"}

# 资源面板页面路由
@app.get("/resource_panel")
async def resource_panel_page():
    """资源面板页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    panel_path = os.path.join(ui_path, "resource_panel", "resource_panel.html")
    if os.path.exists(panel_path):
        return FileResponse(panel_path)
    return {"error": "Resource panel page not found"}

# 订阅页面路由
@app.get("/sub_pro")
async def sub_pro_page():
    """订阅页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    sub_pro_path = os.path.join(ui_path, "sub_pro", "sub_pro.html")
    if os.path.exists(sub_pro_path):
        return FileResponse(sub_pro_path)
    return {"error": "Subscription page not found"}

# 管理员开通页面路由（需要密钥）
@app.get("/sub")
async def sub_admin_page(key: str = None):
    """管理员开通页面（需要密钥参数）"""
    SECRET_KEY = 'usyttnm-uygbmm776sw65doj-suucnnu997sdscerefghhhheedddtgfdl'

    if key != SECRET_KEY:
        return JSONResponse(
            status_code=403,
            content={"error": "访问被拒绝"}
        )

    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    sub_admin_path = os.path.join(ui_path, "sub_admin", "sub_admin.html")
    if os.path.exists(sub_admin_path):
        return FileResponse(sub_admin_path)
    return {"error": "Admin page not found"}

# 用户协议页面路由
@app.get("/terms/user-agreement")
async def user_agreement_page():
    """用户协议页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    agreement_path = os.path.join(ui_path, "terms", "user-agreement.html")
    if os.path.exists(agreement_path):
        return FileResponse(agreement_path)
    return {"error": "User agreement page not found"}

# 隐私政策页面路由
@app.get("/terms/privacy-policy")
async def privacy_policy_page():
    """隐私政策页面"""
    ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    policy_path = os.path.join(ui_path, "terms", "privacy-policy.html")
    if os.path.exists(policy_path):
        return FileResponse(policy_path)
    return {"error": "Privacy policy page not found"}

# 挂载静态文件目录
ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
if os.path.exists(ui_path):
    # 将ui目录挂载到/static路径
    app.mount("/static", CachedStaticFiles(directory=ui_path), name="static")

# 技能公共资源目录
skills_public_dir = get_user_work_base_dir("public").parent / "skills_public"
skills_public_dir.mkdir(parents=True, exist_ok=True)
app.mount("/skills_public", StaticFiles(directory=str(skills_public_dir)), name="skills_public")

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "database": "connected",
        "service": "queen_bee_api",
        "background_tasks": background_tasks.get_background_tasks_status()
    }

if __name__ == "__main__":
    import uvicorn
    print("启动 Queen Bee 服务...")
    print("访问地址: http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
