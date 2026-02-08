"""
Poly Haven 3D 素材工具
"""
from claude_agent_sdk import create_sdk_mcp_server, tool


async def fetch_polyhaven(endpoint: str, params: dict = None) -> dict:
    """请求 Poly Haven API（无需认证）"""
    import httpx
    url = f"https://api.polyhaven.com{endpoint}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if params:
            resp = await client.get(url, params=params)
        else:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def format_polyhaven_asset(asset_id: str, info: dict) -> str:
    """格式化 Poly Haven 资产信息"""
    asset_type = ["HDRI", "Texture", "Model"][info.get("type", 1)]
    categories = ", ".join(info.get("categories", [])[:3])
    tags = ", ".join(info.get("tags", [])[:3])
    downloads = info.get("download_count", 0)

    result = (
        f"🎨 {asset_id} | {asset_type}\n"
        f"   名称: {info.get('name', 'N/A')}\n"
        f"   分类: {categories}\n"
        f"   标签: {tags}\n"
        f"   下载: {downloads:,} 次\n"
        f"   缩略图: {info.get('thumbnail_url', 'N/A')}\n"
    )
    return result


# 内部搜索函数（不被 @tool 包装，可被其他函数调用）
async def _search_polyhaven_assets_impl(asset_type: str, categories: str, limit: int) -> dict:
    """Poly Haven 资产搜索的内部实现"""
    params = {}
    if asset_type != "all":
        params["type"] = asset_type
    if categories:
        params["categories"] = categories

    data = await fetch_polyhaven("/assets", params)

    if not data:
        return {"content": [{"type": "text", "text": "未找到资产"}]}

    # 按下载量排序（取前 limit 个）
    sorted_assets = sorted(
        data.items(),
        key=lambda x: x[1].get("download_count", 0),
        reverse=True
    )[:limit]

    result = [f"🔍 找到 {len(data)} 个资产，显示前 {len(sorted_assets)} 个\n"]
    for asset_id, info in sorted_assets:
        result.append(format_polyhaven_asset(asset_id, info))

    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="polyhaven_search_assets",
    description="从 Poly Haven 搜索 3D 资产。支持 HDRI 环境贴图、纹理贴图、3D 模型。参数：asset_type(hdris/textures/models/all，默认all)、categories(分类过滤，留空返回所有，常用：brick,wood,metal,fabric)、limit(返回数量，默认10)。注意：categories 留空可查看所有资产",
    input_schema={"asset_type": str, "categories": str, "limit": int}
)
async def search_polyhaven_assets(args: dict) -> dict:
    asset_type = args.get("asset_type", "all")
    categories = args.get("categories", "")
    limit = args.get("limit", 10)
    return await _search_polyhaven_assets_impl(asset_type, categories, limit)


@tool(
    name="polyhaven_search_hdris",
    description="搜索 Poly Haven HDRI 环境贴图。用于 3D 渲染的环境光照。参数：categories(分类过滤，留空返回所有，常用：outdoor,sky,indoor,night)、limit(返回数量，默认10)。建议：留空 categories 参数查看所有选项",
    input_schema={"categories": str, "limit": int}
)
async def search_hdris(args: dict) -> dict:
    categories = args.get("categories", "")
    limit = args.get("limit", 10)
    return await _search_polyhaven_assets_impl("hdris", categories, limit)


@tool(
    name="polyhaven_search_textures",
    description="搜索 Poly Haven 纹理贴图。包括颜色贴图、法线贴图、粗糙度贴图等。参数：categories(分类过滤，留空返回所有，常用：brick,wood,metal,fabric,ground)、limit(返回数量，默认10)。建议：留空 categories 参数查看所有选项",
    input_schema={"categories": str, "limit": int}
)
async def search_textures(args: dict) -> dict:
    categories = args.get("categories", "")
    limit = args.get("limit", 10)
    return await _search_polyhaven_assets_impl("textures", categories, limit)


@tool(
    name="polyhaven_search_models",
    description="搜索 Poly Haven 3D 模型。高质量 3D 资产，支持多种格式。参数：categories(分类过滤，留空返回所有)、limit(返回数量，默认10)。建议：留空 categories 参数查看所有选项",
    input_schema={"categories": str, "limit": int}
)
async def search_models(args: dict) -> dict:
    categories = args.get("categories", "")
    limit = args.get("limit", 10)
    return await _search_polyhaven_assets_impl("models", categories, limit)


@tool(
    name="polyhaven_get_download_links",
    description="获取 Poly Haven 资产的下载链接。返回不同分辨率和格式的所有下载链接。参数：asset_id(资产ID)、resolution(分辨率：1k/2k/4k/8k，默认4k)",
    input_schema={"asset_id": str, "resolution": str}
)
async def get_polyhaven_downloads(args: dict) -> dict:
    asset_id = args.get("asset_id", "")
    resolution = args.get("resolution", "4k")

    if not asset_id:
        return {"content": [{"type": "text", "text": "请提供 asset_id"}]}

    data = await fetch_polyhaven(f"/files/{asset_id}")

    if not data:
        return {"content": [{"type": "text", "text": f"未找到资产: {asset_id}"}]}

    # 提取指定分辨率的主要下载链接
    result = [f"📥 {asset_id} 下载链接 ({resolution}):\n"]

    for map_type, map_data in data.items():
        if resolution in map_data:
            result.append(f"\n📎 {map_type}:")
            for format_name, format_info in map_data[resolution].items():
                url = format_info.get("url", "N/A")
                size = format_info.get("size", 0)
                size_mb = f"{size/1024/1024:.1f}MB" if size else "N/A"
                result.append(f"   {format_name}: {url} ({size_mb})")

    return {"content": [{"type": "text", "text": "\n".join(result)}]}


# 创建 Poly Haven SDK MCP 服务器
polyhaven_mcp = create_sdk_mcp_server(
    name="polyhaven-3d",
    version="1.0.0",
    tools=[
        search_polyhaven_assets,
        search_hdris,
        search_textures,
        search_models,
        get_polyhaven_downloads,
    ]
)
