import unittest

import httpx
import openai

from epub_translator.llm.error import get_retry_after_seconds, is_retry_error


def _rate_limit_error(code: str, retry_after: str | None = None) -> openai.RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        status_code=429,
        headers=headers,
        content=b"",
        request=httpx.Request("POST", "https://api.openai.com/"),
    )
    return openai.RateLimitError(
        message="rate limit",
        response=response,
        body={"code": code},
    )


class TestGetRetryAfterSeconds(unittest.TestCase):
    def test_returns_seconds_from_header(self):
        err = _rate_limit_error("rate_limit_exceeded", retry_after="30")
        self.assertEqual(get_retry_after_seconds(err), 30.0)

    def test_returns_float_seconds(self):
        err = _rate_limit_error("rate_limit_exceeded", retry_after="1.5")
        self.assertEqual(get_retry_after_seconds(err), 1.5)

    def test_returns_none_when_header_absent(self):
        err = _rate_limit_error("rate_limit_exceeded")
        self.assertIsNone(get_retry_after_seconds(err))

    def test_returns_none_when_header_not_numeric(self):
        err = _rate_limit_error("rate_limit_exceeded", retry_after="soon")
        self.assertIsNone(get_retry_after_seconds(err))

    def test_returns_none_for_non_rate_limit_error(self):
        self.assertIsNone(get_retry_after_seconds(ValueError("other")))


class TestIsRetryError(unittest.TestCase):
    def test_insufficient_quota_is_not_retried(self):
        err = _rate_limit_error("insufficient_quota")
        self.assertFalse(is_retry_error(err))

    def test_rate_limit_exceeded_is_retried(self):
        err = _rate_limit_error("rate_limit_exceeded")
        self.assertTrue(is_retry_error(err))


if __name__ == "__main__":
    unittest.main()
