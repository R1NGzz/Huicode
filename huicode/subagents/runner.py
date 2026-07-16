from __future__ import annotations

import threading

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

from .catalog import AgentCatalog
from .filtering import TaskAwareToolRegistry
from .history import select_protocol_safe_history
from .types import SubagentLaunchRequest, SubagentResult, SubagentTask


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
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        self.config = config
        self.catalog = catalog
        self.hook_manager = hook_manager

    def __call__(self, request: SubagentLaunchRequest, task: SubagentTask) -> SubagentResult:
        definition = self.catalog.get(request.role or "") if request.type == "defined" else None
        if request.type == "defined" and definition is None:
            return SubagentResult(task.id, "failed", "未知子 Agent 角色", "invalid_role", error=request.role or "")
        permission = clone_permission_context(
            request.parent.permissions.context,
            self.context.workspace,
            requested_mode=definition.permission_mode if definition is not None else None,
        )
        child_context = ToolContext(
            workspace=self.context.workspace,
            timeout_seconds=self.context.timeout_seconds,
            max_output_chars=self.context.max_output_chars,
            permissions=permission,
            read_cache=FileReadCache(),
        )
        state = AgentState()
        if request.type == "fork":
            state.messages = list(select_protocol_safe_history(request.parent.messages))
        instructions = request.parent.project_instructions.strip()
        role_blocks: tuple[str, ...] = ()
        if definition is not None:
            role_block = (
                f'<huicode_instruction type="subagent_role" name="{definition.name}" priority="highest">\n'
                f"{definition.instructions}\n</huicode_instruction>"
            )
            role_blocks = (role_block,)
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
                context_manager=ContextManager(self.context.workspace, self.config.context),
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
