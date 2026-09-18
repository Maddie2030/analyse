from helpers import _redact, _redact_text, _redact_url


def test_diagnostic_redaction_covers_nested_tokens_and_passwords():
    payload = {
        "password": "secret-password",
        "nested": {
            "chapter_token": "secret-chapter-token",
            "safe": "visible",
        },
        "items": [{"refresh_token": "secret-refresh-token"}],
    }
    assert _redact(payload) == {
        "password": "***",
        "nested": {"chapter_token": "***", "safe": "visible"},
        "items": [{"refresh_token": "***"}],
    }


def test_diagnostic_redaction_scrubs_query_and_non_json_text():
    url = _redact_url(
        "http://example.test/api/token/chapter/demo/ch-1?token=super-secret&x=1"
    )
    assert "super-secret" not in url
    assert "token=%2A%2A%2A" in url
    assert "x=1" in url

    text = _redact_text(
        'failed url=/api/token/chapter/demo/ch-1?token=top-secret&x=1 body={"chapter_token":"also-secret"}'
    )
    assert "top-secret" not in text
    assert "also-secret" not in text
    assert "token=***" in text
    assert '"chapter_token":"***"' in text
