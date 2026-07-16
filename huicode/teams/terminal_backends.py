from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .backends import BackendAvailability, BackendHandle, MemberLaunchSpec
from .types import TeamError


class TmuxBackend:
    kind = "tmux"

    def available(self) -> BackendAvailability:
        if shutil.which("tmux") is None:
            return BackendAvailability(False, "未找到 tmux")
        if not os.environ.get("TMUX"):
            return BackendAvailability(False, "当前不在 tmux 会话中")
        return BackendAvailability(True)

    def launch(self, spec: MemberLaunchSpec) -> BackendHandle:
        target = f"huicode-{spec.member_name}"
        command = _worker_command(spec)
        completed = _run(["tmux", "split-window", "-P", "-F", "#{pane_id}", "-c", spec.workspace, *command])
        pane = completed.stdout.strip()
        if not pane:
            raise TeamError("terminal_launch_failed", "tmux 未返回 pane 标识")
        return BackendHandle(self.kind, target, {"pane": pane})

    def wake(self, handle: BackendHandle) -> None:
        _run(["tmux", "send-keys", "-t", handle.data["pane"], "Enter"])

    def stop(self, handle: BackendHandle, timeout: float) -> None:
        del timeout
        _run(["tmux", "kill-pane", "-t", handle.data["pane"]])

    def alive(self, handle: BackendHandle) -> bool:
        completed = subprocess.run(["tmux", "display-message", "-p", "-t", handle.data.get("pane", ""), "#{pane_id}"], shell=False, capture_output=True)
        return completed.returncode == 0


class WindowsTerminalBackend:
    kind = "windows_terminal"

    def available(self) -> BackendAvailability:
        if os.name != "nt":
            return BackendAvailability(False, "仅 Windows 支持 Windows Terminal 后端")
        if shutil.which("wt") is None and shutil.which("wt.exe") is None:
            return BackendAvailability(False, "未找到 Windows Terminal wt")
        return BackendAvailability(True)

    def launch(self, spec: MemberLaunchSpec) -> BackendHandle:
        worker_id = f"huicode-team-{spec.member_id}"
        command = ["wt", "-w", "0", "split-pane", "-d", spec.workspace, *(_worker_command(spec))]
        try:
            process = subprocess.Popen(command, cwd=spec.workspace, shell=False)
        except OSError as exc:
            raise TeamError("terminal_launch_failed", f"无法启动 Windows Terminal: {exc}") from exc
        return BackendHandle(self.kind, worker_id, {"pid": str(process.pid), "wake": worker_id})

    def wake(self, handle: BackendHandle) -> None:
        # Worker 同时轮询邮箱；唤醒标识写入环境无共享句柄时不影响可靠投递。
        handle.wake_event.set()

    def stop(self, handle: BackendHandle, timeout: float) -> None:
        del timeout
        handle.stop_event.set()

    def alive(self, handle: BackendHandle) -> bool:
        try:
            os.kill(int(handle.data.get("pid", "0")), 0)
        except (OSError, ValueError):
            return False
        return True


def _worker_command(spec: MemberLaunchSpec) -> list[str]:
    command = [sys.executable, "-m", "huicode", "--team-worker", spec.team_path, "--member-id", spec.member_id]
    if spec.config_path:
        command.extend(["--config", spec.config_path])
    return command


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise TeamError("terminal_failed", (completed.stderr or completed.stdout).strip()[:800])
    return completed
