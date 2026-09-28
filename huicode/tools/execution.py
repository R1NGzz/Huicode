"""受控的命令执行机制（checklist C52）。

Shell 是这套系统里权限最大的一环：它不受工具能力声明约束，能做任何事。所以这里
不看命令内容（那是黑名单和权限引擎的事），只把**执行的外壳**钉死：

```text
CommandRequest（已解析的工作目录、命令、超时、输出上限、额外环境变量）
        │
        ├─ 1. 环境变量按白名单构造 ────────────── C52「环境变量按策略过滤」
        ├─ 2. 独立进程组启动
        └─ 3. 超时 / 输出超限 → 终止**整棵进程树** ─ C52「超时后整个子进程树退出」
                    │
                    ▼
             ExecutionResult(error_code, ...)
```

**为什么这个模块在 `huicode/tools/` 而不是 `huicode/server/runtime/`。** 执行机制
是 CLI 与 Web 共用的：Shell 工具（CLI 与 Web 都走它）需要它，服务端还要在它上面
加工作目录解析与预算收口。放到服务端包里会让 `huicode/tools/` 依赖
`huicode/server/`——**工具是共用的，服务端不是工具的上游**。服务的部分在
`server/runtime/execution_backend.py`，它在这里的基础上加了两样东西：cwd 经
`WorkspacePathResolver` 解析、超时与输出上限被 `ResourceBudget` 收口。

**工作目录在这里是已经解析好的绝对路径。** 解析（拒绝 `..`、绝对路径、链接逃逸）
是调用方的事：CLI 用工作区根目录，服务端用 T6 的 resolver。这里只负责"在这个目录
里跑"。

**为什么超时之后要杀整棵树。** `subprocess.run(timeout=...)` 超时后杀掉的是直接
子进程。Windows 上 `shell=True` 意味着直接子进程是 `cmd.exe`，真正的命令是它的
子进程；POSIX 上同理。只杀 `cmd.exe` 会留下一堆孤儿进程继续跑——占着端口、
继续写文件，而调用方以为"已经停了"。所以启动时就把子进程放进独立进程组
（POSIX `start_new_session`、Windows `CREATE_NEW_PROCESS_GROUP`），终止时用
`killpg` / `taskkill /T` 整棵带走。

**为什么输出超限是"杀掉"而不是"截断后继续"。** 先读完 1GB 再截断，内存已经没了。
所以在读取端按字节记账，到上限立刻终止并上报失败。呈现层（工具返回给模型的那段）
另外还有一次字符截断，两者不是一回事：前者是内存护栏，后者是可读性。

**没有实现 `max_child_processes`。** 限制进程数需要 OS 级设施（Linux cgroup v2 的
`pids.max`、Windows Job Object），标准库不提供。没有它们就只能轮询枚举进程树，而
那既不准（进程在两次采样之间生灭）又很贵（Windows 上要起 PowerShell 查 CIM，
每次几百毫秒）。能确定做到、也确实需要的是**超时后终止整棵进程树**，那是进程边界
的实质。**留一个看起来生效、实际不生效的配置项比不写更糟**，所以这个字段继续留在
plan.md 里并标注未实现。
"""

from __future__ import annotations

import codecs
import locale
import os
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from huicode.memory.scrub import RESERVED_ENV_PREFIX, SENSITIVE_ENV_NAME_RE

# ── 错误码 ──────────────────────────────────────────────────────────────
# 定义在这里而不是 server/runtime/errors.py：它们是**执行边界**的码，而执行机制
# 在核心包。运行时的聚合集合反向 import，避免同一套词汇表出现两份。
#: 输出超过硬上限。这是**主动终止**而不是"截断后继续"：先读完 1GB 再截断，
#: 内存已经没了。所以到上限就杀掉，并把这一条当作失败上报。
SHELL_OUTPUT_EXCEEDED = "shell_output_exceeded"
SHELL_TIMEOUT = "shell_timeout"
SHELL_SPAWN_FAILED = "shell_spawn_failed"
SHELL_ENV_REJECTED = "shell_env_rejected"

SHELL_ERROR_CODES: frozenset[str] = frozenset({
    SHELL_OUTPUT_EXCEEDED,
    SHELL_TIMEOUT,
    SHELL_SPAWN_FAILED,
    SHELL_ENV_REJECTED,
})

#: 读取输出时的分块大小。太小会让读取线程空转，太大则一次超限就多读很多。
READ_CHUNK_BYTES = 8192

#: 终止进程树之后等它退出的时间。杀不掉就如实上报，不能假装停住了。
KILL_GRACE_SECONDS = 5.0

#: 子进程默认能拿到的环境变量。**白名单而不是黑名单**：进程环境里有几百个变量，
#: 其中任何一个都可能是密钥，靠"列出敏感名字"是必输的仗。白名单的代价是有些工具
#: 会因为缺少变量而行为异常——那种情况由调用方通过 `CommandRequest.env` 显式补，
#: 补的时候会被检查。
ENV_ALLOWLIST: frozenset[str] = frozenset({
    # Windows
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMW6432", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    # POSIX
    "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SHELL",
    # 让 Python 子进程按 UTF-8 输出，避免 Windows 上默认代码页把中文变成乱码
    "PYTHONIOENCODING", "PYTHONUTF8",
})


class ExecutionEnvRejected(ValueError):
    """调用方显式要求了一个按策略不能下发的环境变量。

    **显式请求要报错，不能静默丢掉。** 静默丢弃会让命令在一个与调用方认知不同的
    环境里运行——它可能因此连到别的服务、写到别的地方。继承来的敏感变量则相反：
    调用方没提过它们，静默过滤正是"按策略过滤"的意思。
    """


@dataclass(frozen=True)
class CommandRequest:
    """一次命令执行。`cwd` 是**已经解析并校验过**的绝对目录。"""

    execution_id: str
    command: str
    cwd: Path
    timeout_seconds: float = 60.0
    max_output_bytes: int = 1_048_576
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    error_code: str | None = None
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    output_truncated: bool = False
    duration_ms: int = 0
    command: str = ""
    cwd: str = ""
    tree_killed: bool = False

    @property
    def ok(self) -> bool:
        """命令跑完且退出码为 0。注意非零退出码**不是**执行失败——那是命令自己的
        结果，`error_code` 才表示执行边界出了问题。"""
        return self.error_code is None and self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "error_code": self.error_code,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "output_truncated": self.output_truncated,
            "duration_ms": self.duration_ms,
            "command": self.command,
            "cwd": self.cwd,
            "tree_killed": self.tree_killed,
        }


class _OutputBudget:
    """两条流共享的字节账本。分开记账的话 `cmd 2>&1` 这类写法就等于把上限翻倍。"""

    __slots__ = ("_exceeded", "_limit", "_lock", "_used")

    def __init__(self, limit: int):
        self._limit = limit
        self._used = 0
        self._exceeded = False
        self._lock = threading.Lock()

    def take(self, size: int) -> int:
        """允许接收多少字节。返回小于请求值就表示到上限了。"""
        with self._lock:
            allowed = max(0, min(size, self._limit - self._used))
            self._used += allowed
            if allowed < size:
                self._exceeded = True
            return allowed

    @property
    def exceeded(self) -> bool:
        with self._lock:
            return self._exceeded

    @property
    def used(self) -> int:
        with self._lock:
            return self._used


class CommandRunner:
    """在本机按受控外壳执行命令。

    实例持有"正在跑的进程"表，`cancel` 才能找到要终止的那棵树。所以**它应当被复用**
    （服务端一个进程一个实例），而不是每次执行新建一个。
    """

    def __init__(self) -> None:
        self._running: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def cancel(self, execution_id: str) -> bool:
        """终止指定执行的进程树。返回是否找到了在跑的进程。"""
        with self._lock:
            process = self._running.get(execution_id)
        if process is None:
            return False
        self.terminate_tree(process)
        return True

    def running_ids(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._running)

    def run(
        self, request: CommandRequest, *, timeout_cap: float | None = None, output_cap: int | None = None
    ) -> ExecutionResult:
        """执行命令。`timeout_cap` / `output_cap` 是上层预算的收口（服务端传，
        CLI 不传）。"""
        started = time.monotonic()
        cwd = request.cwd

        try:
            env = build_environment(request.env)
        except ExecutionEnvRejected as exc:
            return self._failure(request, started, SHELL_ENV_REJECTED, str(exc))

        timeout = _clamp(request.timeout_seconds, timeout_cap)
        output_limit = _clamp_int(request.max_output_bytes, output_cap)

        try:
            process = subprocess.Popen(
                request.command,
                cwd=str(cwd),
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            return self._failure(request, started, SHELL_SPAWN_FAILED, f"无法启动命令: {exc}", cwd=cwd)

        with self._lock:
            self._running[request.execution_id] = process

        budget_ledger = _OutputBudget(output_limit)
        captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        readers = [
            threading.Thread(
                target=self._pump,
                args=(process.stdout, captured["stdout"], budget_ledger, process),
                daemon=True,
            ),
            threading.Thread(
                target=self._pump,
                args=(process.stderr, captured["stderr"], budget_ledger, process),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        tree_killed = False
        try:
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                tree_killed = self.terminate_tree(process)
                returncode = self._reap(process)
        finally:
            for reader in readers:
                reader.join(timeout=KILL_GRACE_SECONDS)
            with self._lock:
                self._running.pop(request.execution_id, None)

        output_exceeded = budget_ledger.exceeded and not timed_out
        stdout = _decode(captured["stdout"])
        stderr = _decode(captured["stderr"])
        if output_exceeded:
            stderr = (stderr + "\n输出超过上限，命令已终止").strip()

        return ExecutionResult(
            execution_id=request.execution_id,
            error_code=SHELL_TIMEOUT if timed_out else (SHELL_OUTPUT_EXCEEDED if output_exceeded else None),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            output_truncated=budget_ledger.exceeded,
            duration_ms=int((time.monotonic() - started) * 1000),
            command=request.command,
            cwd=str(cwd),
            tree_killed=tree_killed or output_exceeded,
        )

    # ── 内部 ────────────────────────────────────────────────────────────

    def _pump(
        self,
        stream,
        sink: bytearray,
        ledger: _OutputBudget,
        process: subprocess.Popen[bytes],
    ) -> None:
        """读取一条流并记账。到上限就**立刻终止进程树**，不等主线程轮询。"""
        if stream is None:  # pragma: no cover —— PIPE 一定不是 None
            return
        try:
            while True:
                chunk = stream.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                allowed = ledger.take(len(chunk))
                if allowed:
                    sink.extend(chunk[:allowed])
                if allowed < len(chunk):
                    self.terminate_tree(process)
                    break
        except (OSError, ValueError):
            # 进程被杀时管道会关闭，读取抛错是预期内的。
            pass
        finally:
            try:
                stream.close()
            except OSError:  # pragma: no cover
                pass

    def terminate_tree(self, process: subprocess.Popen[bytes]) -> bool:
        """终止整棵进程树。返回是否真的发出了终止。"""
        if process.poll() is not None:
            return False
        if os.name == "nt":
            # taskkill /T 沿着父子关系走整棵树；/F 是强杀（shell 里的进程不一定响应
            # 温和的信号）。
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=KILL_GRACE_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
                pass
        else:
            import signal

            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            process.kill()
        except OSError:  # pragma: no cover —— 已经退出了
            pass
        return True

    @staticmethod
    def _reap(process: subprocess.Popen[bytes]) -> int | None:
        try:
            return process.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover —— 强杀之后极少见
            return None

    def _failure(
        self,
        request: CommandRequest,
        started: float,
        code: str,
        message: str,
        *,
        cwd: Path | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=request.execution_id,
            error_code=code,
            stderr=message,
            duration_ms=int((time.monotonic() - started) * 1000),
            command=request.command,
            cwd=str(cwd) if cwd is not None else "",
        )


def build_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """按白名单构造子进程环境。

    三层，顺序不能反：

    1. 从当前进程环境里**只取白名单内的**名字；
    2. 去掉名字敏感的（白名单本身不该有敏感项，但这一层是纵深防御——将来有人往
       白名单里加了一个 `AWS_KEY`，这里还能挡住）；
    3. 合并调用方显式要求的变量，**名字敏感的在这里报错而不是丢弃**。
    """
    env: dict[str, str] = {name: value for name, value in os.environ.items() if name.upper() in ENV_ALLOWLIST}
    for name in list(env):
        if is_sensitive_env_name(name):
            env.pop(name, None)

    for name, value in (extra or {}).items():
        if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
            raise ExecutionEnvRejected(f"环境变量名非法: {name!r}")
        if is_sensitive_env_name(name):
            raise ExecutionEnvRejected(f"环境变量 {name} 属于敏感配置，不允许下发给子进程")
        env[name] = str(value)
    return env


def is_sensitive_env_name(name: str) -> bool:
    """这个名字的变量能不能进子进程环境。

    **刻意比文本脱敏规则宽**：误判的代价只是少传一个变量并给出明确错误，漏判的
    代价是密钥进了子进程。`AWS_SECRET_ACCESS_KEY` 这类名字（末段是 `KEY`）是文本
    规则抓不到的，这里必须抓到。
    """
    if not isinstance(name, str) or not name:
        return True
    if name.upper().startswith(RESERVED_ENV_PREFIX):
        return True
    return bool(SENSITIVE_ENV_NAME_RE.search(name))


def _process_group_kwargs() -> dict:
    """让子进程自己成为一个进程组/会话，终止时才能整棵带走。"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _clamp(value: float, cap: float | None) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        seconds = 1.0
    return min(seconds, float(cap)) if cap else seconds


def _clamp_int(value: int, cap: int | None) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        size = 1
    return min(size, int(cap)) if cap else size


def _decode(raw: bytearray) -> str:
    value = bytes(raw)
    if not value:
        return ""
    if value.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return value.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False), "gb18030"):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")
