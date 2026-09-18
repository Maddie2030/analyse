import errno

import httpx

from app.resilience import is_transient_error


def test_httpx_connect_error_is_transient():
    request = httpx.Request("PUT", "http://seaweedfs-filer:8888/test.webp")
    assert is_transient_error(httpx.ConnectError("offline", request=request))


def test_retryable_http_status_is_transient():
    request = httpx.Request("PUT", "http://seaweedfs-filer:8888/test.webp")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("unavailable", request=request, response=response)
    assert is_transient_error(error)


def test_wrapped_transport_error_is_transient():
    request = httpx.Request("GET", "https://example.invalid")
    try:
        try:
            raise httpx.ReadTimeout("temporary", request=request)
        except httpx.ReadTimeout as exc:
            raise RuntimeError("higher-level fetch failed") from exc
    except RuntimeError as wrapped:
        assert is_transient_error(wrapped)


def test_network_oserror_is_transient():
    assert is_transient_error(OSError(errno.ENETUNREACH, "network unreachable"))


def test_validation_error_is_not_transient():
    assert not is_transient_error(ValueError("invalid chapter metadata"))
