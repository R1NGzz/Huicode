from __future__ import annotations

from huicode.prompts.base import PromptBundle, PromptContext, PromptInjectionPolicy, PromptModule
from huicode.prompts.modules import fixed_prompt_modules, optional_prompt_modules


def build_prompt_bundle(
    context: PromptContext,
    policy: PromptInjectionPolicy | None = None,
) -> PromptBundle:
    policy = policy or PromptInjectionPolicy()
    stable_modules = fixed_prompt_modules() + optional_prompt_modules(
        custom_instructions=context.custom_instructions,
        active_skills=context.active_skills,
        long_term_memory=context.long_term_memory,
    )
    dynamic_modules = (_environment_module(context),)
    supplemental_modules = (_mode_instruction_module(context, policy),) + _memory_modules(context)
    return PromptBundle(
        stable_modules=stable_modules,
        dynamic_modules=dynamic_modules,
        supplemental_modules=supplemental_modules,
        metadata={"mode": context.mode, "iteration": context.iteration},
    )


def _memory_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    modules: list[PromptModule] = []
    if context.memory_enabled:
        modules.append(
            PromptModule(
                name="memory_management",
                content=(
                    '<huicode_instruction type="memory_management" scope="session">\n'
                    "会话存档和长期记忆由 HuiCode 后台自动维护，不需要用户权限确认。"
                    "不要为了记录、更新或检查记忆而调用 Read、Write、Edit 或 Bash 访问 "
                    "`.huicode/sessions`、`.huicode/memory` 或用户级记忆目录；"
                    "仅当用户明确要求检查这些内部文件时才可读取。\n"
                    "</huicode_instruction>"
                ),
                stable=False,
                cacheable=False,
            )
        )
    if context.memory_index.strip():
        modules.append(
            PromptModule(
                name="memory_index",
                content=(
                    '<huicode_context type="memory_index" scope="long_term">\n'
                    f"{context.memory_index.strip()}\n\n"
                    "如果需要文件细节，请重新读取 source 指向的笔记或项目文件，不要只凭索引脑补。\n"
                    "</huicode_context>"
                ),
                stable=False,
                cacheable=False,
            )
        )
    if context.memory_warnings:
        warnings = "\n".join(f"- {warning}" for warning in context.memory_warnings)
        modules.append(
            PromptModule(
                name="memory_warnings",
                content=(
                    '<huicode_context type="memory_warnings" scope="turn">\n'
                    f"{warnings}\n"
                    "</huicode_context>"
                ),
                stable=False,
                cacheable=False,
            )
        )
    return tuple(modules)


def _environment_module(context: PromptContext) -> PromptModule:
    tools = ", ".join(context.available_tools) if context.available_tools else "none"
    read_only = ", ".join(context.read_only_tool_names) if context.read_only_tool_names else "none"
    workspace = context.workspace.as_posix()
    content = (
        '<huicode_context type="environment" scope="turn">\n'
        f"workspace: {workspace}\n"
        f"platform: {context.platform}\n"
        f"shell: {context.shell}\n"
        f"now: {context.now}\n"
        f"mode: {context.mode}\n"
        f"iteration: {context.iteration}\n"
        f"max_iterations: {context.max_iterations}\n"
        f"available_tools: {tools}\n"
        f"read_only_tools: {read_only}\n"
        "</huicode_context>"
    )
    return PromptModule(name="environment", content=content, stable=False, cacheable=False)


def _mode_instruction_module(context: PromptContext, policy: PromptInjectionPolicy) -> PromptModule:
    if context.mode == "plan":
        instruction_type = "plan_mode"
        body = _plan_mode_body(context, policy)
    else:
        instruction_type = "execution_mode"
        body = _execution_mode_body(context, policy)
    return PromptModule(
        name=instruction_type,
        content=(
            f'<huicode_instruction type="{instruction_type}" scope="turn">\n'
            f"{body}\n"
            "</huicode_instruction>"
        ),
        stable=False,
        cacheable=False,
    )


def _is_full_iteration(context: PromptContext, policy: PromptInjectionPolicy) -> bool:
    return context.iteration == 1 or (
        policy.repeat_every > 0 and context.iteration % policy.repeat_every == 0
    )


def _plan_mode_body(context: PromptContext, policy: PromptInjectionPolicy) -> str:
    if _is_full_iteration(context, policy):
        return (
            "当前是 Plan Mode。只能使用读类工具：Read、Find、Search、Glob。"
            "请先调查事实，再输出可执行计划；不要写文件、改文件或执行有副作用命令。"
        )
    return "Plan Mode：保持只读，只输出下一步计划和依据。"


def _execution_mode_body(context: PromptContext, policy: PromptInjectionPolicy) -> str:
    if _is_full_iteration(context, policy):
        base = (
            "当前是执行模式。可以使用可用工具完成任务。编辑前必须先读；优先使用专用工具；"
            "尊重 workspace 边界；不要编造工具结果。"
        )
        if context.last_plan:
            return f"{base}\n最近计划摘要：\n{context.last_plan}"
        return base
    return "执行模式：根据工具结果推进任务，保持最小必要操作。"
