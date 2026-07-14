from __future__ import annotations

from collections.abc import Callable

from huicode.tools.base import ToolContext, ToolResult

from .catalog import SkillConfigError
from .manager import SkillManager
from .types import SkillRunResult, SkillRuntimeState


IsolatedRunner = Callable[[str, str], SkillRunResult]


class SkillTool:
    name = "Skill"
    description = (
        "按名称加载一个可复用 Skill 的完整 SOP。先根据系统提供的 Skill 目录选择名称；"
        "shared Skill 会继续当前对话，isolated Skill 会在独立上下文执行并返回摘要。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill 唯一名称"},
            "arguments": {"type": "string", "description": "传给 Skill 的原始任务参数"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    # 激活会修改会话状态，isolated 模式还会启动子 Agent，因此必须串行执行。
    side_effect = True

    def __init__(
        self,
        manager: SkillManager,
        state: SkillRuntimeState,
        isolated_runner: IsolatedRunner | None = None,
    ) -> None:
        self.manager = manager
        self.state = state
        self.isolated_runner = isolated_runner

    def run(self, args: dict, context: ToolContext) -> ToolResult:  # noqa: ARG002
        name = args.get("name")
        arguments = args.get("arguments", "")
        if not isinstance(name, str) or not name.strip():
            return ToolResult.failure("invalid_arguments", "Skill.name 必须是非空字符串")
        if not isinstance(arguments, str):
            return ToolResult.failure("invalid_arguments", "Skill.arguments 必须是字符串")
        definition = self.manager.get(name)
        if definition is None:
            return ToolResult.failure(
                "unknown_skill",
                f"未知 Skill: {name}",
                {"skill": name},
            )
        if definition.mode == "isolated":
            if self.isolated_runner is None:
                return ToolResult.failure(
                    "isolated_runner_unavailable",
                    f"Skill {definition.name} 的隔离执行器不可用",
                    {"skill": definition.name},
                )
            result = self.isolated_runner(definition.name, arguments)
            data = {
                "skill": definition.name,
                "mode": definition.mode,
                "source": definition.source,
                "status": result.status,
                "iterations": result.iterations,
                "stop_reason": result.stop_reason,
                "summary": result.summary,
            }
            if result.ok:
                return ToolResult.success(data, f"{definition.name} 完成: {result.summary}")
            return ToolResult.failure(
                "skill_run_failed",
                result.summary,
                data,
                summary=f"{definition.name} 执行失败: {result.summary}",
            )
        try:
            self.manager.activate_shared(self.state, definition.name, arguments)
        except SkillConfigError as exc:
            return ToolResult.failure("skill_activation_failed", str(exc), {"skill": definition.name})
        return ToolResult.success(
            {
                "skill": definition.name,
                "mode": definition.mode,
                "source": definition.source,
            },
            f"已激活 {definition.name} [{definition.mode}]",
        )
