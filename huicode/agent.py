from __future__ import annotations

import json
import os
import platform
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO

from huicode.context import ContextManager, TokenEstimate
from huicode.agent_events import AgentEvent, AgentOptions, AgentState, CollectedResponse, ToolBatch
from huicode.config import LLMConfig
from huicode.prompts import PromptBundle, PromptContext, build_prompt_bundle, enhance_tool_specs, normalize_cache_usage
from huicode.providers.base import ConversationMessage, Provider, ToolCall
from huicode.sse import APIError
from huicode.skills.manager import SkillManager
from huicode.tools.base import ToolContext, ToolResult
from huicode.tools.executor import execute_tool_call
from huicode.tools.registry import ToolRegistry
from huicode.tui import render_agent_event


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
) -> Iterator[AgentEvent]:
    try:
        yield from _run_agent_loop_impl(
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
        )
    finally:
        state.skills.turn_model_override = None


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
) -> Iterator[AgentEvent]:
    state.cancel_requested = False
    state.iterations = 0
    state.unknown_tool_count = 0
    empty_response_count = 0
    override_providers: dict[str, Provider] = {}
    context_manager = ContextManager(context.workspace, config.context)
    turn_start = len(state.messages)
    user_message = ConversationMessage(role="user", content=_build_user_text(user_text, state, options))
    state.messages.append(user_message)
    if memory is not None:
        memory.record_message(state, user_message)

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
            },
        )
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
            prompt = build_agent_prompt(
                context=context,
                registry=registry,
                state=state,
                options=options,
                iteration=iteration,
                skill_manager=skill_manager,
            )
            selected_tools = select_tools(registry, options, state, skill_manager)
            preparation = context_manager.prepare_before_request(
                provider=current_provider,
                state=state,
                context=context,
                config=config,
                prompt=prompt,
                tools=selected_tools,
            )
            request_estimate = TokenEstimate(
                tokens=preparation.request_tokens,
                chars=preparation.request_chars,
                source="chars",
            )
            for report in preparation.reports:
                yield AgentEvent(kind="context", iteration=iteration, data=report.to_dict())
            response = yield from collect_model_response(
                provider=current_provider,
                messages=state.messages,
                tools=selected_tools,
                prompt=prompt,
                iteration=iteration,
            )
            if response.usage:
                context_manager.record_usage(state, response.usage, request_estimate)
        except KeyboardInterrupt:
            state.cancel_requested = True
            yield AgentEvent(
                kind="done",
                iteration=iteration,
                stop_reason="cancelled",
                data={"message": "生成已中断。"},
            )
            return
        except (APIError, RuntimeError, ValueError) as exc:
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

        if _is_empty_response(response):
            empty_response_count += 1
            if empty_response_count <= options.max_empty_responses:
                state.messages.append(ConversationMessage(role="user", content=_empty_response_retry_prompt()))
                continue
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

        if not response.tool_calls:
            state.unknown_tool_count = 0
            if options.mode == "plan" and response.text:
                state.last_plan = response.text
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
) -> PromptBundle:
    selected_tools = select_tools(registry, options, state, skill_manager)
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
        skill_catalog=(skill_manager.catalog_items() if skill_manager is not None else ()),
    )
    return build_prompt_bundle(prompt_context)


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
            futures = []
            for index, call in enumerate(batch.parallel_read_calls):
                denied = _plan_mode_denial(registry, call, options)
                if denied is not None:
                    results[index] = denied
                    continue
                futures.append((index, executor.submit(execute_tool_call, registry, call, context)))
            for index, future in futures:
                results[index] = future.result()
        for call, result in zip(batch.parallel_read_calls, results, strict=False):
            if result is None:
                result = ToolResult.failure("tool_exception", "工具执行未返回结果", {"tool": call.name})
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
        result = _plan_mode_denial(registry, call, options)
        if result is None:
            result = execute_tool_call(registry, call, context)
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
        "上一轮没有返回任何可显示内容。请不要复述本提示，也不要再次调用工具；"
        "请直接根据已有工具结果，用中文回答用户最初的问题。"
    )


def _all_unknown_tool_results(outcomes: list[tuple[ToolCall, ToolResult]]) -> bool:
    if not outcomes:
        return False
    return all(
        not result.ok and result.error is not None and result.error.code == "unknown_tool"
        for _, result in outcomes
    )
