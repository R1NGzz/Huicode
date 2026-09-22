from __future__ import annotations

import json
import html
import os
import platform
import re
import sys
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, TextIO

from huicode.agent_guard import is_production_source_path, is_verification_command, normalized_path
from huicode.context import ContextLifecycleCallbacks, ContextManager, TokenEstimate
from huicode.agent_events import AgentEvent, AgentOptions, AgentState, CollectedResponse, ToolBatch
from huicode.config import LLMConfig
from huicode.hooks import HookManager
from huicode.hooks.events import context_data, error_data, make_event, message_data, tool_data
from huicode.prompts import (
    PromptBundle,
    PromptContext,
    PromptInjectionPolicy,
    build_prompt_bundle,
    enhance_tool_specs,
    normalize_cache_usage,
)
from huicode.providers.base import ConversationMessage, Provider, ToolCall
from huicode.sse import APIError
from huicode.skills.manager import SkillManager
from huicode.tools.base import ToolContext, ToolResult
from huicode.tools.executor import execute_tool_call
from huicode.tools.registry import ToolRegistry
from huicode.tui import render_agent_event

if TYPE_CHECKING:
    from huicode.prompts.base import PromptModule
    from huicode.subagents.manager import SubagentManager


class AgentPromptOverrides:
    def __init__(
        self,
        *,
        role_instruction_blocks: tuple[str, ...] = (),
        stable_modules: tuple["PromptModule", ...] | None = None,
    ) -> None:
        self.role_instruction_blocks = role_instruction_blocks
        self.stable_modules = stable_modules


def prompt_injection_policy(config: LLMConfig | None = None) -> PromptInjectionPolicy:
    """Return the prompt cadence configured for the current run."""
    if config is None or not config.orchestration.enabled:
        return PromptInjectionPolicy()
    settings = config.orchestration
    return PromptInjectionPolicy(
        repeat_every=settings.prompt_repeat_every,
        catalog_repeat_every=settings.catalog_repeat_every,
        plan_preview_chars=settings.plan_preview_chars,
        exploration_soft_limit=settings.exploration_soft_limit,
        interface_closure=settings.interface_closure,
        scope_audit=settings.scope_audit,
    )


def run_agent_turn(
    provider: Provider,
    registry: ToolRegistry,
    context: ToolContext,
    messages: list[ConversationMessage],
    user_text: str,
    config: LLMConfig,
    output: TextIO | None = None,
) -> bool:
    out = output or sys.stdout
    state = AgentState(messages=messages)
    ok = True
    for event in run_agent_loop(
        provider=provider,
        registry=registry,
        context=context,
        state=state,
        user_text=user_text,
        config=config,
        options=AgentOptions(),
    ):
        if event.kind == "thinking" and not config.thinking.show:
            continue
        if event.kind == "usage" and not config.show_usage:
            continue
        render_agent_event(event, out)
        if event.kind == "error" or (event.kind == "done" and event.stop_reason in {"cancelled", "error"}):
            ok = False
    return ok


def run_agent_loop(
    provider: Provider,
    registry: ToolRegistry,
    context: ToolContext,
    state: AgentState,
    user_text: str,
    config: LLMConfig,
    options: AgentOptions,
    memory=None,
    skill_manager: SkillManager | None = None,
    provider_override_factory=None,
    hook_manager: HookManager | None = None,
    context_manager: ContextManager | None = None,
    agent_scope: str = "main",
    subagent_manager: "SubagentManager | None" = None,
    prompt_overrides: AgentPromptOverrides | None = None,
) -> Iterator[AgentEvent]:
    if config.agent_guard.protect_test_edits and not context.protect_test_edits:
        context = replace(context, protect_test_edits=True)
    done_reason = ""
    try:
        for event in _run_agent_loop_impl(
            provider=provider,
            registry=registry,
            context=context,
            state=state,
            user_text=user_text,
            config=config,
            options=options,
            memory=memory,
            skill_manager=skill_manager,
            provider_override_factory=provider_override_factory,
            hook_manager=hook_manager,
            context_manager=context_manager,
            agent_scope=agent_scope,
            subagent_manager=subagent_manager,
            prompt_overrides=prompt_overrides,
        ):
            if event.kind == "done":
                done_reason = event.stop_reason
                _dispatch_turn_end(
                    hook_manager,
                    context,
                    state,
                    options,
                    event.stop_reason,
                    event.iteration or state.iterations,
                    agent_scope,
                )
            yield event
    finally:
        state.skills.turn_model_override = None
        if hook_manager is not None and state.hooks.turn_id:
            if not done_reason:
                _dispatch_turn_end(
                    hook_manager,
                    context,
                    state,
                    options,
                    "cancelled",
                    state.iterations,
                    agent_scope,
                )
            hook_manager.end_turn(state.hooks)


def _run_agent_loop_impl(
    provider: Provider,
    registry: ToolRegistry,
    context: ToolContext,
    state: AgentState,
    user_text: str,
    config: LLMConfig,
    options: AgentOptions,
    memory=None,
    skill_manager: SkillManager | None = None,
    provider_override_factory=None,
    hook_manager: HookManager | None = None,
    context_manager: ContextManager | None = None,
    agent_scope: str = "main",
    subagent_manager: "SubagentManager | None" = None,
    prompt_overrides: AgentPromptOverrides | None = None,
) -> Iterator[AgentEvent]:
    if state.pending_verification and state.verification_due_iteration > 0:
        state.verification_due_iteration = 0
    state.cancel_requested = False
    state.iterations = 0
    state.unknown_tool_count = 0
    state.read_only_tool_calls = 0
    state.production_edit_count = 0
    state.last_production_edit_iteration = 0
    state.last_verification_iteration = 0
    state.changed_production_paths = ()
    state.verification_failures = 0
    state.last_verification_failure = ""
    empty_response_count = 0
    override_providers: dict[str, Provider] = {}
    context_manager = context_manager or ContextManager(context.workspace, config.context)
    turn_start = len(state.messages)
    state.hooks.turn_id = uuid.uuid4().hex[:12]
    _dispatch_hook(
        hook_manager,
        make_event(
            "turn_start",
            session_id=_hook_session_id(hook_manager),
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            agent_scope=agent_scope,
            data={"turn": {"input": user_text, "message_count_before": turn_start}},
        ),
        state,
    )
    user_message = ConversationMessage(role="user", content=_build_user_text(user_text, state, options))
    state.messages.append(user_message)
    if memory is not None:
        memory.record_message(state, user_message)
    _dispatch_hook(
        hook_manager,
        make_event(
            "message_received",
            session_id=_hook_session_id(hook_manager),
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            agent_scope=agent_scope,
            data=message_data(user_message, is_final=False),
        ),
        state,
    )

    while state.iterations < options.max_iterations:
        state.iterations += 1
        iteration = state.iterations
        yield AgentEvent(
            kind="progress",
            iteration=iteration,
            data={
                "stage": "assistant_turn_start",
                "mode": options.mode,
                "permission_mode": context.permissions.mode if context.permissions else "disabled",
                "orchestration": {
                    "read_only_tool_calls": state.read_only_tool_calls,
                    "production_edit_count": state.production_edit_count,
                    "last_production_edit_iteration": state.last_production_edit_iteration,
                    "last_verification_iteration": state.last_verification_iteration,
                    "changed_production_paths": list(state.changed_production_paths),
                    "verification_failures": state.verification_failures,
                },
            },
        )
        lease = None
        try:
            current_provider = _provider_for_iteration(
                provider,
                config,
                state.skills.turn_model_override,
                provider_override_factory,
                override_providers,
            )
            if memory is not None:
                memory.refresh_prompt_memory(state)
            if agent_scope == "main" and subagent_manager is not None:
                lease = subagent_manager.acquire_result_lease()
            result_blocks = _subagent_result_blocks(lease.results) if lease is not None else ()
            prompt = build_agent_prompt(
                context=context,
                registry=registry,
                state=state,
                options=options,
                iteration=iteration,
                skill_manager=skill_manager,
                hook_manager=hook_manager,
                subagent_manager=subagent_manager if agent_scope == "main" else None,
                prompt_overrides=prompt_overrides,
                subagent_result_blocks=result_blocks,
                config=config,
            )
            selected_tools = select_tools(registry, options, state, skill_manager)
            preparation = context_manager.prepare_before_request(
                provider=current_provider,
                state=state,
                context=context,
                config=config,
                prompt=prompt,
                tools=selected_tools,
                callbacks=_context_callbacks(
                    hook_manager,
                    context,
                    state,
                    options,
                    iteration,
                    agent_scope,
                ),
            )
            request_estimate = TokenEstimate(
                tokens=preparation.request_tokens,
                chars=preparation.request_chars,
                source="chars",
            )
            for report in preparation.reports:
                yield AgentEvent(kind="context", iteration=iteration, data=report.to_dict())
            if hook_manager is not None:
                prompt = build_agent_prompt(
                    context=context,
                    registry=registry,
                    state=state,
                    options=options,
                    iteration=iteration,
                    skill_manager=skill_manager,
                    hook_manager=hook_manager,
                    subagent_manager=subagent_manager if agent_scope == "main" else None,
                    prompt_overrides=prompt_overrides,
                    subagent_result_blocks=result_blocks,
                    config=config,
                )
            if agent_scope == "main" and subagent_manager is not None:
                from huicode.permissions import clone_permission_context
                from huicode.subagents.types import ParentAgentSnapshot, PermissionSnapshot

                permission = clone_permission_context(context.permissions, context.workspace)
                subagent_manager.capture_parent(
                    ParentAgentSnapshot(
                        messages=tuple(deepcopy(state.messages)),
                        prompt=prompt,
                        visible_tools=tuple(tool.name for tool in selected_tools),
                        mode=options.mode,
                        permissions=PermissionSnapshot(permission),
                        project_instructions=state.memory.instructions_text,
                    )
                )
            try:
                response = yield from collect_model_response(
                    provider=current_provider,
                    messages=state.messages,
                    tools=selected_tools,
                    prompt=prompt,
                    iteration=iteration,
                )
                if lease is not None and subagent_manager is not None:
                    subagent_manager.ack_result_lease(lease.id)
                    lease = None
            finally:
                if hook_manager is not None:
                    hook_manager.consume_next_request(state.hooks)
            if response.usage:
                context_manager.record_usage(state, response.usage, request_estimate)
        except KeyboardInterrupt:
            if lease is not None and subagent_manager is not None:
                subagent_manager.release_result_lease(lease.id)
            state.cancel_requested = True
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="cancelled",
                data={"message": "生成已中断。"},
            )
            return
        except (APIError, RuntimeError, ValueError) as exc:
            if lease is not None and subagent_manager is not None:
                subagent_manager.release_result_lease(lease.id)
            _dispatch_agent_error(hook_manager, context, state, options, iteration, agent_scope, exc)
            yield AgentEvent(
                kind="error",
                iteration=iteration,
                data={"message": f"请求错误: {exc}"},
            )
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="error",
                data={"message": f"请求错误: {exc}"},
            )
            return
        except Exception as exc:  # noqa: BLE001 - Provider 边界需要释放结果租约
            if lease is not None and subagent_manager is not None:
                subagent_manager.release_result_lease(lease.id)
            _dispatch_agent_error(hook_manager, context, state, options, iteration, agent_scope, exc)
            yield AgentEvent(kind="error", iteration=iteration, data={"message": f"请求错误: {exc}"})
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="error",
                data={"message": f"请求错误: {exc}"},
            )
            return

        if _is_empty_response(response):
            empty_response_count += 1
            if empty_response_count <= options.max_empty_responses:
                state.messages.append(ConversationMessage(role="user", content=_empty_response_retry_prompt()))
                continue
            _dispatch_agent_error(
                hook_manager,
                context,
                state,
                options,
                iteration,
                agent_scope,
                RuntimeError("模型返回了空回复"),
            )
            yield AgentEvent(
                kind="error",
                iteration=iteration,
                data={"message": "模型返回了空回复，已停止本次执行。"},
            )
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="error",
                data={"message": "模型返回了空回复，已停止本次执行。"},
            )
            return

        empty_response_count = 0
        assistant_message = ConversationMessage(
            role="assistant",
            content=response.text,
            thinking=response.thinking,
            thinking_signature=response.thinking_signature,
            tool_calls=response.tool_calls,
        )
        state.messages.append(assistant_message)
        if memory is not None:
            memory.record_message(state, assistant_message)
        _dispatch_hook(
            hook_manager,
            make_event(
                "message_completed",
                session_id=_hook_session_id(hook_manager),
                workspace=context.workspace,
                mode=options.mode,
                turn_id=state.hooks.turn_id,
                iteration=iteration,
                agent_scope=agent_scope,
                data=message_data(assistant_message, is_final=not response.tool_calls),
            ),
            state,
        )

        if not response.tool_calls:
            state.unknown_tool_count = 0
            if options.mode == "plan" and response.text:
                state.last_plan = response.text
            if config.agent_guard.verification_gate and state.pending_verification and options.mode != "plan":
                state.messages.append(
                    ConversationMessage(
                        role="user",
                        content=_verification_required_retry_prompt(state),
                    )
                )
                continue
            if memory is not None:
                report = memory.schedule_update_after_final(state, options.mode, turn_start)
                if report.message and not report.noop:
                    yield AgentEvent(kind="memory", iteration=iteration, data={"message": report.message, "ok": report.ok})
            yield AgentEvent(kind="done", iteration=iteration, stop_reason="final")
            return

        outcomes = yield from execute_tool_batches(
            registry,
            context,
            state,
            response.tool_calls,
            iteration,
            options,
            context_manager,
            memory,
            hook_manager,
            agent_scope,
            verification_gate=config.agent_guard.verification_gate,
            max_production_files=config.agent_guard.max_production_files,
        )
        if _all_unknown_tool_results(outcomes):
            state.unknown_tool_count += len(outcomes)
        else:
            state.unknown_tool_count = 0

        if state.unknown_tool_count >= options.max_unknown_tools:
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="unknown_tool_limit",
                data={"message": "连续请求未知工具，已停止本次执行。"},
            )
            return

        if state.cancel_requested:
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="cancelled",
                data={"message": "生成已中断。"},
            )
            return

    yield AgentEvent(
        kind="done",
        iteration=state.iterations,
        stop_reason="max_iterations",
        data={"message": f"已达到最大迭代次数 {options.max_iterations}，停止执行。"},
    )


def collect_model_response(
    provider: Provider,
    messages: list[ConversationMessage],
    tools,
    prompt: PromptBundle | None,
    iteration: int,
) -> Iterator[AgentEvent]:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    thinking_signature_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    usage: dict[str, object] = {}

    for event in provider.stream_chat(messages, tools=tools, allow_tool_calls=True, prompt=prompt):
        if event.kind == "text":
            text_parts.append(event.text)
            yield AgentEvent(kind="text", text=event.text, iteration=iteration)
            continue
        if event.kind == "thinking":
            if event.text:
                thinking_parts.append(event.text)
            if event.thinking_signature:
                thinking_signature_parts.append(event.thinking_signature)
            yield AgentEvent(
                kind="thinking",
                text=event.text,
                iteration=iteration,
                data={"thinking_signature": event.thinking_signature},
            )
            continue
        if event.kind == "usage":
            normalized_usage = normalize_cache_usage(event.usage)
            usage.update(normalized_usage)
            yield AgentEvent(kind="usage", iteration=iteration, data={"usage": dict(normalized_usage)})
            continue
        if event.tool_call is not None:
            tool_calls.append(event.tool_call)

    return CollectedResponse(
        text="".join(text_parts),
        thinking="".join(thinking_parts),
        thinking_signature="".join(thinking_signature_parts),
        tool_calls=tool_calls,
        usage=usage,
    )


def select_tools(
    registry: ToolRegistry,
    options: AgentOptions,
    state: AgentState | None = None,
    skill_manager: SkillManager | None = None,
):
    if options.mode == "plan":
        allowed = {
            name
            for name in options.read_only_tool_names
            if registry.resolve_name(name) is not None
        }
    else:
        allowed = set(registry.ordinary_tool_names())
    if state is not None and skill_manager is not None:
        skill_allowed = skill_manager.active_allowed_tools(state.skills)
        if skill_allowed is not None:
            allowed.intersection_update(skill_allowed)
    return enhance_tool_specs(registry.to_specs(allowed, include_system=True))


def build_agent_prompt(
    context: ToolContext,
    registry: ToolRegistry,
    state: AgentState,
    options: AgentOptions,
    iteration: int,
    skill_manager: SkillManager | None = None,
    hook_manager: HookManager | None = None,
    subagent_manager: "SubagentManager | None" = None,
    prompt_overrides: AgentPromptOverrides | None = None,
    subagent_result_blocks: tuple[str, ...] = (),
    config: LLMConfig | None = None,
) -> PromptBundle:
    selected_tools = select_tools(registry, options, state, skill_manager)
    policy = prompt_injection_policy(config)
    prompt_context = PromptContext(
        workspace=context.workspace,
        platform=platform.platform(),
        shell=_current_shell(),
        now=datetime.now().astimezone().isoformat(timespec="seconds"),
        mode=options.mode,
        iteration=iteration,
        max_iterations=options.max_iterations,
        available_tools=tuple(tool.name for tool in selected_tools),
        read_only_tool_names=tuple(sorted(options.read_only_tool_names)),
        last_plan=state.last_plan,
        custom_instructions=state.memory.instructions_text,
        memory_enabled=bool(state.memory.session_id),
        memory_index=state.memory.memory_index_text,
        memory_warnings=tuple(state.memory.warnings),
        active_skill_blocks=(
            skill_manager.active_prompt_blocks(state.skills) if skill_manager is not None else ()
        ),
        hook_instruction_blocks=(
            hook_manager.prompt_blocks(state.hooks) if hook_manager is not None else ()
        ),
        skill_catalog=(skill_manager.catalog_items() if skill_manager is not None else ()),
        agent_catalog=(
            subagent_manager.catalog.catalog_items() if subagent_manager is not None else ()
        ),
        role_instruction_blocks=(
            prompt_overrides.role_instruction_blocks if prompt_overrides is not None else ()
        ),
        subagent_result_blocks=subagent_result_blocks,
        verification_required=state.pending_verification,
        verification_paths=state.pending_verification_paths,
        verification_status=state.last_verification,
        read_only_tool_calls=state.read_only_tool_calls,
        production_edit_count=state.production_edit_count,
        last_production_edit_iteration=state.last_production_edit_iteration,
        last_verification_iteration=state.last_verification_iteration,
        exploration_soft_limit=policy.exploration_soft_limit,
        changed_production_paths=state.changed_production_paths,
        verification_failures=state.verification_failures,
        last_verification_failure=state.last_verification_failure,
        stable_modules_override=(
            prompt_overrides.stable_modules if prompt_overrides is not None else None
        ),
    )
    return build_prompt_bundle(prompt_context, policy)


def _subagent_result_blocks(results) -> tuple[str, ...]:  # noqa: ANN001
    blocks = []
    for result in results:
        usage = html.escape(json.dumps(result.usage, ensure_ascii=False, sort_keys=True))
        blocks.append(
            "\n".join(
                [
                    f"task_id: {html.escape(result.task_id)}",
                    f"status: {html.escape(result.status)}",
                    f"stop_reason: {html.escape(result.stop_reason)}",
                    f"iterations: {result.iterations}",
                    f"usage: {usage}",
                    f"summary: {html.escape(result.summary)}",
                    f"error: {html.escape(result.error)}" if result.error else "",
                    f"worktree_path: {html.escape(result.worktree_path)}" if result.worktree_path else "",
                    f"worktree_branch: {html.escape(result.worktree_branch)}" if result.worktree_branch else "",
                    f"worktree_state: {html.escape(result.worktree_state)}" if result.worktree_state else "",
                    f"worktree_reason: {html.escape(result.worktree_reason)}" if result.worktree_reason else "",
                ]
            ).strip()
        )
    return tuple(blocks)


def _provider_for_iteration(provider, config, model_override, factory, cache):  # noqa: ANN001, ANN202
    if not model_override or model_override == provider.model:
        return provider
    if model_override in cache:
        return cache[model_override]
    if factory is not None:
        selected = factory(model_override)
    else:
        from huicode.provider_factory import create_provider_with_model

        selected = create_provider_with_model(config, model_override)
    cache[model_override] = selected
    return selected


def _current_shell() -> str:
    return os.environ.get("SHELL") or os.environ.get("ComSpec") or os.environ.get("COMSPEC") or "unknown"


def batch_tool_calls(calls: list[ToolCall], registry: ToolRegistry) -> ToolBatch:
    parallel_read_calls: list[ToolCall] = []
    serial_calls: list[ToolCall] = []
    for call in calls:
        if registry.is_side_effect(call.name):
            serial_calls.append(call)
        else:
            parallel_read_calls.append(call)
    return ToolBatch(parallel_read_calls=parallel_read_calls, serial_calls=serial_calls)


def execute_tool_batches(
    registry: ToolRegistry,
    context: ToolContext,
    state: AgentState,
    calls: list[ToolCall],
    iteration: int,
    options: AgentOptions | None = None,
    context_manager: ContextManager | None = None,
    memory=None,
    hook_manager: HookManager | None = None,
    agent_scope: str = "main",
    verification_gate: bool = False,
    max_production_files: int = 0,
) -> Iterator[AgentEvent]:
    options = options or AgentOptions()
    batch = batch_tool_calls(calls, registry)
    outcomes: list[tuple[ToolCall, ToolResult]] = []

    if batch.parallel_read_calls:
        for call in batch.parallel_read_calls:
            yield AgentEvent(kind="tool_call", tool_call=call, iteration=iteration)
        max_workers = max(1, len(batch.parallel_read_calls))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results: list[ToolResult | None] = [None] * len(batch.parallel_read_calls)
            result_sources: list[str] = ["tool"] * len(batch.parallel_read_calls)
            futures = []
            for index, call in enumerate(batch.parallel_read_calls):
                denied = _verification_tool_denial(
                    state,
                    registry,
                    call,
                    iteration,
                    verification_gate,
                )
                if denied is not None:
                    results[index] = denied
                    result_sources[index] = "verification"
                    continue
                denied = _hook_tool_denial(
                    hook_manager,
                    context,
                    state,
                    call,
                    iteration,
                    options,
                    agent_scope,
                )
                if denied is not None:
                    results[index] = denied
                    result_sources[index] = "hook"
                    continue
                denied = _plan_mode_denial(registry, call, options)
                if denied is not None:
                    results[index] = denied
                    result_sources[index] = "plan"
                    continue
                futures.append((index, executor.submit(execute_tool_call, registry, call, context)))
            for index, future in futures:
                results[index] = future.result()
        for index, (call, result) in enumerate(zip(batch.parallel_read_calls, results, strict=False)):
            if result is None:
                result = ToolResult.failure("tool_exception", "工具执行未返回结果", {"tool": call.name})
            source = result_sources[index] if index < len(result_sources) else _tool_result_source(result)
            if source == "tool":
                source = _tool_result_source(result)
            _dispatch_tool_after(
                hook_manager,
                context,
                state,
                call,
                result,
                source,
                iteration,
                options,
                agent_scope,
            )
            _update_orchestration_state(state, registry, call, result, iteration)
            if verification_gate:
                _update_verification_state(state, registry, call, result)
            context_report = None
            if context_manager is not None:
                result, context_report = context_manager.compact_tool_result(call, result, context, iteration)
            tool_message = _tool_message(call, result)
            state.messages.append(tool_message)
            if memory is not None:
                memory.record_message(state, tool_message)
            outcomes.append((call, result))
            yield AgentEvent(kind="tool_result", tool_call=call, tool_result=result, iteration=iteration)
            if context_report is not None:
                yield AgentEvent(kind="context", iteration=iteration, data=context_report.to_dict())

    for call in batch.serial_calls:
        yield AgentEvent(kind="tool_call", tool_call=call, iteration=iteration)
        source = "hook"
        result = _verification_tool_denial(
            state,
            registry,
            call,
            iteration,
            verification_gate,
        )
        if result is not None:
            source = "verification"
        if result is None:
            result = _production_scope_denial(
                state,
                registry,
                call,
                max_production_files,
            )
            if result is not None:
                source = "scope"
        if result is None:
            result = _hook_tool_denial(
                hook_manager,
                context,
                state,
                call,
                iteration,
                options,
                agent_scope,
            )
        if result is None:
            source = "plan"
            result = _plan_mode_denial(registry, call, options)
        if result is None:
            source = "tool"
            result = execute_tool_call(registry, call, context)
            source = _tool_result_source(result)
        _dispatch_tool_after(
            hook_manager,
            context,
            state,
            call,
            result,
            source,
            iteration,
            options,
            agent_scope,
        )
        _update_orchestration_state(state, registry, call, result, iteration)
        if verification_gate:
            _update_verification_state(state, registry, call, result)
        context_report = None
        if context_manager is not None:
            result, context_report = context_manager.compact_tool_result(call, result, context, iteration)
        tool_message = _tool_message(call, result)
        state.messages.append(tool_message)
        if memory is not None:
            memory.record_message(state, tool_message)
        outcomes.append((call, result))
        yield AgentEvent(kind="tool_result", tool_call=call, tool_result=result, iteration=iteration)
        if context_report is not None:
            yield AgentEvent(kind="context", iteration=iteration, data=context_report.to_dict())

    return outcomes


def _production_scope_denial(
    state: AgentState,
    registry: ToolRegistry,
    call: ToolCall,
    max_production_files: int,
) -> ToolResult | None:
    """Keep an evaluation run from expanding a patch past its configured file budget."""
    if max_production_files <= 0:
        return None
    resolved_name = registry.resolve_name(call.name) or call.name
    if resolved_name not in {"Edit", "Write"}:
        return None
    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    path = arguments.get("path")
    if not is_production_source_path(path):
        return None
    normalized = normalized_path(path)
    if not normalized or normalized in state.changed_production_paths:
        return None
    if len(state.changed_production_paths) < max_production_files:
        return None
    return ToolResult.failure(
        "production_scope_limit",
        "评测范围保护阻止新增生产文件；请在现有改动文件中完成最小修复并先检查 diff。",
        {
            "path": normalized,
            "max_production_files": max_production_files,
            "changed_production_paths": list(state.changed_production_paths),
        },
    )


def _plan_mode_denial(registry: ToolRegistry, call: ToolCall, options: AgentOptions) -> ToolResult | None:
    if options.mode != "plan":
        return None
    resolved_name = registry.resolve_name(call.name)
    if resolved_name is None:
        return None
    if resolved_name in registry.system_tool_names():
        return None
    if call.name in options.read_only_tool_names or resolved_name in options.read_only_tool_names:
        return None
    return ToolResult.failure(
        "permission_denied",
        "Plan Mode 只允许读类工具",
        {
            "tool": call.name,
            "resolved_tool": resolved_name,
            "mode": options.mode,
            "allowed_tools": sorted(options.read_only_tool_names),
        },
        summary="Plan Mode 只允许读类工具，已拒绝执行",
    )


def _tool_message(call: ToolCall, result: ToolResult) -> ConversationMessage:
    return ConversationMessage(
        role="tool",
        content=result.summary,
        tool_call_id=call.id,
        tool_name=call.name,
        tool_result=result,
    )


def _update_orchestration_state(
    state: AgentState,
    registry,
    call: ToolCall,
    result: ToolResult,
    iteration: int,
) -> None:  # noqa: ANN001
    """Record cheap progress counters used by the long-task prompt."""
    resolved_name = registry.resolve_name(call.name) or call.name
    if resolved_name in {"Read", "Find", "Search", "Glob"}:
        state.read_only_tool_calls += 1

    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    if result.ok and resolved_name in {"Edit", "Write"}:
        path = arguments.get("path")
        if is_production_source_path(path):
            state.production_edit_count += 1
            state.read_only_tool_calls = 0
            state.last_production_edit_iteration = iteration
            normalized = normalized_path(path)
            if normalized and normalized not in state.changed_production_paths:
                state.changed_production_paths = (*state.changed_production_paths, normalized)[-12:]
        return

    if resolved_name == "Bash" and is_verification_command(arguments.get("command")):
        if result.ok:
            state.last_verification_iteration = iteration
            state.last_verification_failure = ""
        else:
            state.verification_failures += 1
            state.last_verification_failure = result.summary.strip().replace("\n", " ")[:240]


def _update_verification_state(state: AgentState, registry, call: ToolCall, result: ToolResult) -> None:  # noqa: ANN001
    resolved_name = registry.resolve_name(call.name) or call.name
    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    if result.ok and resolved_name in {"Edit", "Write"}:
        path = arguments.get("path")
        if is_production_source_path(path):
            paths = set(state.pending_verification_paths)
            paths.add(str(path).replace("\\", "/"))
            state.pending_verification = True
            state.pending_verification_paths = tuple(sorted(paths))
            state.last_verification = "等待运行相关测试或导入/编译检查"
            state.verification_due_iteration = state.iterations
        return

    if resolved_name != "Bash" or not state.pending_verification:
        return
    command = arguments.get("command")
    if not is_verification_command(command):
        return
    state.verification_attempts += 1
    if result.ok:
        state.pending_verification = False
        state.pending_verification_paths = ()
        state.last_verification = "验证命令成功"
        state.verification_due_iteration = 0
    else:
        failure = result.summary.strip().replace("\n", " ")[:240]
        state.last_verification = f"验证命令失败：{failure or '命令退出非零'}"
        state.verification_due_iteration = 0


def _verification_required_retry_prompt(state: AgentState) -> str:
    paths = ", ".join(state.pending_verification_paths) if state.pending_verification_paths else "受影响生产源文件"
    status = state.last_verification or "尚未运行验证"
    return (
        "运行时验证闸门暂未满足：生产代码已经修改，但不能直接结束任务。"
        f"受影响文件：{paths}。当前状态：{status}。"
        "下一步必须调用 Bash 运行相关测试、导入/编译检查或最小复现；"
        "若验证失败，修复生产代码后再次验证；不要修改测试文件。"
    )


def _verification_tool_denial(
    state: AgentState,
    registry,
    call: ToolCall,
    iteration: int,
    verification_gate: bool,
) -> ToolResult | None:  # noqa: ANN001
    if not verification_gate or not state.pending_verification:
        return None
    if state.verification_due_iteration <= 0 or state.verification_due_iteration >= iteration:
        return None
    resolved_name = registry.resolve_name(call.name) or call.name
    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    if resolved_name == "Bash" and is_verification_command(arguments.get("command")):
        return None
    return ToolResult.failure(
        "verification_required",
        "生产代码修改后的下一轮必须先运行相关测试、导入/编译检查或最小复现",
        {
            "tool": call.name,
            "allowed_tool": "Bash",
            "paths": list(state.pending_verification_paths),
            "status": state.last_verification,
        },
        summary="验证闸门已拒绝本次工具调用，请先用 Bash 完成验证",
    )


def _build_user_text(user_text: str, state: AgentState, options: AgentOptions) -> str:
    if options.mode != "do" or not state.last_plan:
        return user_text
    task_text = user_text.strip() or "请根据最近计划继续执行。"
    return (
        "以下是最近一次计划，请参考它继续执行，不必原样复述计划。\n"
        f"{state.last_plan}\n\n"
        f"当前执行任务：\n{task_text}"
    )


def _is_empty_response(response: CollectedResponse) -> bool:
    return not response.text and not response.thinking and not response.tool_calls


def _empty_response_retry_prompt() -> str:
    return (
        "上一轮没有返回文本或工具调用。请继续执行用户最初的任务，不要复述本提示；"
        "可以根据需要继续调用工具。若任务已完成，请直接给出最终结果。"
    )


def _all_unknown_tool_results(outcomes: list[tuple[ToolCall, ToolResult]]) -> bool:
    if not outcomes:
        return False
    return all(
        not result.ok and result.error is not None and result.error.code == "unknown_tool"
        for _, result in outcomes
    )


def _hook_session_id(manager: HookManager | None) -> str:
    return manager.session_id if manager is not None else ""


def _dispatch_hook(manager: HookManager | None, event, state: AgentState):  # noqa: ANN001, ANN202
    if manager is None:
        return None
    try:
        return manager.dispatch(event, state.hooks)
    except Exception:
        return None


def _dispatch_turn_end(
    manager: HookManager | None,
    context: ToolContext,
    state: AgentState,
    options: AgentOptions,
    stop_reason: str,
    iteration: int,
    agent_scope: str,
) -> None:
    if manager is None:
        return
    _dispatch_hook(
        manager,
        make_event(
            "turn_end",
            session_id=manager.session_id,
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            iteration=iteration,
            agent_scope=agent_scope,
            data={"turn": {"stop_reason": stop_reason, "iterations": state.iterations}},
        ),
        state,
    )


def _dispatch_agent_error(
    manager: HookManager | None,
    context: ToolContext,
    state: AgentState,
    options: AgentOptions,
    iteration: int,
    agent_scope: str,
    error: BaseException,
) -> None:
    if manager is None:
        return
    _dispatch_hook(
        manager,
        make_event(
            "agent_error",
            session_id=manager.session_id,
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            iteration=iteration,
            agent_scope=agent_scope,
            data=error_data(error, category="provider"),
        ),
        state,
    )


def _context_callbacks(
    manager: HookManager | None,
    context: ToolContext,
    state: AgentState,
    options: AgentOptions,
    iteration: int,
    agent_scope: str,
) -> ContextLifecycleCallbacks | None:
    if manager is None:
        return None

    def before(values: dict[str, object]) -> None:
        _dispatch_hook(
            manager,
            make_event(
                "context_before_compact",
                session_id=manager.session_id,
                workspace=context.workspace,
                mode=options.mode,
                turn_id=state.hooks.turn_id,
                iteration=iteration,
                agent_scope=agent_scope,
                data=context_data(**values),
            ),
            state,
        )

    def after(report) -> None:  # noqa: ANN001
        _dispatch_hook(
            manager,
            make_event(
                "context_after_compact",
                session_id=manager.session_id,
                workspace=context.workspace,
                mode=options.mode,
                turn_id=state.hooks.turn_id,
                iteration=iteration,
                agent_scope=agent_scope,
                data=context_data(report),
            ),
            state,
        )

    return ContextLifecycleCallbacks(before_compact=before, after_compact=after)


def _hook_tool_denial(
    manager: HookManager | None,
    context: ToolContext,
    state: AgentState,
    call: ToolCall,
    iteration: int,
    options: AgentOptions,
    agent_scope: str,
) -> ToolResult | None:
    if manager is None:
        return None
    result = _dispatch_hook(
        manager,
        make_event(
            "tool_before",
            session_id=manager.session_id,
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            iteration=iteration,
            agent_scope=agent_scope,
            data=tool_data(call),
        ),
        state,
    )
    if result is None or not result.denied:
        return None
    return ToolResult.failure(
        "hook_denied",
        result.deny_reason or f"Hook {result.denied_by} 拒绝工具调用",
        {
            "tool": call.name,
            "rule_id": result.denied_by,
            "source": "hook",
        },
        f"hook denied by {result.denied_by}: {result.deny_reason}",
    )


def _dispatch_tool_after(
    manager: HookManager | None,
    context: ToolContext,
    state: AgentState,
    call: ToolCall,
    result: ToolResult,
    source: str,
    iteration: int,
    options: AgentOptions,
    agent_scope: str,
) -> None:
    if manager is None:
        return
    _dispatch_hook(
        manager,
        make_event(
            "tool_after",
            session_id=manager.session_id,
            workspace=context.workspace,
            mode=options.mode,
            turn_id=state.hooks.turn_id,
            iteration=iteration,
            agent_scope=agent_scope,
            data=tool_data(call, result, source=source),
        ),
        state,
    )


def _tool_result_source(result: ToolResult) -> str:
    if result.ok or result.error is None:
        return "tool"
    if result.error.code == "permission_denied":
        source = str(result.error.details.get("source", "permission"))
        return "plan" if "Plan Mode" in result.summary else source
    if result.error.code == "unknown_tool":
        return "registry"
    return "tool"
