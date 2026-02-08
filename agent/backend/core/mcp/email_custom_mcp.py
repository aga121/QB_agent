"""SMTP email sender MCP."""
import json
import mimetypes
import smtplib
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..system import config


def _get_smtp_connection() -> smtplib.SMTP:
    if config.SMTP_USE_SSL:
        client = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
    else:
        client = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        if config.SMTP_USE_TLS:
            client.starttls()
    client.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
    return client


def _attach_file(msg: MIMEMultipart, file_path: Path) -> None:
    content_type, encoding = mimetypes.guess_type(str(file_path))
    if content_type is None or encoding is not None:
        content_type = "application/octet-stream"
    maintype, subtype = content_type.split("/", 1)

    with file_path.open("rb") as f:
        payload = f.read()

    part = MIMEBase(maintype, subtype)
    part.set_payload(payload)
    encoders.encode_base64(part)
    filename = Header(file_path.name, "utf-8").encode()
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)


@tool(
    name="发送",
    description=(
        "使用配置好的 SMTP 主账号发送邮件（content 为 HTML）。"
        "参数：to(收件邮箱)、content(邮件内容，默认HTML)、attachments(附件路径数组，可选)、"
        "subject(主题，可选)。附件必须是可访问的完整文件路径（例如 /home/queen/...）。"
        f"必须备注当前发送的agent名称注明是AI，及官网{config.PUBLIC_BASE_URL}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "content": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
        },
        "required": ["to", "content"],
    }
)
async def send_email(args: dict) -> dict:
    to_address = (args.get("to") or "").strip()
    content = args.get("content") or ""
    if not to_address or not content:
        return {"content": [{"type": "text", "text": "请提供收件邮箱和内容"}]}

    subject = (args.get("subject") or "Queen Bee 通知").strip()
    attachments = args.get("attachments") or []

    msg = MIMEMultipart()
    from_name = config.SMTP_FROM_NAME or config.SMTP_USERNAME
    msg["From"] = formataddr((from_name, config.SMTP_USERNAME))
    msg["To"] = to_address
    msg["Subject"] = Header(subject, "utf-8")

    msg.attach(MIMEText(content, "html", "utf-8"))

    for item in attachments:
        path = Path(item)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            return {"content": [{"type": "text", "text": f"附件不存在: {item}"}]}
        _attach_file(msg, path)

    try:
        client = _get_smtp_connection()
        client.sendmail(config.SMTP_USERNAME, [to_address], msg.as_string())
        client.quit()
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"发送失败: {exc}"}]}

    payload = {
        "to": to_address,
        "subject": subject,
        "attachments": len(attachments),
        "success": True,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True)}]}


email_mcp = create_sdk_mcp_server(
    name="send",
    version="1.0.0",
    tools=[send_email]
)
