import httpx
import openai
import requests


def is_retry_error(err: Exception) -> bool:
    if _is_openai_retry_error(err):
        return True
    if _is_httpx_retry_error(err):
        return True
    if _is_request_retry_error(err):
        return True
    return False


# https://help.openai.com/en/articles/6897213-openai-library-error-types-guidance
def _is_openai_retry_error(err: Exception) -> bool:
    if isinstance(err, openai.Timeout):
        return True
    if isinstance(err, openai.APIConnectionError):
        return True
    if isinstance(err, openai.RateLimitError):
        return err.code != "insufficient_quota"
    if isinstance(err, openai.InternalServerError):
        return err.status_code in (502, 503, 504)
    return False


def get_retry_after_seconds(err: Exception) -> float | None:
    if isinstance(err, openai.RateLimitError):
        retry_after = err.response.headers.get("retry-after")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return None


# https://www.python-httpx.org/exceptions/
def _is_httpx_retry_error(err: Exception) -> bool:
    if isinstance(err, httpx.RemoteProtocolError):
        return True
    if isinstance(err, httpx.StreamError):
        return True
    if isinstance(err, httpx.TimeoutException):
        return True
    if isinstance(err, httpx.NetworkError):
        return True
    if isinstance(err, httpx.ProtocolError):
        return True
    return False


# https://requests.readthedocs.io/en/latest/api/#exceptions
def _is_request_retry_error(err: Exception) -> bool:
    if isinstance(err, requests.ConnectionError):
        return True
    if isinstance(err, requests.ConnectTimeout):
        return True
    if isinstance(err, requests.ReadTimeout):
        return True
    if isinstance(err, requests.Timeout):
        return True
    return False
