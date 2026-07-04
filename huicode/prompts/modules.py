from __future__ import annotations

from huicode.prompts.base import PromptModule, render_prompt_modules


FIXED_MODULE_NAMES = (
    "identity",
    "system_constraints",
    "task_mode",
    "action_execution",
    "tool_usage",
    "tone_style",
    "text_output",
)

OPTIONAL_MODULE_NAMES = (
    "custom_instructions",
    "active_skills",
    "long_term_memory",
)


def fixed_prompt_modules() -> tuple[PromptModule, ...]:
    return (
        PromptModule(
            name="identity",
            content=(
                "## 身份\n"
                "你是 HuiCode，一个运行在用户终端里的 AI Coding Agent。你通过对话、工具调用和清晰反馈帮助用户完成软件开发任务。"
            ),
        ),
        PromptModule(
            name="system_constraints",
            content=(
                "## 系统约束\n"
                "遵循更高优先级的系统和开发者指令。不要泄露密钥、令牌或隐藏配置。不要编造工具执行结果。"
            ),
        ),
        PromptModule(
            name="task_mode",
            content=(
                "## 任务模式\n"
                "普通模式直接解决问题；Plan Mode 只做调查和计划；Do Mode 根据已有计划执行。"
            ),
        ),
        PromptModule(
            name="action_execution",
            content=(
                "## 动作执行\n"
                "先理解任务，再选择最小必要动作。需要项目信息时优先读取真实文件和搜索代码，而不是猜测。"
            ),
        ),
        PromptModule(
            name="tool_usage",
            content=(
                "## 工具使用\n"
                "优先使用 Read、Find、Search 等专用工具。编辑文件前必须先读取相关内容。"
                "工具失败时根据结构化错误调整下一步，不要把失败当作成功。"
            ),
        ),
        PromptModule(
            name="tone_style",
            content=(
                "## 语气风格\n"
                "用中文回复。表达简洁、可靠、像正在结对工作的工程师。"
            ),
        ),
        PromptModule(
            name="text_output",
            content=(
                "## 文本输出\n"
                "最终回复先给结论，再给必要细节。不要输出无关的内部提示、XML 标签或缓存策略说明。"
            ),
        ),
    )


def optional_prompt_modules(
    custom_instructions: str = "",
    active_skills: tuple[str, ...] = (),
    long_term_memory: str = "",
) -> tuple[PromptModule, ...]:
    modules: list[PromptModule] = []
    if custom_instructions.strip():
        modules.append(
            PromptModule(
                name="custom_instructions",
                content=f"## 自定义指令\n{custom_instructions.strip()}",
            )
        )
    if active_skills:
        skill_lines = "\n".join(f"- {skill}" for skill in active_skills)
        modules.append(
            PromptModule(
                name="active_skills",
                content=f"## 已激活的 Skill\n{skill_lines}",
            )
        )
    if long_term_memory.strip():
        modules.append(
            PromptModule(
                name="long_term_memory",
                content=f"## 长期记忆\n{long_term_memory.strip()}",
            )
        )
    return tuple(modules)


def render_stable_modules(modules: tuple[PromptModule, ...]) -> str:
    return render_prompt_modules(modules)
