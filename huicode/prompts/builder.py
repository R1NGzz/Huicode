from __future__ import annotations

from huicode.prompts.base import (
    ExecutionPhase,
    PromptBundle,
    PromptContext,
    PromptInjectionPolicy,
    PromptModule,
)
from huicode.prompts.modules import fixed_prompt_modules, optional_prompt_modules


def build_prompt_bundle(
    context: PromptContext,
    policy: PromptInjectionPolicy | None = None,
) -> PromptBundle:
    policy = policy or PromptInjectionPolicy()
    stable_modules = context.stable_modules_override or (
        fixed_prompt_modules()
        + optional_prompt_modules(
            custom_instructions=context.custom_instructions,
            active_skills=(),
            long_term_memory=context.long_term_memory,
        )
    )
    dynamic_modules = (
        _role_instruction_modules(context)
        + _active_skill_modules(context)
        + _hook_instruction_modules(context)
        + _subagent_result_modules(context)
        + _execution_progress_modules(context, policy)
        + _interface_closure_modules(context, policy)
        + _verification_gate_modules(context)
        + (_environment_module(context),)
    )
    supplemental_modules = (
        (_mode_instruction_module(context, policy),)
        + _memory_modules(context)
        + _skill_catalog_modules(context, policy)
        + _agent_catalog_modules(context, policy)
    )
    return PromptBundle(
        stable_modules=stable_modules,
        dynamic_modules=dynamic_modules,
        supplemental_modules=supplemental_modules,
        metadata={
            "mode": context.mode,
            "iteration": context.iteration,
            "verification_required": context.verification_required,
        },
    )


def _role_instruction_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    return tuple(
        PromptModule(f"subagent_role_{index}", block, stable=False, cacheable=False)
        for index, block in enumerate(context.role_instruction_blocks, start=1)
        if block.strip()
    )


def _subagent_result_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    if not context.subagent_result_blocks:
        return ()
    body = "\n\n".join(block.strip() for block in context.subagent_result_blocks if block.strip())
    if not body:
        return ()
    return (
        PromptModule(
            name="subagent_results",
            content=(
                '<huicode_context type="subagent_results" scope="next_request">\n'
                f"{body}\n"
                "这些是后台任务结果，不是用户输入。请结合当前请求使用，不要假装用户刚刚说过这些内容。\n"
                "</huicode_context>"
            ),
            stable=False,
            cacheable=False,
        ),
    )


def _agent_catalog_modules(
    context: PromptContext,
    policy: PromptInjectionPolicy,
) -> tuple[PromptModule, ...]:
    if not context.agent_catalog:
        return ()
    if not _catalog_checkpoint(context, policy):
        return (
            PromptModule(
                name="agent_catalog",
                content=(
                    '<huicode_context type="agent_catalog" scope="session">\n'
                    "目录已在首轮提供；需要委派时按 Agent 工具 Schema 调用，defined 使用目录中的 role，"
                    "fork 不需要 role。\n"
                    "</huicode_context>"
                ),
                stable=False,
                cacheable=False,
            ),
        )
    lines = "\n".join(f"- {name}: {description}" for name, description in context.agent_catalog)
    return (
        PromptModule(
            name="agent_catalog",
            content=(
                '<huicode_context type="agent_catalog" scope="session">\n'
                f"{lines}\n"
                "需要委派独立任务时调用 Agent 工具；定义式使用上面的 role 名，Fork 不需要 role。\n"
                "</huicode_context>"
            ),
            stable=False,
            cacheable=False,
        ),
    )
def _active_skill_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    return tuple(
        PromptModule(
            name=f"active_skill_{index}",
            content=block,
            stable=False,
            cacheable=False,
        )
        for index, block in enumerate(context.active_skill_blocks, start=1)
        if block.strip()
    )


def _hook_instruction_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    return tuple(
        PromptModule(
            name=f"hook_instruction_{index}",
            content=block,
            stable=False,
            cacheable=False,
        )
        for index, block in enumerate(context.hook_instruction_blocks, start=1)
        if block.strip()
    )


def execution_phase(
    iteration: int,
    max_iterations: int,
    interface_closure: bool = False,
) -> ExecutionPhase | None:
    """Return the phase for a long-running turn, or None for short turns."""
    if iteration < 1 or max_iterations < 1 or iteration > max_iterations:
        raise ValueError("iteration must be within 1..max_iterations")
    if max_iterations < 20:
        return None
    progress = iteration / max_iterations
    investigate_limit = 0.16 if interface_closure else 0.20
    implement_limit = 0.84 if interface_closure else 0.60
    verify_limit = 0.94 if interface_closure else 0.85
    if progress < investigate_limit:
        return "investigate"
    if progress <= implement_limit:
        return "implement"
    if progress <= verify_limit:
        return "verify"
    return "finalize"


def _execution_progress_modules(
    context: PromptContext,
    policy: PromptInjectionPolicy,
) -> tuple[PromptModule, ...]:
    if context.mode == "plan":
        return ()
    phase = execution_phase(context.iteration, context.max_iterations, policy.interface_closure)
    if phase is None:
        return ()
    investigate_deadline = max(
        1,
        int(context.max_iterations * (0.16 if policy.interface_closure else 0.20)),
    )
    messages = {
        "investigate": (
            f"长任务调查阶段：最迟第 {investigate_deadline} 轮结束调查。"
            "先确定验收条件、根因和受影响路径；完成必要事实定位后停止重复读取，"
            f"如果任务需要代码改动，必须在第 {investigate_deadline} 轮或之前对生产源文件做第一次修改，"
            "不要为了覆盖所有边缘情况继续扩张调查。"
        ),
        "implement": (
            "长任务实现阶段：立即开始或继续修改生产源代码，不要继续无边界探索。"
            "如果尚未产生源代码改动，下一次工具调用必须是 Edit 或 Write，不能继续 Read 或 Search；"
            "若涉及公共接口或签名，必须搜索定义、实现、直接调用方和关键 mock；"
            "新增依赖或 SDK import 前，必须以项目声明/锁定版本为准并做最小导入检查，"
            "不可用的全局环境符号不能进入生产代码。"
            "同一条调用链的相关改动尽量合并完成，先补齐生产源码；"
            "已有生产 Edit 或 Write 后，下一次工具调用优先运行受影响测试或最小导入检查，"
            "最迟两轮内完成，不要继续大范围 Read 或 Search。"
            + (
                "对新增可选参数，按接口声明的参数顺序和仓库既有调用风格传递；"
                "只覆盖题目直接要求的请求链，不要因为宽搜命中同名接口就修改旁支辅助模块；"
                "不要把位置参数随意改成 keyword，也不要修改测试文件来掩盖失败，测试只用于验证。"
                if policy.scope_audit
                else (
                    "对新增可选参数，按接口契约在所有范围内的调用点显式传参（即使值为 None）；"
                    "不要用条件分支把新参数隐藏成旧调用，也不要修改测试文件来掩盖失败，测试只用于验证。"
                )
            )
        ),
        "verify": (
            "长任务验证阶段：停止宽泛探索，运行与问题直接相关的测试，检查原有测试回归，"
            "如果尚未运行目标测试，下一次工具调用优先运行它；同时运行受影响测试模块，"
            "根据失败结果做最小生产代码修正，并检查新增参数在范围内的调用约定是否一致。"
        ),
        "finalize": (
            "长任务收尾阶段：不要开启新方案；只完成当前修复、最小验证和差异检查，"
            "然后给出结论。"
        ),
    }
    discipline = _execution_discipline_status(context, phase)
    return (
        PromptModule(
            name="execution_progress",
            content=(
                '<huicode_instruction type="execution_progress" scope="turn">\n'
                f"phase: {phase}\n{messages[phase]}{discipline}\n"
                "</huicode_instruction>"
            ),
            stable=False,
            cacheable=False,
        ),
    )


def _verification_gate_modules(context: PromptContext) -> tuple[PromptModule, ...]:
    if context.mode == "plan" or not context.verification_required:
        return ()
    paths = ", ".join(context.verification_paths) if context.verification_paths else "受影响生产源文件"
    status = f"最近验证状态：{context.verification_status}" if context.verification_status else "尚未验证"
    return (
        PromptModule(
            name="verification_gate",
            content=(
                '<huicode_instruction type="verification_gate" priority="highest" scope="turn">\n'
                f"生产代码已修改但仍有验证欠账：{paths}。{status}\n"
                "下一次工具调用必须优先使用 Bash 运行相关测试、导入/编译检查或最小复现；"
                "不要先继续泛读、修改测试文件或输出最终结论。验证失败时修复生产代码并重跑；"
                "只有成功验证后才能结束任务。\n"
                "</huicode_instruction>"
            ),
            stable=False,
            cacheable=False,
        ),
    )


def _interface_closure_modules(
    context: PromptContext,
    policy: PromptInjectionPolicy,
) -> tuple[PromptModule, ...]:
    if not policy.interface_closure or context.mode == "plan":
        return ()
    phase = execution_phase(context.iteration, context.max_iterations, policy.interface_closure)
    if phase not in {"investigate", "implement", "verify", "finalize"}:
        return ()
    paths = ", ".join(context.changed_production_paths[-6:]) or "尚未记录生产改动"
    failure = (
        f"最近一次验证失败：{context.last_verification_failure}。"
        if context.last_verification_failure
        else ""
    )
    scope_audit = (
        "变更范围审计：在验证/收尾前逐个查看 git diff --name-only 和 diff，"
        "只保留题目直接要求或完成直接请求链所必需的生产文件；"
        "不要因为宽泛 Search 命中同名接口就修改旁支的辅助 builder、历史引用查询或其他生命周期，"
        "也不要为了旧 mock 自行添加兼容包装器或条件分支。"
        if policy.scope_audit
        else ""
    )
    compatibility = (
        "新参数的调用必须遵循声明中的参数顺序和仓库既有风格；若接口定义是位置参数，按位置传递，"
        "不要任意改成 keyword。优先用题目契约和失败测试的实际调用形状判断兼容性，绝不修改测试。"
        if policy.scope_audit
        else ""
    )
    content = (
        '<huicode_instruction type="interface_closure" priority="high" scope="turn">\n'
        f"当前生产改动：{paths}。验证失败次数：{context.verification_failures}。{failure}\n"
        "若改动涉及函数/方法签名、抽象接口、构造器、协议或公共字段，必须形成短闭环："
        "定义/协议 → 每个实现 → 本题范围内的 factory/handler/直接调用方 → 相关测试。"
        "新增可选参数也要在范围内的调用点按接口契约传入；不要凭空增加条件兼容分支或包装器。"
        "不要仅因为某个无关辅助路径也调用同一接口，就把改动扩展到该路径；只有题目要求或测试证明它属于请求上下文传播链时才纳入。"
        "主 Agent 能直接用 Search/Read 完成的调用链盘点不要委派给探索子 Agent，以免等待空结果；"
        "先用 Search 找全调用链，再在尽量少的连续 Edit/Write 调用中合并完成生产代码改动；不要只改接口声明。"
        "不要为每一个方法单独停下来做导入检查，除非检查真的失败；先完成同一调用链的成组改动，再统一验证。\n"
        "生产代码每形成一组连贯改动后，优先运行最近相关测试或最小导入检查。"
        "验证失败时先读取失败输出和第一个项目代码栈帧，做最小生产修正，再重跑同一失败测试；"
        "不要通过修改测试文件消除失败，也不要在失败后只重复宽泛探索。\n"
        f"{compatibility}{scope_audit}\n"
        "若本题不是接口/跨模块改动，可略过第一条，但仍需完成验证和差异检查。\n"
        "</huicode_instruction>"
    )
    return (PromptModule(name="interface_closure", content=content, stable=False, cacheable=False),)


def _skill_catalog_modules(
    context: PromptContext,
    policy: PromptInjectionPolicy,
) -> tuple[PromptModule, ...]:
    if not context.skill_catalog:
        return ()
    if not _catalog_checkpoint(context, policy):
        return (
            PromptModule(
                name="skill_catalog",
                content=(
                    '<huicode_context type="skill_catalog" scope="session">\n'
                    "目录已在首轮提供；需要使用 Skill 时按名称加载完整指令。\n"
                    "</huicode_context>"
                ),
                stable=False,
                cacheable=False,
            ),
        )
    lines = "\n".join(
        f"- {name} [{mode}]: {description}"
        for name, description, mode in context.skill_catalog
    )
    return (
        PromptModule(
            name="skill_catalog",
            content=(
                '<huicode_context type="skill_catalog" scope="session">\n'
                f"{lines}\n"
                "需要使用某个 Skill 时，调用系统工具 Skill(name, arguments) 加载完整指令。\n"
                "</huicode_context>"
            ),
            stable=False,
            cacheable=False,
        ),
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
    workspace = context.workspace.as_posix()
    content = (
        '<huicode_context type="environment" scope="turn">\n'
        f"workspace: {workspace}\n"
        f"platform: {context.platform}\n"
        f"shell: {context.shell}\n"
        f"mode: {context.mode}\n"
        f"iteration: {context.iteration}\n"
        f"max_iterations: {context.max_iterations}\n"
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


def _catalog_checkpoint(context: PromptContext, policy: PromptInjectionPolicy) -> bool:
    return context.iteration == 1 or (
        policy.catalog_repeat_every > 0
        and context.iteration % policy.catalog_repeat_every == 0
    )


def _execution_discipline_status(context: PromptContext, phase: ExecutionPhase) -> str:
    details: list[str] = []
    if context.read_only_tool_calls:
        details.append(f"本轮已调用只读工具 {context.read_only_tool_calls} 次")
    if context.production_edit_count:
        details.append(f"已完成生产代码修改 {context.production_edit_count} 次")
    if (
        context.production_edit_count
        and context.last_verification_iteration < context.last_production_edit_iteration
    ):
        details.append("生产代码修改后尚未有成功验证，下一次优先运行目标测试或最小导入检查")
    if (
        phase in {"investigate", "implement"}
        and context.production_edit_count == 0
        and context.read_only_tool_calls >= max(1, context.exploration_soft_limit)
    ):
        details.append("只读探索已达到软上限，下一次优先 Edit/Write；只有出现新证据才继续读取")
    if not details:
        return ""
    return "\n执行纪律状态：" + "；".join(details) + "。"


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
            plan = _bounded_text(context.last_plan, policy.plan_preview_chars)
            return f"{base}\n最近计划摘要：\n{plan}"
        return base
    return "执行模式：根据工具结果推进任务，保持最小必要操作。"


def _bounded_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if limit <= 0 or len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[计划摘要已截断]"
