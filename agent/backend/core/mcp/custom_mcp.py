"""
兼容旧路径的 MCP 导出入口
"""
from .pixabay_custom_mcp import pixabay_mcp
from .polyhaven_custom_mcp import polyhaven_mcp
from .lordicon_custom_mcp import lordicon_mcp
from .drawio_custom_mcp import drawio_mcp
from .kroki_custom_mcp import kroki_mcp
from .email_custom_mcp import email_mcp
from .pexels_custom_mcp import pexels_mcp
from .kbs_custom_mcp import kbs_mcp

__all__ = [
    "pixabay_mcp",
    "pexels_mcp",
    "polyhaven_mcp",
    "lordicon_mcp",
    "drawio_mcp",
    "kroki_mcp",
    "email_mcp",
    "kbs_mcp",
]
