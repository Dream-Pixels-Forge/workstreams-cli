"""Cross-terminal notifications (desktop + file-based for other workstreams)."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_log import default_log_dir

NOTIFY_SENDERS = [
    "notify-send",
    "terminal-notify",
]


class Notifier:
    """Send notifications to other terminals / desktops."""

    def __init__(self, project: str, log_dir: Optional[Path] = None):
        self.project = project
        self.notify_dir = Path(log_dir) if log_dir else default_log_dir(project)
        self.notify_dir.mkdir(parents=True, exist_ok=True)
        self.notify_file = self.notify_dir / "notifications.jsonl"

    def send(self, title: str, message: str, urgency: str = "normal") -> bool:
        """Send notification via desktop notification and file."""
        sent = False
        system = platform.system()

        if system == "Darwin":
            script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
            try:
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                sent = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif system == "Windows":
            # Windows: use PowerShell for desktop notification
            ps_script = (
                f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, {json.dumps(title)}, {json.dumps(message)}, 'Info')"
            )
            try:
                subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                sent = True
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            # Linux: notify-send. Use --transient + --expire-time so the
            # notification auto-dismisses instead of staying open. Critical
            # urgency notifications are modal/blocking by spec — downgrade
            # them and rely on expire-time so they don't pin forever.
            effective_urgency = "normal" if urgency == "critical" else urgency
            expire_ms = 15000 if urgency == "critical" else 8000
            cmd = [
                "notify-send",
                "--transient",
                "--expire-time", str(expire_ms),
                "-u", effective_urgency,
                title,
                message,
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                sent = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                # Fallback: terminal-notify writes to stdout of the terminal
                try:
                    result = subprocess.run(
                        ["terminal-notify", title, message],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    sent = result.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass

        # Always write to notification file for other instances to pick up
        notif = {
            "title": title,
            "message": message,
            "urgency": urgency,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            with open(self.notify_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(notif) + "\n")
            sent = True
        except OSError:
            pass
        return sent

    def get_notifications(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get pending notifications."""
        if not self.notify_file.exists():
            return []
        notifs: List[Dict[str, Any]] = []
        with open(self.notify_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    notif = json.loads(line)
                    if since is not None:
                        ts_raw = notif.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_raw)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=UTC)
                            if ts < since:
                                continue
                        except ValueError:
                            pass
                    notifs.append(notif)
                except json.JSONDecodeError:
                    continue
        return notifs

    def clear_notifications(self) -> None:
        if self.notify_file.exists():
            self.notify_file.unlink()
