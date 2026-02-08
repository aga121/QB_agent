"""
Draw.io 导出工具
"""
import json
import logging
import time
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

logger = logging.getLogger(__name__)


def _normalize_drawio_format(format_value: str) -> str | None:
    fmt = (format_value or "png").strip().lower()
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt not in {"png", "jpg", "pdf", "svg"}:
        return None
    return fmt


@tool(
    name="drawio_export",
    description=(
        "将 draw.io XML 导出为图片/PDF。必须传 output_path 保存文件，严禁读取图片内容回显（只需查看大小）。"
        "优先使用 xml_path（先落盘再传路径更稳定）。参数："
        "xml(draw.io 源XML，可选)、xml_path(xml 文件路径，可选)、"
        "format(png/jpg/pdf/svg，默认png)、"
        "output_path(保存路径，必填)。"
        "xml 与 xml_path 二选一，若都提供优先 xml。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "xml": {"type": "string"},
            "xml_path": {"type": "string"},
            "format": {"type": "string"},
            "output_path": {"type": "string"},
        },
        "anyOf": [
            {"required": ["xml"]},
            {"required": ["xml_path"]},
        ],
    }
)
async def drawio_export(args: dict) -> dict:
    start_time = time.time()
    xml = args.get("xml") or ""
    xml_inline = bool(xml.strip())
    xml_path = (args.get("xml_path") or "").strip()
    if not xml_inline:
        if not xml_path:
            return {"content": [{"type": "text", "text": "请提供 draw.io XML 或 xml_path"}]}
        try:
            xml = Path(xml_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"content": [{"type": "text", "text": f"xml_path 不存在: {xml_path}"}]}
        except OSError as exc:
            return {"content": [{"type": "text", "text": f"读取 xml_path 失败: {exc}"}]}

    fmt = _normalize_drawio_format(args.get("format", "png"))
    if not fmt:
        return {"content": [{"type": "text", "text": "format 仅支持 png/jpg/pdf/svg"}]}

    output_path = (args.get("output_path") or "").strip()
    if not output_path:
        return {"content": [{"type": "text", "text": "请提供 output_path（必须落盘；不要读取图片内容回显）"}]}

    import httpx
    from ..system.config import DRAWIO_EXPORT_URL

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(DRAWIO_EXPORT_URL, data={"format": fmt, "xml": xml})
        resp.raise_for_status()
        content = resp.content
    elapsed = time.time() - start_time
    logger.info("drawio_export: format=%s size=%s bytes elapsed=%.3fs", fmt, len(content), elapsed)

    saved_xml_path = None
    if output_path:
        path = Path(output_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if xml_inline:
            xml_file = path.with_suffix(".xml")
            xml_file.write_text(xml, encoding="utf-8")
            saved_xml_path = str(xml_file)

    payload = {
        "format": fmt,
        "content_type": resp.headers.get("content-type", "application/octet-stream"),
        "size_bytes": len(content),
        "saved_path": str(Path(output_path).resolve()),
        "saved_xml_path": saved_xml_path,
        "xml": xml,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True)}]}


drawio_mcp = create_sdk_mcp_server(
    name="drawio-export",
    version="1.0.0",
    tools=[drawio_export]
)
