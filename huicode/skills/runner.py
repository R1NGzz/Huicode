from __future__ import annotations

from collections.abc import Callable

from huicode.agent import run_agent_loop
from huicode.agent_events import AgentOptions, AgentState
from huicode.config import LLMConfig
from huicode.provider_factory import create_provider_with_model
from huicode.providers.base import ConversationMessage, Provider
from huicode.tools.base import ToolContext
from huicode.tools.registry import ToolRegistry

from .manager import SkillManager
from .parser import render_skill_body
from .tool import SkillTool
from .types import ActiveSkill, SkillRunResult


ProviderFactory = Callable[[str], Provider]


class SkillRunner:
    def __init__(
        self,
        *,
        provider: Provider,
        registry: ToolRegistry,
        context: ToolContext,
        config: LLMConfig,
        manager: SkillManager,
        options: AgentOptions,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        self.config = config
        self.manager = manager
        self.options = options
        self.provider_factory = provider_factory

    def run(
        self,
        name: str,
        arguments: str,
        *,
        parent_messages: list[ConversationMessage] | None = None,
        depth: int = 1,
    ) -> SkillRunResult:
        if depth > 3:
            return SkillRunResult(
                ok=False,
                status="error",
                summary="Skill 嵌套深度超过上限 3",
                stop_reason="nested_depth_exceeded",
            )
        definition = self.manager.get(name)
        if definition is None:
            return SkillRunResult(False, "error", f"未知 Skill: {name}", stop_reason="unknown_skill")
        if definition.mode != "isolated":
            return SkillRunResult(False, "error", f"Skill {name} 不是 isolated 模式", stop_reason="wrong_mode")

        messages = select_protocol_safe_history(
            list(parent_messages or []),
            definition.history_messages,
        )
        state = AgentState(messages=messages)
        state.skills.nesting_depth = depth
        state.skills.catalog_generation = self.manager.snapshot.generation
        state.skills.active[definition.name] = ActiveSkill(
            definition=definition,
            arguments=arguments,
            rendered_body=render_skill_body(definition, arguments),
            activated_order=0,
        )
        state.skills.next_activation_order = 1

        child_registry = self.registry.clone(exclude={"Skill"})
        child_runner = SkillRunner(
            provider=self.provider,
            registry=child_registry,
            context=self.context,
            config=self.config,
            manager=self.manager,
            options=self.options,
            provider_factory=self.provider_factory,
        )
        child_registry.register(
            SkillTool(
                self.manager,
                state.skills,
                isolated_runner=lambda nested_name, nested_args: child_runner.run(
                    nested_name,
                    nested_args,
                    parent_messages=state.messages,
                    depth=depth + 1,
                ),
            ),
            system=True,
        )

        selected_provider = self._provider_for(definition.model)
        events = run_agent_loop(
            provider=selected_provider,
            registry=child_registry,
            context=self.context,
            state=state,
            user_text=arguments or f"执行 Skill {definition.name}",
            config=self.config,
            options=self.options,
            skill_manager=self.manager,
            provider_override_factory=self.provider_factory,
        )
        stop_reason = "error"
        error_message = ""
        try:
            for event in events:
                if event.kind == "error":
                    error_message = str(event.data.get("message", "Skill 执行失败"))
                if event.kind == "done":
                    stop_reason = event.stop_reason
                    if event.data.get("message"):
                        error_message = str(event.data["message"])
        except Exception as exc:  # noqa: BLE001 - 子 Agent 不能击穿主循环
            return SkillRunResult(
                False,
                "error",
                f"Skill 子会话异常: {exc}",
                iterations=state.iterations,
                stop_reason="error",
            )

        if stop_reason == "final":
            summary = _last_assistant_text(state.messages)
            return SkillRunResult(
                True,
                "completed",
                summary or "Skill 已完成，但没有返回文本摘要。",
                iterations=state.iterations,
                stop_reason=stop_reason,
            )
        return SkillRunResult(
            False,
            "error",
            error_message or f"Skill 未完成，停止原因: {stop_reason}",
            iterations=state.iterations,
            stop_reason=stop_reason,
        )

    def _provider_for(self, model: str | None) -> Provider:
        if not model or model == self.provider.model:
            return self.provider
        if self.provider_factory is not None:
            return self.provider_factory(model)
        return create_provider_with_model(self.config, model)


def select_protocol_safe_history(
    messages: list[ConversationMessage],
    history_messages: int,
) -> list[ConversationMessage]:
    if history_messages <= 0 or not messages:
        return []
    segments: list[list[ConversationMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "assistant" and message.tool_calls:
            group = [message]
            expected = {call.id for call in message.tool_calls}
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == "tool":
                group.append(messages[cursor])
                cursor += 1
            returned = {item.tool_call_id for item in group[1:] if item.tool_call_id}
            if expected.issubset(returned):
                segments.append(group)
            index = cursor
            continue
        if message.role != "tool":
            segments.append([message])
        index += 1

    chosen: list[list[ConversationMessage]] = []
    count = 0
    for segment in reversed(segments):
        chosen.append(segment)
        count += len(segment)
        if count >= history_messages:
            break
    chosen.reverse()
    return [message for segment in chosen for message in segment]


def _last_assistant_text(messages: list[ConversationMessage]) -> str:
    for message in reversed(messages):
        if message.role == "assistant" and message.content.strip():
            return message.content.strip()
    return ""
