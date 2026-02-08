"""
Pixabay 多媒体资源 SDK MCP 服务器
在 Agent 进程内运行，无需独立进程
"""
import itertools
from claude_agent_sdk import create_sdk_mcp_server, tool

# API key 轮询器
_key_pool = None


def get_next_key() -> str:
    """获取下一个 API key（轮询）"""
    global _key_pool
    if _key_pool is None:
        from ..system.config import PIXABAY_API_KEYS
        _key_pool = itertools.cycle(PIXABAY_API_KEYS)
    return next(_key_pool)


async def fetch_pixabay(endpoint: str, params: dict) -> dict:
    """请求 Pixabay API"""
    import httpx
    params["key"] = get_next_key()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(endpoint, params=params)
        resp.raise_for_status()
        return resp.json()


def format_image(hit: dict) -> str:
    """格式化单张图片信息"""
    return (
        f"📷 {hit.get('id')} | {hit.get('type')}\n"
        f"   标签: {hit.get('tags')}\n"
        f"   预览: {hit.get('previewURL')}\n"
        f"   网页: {hit.get('webformatURL')}\n"
        f"   作者: {hit.get('user')}\n"
        f"   来源: {hit.get('pageURL')}"
    )


def format_video(hit: dict) -> str:
    """格式化单个视频信息"""
    medium = hit.get("videos", {}).get("medium", {})
    return (
        f"🎬 {hit.get('id')} | {hit.get('type')} | {hit.get('duration')}秒\n"
        f"   标签: {hit.get('tags')}\n"
        f"   视频: {medium.get('url', 'N/A')}\n"
        f"   作者: {hit.get('user')}\n"
        f"   来源: {hit.get('pageURL')}"
    )


# ==================== 图片工具 ====================

# 内部搜索函数（不被 @tool 包装，可被其他函数调用）
async def _search_pixabay_images_impl(q: str, image_type: str, safesearch: str, per_page: int) -> dict:
    """Pixabay 图片搜索的内部实现"""
    # per_page 范围: 3-200
    per_page = max(3, min(per_page, 200))
    params = {
        "q": q,
        "image_type": image_type,
        "safesearch": safesearch,
        "per_page": per_page
    }
    data = await fetch_pixabay("https://pixabay.com/api/", params)
    hits = data.get("hits", [])

    if not hits:
        return {"content": [{"type": "text", "text": f"未找到图片: {q}"}]}

    result = [f"🔍 找到 {data.get('totalHits', 0)} 张图片\n"]
    for h in hits[:params["per_page"]]:
        result.append(format_image(h))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="pixabay_search_images",
    description="从 Pixabay 免费图库搜索图片。支持照片、插图、矢量图。返回图片的预览链接、下载链接、标签等信息。参数：q(搜索关键词)、image_type(图片类型：all/photo/illustration/vector)、safesearch(安全搜索：true/false)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "image_type": str, "safesearch": str, "per_page": int}
)
async def search_images(args: dict) -> dict:
    q = args.get("q", "")
    image_type = args.get("image_type", "all")
    safesearch = args.get("safesearch", "true")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_images_impl(q, image_type, safesearch, per_page)


@tool(
    name="pixabay_search_photos",
    description="搜索 Pixabay 照片资源。适用于需要真实照片的场景。参数：q(搜索关键词)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "per_page": int}
)
async def search_photos(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_images_impl(q, "photo", "true", per_page)


@tool(
    name="pixabay_search_illustrations",
    description="搜索 Pixabay 插图资源。适用于需要插画风格的场景。参数：q(搜索关键词)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "per_page": int}
)
async def search_illustrations(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_images_impl(q, "illustration", "true", per_page)


@tool(
    name="pixabay_search_vectors",
    description="搜索 Pixabay 矢量图资源。适用于需要可缩放图形的场景，如Logo、图标等。参数：q(搜索关键词)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "per_page": int}
)
async def search_vectors(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_images_impl(q, "vector", "true", per_page)


# ==================== 视频工具 ====================

# 内部搜索函数（不被 @tool 包装，可被其他函数调用）
async def _search_pixabay_videos_impl(q: str, video_type: str, per_page: int) -> dict:
    """Pixabay 视频搜索的内部实现"""
    # per_page 范围: 3-200
    per_page = max(3, min(per_page, 200))
    params = {
        "q": q,
        "video_type": video_type,
        "per_page": per_page
    }
    data = await fetch_pixabay("https://pixabay.com/api/videos/", params)
    hits = data.get("hits", [])

    if not hits:
        return {"content": [{"type": "text", "text": f"未找到视频: {q}"}]}

    result = [f"🔍 找到 {data.get('totalHits', 0)} 个视频\n"]
    for h in hits[:params["per_page"]]:
        result.append(format_video(h))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="pixabay_search_videos",
    description="从 Pixabay 免费视频库搜索视频。支持影片和动画。返回视频的下载链接、时长、分辨率等信息。参数：q(搜索关键词)、video_type(视频类型：all/film/animation)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "video_type": str, "per_page": int}
)
async def search_videos(args: dict) -> dict:
    q = args.get("q", "")
    video_type = args.get("video_type", "all")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_videos_impl(q, video_type, per_page)


@tool(
    name="pixabay_search_films",
    description="搜索 Pixabay 影片资源（实拍视频）。适用于需要真实拍摄素材的场景。参数：q(搜索关键词)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "per_page": int}
)
async def search_films(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_videos_impl(q, "film", per_page)


@tool(
    name="pixabay_search_animations",
    description="搜索 Pixabay 动画资源。适用于需要动画效果的场景。参数：q(搜索关键词)、per_page(返回数量，3-200，默认20)",
    input_schema={"q": str, "per_page": int}
)
async def search_animations(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pixabay_videos_impl(q, "animation", per_page)


# ==================== 创建 SDK MCP 服务器 ====================

pixabay_mcp = create_sdk_mcp_server(
    name="pixabay-media",
    version="1.0.0",
    tools=[
        search_images,
        search_photos,
        search_illustrations,
        search_vectors,
        search_videos,
        search_films,
        search_animations,
    ]
)
