"""
linux_tools.py — read-only Linux diagnostics.

Every function here only reads system state. Nothing here can restart a
service, kill a process, or modify anything — state-changing actions live
in approval.py behind an explicit propose/confirm flow instead.
"""

import subprocess


def _run(cmd: list) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "(command timed out)"
    except FileNotFoundError:
        return f"(command not found: {cmd[0]} — is this running on a Linux host?)"


def check_service_status(service_name: str) -> str:
    """Check whether a systemd service is active, and its recent state."""
    return _run(["systemctl", "status", service_name, "--no-pager"])


def get_service_logs(service_name: str, lines: int = 50) -> str:
    """Get recent journalctl logs for a systemd service."""
    return _run(["journalctl", "-u", service_name, "-n", str(lines), "--no-pager"])


def check_port(port: int) -> str:
    """Check what's listening on a given port."""
    return _run(["ss", "-tulpn"]) or _run(["netstat", "-tulpn"])


def check_disk_usage() -> str:
    """Check disk usage across mounted filesystems."""
    return _run(["df", "-h"])


def check_memory_usage() -> str:
    """Check system memory usage."""
    return _run(["free", "-h"])
