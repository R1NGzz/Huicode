import unittest

from huicode.agent_events import AgentState
from huicode.context.estimator import TokenEstimator
from huicode.prompts.base import PromptBundle, PromptModule
from huicode.providers.base import ConversationMessage, ToolCall, ToolSpec
from huicode.tools.base import ToolResult


class ContextEstimatorTests(unittest.TestCase):
    def test_estimates_message_with_tool_result_and_thinking(self) -> None:
        estimator = TokenEstimator()
        message = ConversationMessage(
            role="assistant",
            content="结论",
            thinking="推理",
            thinking_signature="sig-1",
            tool_calls=[ToolCall("call_1", "Read", {"path": "README.md"}, raw_arguments='{"path":"README.md"}')],
        )

        estimate = estimator.estimate_message(message)

        self.assertGreater(estimate.tokens, 0)
        self.assertGreater(estimate.chars, len("结论"))

    def test_estimates_request_with_prompt_and_tools(self) -> None:
        estimator = TokenEstimator()
        prompt = PromptBundle(stable_modules=(PromptModule("system", "固定提示"),))
        tools = [ToolSpec("Read", "读取文件", {"type": "object"})]
        messages = [ConversationMessage("user", "你好")]

        estimate = estimator.estimate_request(messages, prompt, tools)

        self.assertGreater(estimate.tokens, estimator.estimate_messages(messages).tokens)
        self.assertEqual(estimate.source, "chars")

    def test_usage_anchor_updates_future_estimates(self) -> None:
        estimator = TokenEstimator()
        state = AgentState().context
        first_messages = [ConversationMessage("user", "a" * 80)]
        first = estimator.estimate_request(first_messages, None, None, state)

        estimator.record_usage(state, {"input_tokens": 100}, first)
        second_messages = [ConversationMessage("user", "a" * 120)]
        second = estimator.estimate_request(second_messages, None, None, state)

        self.assertEqual(state.last_input_tokens, 100)
        self.assertEqual(second.source, "usage_anchor")
        self.assertGreaterEqual(second.tokens, 110)

    def test_prompt_tokens_fallback_is_recorded(self) -> None:
        estimator = TokenEstimator()
        state = AgentState().context
        estimate = estimator.estimate_request([ConversationMessage("user", "hello")], None, None, state)

        estimator.record_usage(state, {"prompt_tokens": 33}, estimate)

        self.assertEqual(state.last_input_tokens, 33)

    def test_estimates_tool_message_json(self) -> None:
        estimator = TokenEstimator()
        message = ConversationMessage(
            role="tool",
            content="ok",
            tool_call_id="call_1",
            tool_name="Read",
            tool_result=ToolResult.success({"content": "x" * 300}, "ok"),
        )

        estimate = estimator.estimate_message(message)

        self.assertGreater(estimate.tokens, 50)


if __name__ == "__main__":
    unittest.main()

