"""
Resource panel API (per-user).
"""

import os
import re
import time
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agent.backend.core.auth.auth_filter import get_current_user_id
from agent.backend.core.agent.agent_manager import get_user_work_base_dir
from agent.backend.core.firewall.firewall_bash import is_firewall_enabled
from agent.backend.core.system import config

router = APIRouter(prefix="/api/v1/resource_panel", tags=["resource_panel"])

_PID_RE = re.compile(r"pid=(\d+)")


def _is_windows() -> bool:
    """判断当前是否为 Windows 环境"""
    return os.name == 'nt' or sys.platform.startswith('win')


def _get_windows_default_status(user_id: str) -> Dict[str, Any]:
    """
    Windows 环境下返回空的资源状态数据
    """
    base_dir = get_user_work_base_dir(user_id)

    return {
        "firewall_enabled": False,
        "timestamp": int(time.time()),
        "workspace": str(base_dir),
        "threads": {
            "current": 0,
            "max": 0,
        },
        "memory": {
            "current_bytes": 0,
            "max_bytes": 0,
        },
        "disk": {
            "bytes": 0,
        },
        "cpu": {
            "usage_usec": 0,
        },
        "disk_stats": {
            "reads_completed": 0,
            "writes_completed": 0,
            "read_bytes": 0,
            "write_bytes": 0,
        },
        "jobs": [],
        "platform": "windows",
    }


def _run_command(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _linux_user(user_id: str) -> str:
    from agent.backend.core.firewall.firewall_bash import _to_linux_user  # type: ignore
    return _to_linux_user(user_id)


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _read_cpu_usage_usec(path: Path) -> int | None:
    try:
        data = path.read_text().splitlines()
        for line in data:
            if line.startswith("usage_usec"):
                return int(line.split()[1])
    except Exception:
        return None
    return None


def _read_diskstats() -> Dict[str, int]:
    """Aggregate disk stats from /proc/diskstats."""
    try:
        device_names = {
            p.name
            for p in Path("/sys/block").iterdir()
            if p.is_dir() and not p.name.startswith(("loop", "ram"))
        }
    except Exception:
        device_names = set()

    stats = {
        "reads_completed": 0,
        "writes_completed": 0,
        "read_bytes": 0,
        "write_bytes": 0,
    }

    try:
        for line in Path("/proc/diskstats").read_text().splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            if device_names and name not in device_names:
                continue
            reads_completed = int(parts[3])
            sectors_read = int(parts[5])
            writes_completed = int(parts[7])
            sectors_written = int(parts[9])
            stats["reads_completed"] += reads_completed
            stats["writes_completed"] += writes_completed
            stats["read_bytes"] += sectors_read * 512
            stats["write_bytes"] += sectors_written * 512
    except Exception:
        pass
    return stats


def _list_pids(cgroup_path: Path) -> List[int]:
    procs_path = cgroup_path / "cgroup.procs"
    try:
        return [int(p) for p in procs_path.read_text().split()]
    except Exception:
        return []


def _pid_cmdline(pid: int) -> str:
    try:
        data = Path(f"/proc/{pid}/cmdline").read_text()
        parts = [p for p in data.split("\x00") if p]
        return " ".join(parts) if parts else f"pid {pid}"
    except Exception:
        return f"pid {pid}"


def _pid_threads(pid: int) -> int:
    try:
        return len(list((Path(f"/proc/{pid}/task")).iterdir()))
    except Exception:
        return 0


def _ports_by_pid() -> Dict[int, List[str]]:
    ports: Dict[int, List[str]] = {}
    for cmd in (["ss", "-lntpH"], ["ss", "-lunpH"]):
        result = _run_command(cmd)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            pid_matches = _PID_RE.findall(line)
            if not pid_matches:
                continue
            port = line.split()[3].split(":")[-1]
            for pid_str in pid_matches:
                pid = int(pid_str)
                ports.setdefault(pid, [])
                if port not in ports[pid]:
                    ports[pid].append(port)
    return ports


def _list_jobs(linux_user: str) -> List[Dict[str, Any]]:
    result = _run_command(
        ["systemctl", "list-units", f"job-{linux_user}-*", "--no-legend", "--plain"]
    )
    if result.returncode != 0:
        return []
    ports_map = _ports_by_pid()
    jobs: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        active_state = parts[2] if len(parts) > 2 else "unknown"
        cg = _run_command(["systemctl", "show", unit, "-p", "ControlGroup", "--value"])
        cgroup = cg.stdout.strip()
        if not cgroup:
            continue
        cgroup_path = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
        pids = _list_pids(cgroup_path)
        cmd = _pid_cmdline(pids[0]) if pids else unit
        mem_bytes = _read_int(cgroup_path / "memory.current") or 0
        mem_mb = round(mem_bytes / 1024 / 1024, 1) if mem_bytes else 0
        cpu_usage_usec = _read_cpu_usage_usec(cgroup_path / "cpu.stat") or 0
        thread_count = sum(_pid_threads(pid) for pid in pids)
        ports = sorted({p for pid in pids for p in ports_map.get(pid, [])})
        jobs.append(
            {
                "unit": unit,
                "command": cmd,
                "ports": ports,
                "memory_mb": mem_mb,
                "cpu_usage_usec": cpu_usage_usec,
                "threads": thread_count,
                "status": active_state,
            }
        )
    return jobs


@router.post("/stop")
async def stop_job(
    unit: str,
    user_id: str = Query(...),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    # Windows 环境下不支持停止 job
    if _is_windows():
        return {
            "success": False,
            "message": "Windows 环境下不支持此操作",
            "platform": "windows"
        }

    linux_user = _linux_user(user_id)
    if not unit.startswith(f"job-{linux_user}-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法任务标识",
        )

    result = _run_command(["systemctl", "kill", unit])
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="停止任务失败",
        )
    return {"success": True}


@router.get("/status")
async def get_resource_status(
    user_id: str = Query(...),
    current_user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户身份验证失败",
        )

    # Windows 环境下返回默认数据
    if _is_windows():
        return _get_windows_default_status(user_id)

    linux_user = _linux_user(user_id)
    base_dir = get_user_work_base_dir(user_id)
    slice_path = Path(f"/sys/fs/cgroup/user.slice/user-{linux_user}.slice")

    memory_current = _read_int(slice_path / "memory.current") or 0
    memory_max = _read_int(slice_path / "memory.max") or 0
    pids_current = _read_int(slice_path / "pids.current") or 0
    pids_max = _read_int(slice_path / "pids.max") or 0
    cpu_usage_usec = _read_cpu_usage_usec(slice_path / "cpu.stat") or 0
    disk_stats = _read_diskstats()

    disk_bytes = 0
    du = _run_command(["du", "-sb", str(base_dir)])
    if du.returncode == 0 and du.stdout.strip():
        try:
            disk_bytes = int(du.stdout.split()[0])
        except Exception:
            pass

    jobs = _list_jobs(linux_user)

    return {
        "firewall_enabled": is_firewall_enabled(),
        "timestamp": int(time.time()),
        "workspace": str(base_dir),
        "threads": {
            "current": pids_current,
            "max": pids_max,
        },
        "memory": {
            "current_bytes": memory_current,
            "max_bytes": memory_max,
        },
        "disk": {
            "bytes": disk_bytes,
        },
        "cpu": {
            "usage_usec": cpu_usage_usec,
        },
        "disk_stats": disk_stats,
        "jobs": jobs,
        "platform": "linux",  # 标识平台
    }
