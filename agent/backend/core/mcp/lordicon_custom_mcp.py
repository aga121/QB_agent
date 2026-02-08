"""
Lordicon 动态图标工具
"""
from claude_agent_sdk import create_sdk_mcp_server, tool


async def fetch_lordicon(endpoint: str, params: dict = None) -> dict:
    """请求 Lordicon API"""
    import httpx
    from ..system.config import LORDICON_API_KEY

    url = f"https://api.lordicon.com{endpoint}"
    headers = {"Authorization": f"Bearer {LORDICON_API_KEY}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        if params:
            resp = await client.get(url, params=params, headers=headers)
        else:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def format_lordicon_icon(icon: dict) -> str:
    """格式化单个图标信息（精简版，节省上下文）"""
    premium_mark = "🔒" if icon.get("premium") else "✅"

    # 不返回完整 URL，只返回标识信息
    return (
        f"{icon.get('title')} | {icon.get('family')}/{icon.get('style')}:{icon.get('index')} | {premium_mark}"
    )


# 内部搜索函数（不被 @tool 包装，可被其他函数调用）
async def _search_lordicon_icons_impl(
    search: str,
    family: str,
    style: str,
    premium: bool,
    per_page: int
) -> dict:
    """Lordicon 图标搜索的内部实现"""
    params = {}
    if search:
        params["search"] = search
    if family:
        params["family"] = family
    if style:
        params["style"] = style
    if premium is not None:
        params["premium"] = "true" if premium else "false"
    if per_page:
        params["per_page"] = min(per_page, 100)

    data = await fetch_lordicon("/v1/icons", params)

    if not data:
        return {"content": [{"type": "text", "text": "未找到图标"}]}

    # 格式化返回（包含完整 URL）
    result = [f"🔍 找到 {len(data)} 个图标\n"]
    for i, icon in enumerate(data, 1):
        premium_mark = "🔒" if icon.get("premium") else "✅"
        files = icon.get("files", {})

        result.append(
            f"{i}. {icon.get('title')} | {icon.get('family')}/{icon.get('style')}:{icon.get('index')} | {premium_mark}"
        )
        if "json" in files:
            result.append(f"   JSON: {files['json']}")
        if "svg" in files:
            result.append(f"   SVG: {files['svg']}")
        if "preview" in files:
            result.append(f"   预览: {files['preview']}")

    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="lordicon_search_icons",
    description="从 Lordicon 搜索动态图标（仅免费图标）。支持多个家族和风格。参数：search(搜索关键词)、family(家族：system/wired，留空返回所有)、style(风格：regular/solid/flat/gradient/lineal/outline，留空返回所有)、per_page(返回数量，默认20，最大100)。建议：留空 family 和 style 参数查看所有图标",
    input_schema={"search": str, "family": str, "style": str, "per_page": int}
)
async def search_lordicon_icons(args: dict) -> dict:
    search = args.get("search", "")
    family = args.get("family", "")
    style = args.get("style", "")
    per_page = args.get("per_page", 20)
    return await _search_lordicon_icons_impl(search, family, style, False, per_page)


@tool(
    name="lordicon_search_system",
    description="搜索 Lordicon System 家族图标（简洁线条风格，仅免费）。参数：style(风格：regular/solid，留空返回所有)、search(搜索关键词)、per_page(返回数量，默认20)。建议：留空 style 参数查看所有风格",
    input_schema={"style": str, "search": str, "per_page": int}
)
async def search_lordicon_system(args: dict) -> dict:
    style = args.get("style", "")
    search = args.get("search", "")
    per_page = args.get("per_page", 20)
    return await _search_lordicon_icons_impl(search, "system", style, False, per_page)


@tool(
    name="lordicon_search_wired",
    description="搜索 Lordicon Wired 家族图标（丰富填充风格，仅免费）。参数：style(风格：flat/gradient/lineal/outline，留空返回所有)、search(搜索关键词)、per_page(返回数量，默认20)。建议：留空 style 参数查看所有风格",
    input_schema={"style": str, "search": str, "per_page": int}
)
async def search_lordicon_wired(args: dict) -> dict:
    style = args.get("style", "")
    search = args.get("search", "")
    per_page = args.get("per_page", 20)
    return await _search_lordicon_icons_impl(search, "wired", style, False, per_page)


@tool(
    name="lordicon_get_variants",
    description="获取 Lordicon 所有可用的图标家族和风格列表，包括免费和付费图标数量统计。无参数",
    input_schema={}
)
async def get_lordicon_variants(args: dict) -> dict:
    data = await fetch_lordicon("/v1/variants")

    if not data:
        return {"content": [{"type": "text", "text": "未找到图标家族信息"}]}

    result = ["🎨 Lordicon 图标家族和风格统计\n"]
    for variant in data:
        free_count = variant.get("free", 0)
        premium_count = variant.get("premium", 0)
        result.append(
            f"   {variant.get('family')}/{variant.get('style')}: "
            f"免费 {free_count} 个 | 付费 {premium_count} 个"
        )

    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="lordicon_free_only",
    description="搜索 Lordicon 仅免费图标（无需付费计划）。参数：search(搜索关键词)、family(家族：system/wired，留空返回所有)、style(风格)、per_page(返回数量，默认20)",
    input_schema={"search": str, "family": str, "style": str, "per_page": int}
)
async def search_lordicon_free(args: dict) -> dict:
    search = args.get("search", "")
    family = args.get("family", "")
    style = args.get("style", "")
    per_page = args.get("per_page", 20)
    return await _search_lordicon_icons_impl(search, family, style, False, per_page)


# 创建 Lordicon SDK MCP 服务器
lordicon_mcp = create_sdk_mcp_server(
    name="lordicon",
    version="1.0.0",
    tools=[
        search_lordicon_icons,
        search_lordicon_system,
        search_lordicon_wired,
        get_lordicon_variants,
        search_lordicon_free,
    ]
)
