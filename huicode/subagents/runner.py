from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from huicode.agent import AgentPromptOverrides, run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig
from huicode.context import ContextManager
from huicode.hooks import HookManager
from huicode.permissions import clone_permission_context
from huicode.provider_factory import create_provider_with_model
from huicode.providers.base import Provider
from huicode.tools.base import FileReadCache, ToolContext
from huicode.tools.registry import ToolRegistry
from huicode.workspaces import WorkspaceContextLoader
from huicode.worktrees import WorktreeHandle, WorktreeManager

from .catalog import AgentCatalog
from .filtering import TaskAwareToolRegistry
from .history import select_protocol_safe_history
from .types import AgentDefinition, SubagentLaunchRequest, SubagentResult, SubagentTask


class IsolatedSubagentRunner:
    def __init__(
        self,
        *,
        provider: Provider,
        registry: ToolRegistry,
        context: ToolContext,
        config: LLMConfig,
        catalog: AgentCatalog,
        hook_manager: HookManager | None = None,
        worktree_manager: WorktreeManager | None = None,
        workspace_context_loader: WorkspaceContextLoader | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        self.config = config
        self.catalog = catalog
        self.hook_manager = hook_manager
        self.worktree_manager = worktree_manager
        self.workspace_context_loader = workspace_context_loader

    def __call__(self, request: SubagentLaunchRequest, task: SubagentTask) -> SubagentResult:
        definition = self.catalog.get(request.role or "") if request.type == "defined" else None
        if request.type == "defined" and definition is None:
            return SubagentResult(task.id, "failed", "未知子 Agent 角色", "invalid_role", error=request.role or "")
        worktree: WorktreeHandle | None = None
        workspace = self.context.workspace
        if definition is not None and definition.isolation == "worktree":
            if self.worktree_manager is None:
                return SubagentResult(
                    task.id,
                    "failed",
                    "Worktree 管理器未初始化",
                    "worktree_prepare_failed",
                    error="Worktree 管理器未初始化",
                )
            try:
                worktree = self.worktree_manager.prepare(task.id, definition.name)
                workspace = self.worktree_manager.enter(worktree)
            except Exception as exc:  # noqa: BLE001
                if worktree is not None:
                    try:
                        self.worktree_manager.exit(worktree)
                        self.worktree_manager.finalize(worktree, "failed")
                    except Exception:
                        pass
                return SubagentResult(
                    task.id,
                    "failed",
                    f"Worktree 准备失败: {exc}",
                    "worktree_prepare_failed",
                    error=str(exc),
                    worktree_path=str(worktree.path) if worktree is not None else "",
                    worktree_branch=worktree.branch if worktree is not None else "",
                    worktree_state="retained" if worktree is not None else "",
                    worktree_reason="进入隔离目录失败" if worktree is not None else "",
                )
        try:
            result = self._execute(request, task, definition, workspace, worktree)
        except Exception as exc:  # noqa: BLE001
            result = SubagentResult(
                task.id,
                "failed",
                f"子 Agent 运行失败: {exc}",
                "error",
                error=str(exc),
            )
        disposition = None
        if worktree is not None and self.worktree_manager is not None:
            errors: list[str] = []
            try:
                self.worktree_manager.exit(worktree)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"退出 Worktree 失败: {exc}")
            try:
                disposition = self.worktree_manager.finalize(worktree, result.status)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Worktree 结束处理失败: {exc}")
            if errors:
                combined = "; ".join(errors)
                result = replace(
                    result,
                    error=f"{result.error}; {combined}" if result.error else combined,
                )
        return replace(
            result,
            worktree_path=str(worktree.path) if worktree is not None else "",
            worktree_branch=worktree.branch if worktree is not None else "",
            worktree_state=disposition.state if disposition is not None else "",
            worktree_reason=disposition.reason if disposition is not None else "",
        )

    def _execute(
        self,
        request: SubagentLaunchRequest,
        task: SubagentTask,
        definition: AgentDefinition | None,
        workspace: Path,
        worktree: WorktreeHandle | None,
    ) -> SubagentResult:
        permission = clone_permission_context(
            request.parent.permissions.context,
            workspace,
            requested_mode=definition.permission_mode if definition is not None else None,
        )
        child_context = ToolContext(
            workspace=workspace,
            timeout_seconds=self.context.timeout_seconds,
            max_output_chars=self.context.max_output_chars,
            permissions=permission,
            read_cache=FileReadCache(),
        )
        state = AgentState()
        if request.type == "fork":
            state.messages = list(select_protocol_safe_history(request.parent.messages))
        instructions = request.parent.project_instructions.strip()
        if worktree is not None and self.workspace_context_loader is not None:
            workspace_data = self.workspace_context_loader.load(workspace)
            instructions = workspace_data.instructions.strip()
            state.memory.memory_index_text = workspace_data.memory_index
            state.memory.warnings = list(workspace_data.warnings)
        role_blocks: tuple[str, ...] = ()
        if definition is not None:
            role_block = (
                f'<huicode_instruction type="subagent_role" name="{definition.name}" priority="highest">\n'
                f"{definition.instructions}\n</huicode_instruction>"
            )
            role_blocks = (role_block,)
        if worktree is not None:
            worktree_block = (
                '<huicode_instruction type="worktree" priority="highest">\n'
                f"当前隔离工作目录: {worktree.path}\n"
                f"当前独立分支: {worktree.branch}\n"
                "所有文件和命令操作必须限制在当前隔离工作目录中，不得修改主工作区。\n"
                "不要自行合并分支；完成后报告修改和验证结果。\n"
                "</huicode_instruction>"
            )
            role_blocks = (*role_blocks, worktree_block)
        state.memory.instructions_text = instructions
        model = self.provider.model
        if definition is not None and definition.model != "inherit":
            model = self.config.subagents.model_aliases[definition.model]
        provider = self.provider if model == self.provider.model else create_provider_with_model(self.config, model)
        options = AgentOptions(
            mode=request.parent.mode,
            max_iterations=definition.max_iterations if definition is not None else 50,
        )
        child_registry = TaskAwareToolRegistry(
            self.registry,
            task,
            request.parent.visible_tools,
            kind=request.type,
            definition=definition,
            background_allowed=self.config.subagents.background_allowed_tools,
            mode=request.parent.mode,
            read_only_names=options.read_only_tool_names,
        )
        monitor = threading.Thread(target=self._monitor_cancel, args=(task, state), daemon=True)
        monitor.start()
        text: list[str] = []
        usage: dict[str, object] = {}
        stop_reason = "error"
        error = ""
        scope = (
            f"subagent:defined:{definition.name}:{task.id}"
            if definition is not None
            else f"subagent:fork:{task.id}"
        )
        try:
            for event in run_agent_loop(
                provider=provider,
                registry=child_registry,
                context=child_context,
                state=state,
                user_text=request.task,
                config=self.config,
                options=options,
                hook_manager=self.hook_manager,
                context_manager=ContextManager(workspace, self.config.context),
                agent_scope=scope,
                prompt_overrides=AgentPromptOverrides(
                    role_instruction_blocks=role_blocks,
                    stable_modules=(
                        request.parent.prompt.stable_modules if request.type == "fork" else None
                    ),
                ),
            ):
                if event.kind == "text":
                    text.append(event.text)
                elif event.kind == "usage":
                    usage.update(event.data.get("usage", {}))
                elif event.kind == "error":
                    error = str(event.data.get("message", ""))
                elif event.kind == "done":
                    stop_reason = event.stop_reason
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            stop_reason = "error"
        summary = "".join(text).strip() or error or f"子 Agent 停止: {stop_reason}"
        status = "completed" if stop_reason == "final" else "cancelled" if stop_reason == "cancelled" else "failed"
        return SubagentResult(
            task_id=task.id,
            status=status,  # type: ignore[arg-type]
            summary=summary,
            stop_reason=stop_reason,
            iterations=state.iterations,
            usage=usage,
            error=error,
        )

    @staticmethod
    def _monitor_cancel(task: SubagentTask, state: AgentState) -> None:
        task.cancel_event.wait()
        state.cancel_requested = True
