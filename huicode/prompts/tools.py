from __future__ import annotations

from dataclasses import replace

from huicode.providers.base import ToolSpec


COMMON_RULES = (
    "通用规则：优先使用最贴合任务的专用工具；不要编造工具结果；"
    "所有路径都必须尊重 workspace 边界。"
)

TOOL_RULES = {
    "Read": "读取文件真实内容；分析或编辑文件前优先调用它确认现状。",
    "Write": "写入会覆盖目标文件；只有在明确需要创建或整体替换文件时使用。",
    "Edit": "编辑前必须先 Read；old_text 必须在原文中唯一匹配，匹配不到或多次匹配都应让模型重试。",
    "Bash": "执行命令前确认是否真的需要 shell；查找文件优先用 Find，搜索内容优先用 Search；不要越过 workspace 边界。",
    "Find": "按 glob 模式找文件；用于定位路径时优先于 Bash。",
    "Search": "搜索代码或文本内容；用于定位符号、配置和错误文本时优先于 Bash。",
}


def enhance_tool_specs(specs: list[ToolSpec]) -> list[ToolSpec]:
    enhanced: list[ToolSpec] = []
    for spec in specs:
        extra = TOOL_RULES.get(spec.name, "")
        if extra:
            description = f"{spec.description}\n\n{COMMON_RULES}\n{extra}"
        else:
            description = f"{spec.description}\n\n{COMMON_RULES}"
        enhanced.append(replace(spec, description=description))
    return enhanced
