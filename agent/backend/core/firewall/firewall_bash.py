"""Linux cgroup-based user firewall helpers."""

import asyncio
import importlib
import inspect
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from ..system import config
from ..db.dbutil import DatabaseUtil
import psycopg2.extras

logger = logging.getLogger(__name__)
LINUX_USER_PREFIX = config.LINUX_USER_PREFIX
USER_ID_PATTERN = re.compile(r"userid_([^/\\\\]+)")
FIREWALL_ENV_KEY = "FIREWALL_ENABLED"
db = DatabaseUtil()


def is_firewall_enabled() -> bool:
    """从配置文件检查防火墙是否启用"""
    return config.is_firewall_enabled()


def _to_linux_user(user_id: str) -> str:
    """Map UUID-style user_id to a valid Linux username."""
    safe = "".join(ch for ch in user_id.lower() if ch.isalnum())
    return f"{LINUX_USER_PREFIX}{safe[:16]}"


def _extract_user_id(work_dir: str) -> str | None:
    match = USER_ID_PATTERN.search(work_dir)
    if not match:
        return None
    return match.group(1)


def _resolve_user_workspace(work_dir: str, user_id: str | None) -> str:
    if not user_id:
        return work_dir
    base_dir = config.get_work_base_dir()
    return str(base_dir / f"userid_{user_id}")


def _wrap_bash_command(command: str, linux_user: str, work_dir: str) -> str:
    job_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
    unit = f"job-{linux_user}-{job_id}"
    return (
        f"sudo chown -R {shlex.quote(linux_user)}:{shlex.quote(linux_user)} {shlex.quote(work_dir)} && "
        f"sudo systemd-run --scope --slice=user-{shlex.quote(linux_user)}.slice "
        f"--unit={shlex.quote(unit)} "
        f"--working-directory={shlex.quote(work_dir)} "
        f"--uid={shlex.quote(linux_user)} --gid={shlex.quote(linux_user)} --quiet "
        f"bash -lc {shlex.quote(command)}"
    )


def _port_range_hint(username: str | None, port_start: int, port_end: int) -> str:
    slug_user = username or "<username>"
    return (
        f"只允许使用端口 {port_start}-{port_end}（共{config.USER_PORT_BLOCK_SIZE}个端口）。"
        "启动或关闭服务只能使用该范围端口。服务启动成功后请务必提示用户访问否则会出错："
        f"{config.PUBLIC_BASE_URL}/agent/{slug_user}-<port>"
    )


def _extract_port_from_command(command: str) -> int | None:
    patterns = [
        r"--port(?:=|\s+)(\d{2,5})",
        r"-p(?:=|\s+)(\d{2,5})",
        r":(\d{2,5})(?:/|\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            port = int(match.group(1))
            if 1 <= port <= 65535:
                return port
    return None


def _get_user_port_range(user_id: str) -> tuple[int, int] | None:
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT port_start, port_end FROM user_set WHERE user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return int(row["port_start"]), int(row["port_end"])
    finally:
        conn.close()


def _get_username(user_id: str) -> str | None:
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return row["username"] if row else None
    finally:
        conn.close()


def _get_user_storage_quota(user_id: str) -> int | None:
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT storage_quota_bytes FROM user_set WHERE user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        return int(row["storage_quota_bytes"]) if row else None
    finally:
        conn.close()


def _get_user_workspace_size_bytes(user_id: str) -> int | None:
    if os.name == "nt":
        return None
    base_dir = config.get_user_work_base_dir(user_id)
    try:
        result = subprocess.run(
            ["du", "-sb", str(base_dir)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return int(result.stdout.split()[0])
    except Exception:
        return None


def check_user_storage_quota(user_id: str) -> tuple[bool, int, int]:
    """Return (allowed, used_bytes, quota_bytes)."""
    if not is_firewall_enabled() or os.name == "nt":
        return True, 0, 0
    quota = _get_user_storage_quota(user_id)
    if quota is None:
        return True, 0, 0
    used = _get_user_workspace_size_bytes(user_id)
    if used is None:
        return True, 0, quota
    return used <= quota, used, quota


def ensure_user_settings(user_id: str) -> tuple[int, int]:
    """Ensure user_set exists and return assigned port range."""
    conn = db.get_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT port_start, port_end FROM user_set WHERE user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            return int(row["port_start"]), int(row["port_end"])

        cursor.execute("LOCK TABLE user_set IN EXCLUSIVE MODE")
        cursor.execute(
            "SELECT COALESCE(MAX(port_end), %s) AS max_end FROM user_set",
            (config.USER_PORT_POOL_START - 1,),
        )
        max_end = cursor.fetchone()["max_end"]
        port_start = max(int(max_end) + 1, config.USER_PORT_POOL_START)
        port_end = port_start + config.USER_PORT_BLOCK_SIZE - 1
        if port_end > config.USER_PORT_POOL_END:
            raise RuntimeError("用户端口池已用尽")

        cursor.execute(
            """
            INSERT INTO user_set
            (id, user_id, port_start, port_end, storage_quota_bytes, settings, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                port_start,
                port_end,
                config.USER_DEFAULT_STORAGE_QUOTA_BYTES,
                json.dumps({}),
            ),
        )
        conn.commit()
        return port_start, port_end
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _nft_available() -> bool:
    try:
        result = subprocess.run(
            ["sh", "-c", "command -v nft"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_root_block_device() -> str | None:
    try:
        result = subprocess.run(
            ["findmnt", "-no", "SOURCE", "/"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        source = result.stdout.strip()
        if not source.startswith("/dev/"):
            return None
        parent = subprocess.run(
            ["lsblk", "-no", "PKNAME", source],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        if parent:
            return f"/dev/{parent}"
        return source
    except Exception:
        return None


def _apply_user_io_limits(linux_user: str) -> None:
    read_limit = (config.USER_IO_READ_BW_LIMIT or "").strip()
    write_limit = (config.USER_IO_WRITE_BW_LIMIT or "").strip()
    if not read_limit and not write_limit:
        return
    device = _get_root_block_device()
    if not device:
        logger.warning("firewall: unable to resolve root device for IO limits")
        return

    props = []
    if read_limit:
        props.append(f"IOReadBandwidthMax={device} {read_limit}")
    if write_limit:
        props.append(f"IOWriteBandwidthMax={device} {write_limit}")
    if not props:
        return

    _run_command(
        ["sudo", "systemctl", "set-property", f"user-{linux_user}.slice", *props],
        check=False,
    )


def _apply_user_port_firewall(linux_user: str, port_start: int, port_end: int) -> None:
    """Best-effort nftables rule to allow only the assigned port range."""
    if not _nft_available():
        logger.warning("firewall: nft not available, skip port rules for %s", linux_user)
        return

    table = "queenbee_ports"
    chain = "user_ports"
    port_range = f"{port_start}-{port_end}"
    rules = [
        ["sudo", "nft", "add", "table", "inet", table],
        [
            "sudo",
            "nft",
            "add",
            "chain",
            "inet",
            table,
            chain,
            "{",
            "type",
            "filter",
            "hook",
            "input",
            "priority",
            "0",
            ";",
            "policy",
            "accept",
            ";",
            "}",
        ],
        [
            "sudo",
            "nft",
            "add",
            "rule",
            "inet",
            table,
            chain,
            "meta",
            "skuid",
            linux_user,
            "tcp",
            "dport",
            port_range,
            "accept",
        ],
        [
            "sudo",
            "nft",
            "add",
            "rule",
            "inet",
            table,
            chain,
            "meta",
            "skuid",
            linux_user,
            "ct",
            "state",
            "established,related",
            "accept",
        ],
        [
            "sudo",
            "nft",
            "add",
            "rule",
            "inet",
            table,
            chain,
            "meta",
            "skuid",
            linux_user,
            "tcp",
            "dport",
            "!=",
            port_range,
            "drop",
        ],
        [
            "sudo",
            "nft",
            "add",
            "rule",
            "inet",
            table,
            chain,
            "meta",
            "skuid",
            linux_user,
            "udp",
            "dport",
            "!=",
            port_range,
            "drop",
        ],
    ]
    for cmd in rules:
        _run_command(cmd, check=False)




def _is_allowed_wrapped_command(command: str, linux_user: str, work_dir: str) -> bool:
    try:
        parts = shlex.split(command)
    except Exception:
        parts = []

    def _has_required_workdir(cmd: str) -> bool:
        if not work_dir:
            return True
        workdir_snippet = f"cd {shlex.quote(work_dir)}"
        return "bash -lc" in cmd and workdir_snippet in cmd

    if parts and parts[0] == "time":
        parts = parts[1:]

    def has_systemd_run(tokens: list[str], start_idx: int) -> bool:
        if start_idx + 1 >= len(tokens):
            return False
        if tokens[start_idx] != "sudo" or tokens[start_idx + 1] != "systemd-run":
            return False
        try:
            scope_ok = "--scope" in tokens[start_idx + 2 :]
            slice_ok = f"--slice=user-{linux_user}.slice" in tokens[start_idx + 2 :]
            return scope_ok and slice_ok
        except Exception:
            return False

    # Direct prefix: sudo systemd-run ...
    if has_systemd_run(parts, 0):
        return _has_required_workdir(command)

    # Legacy prefix: sudo chown ... && sudo systemd-run ...
    for idx in range(len(parts) - 1):
        if parts[idx] == "sudo" and parts[idx + 1] == "systemd-run":
            if has_systemd_run(parts, idx):
                return _has_required_workdir(command)

    return False


def get_bash_isolation_prompt(work_dir: str) -> str:
    user_id = _extract_user_id(work_dir)
    linux_user = _to_linux_user(user_id) if user_id else None
    if os.name == "nt" or not linux_user:
        return ""
    port_hint = ""
    if user_id:
        try:
            username = _get_username(user_id)
            port_start, port_end = ensure_user_settings(user_id)
            port_hint = f"\n[IMPORTANT] {_port_range_hint(username, port_start, port_end)}\n"
        except Exception as exc:
            logger.warning("firewall: port hint unavailable (user_id=%s): %s", user_id, exc)
    template = _wrap_bash_command("<your_command>", linux_user, work_dir)
    return f"{config.FIREWALL_BASH_ISOLATION_PROMPT}{port_hint}"


def _allow_permission_result(updated_input: dict) -> dict:
    for module_name in ("claude_agent_sdk.permissions", "claude_agent_sdk"):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        allow_cls = getattr(mod, "PermissionResultAllow", None)
        if allow_cls:
            try:
                sig = inspect.signature(allow_cls)
                if "updatedInput" in sig.parameters:
                    return allow_cls(updatedInput=updated_input)
                if "input_data" in sig.parameters:
                    return allow_cls(updated_input)
            except Exception:
                pass
            try:
                return allow_cls()
            except Exception:
                pass
    return {"behavior": "allow", "updatedInput": updated_input}


def _is_path_allowed(path: str, allowed_dir: str) -> bool:
    """检查路径是否在允许的目录内"""
    if not path:
        return True
    try:
        abs_path = os.path.abspath(path)
        abs_allowed = os.path.abspath(allowed_dir)
        return os.path.commonpath([abs_path, abs_allowed]) == abs_allowed
    except Exception:
        return False


def build_tool_permission_handler(work_dir: str):
    if not is_firewall_enabled():
        async def _passthrough(tool_name: str, input_data: dict, context: dict) -> dict:
            return _allow_permission_result(dict(input_data or {}))
        return _passthrough
    user_id = _extract_user_id(work_dir)
    linux_user = _to_linux_user(user_id) if user_id else None
    user_workspace = _resolve_user_workspace(work_dir, user_id)
    bash_work_dir = work_dir

    async def _handler(tool_name: str, input_data: dict, context: dict) -> dict:
        updated_input = dict(input_data or {})
        resolved_tool = tool_name or updated_input.get("tool_name")
        if resolved_tool:
            logger.info("firewall : tool permission check %s", resolved_tool)
        logger.info("firewall: can_use_tool invoked (tool=%s)", resolved_tool or "unknown")

        # 限制 Read/Grep/Glob 只能访问工作目录
        if linux_user and resolved_tool in ("Read", "Grep", "Glob"):
            file_path = updated_input.get("file_path") or updated_input.get("path") or updated_input.get("pattern")
            if file_path:
                logger.info("firewall: path check (tool=%s, path=%s, workspace=%s)", resolved_tool, file_path, user_workspace)
                if not _is_path_allowed(str(file_path), user_workspace):
                    logger.warning("firewall: BLOCKED access outside workspace (tool=%s, path=%s, workspace=%s)", resolved_tool, file_path, user_workspace)
                    return {
                        "behavior": "deny",
                        "systemMessage": f"安全限制：只能访问工作目录 {user_workspace} 内的文件。",
                    }

        if (
            os.name != "nt"
            and resolved_tool == "Bash"
            and linux_user
            and updated_input.get("command")
        ):
            command = updated_input["command"]
            wrapped = _wrap_bash_command(
                command, linux_user, bash_work_dir
            )
            updated_input["command"] = wrapped
            logger.info(
                "firewall: bash wrapped (user_id=%s linux_user=%s) %s",
                user_id,
                linux_user,
                wrapped,
            )
        return _allow_permission_result(updated_input)

    return _handler


def build_tool_hooks(work_dir: str):
    if not is_firewall_enabled():
        return None
    try:
        from claude_agent_sdk import HookMatcher
    except Exception:
        return None

    user_id = _extract_user_id(work_dir)
    linux_user = _to_linux_user(user_id) if user_id else None
    user_workspace = _resolve_user_workspace(work_dir, user_id)
    bash_work_dir = work_dir
    port_hint = ""
    username = None
    port_start = None
    port_end = None
    if user_id:
        try:
            username = _get_username(user_id)
            port_start, port_end = ensure_user_settings(user_id)
            port_hint = _port_range_hint(username, port_start, port_end)
        except Exception as exc:
            logger.warning("firewall: port hint unavailable (user_id=%s): %s", user_id, exc)

    async def _pre_tool_logger(input_data: dict, tool_use_id, context) -> dict:
        tool_name = input_data.get("tool_name")
        if tool_name == "Bash":
            tool_input = input_data.get("tool_input") or {}
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            if command:
                logger.info("firewall: bash命令防火墙启动： %s", command)
                port = _extract_port_from_command(command)
                if os.name != "nt" and linux_user:
                    wrapped = _wrap_bash_command(command, linux_user, bash_work_dir)
                    tool_input = dict(tool_input)
                    tool_input["command"] = wrapped
                    logger.info(
                        "firewall: bash wrapped (hook user_id=%s linux_user=%s) %s",
                        user_id,
                        linux_user,
                        wrapped,
                    )
                    output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                            "updatedInput": tool_input,
                        }
                    }
                    if port_hint:
                        output["systemMessage"] = port_hint
                    return output
                if port and username:
                    return {
                        "systemMessage": (
                            f"服务启动成功后请提示用户访问："
                            f"{config.PUBLIC_BASE_URL}/agent/{username}-{port}"
                        )
                    }
                if port_hint:
                    return {"systemMessage": port_hint}
        return {}

    return {
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[_pre_tool_logger]),
        ]
    }


def _run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


async def ensure_user_firewall(user_id: str) -> None:
    """Initialize per-user Linux resources on first login."""
    if not is_firewall_enabled():
        return
    if os.name == "nt":
        logger.info("firewall: windows detected, skip (user_id=%s)", user_id)
        return

    try:
        stat = await asyncio.to_thread(
            _run_command, ["stat", "-fc", "%T", "/sys/fs/cgroup"]
        )
        if stat.stdout.strip() != "cgroup2fs":
            logger.warning(
                "firewall: cgroup v2 not detected (%s), skip (user_id=%s)",
                stat.stdout.strip(),
                user_id,
            )
            return
    except Exception as exc:
        logger.exception("firewall: cgroup check failed (user_id=%s): %s", user_id, exc)
        return

    linux_user = _to_linux_user(user_id)
    env_base = os.getenv("AGENT_WORK_BASE_DIR")
    base_dir = Path(env_base).expanduser() if env_base else Path("/home/queen")
    workspace_dir = base_dir / f"userid_{user_id}"
    logger.info(
        "firewall: workspace_dir=%s (user_id=%s linux_user=%s)",
        workspace_dir,
        user_id,
        linux_user,
    )

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["id", linux_user],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            logger.info("firewall: creating linux user %s", linux_user)
            # 创建统一的 qb_user 基础目录
            qb_base_dir = Path("/home/qb_user")
            await asyncio.to_thread(
                _run_command, ["sudo", "mkdir", "-p", str(qb_base_dir)]
            )
            # 使用 -d 指定家目录为 /home/qb_user/{user_id}
            user_home = qb_base_dir / user_id
            await asyncio.to_thread(
                _run_command,
                ["sudo", "useradd", "-m", "-s", "/bin/bash", "-d", str(user_home), linux_user],
            )
    except Exception as exc:
        logger.exception("firewall: user setup failed (user_id=%s): %s", user_id, exc)
        return

    try:
        await asyncio.to_thread(
            _run_command, ["sudo", "mkdir", "-p", str(workspace_dir)]
        )
        await asyncio.to_thread(
            _run_command,
            ["sudo", "chown", "-R", f"{linux_user}:{linux_user}", str(workspace_dir)],
        )
        await asyncio.to_thread(
            _run_command, ["sudo", "chmod", "700", str(workspace_dir)]
        )
        await asyncio.to_thread(
            _run_command,
            [
                "sudo",
                "systemctl",
                "set-property",
                f"user-{linux_user}.slice",
                f"MemoryMax={config.CGROUP_MEMORY_MAX}",
                f"TasksMax={config.CGROUP_TASKS_MAX}",
                f"CPUQuota={config.CGROUP_CPU_QUOTA}",
            ],
        )
        await asyncio.to_thread(_apply_user_io_limits, linux_user)
        try:
            port_start, port_end = ensure_user_settings(user_id)
            await asyncio.to_thread(
                _apply_user_port_firewall,
                linux_user,
                port_start,
                port_end,
            )
        except Exception as exc:
            logger.warning("firewall: port rules skipped (user_id=%s): %s", user_id, exc)
        logger.info("firewall: initialized (user_id=%s linux_user=%s)", user_id, linux_user)
    except Exception as exc:
        logger.exception("firewall: workspace/slice setup failed (user_id=%s): %s", user_id, exc)
        return
