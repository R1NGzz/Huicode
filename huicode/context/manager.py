from __future__ import annotations

from pathlib import Path

from huicode.config import ContextConfig, LLMConfig
from huicode.context.estimator import TokenEstimate, TokenEstimator
from huicode.context.history import apply_summary, split_recent_messages
from huicode.context.lightweight import compact_single_tool_result, compact_tool_groups
from huicode.context.state import ContextState
from huicode.context.store import ToolResultStore
from huicode.context.summarizer import HistorySummarizer
from huicode.context.types import ContextCompressionReport, ContextPreparation
from huicode.prompts import PromptBundle
from huicode.providers.base import ConversationMessage, Provider, ToolCall, ToolSpec
from huicode.tools.base import ToolContext, ToolResult


class ContextManager:
    def __init__(
        self,
        workspace: Path,
        settings: ContextConfig,
        estimator: TokenEstimator | None = None,
        summarizer: HistorySummarizer | None = None,
    ) -> None:
        self.workspace = workspace
        self.settings = settings
        self.estimator = estimator or TokenEstimator()
        self.summarizer = summarizer or HistorySummarizer()
        self.store = ToolResultStore(workspace, self.estimator)

    def compact_tool_result(
        self,
        call: ToolCall,
        result: ToolResult,
        context: ToolContext,
        iteration: int,
    ) -> tuple[ToolResult, ContextCompressionReport | None]:
        _ = context
        if not self.settings.enabled:
            return result, None
        compacted, spill = compact_single_tool_result(
            call,
            result,
            self.store,
            self.settings,
            self.estimator,
            iteration,
        )
        if spill is None:
            return result, None
        return compacted, ContextCompressionReport(
            kind="lightweight",
            spilled_count=1,
            tokens_freed=spill.tokens_freed,
            message="spilled 1 tool result(s) to disk",
            paths=(spill.path,),
        )

    def prepare_before_request(
        self,
        provider: Provider,
        state,
        context: ToolContext,
        config: LLMConfig,
        prompt: PromptBundle | None,
        tools: list[ToolSpec] | None,
    ) -> ContextPreparation:
        _ = context
        if not self.settings.enabled:
            estimate = self.estimator.estimate_request(state.messages, prompt, tools, state.context)
            return ContextPreparation(request_tokens=estimate.tokens, request_chars=estimate.chars)

        reports: list[ContextCompressionReport] = []
        updated_messages, report = compact_tool_groups(
            state.messages,
            self.store,
            self.settings,
            self.estimator,
            max(1, state.iterations),
        )
        history_changed = updated_messages != state.messages
        if history_changed:
            _replace_messages_in_place(state.messages, updated_messages)
        if report is not None:
            reports.append(report)

        estimate = self.estimator.estimate_request(state.messages, prompt, tools, state.context)
        threshold = self.settings.window_tokens - self.settings.auto_margin_tokens
        if estimate.tokens < threshold:
            return ContextPreparation(
                request_tokens=estimate.tokens,
                request_chars=estimate.chars,
                history_changed=history_changed,
                reports=tuple(reports),
            )

        if state.context.summary_fuse_open:
            reports.append(
                ContextCompressionReport(
                    kind="fuse",
                    tokens_before=estimate.tokens,
                    tokens_after=estimate.tokens,
                    message="上下文摘要已熔断，本轮仅执行轻量压缩",
                )
            )
            return ContextPreparation(
                request_tokens=estimate.tokens,
                request_chars=estimate.chars,
                history_changed=history_changed,
                reports=tuple(reports),
            )

        summary_report = self._run_summary(provider, state, config, prompt, tools, manual=False)
        reports.append(summary_report)
        if summary_report.kind == "summary":
            history_changed = True
        estimate = self.estimator.estimate_request(state.messages, prompt, tools, state.context)
        return ContextPreparation(
            request_tokens=estimate.tokens,
            request_chars=estimate.chars,
            history_changed=history_changed,
            reports=tuple(reports),
        )

    def manual_compact(
        self,
        provider: Provider,
        state,
        context: ToolContext,
        config: LLMConfig,
        prompt: PromptBundle | None,
        tools: list[ToolSpec] | None,
    ) -> ContextCompressionReport:
        _ = context, prompt, tools
        if not self.settings.enabled:
            return ContextCompressionReport(kind="skip", message="上下文管理未启用")
        updated_messages, report = compact_tool_groups(
            state.messages,
            self.store,
            self.settings,
            self.estimator,
            max(1, state.iterations),
        )
        if updated_messages != state.messages:
            _replace_messages_in_place(state.messages, updated_messages)
        if report is not None:
            return report
        return self._run_summary(provider, state, config, None, None, manual=True)

    def record_usage(self, state, usage: dict[str, object], request_estimate: TokenEstimate) -> None:
        self.estimator.record_usage(state.context, usage, request_estimate)

    def reset(self, state) -> None:
        state.context.reset()

    def _run_summary(
        self,
        provider: Provider,
        state,
        config: LLMConfig,
        prompt: PromptBundle | None,
        tools: list[ToolSpec] | None,
        manual: bool,
    ) -> ContextCompressionReport:
        _ = prompt, tools
        before = self.estimator.estimate_messages(state.messages).tokens
        older, recent = split_recent_messages(state.messages, self.settings, self.estimator)
        if not older or not recent:
            return ContextCompressionReport(kind="skip", tokens_before=before, tokens_after=before, message="没有可压缩的早期历史")

        threshold = self.settings.window_tokens - (
            self.settings.manual_margin_tokens if manual else self.settings.auto_margin_tokens
        )
        if not manual and before < threshold:
            return ContextCompressionReport(kind="skip", tokens_before=before, tokens_after=before, message="当前历史尚未接近窗口上限")

        summary = self.summarizer.summarize(provider, older, config)
        if not summary.ok:
            state.context.summary_failure_count += 1
            if state.context.summary_failure_count >= self.settings.max_summary_failures:
                state.context.summary_fuse_open = True
            state.context.last_compaction_reason = "summary_failure"
            return ContextCompressionReport(
                kind="failure",
                tokens_before=before,
                tokens_after=before,
                message=summary.error_message,
            )

        _replace_messages_in_place(state.messages, apply_summary(older, recent, summary.summary_text))
        after = self.estimator.estimate_messages(state.messages).tokens
        state.context.summary_failure_count = 0
        state.context.summary_fuse_open = False
        state.context.summary_count += 1
        state.context.last_summary_tokens_freed = max(0, before - after)
        state.context.last_compaction_reason = "summary"
        return ContextCompressionReport(
            kind="summary",
            summary_created=True,
            tokens_before=before,
            tokens_after=after,
            tokens_freed=max(0, before - after),
            message="summary created",
        )


def _replace_messages_in_place(target: list[ConversationMessage], replacement: list[ConversationMessage]) -> None:
    target[:] = replacement
