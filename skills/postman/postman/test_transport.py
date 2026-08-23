"""전송 계층 단위 시험 — `certifi` 폴백과 토큰 비노출 (002 후속 항목 42).

여기서 덮는 것은 **조용히 깨지는 것**이다. CA 번들이 없는 파이썬에서 우체부는
`status=0`만 반복하며 원인을 말하지 않았다(002-N7 결함 1). 그 침묵이 되돌아오지 않도록,
폴백이 실제로 다른 오프너를 쓰는지·못 쓸 때 사유를 말하는지를 단언한다.

네트워크에 나가지 않는다 — 오프너를 통째로 가짜로 갈아끼운다.
"""
import io
import json
import logging
import ssl
import urllib.error

import pytest

from postman import transport as transport_mod
from postman.transport import HttpTransport, TelegramError

TOKEN = "123456:AAsecret-token-value"


def verify_error():
    """urllib이 올리는 모양 그대로 — `URLError(reason=SSLCertVerificationError)`."""
    inner = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get "
                                            "local issuer certificate")
    return urllib.error.URLError(inner)


class FakeResponse(object):
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener(object):
    """`open(request, timeout=)`만 흉내낸다. `error`를 주면 그것을 올린다."""

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {"ok": True, "result": "fine"}
        self.error = error
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append(request.full_url)
        if self.error is not None:
            raise self.error() if callable(self.error) else self.error
        return FakeResponse(self.payload)


# ------------------------------------------------------------- certifi 폴백

def test_certificate_failure_falls_back_to_the_certifi_bundle():
    """기본 오프너가 검증에 실패하면 폴백 오프너로 되짚어 **성공**한다."""
    # Arrange
    primary = FakeOpener(error=verify_error)
    fallback = FakeOpener(payload={"ok": True, "result": {"id": 7}})
    http = HttpTransport(TOKEN, opener=primary, fallback_opener=lambda: fallback)

    # Act
    result = http.call("getMe")

    # Assert
    assert result == {"id": 7}
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_fallback_opener_is_promoted_so_the_next_call_skips_the_failure():
    """되짚기가 통하면 다음 호출은 실패하는 오프너를 다시 거치지 않는다."""
    primary = FakeOpener(error=verify_error)
    fallback = FakeOpener()
    http = HttpTransport(TOKEN, opener=primary, fallback_opener=lambda: fallback)

    http.call("getMe")
    http.call("getMe")

    assert len(primary.calls) == 1      # 두 번째 호출은 여기 오지 않는다
    assert len(fallback.calls) == 2


def test_missing_certifi_reports_the_cause_instead_of_a_bare_status_zero(caplog):
    """번들이 없으면 **원인을 말한다.** 002-N7 결함 1이 조용했던 자리다."""
    http = HttpTransport(TOKEN, opener=FakeOpener(error=verify_error),
                         fallback_opener=lambda: None)

    with caplog.at_level(logging.ERROR, logger="postman.transport"):
        with pytest.raises(TelegramError) as caught:
            http.call("getMe")

    assert caught.value.status == 0
    assert caught.value.description == "SSLCertVerificationError"
    assert "certifi" in caplog.text
    assert transport_mod.CA_BUNDLE_ENV in caplog.text


def test_fallback_that_also_fails_verification_keeps_saying_the_right_cause(caplog):
    """폴백까지 실패하면 그 사유를 말하고, **두 번째 호출도 같은 사유**를 말한다.

    폴백 오프너를 버리면 두 번째 호출이 "번들이 없다"는 엉뚱한 사유로 보고된다.
    (외침의 크기는 첫 회만 ERROR다 — 도배 방지 시험이 그쪽을 덮는다.)
    """
    http = HttpTransport(TOKEN, opener=FakeOpener(error=verify_error),
                         fallback_opener=lambda: FakeOpener(error=verify_error))

    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="postman.transport"):
            with pytest.raises(TelegramError):
                http.call("getMe")
        assert "certifi 번들로도" in caplog.text
        assert "번들이 없어" not in caplog.text


def test_the_cause_is_shouted_once_and_then_kept_at_debug(caplog):
    """폴링은 초 단위다 — 같은 사유를 매번 ERROR로 외치면 로그가 이 한 줄로 도배된다."""
    http = HttpTransport(TOKEN, opener=FakeOpener(error=verify_error),
                         fallback_opener=lambda: None)

    with caplog.at_level(logging.DEBUG, logger="postman.transport"):
        for _ in range(3):
            with pytest.raises(TelegramError):
                http.call("getMe")

    levels = [r.levelno for r in caplog.records if "certifi 번들이 없어" in r.getMessage()]
    assert levels == [logging.ERROR, logging.DEBUG, logging.DEBUG]


def test_the_bundle_is_built_once_even_after_repeated_failures():
    """번들 만들기는 한 번뿐이다 — 매 호출 임포트를 다시 시도하지 않는다."""
    built = []

    def factory():
        built.append(1)
        return None

    http = HttpTransport(TOKEN, opener=FakeOpener(error=verify_error), fallback_opener=factory)
    for _ in range(3):
        with pytest.raises(TelegramError):
            http.call("getMe")

    assert len(built) == 1


def test_non_certificate_failures_do_not_touch_the_fallback():
    """타임아웃·연결 거부는 폴백 대상이 아니다. 타입 이름만 남는 기존 동작 그대로."""
    fallback = FakeOpener()
    http = HttpTransport(TOKEN, opener=FakeOpener(error=urllib.error.URLError("timed out")),
                         fallback_opener=lambda: fallback)

    with pytest.raises(TelegramError) as caught:
        http.call("getMe")

    assert caught.value.status == 0
    assert caught.value.description == "URLError"
    assert fallback.calls == []


def test_token_never_reaches_the_exception_text_on_a_certificate_failure():
    """검증 실패 경로에도 토큰이 새지 않는다 — URL은 예외 문구에 오르지 않는다."""
    http = HttpTransport(TOKEN, opener=FakeOpener(error=verify_error),
                         fallback_opener=lambda: None)

    with pytest.raises(TelegramError) as caught:
        http.call("getMe")

    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)


# ------------------------------------------------------------- 판별기 자체

def test_verify_failure_is_detected_through_the_urllib_wrapper():
    assert transport_mod._is_verify_failure(verify_error())
    assert transport_mod._is_verify_failure(ssl.SSLCertVerificationError(1, "x"))


def test_verify_failure_detector_rejects_unrelated_errors():
    assert not transport_mod._is_verify_failure(urllib.error.URLError("timed out"))
    assert not transport_mod._is_verify_failure(ssl.SSLError(1, "handshake"))
    assert not transport_mod._is_verify_failure(ValueError("nope"))
    assert not transport_mod._is_verify_failure(None)


def test_certifi_opener_returns_none_when_the_bundle_is_absent(monkeypatch):
    """번들이 없으면 예외가 아니라 None이다 — 호출자가 매 호출 재시도하지 않게."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("no certifi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert transport_mod.certifi_opener() is None


# ------------------------------------------------------------- 기존 동작 회귀

def test_http_error_keeps_the_telegram_description_and_retry_after():
    body = json.dumps({"description": "Too Many Requests", "parameters": {"retry_after": 12}})
    error = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {},
                                   io.BytesIO(body.encode("utf-8")))
    http = HttpTransport(TOKEN, opener=FakeOpener(error=error), fallback_opener=lambda: None)

    with pytest.raises(TelegramError) as caught:
        http.call("sendMessage")

    assert caught.value.status == 429
    assert caught.value.retry_after == 12


def test_not_ok_payload_becomes_a_telegram_error():
    http = HttpTransport(TOKEN, opener=FakeOpener(payload={"ok": False, "error_code": 400,
                                                           "description": "Bad Request"}))

    with pytest.raises(TelegramError) as caught:
        http.call("sendMessage")

    assert caught.value.status == 400
    assert caught.value.description == "Bad Request"
