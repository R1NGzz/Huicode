import unittest

from huicode.prompts import normalize_cache_usage


class PromptCacheTests(unittest.TestCase):
    def test_anthropic_cache_fields_are_normalized(self) -> None:
        usage = normalize_cache_usage(
            {"input_tokens": 10, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 7}
        )
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["cache"]["creation_input_tokens"], 3)
        self.assertEqual(usage["cache"]["read_input_tokens"], 7)

    def test_openai_cached_tokens_are_normalized(self) -> None:
        usage = normalize_cache_usage(
            {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 6}}
        )
        self.assertEqual(usage["cache"]["cached_tokens"], 6)

    def test_missing_cache_fields_return_empty_summary(self) -> None:
        usage = normalize_cache_usage({"total_tokens": 1})
        self.assertEqual(usage["cache"], {})


if __name__ == "__main__":
    unittest.main()
