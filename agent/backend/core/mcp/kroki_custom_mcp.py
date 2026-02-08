"""
Kroki 图表渲染工具
"""
import json
import logging
import re
import time
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

logger = logging.getLogger(__name__)

_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _normalize_format(format_value: str) -> str | None:
    fmt = (format_value or "svg").strip().lower()
    if fmt not in {"svg", "png", "pdf"}:
        return None
    return fmt


def _normalize_diagram_type(diagram_type: str) -> str | None:
    dtype = (diagram_type or "").strip().lower()
    if not dtype:
        return None
    if not _TYPE_RE.match(dtype):
        return None
    return dtype


@tool(
    name="kroki_render",
    description=(
        "使用 Kroki 将图表源码渲染为图片/PDF。必须传 output_path 保存文件，严禁读取图片内容回显。参数："
        "diagram(图表源码，可选)、diagram_path(图表文本路径，可选)、"
        "diagram_type(必填，常用: mermaid/plantuml/graphviz/excalidraw/drawio；"
        "亦可使用 Kroki 支持的其他类型)。"
        "提示：若需要 AWS 图标，推荐 diagram_type=plantuml 并使用 PlantUML 标准库的 awslib。"
        "若使用 PlantUML 手绘风格，请在源码顶部加：!option handwritten true。"
        "手绘风格：diagram_type=excalidraw，仅支持 svg 输出；diagram/diagram_path 传 .excalidraw JSON（可从 Excalidraw 导出）。"
        "format(svg/png/pdf，默认svg)、"
        "output_path(保存路径，必填)。"
        "diagram 与 diagram_path 二选一，若都提供优先 diagram。"
        "注意：禁止读取/回显生成的图片内容或base64，仅允许查看文件大小或返回路径。"
        "示例: diagram_type=mermaid, diagram='graph TD; A-->B', output_path='outputs/a.svg'。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "diagram": {"type": "string"},
            "diagram_path": {"type": "string"},
            "diagram_type": {"type": "string"},
            "format": {"type": "string"},
            "output_path": {"type": "string"},
        },
        "required": ["diagram_type", "output_path"],
        "anyOf": [
            {"required": ["diagram"]},
            {"required": ["diagram_path"]},
        ],
    }
)
async def kroki_render(args: dict) -> dict:
    start_time = time.time()
    diagram = args.get("diagram") or ""
    diagram_inline = bool(diagram.strip())
    diagram_path = (args.get("diagram_path") or "").strip()
    if not diagram_inline:
        if not diagram_path:
            return {"content": [{"type": "text", "text": "请提供 diagram 或 diagram_path"}]}
        try:
            diagram = Path(diagram_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"content": [{"type": "text", "text": f"diagram_path 不存在: {diagram_path}"}]}
        except OSError as exc:
            return {"content": [{"type": "text", "text": f"读取 diagram_path 失败: {exc}"}]}

    dtype = _normalize_diagram_type(args.get("diagram_type"))
    if not dtype:
        return {"content": [{"type": "text", "text": "diagram_type 仅支持字母/数字/-/_ 组合"}]}

    fmt = _normalize_format(args.get("format", "svg"))
    if not fmt:
        return {"content": [{"type": "text", "text": "format 仅支持 svg/png/pdf"}]}
    if dtype == "excalidraw" and fmt != "svg":
        return {"content": [{"type": "text", "text": "excalidraw 仅支持 svg 输出，请将 format 设为 svg"}]}

    output_path = (args.get("output_path") or "").strip()
    if not output_path:
        return {"content": [{"type": "text", "text": "请提供 output_path（必须落盘；不要读取图片内容回显）"}]}

    import httpx
    from ..system.config import KROKI_URL

    endpoint = f"{KROKI_URL.rstrip('/')}/{dtype}/{fmt}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(endpoint, content=diagram.encode("utf-8"), headers={"Content-Type": "text/plain"})
        resp.raise_for_status()
        content = resp.content
    elapsed = time.time() - start_time
    logger.info("kroki_render: type=%s format=%s size=%s bytes elapsed=%.3fs", dtype, fmt, len(content), elapsed)

    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    saved_source_path = None
    if diagram_inline:
        source_file = path.with_suffix(".txt")
        source_file.write_text(diagram, encoding="utf-8")
        saved_source_path = str(source_file)

    payload = {
        "diagram_type": dtype,
        "format": fmt,
        "content_type": resp.headers.get("content-type", "application/octet-stream"),
        "size_bytes": len(content),
        "saved_path": str(path.resolve()),
        "saved_source_path": saved_source_path,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True)}]}


kroki_mcp = create_sdk_mcp_server(
    name="kroki-render",
    version="1.0.0",
    tools=[kroki_render]
)
