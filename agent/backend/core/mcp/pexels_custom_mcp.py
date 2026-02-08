"""
Pexels 多媒体资源 SDK MCP 服务器
在 Agent 进程内运行，无需独立进程
"""
import itertools
from claude_agent_sdk import create_sdk_mcp_server, tool

_key_pool = None


def get_next_key() -> str:
    """获取下一个 API key（轮询）"""
    global _key_pool
    if _key_pool is None:
        from ..system.config import PEXELS_API_KEYS
        _key_pool = itertools.cycle(PEXELS_API_KEYS)
    return next(_key_pool)


async def fetch_pexels(endpoint: str, params: dict) -> dict:
    """请求 Pexels API"""
    import httpx
    headers = {"Authorization": get_next_key()}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(endpoint, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


def format_photo(item: dict) -> str:
    """格式化单张图片信息"""
    src = item.get("src") or {}
    return (
        f"📷 {item.get('id')} | {item.get('photographer')}\n"
        f"   预览: {src.get('medium')}\n"
        f"   高清: {src.get('large2x') or src.get('large')}\n"
        f"   原图: {src.get('original')}\n"
        f"   来源: {item.get('url')}"
    )


def _pick_best_video_file(files: list) -> dict:
    if not files:
        return {}
    return max(files, key=lambda f: f.get("width") or 0)


def format_video(item: dict) -> str:
    """格式化单个视频信息"""
    best = _pick_best_video_file(item.get("video_files") or [])
    return (
        f"🎬 {item.get('id')} | {item.get('duration')}秒\n"
        f"   预览: {item.get('image')}\n"
        f"   视频: {best.get('link')}\n"
        f"   来源: {item.get('url')}"
    )


async def _search_pexels_photos_impl(q: str, per_page: int, orientation: str, size: str) -> dict:
    per_page = max(3, min(per_page, 80))
    params = {"query": q, "per_page": per_page}
    if orientation:
        params["orientation"] = orientation
    if size:
        params["size"] = size
    data = await fetch_pexels("https://api.pexels.com/v1/search", params)
    photos = data.get("photos", [])
    if not photos:
        return {"content": [{"type": "text", "text": f"未找到图片: {q}"}]}
    result = [f"🔍 找到 {data.get('total_results', 0)} 张图片\n"]
    for item in photos[:per_page]:
        result.append(format_photo(item))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}

async def _curated_pexels_photos_impl(per_page: int, page: int) -> dict:
    per_page = max(3, min(per_page, 80))
    page = max(1, min(page, 1000))
    params = {"per_page": per_page, "page": page}
    data = await fetch_pexels("https://api.pexels.com/v1/curated", params)
    photos = data.get("photos", [])
    if not photos:
        return {"content": [{"type": "text", "text": "未找到精选图片"}]}
    result = [f"✨ 精选图片 {len(photos)} 张\n"]
    for item in photos[:per_page]:
        result.append(format_photo(item))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="pexels_search_photos",
    description=(
        "从 Pexels 免费图库搜索图片。返回预览、高清、原图链接等信息。"
        "参数：q(搜索关键词)、per_page(返回数量，3-80，默认20)、"
        "orientation(方向：landscape/portrait/square，可选)、size(尺寸：large/medium/small，可选)"
    ),
    input_schema={"q": str, "per_page": int, "orientation": str, "size": str}
)
async def search_photos(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    orientation = args.get("orientation", "")
    size = args.get("size", "")
    return await _search_pexels_photos_impl(q, per_page, orientation, size)

@tool(
    name="pexels_curated_photos",
    description=(
        "获取 Pexels 官方精选图片（curated）。"
        "参数：per_page(返回数量，3-80，默认20)、page(页码，默认1)"
    ),
    input_schema={"per_page": int, "page": int}
)
async def curated_photos(args: dict) -> dict:
    per_page = args.get("per_page", 20)
    page = args.get("page", 1)
    return await _curated_pexels_photos_impl(per_page, page)


async def _search_pexels_videos_impl(q: str, per_page: int) -> dict:
    per_page = max(3, min(per_page, 80))
    params = {"query": q, "per_page": per_page}
    data = await fetch_pexels("https://api.pexels.com/videos/search", params)
    videos = data.get("videos", [])
    if not videos:
        return {"content": [{"type": "text", "text": f"未找到视频: {q}"}]}
    result = [f"🔍 找到 {data.get('total_results', 0)} 个视频\n"]
    for item in videos[:per_page]:
        result.append(format_video(item))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}

async def _popular_pexels_videos_impl(per_page: int, page: int) -> dict:
    per_page = max(3, min(per_page, 80))
    page = max(1, min(page, 1000))
    params = {"per_page": per_page, "page": page}
    data = await fetch_pexels("https://api.pexels.com/videos/popular", params)
    videos = data.get("videos", [])
    if not videos:
        return {"content": [{"type": "text", "text": "未找到热门视频"}]}
    result = [f"🔥 热门视频 {len(videos)} 个\n"]
    for item in videos[:per_page]:
        result.append(format_video(item))
    return {"content": [{"type": "text", "text": "\n".join(result)}]}


@tool(
    name="pexels_search_videos",
    description=(
        "从 Pexels 视频库搜索视频。返回预览、视频链接等信息。"
        "参数：q(搜索关键词)、per_page(返回数量，3-80，默认20)"
    ),
    input_schema={"q": str, "per_page": int}
)
async def search_videos(args: dict) -> dict:
    q = args.get("q", "")
    per_page = args.get("per_page", 20)
    return await _search_pexels_videos_impl(q, per_page)

@tool(
    name="pexels_popular_videos",
    description=(
        "获取 Pexels 热门视频（popular）。"
        "参数：per_page(返回数量，3-80，默认20)、page(页码，默认1)"
    ),
    input_schema={"per_page": int, "page": int}
)
async def popular_videos(args: dict) -> dict:
    per_page = args.get("per_page", 20)
    page = args.get("page", 1)
    return await _popular_pexels_videos_impl(per_page, page)

pexels_mcp = create_sdk_mcp_server(
    name="pexels-media",
    version="1.0.0",
    tools=[
        search_photos,
        curated_photos,
        search_videos,
        popular_videos,
    ]
)
