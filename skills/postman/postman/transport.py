"""텔레그램 HTTP 계층 — 표준 라이브러리만 (ADR-002 D2, ADR-001 D6 승계).

이 파일이 네트워크에 닿는 유일한 지점이다. 나머지 모듈은 `call(method, params)`만
알기 때문에 테스트가 가짜 전송기로 통째로 갈아끼울 수 있다.

**토큰은 URL에만 들어가고 어디로도 새지 않는다.** urllib이 올리는 예외 문구에 URL이
섞일 수 있으므로, 예외는 전부 여기서 잡아 **타입 이름만** 남기고 다시 던진다.

**인증서 검증 실패는 한 번만 `certifi` 번들로 되짚는다** (002-N7 결함 1). CA 번들이 없는
파이썬(python.org 프레임워크 빌드에서 `Install Certificates.command`를 안 돌린 상태)에서는
기본 컨텍스트가 `CERTIFICATE_VERIFY_FAILED`를 내는데, 그것이 호출자에게는 `status=0`으로만
보여 **원인을 말하지 않은 채 조용히 텔레그램에 못 닿는다.** 그래서 이 계층이 직접
`certifi` 번들로 한 번 되짚고, 되짚었다는 사실과 못 되짚은 사유를 로그에 남긴다.

**폴백은 검증을 끄는 것이 아니다.** 다른 CA 번들로 **검증을 다시 하는 것**이다 —
`ssl.create_default_context(cafile=...)`는 호스트명 검사와 `CERT_REQUIRED`를 그대로 유지한다.
이 자리를 `_create_unverified_context`로 "간단히" 바꾸면 중간자에게 통로가 열린다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import json
import logging
import ssl
import urllib.error
import urllib.request

log = logging.getLogger("postman.transport")

DEFAULT_API_BASE = "https://api.telegram.org"

# 폴백도 실패했을 때 사람에게 가리킬 영구 조치. 값이 아니라 **변수 이름**만 로그에 나간다.
CA_BUNDLE_ENV = "SSL_CERT_FILE"


class TelegramError(Exception):
    """API 호출 실패. `description`은 텔레그램이 준 문구이거나 예외 **타입 이름**뿐이다."""

    def __init__(self, status, description, retry_after=None):
        Exception.__init__(self, "telegram %s: %s" % (status, description))
        self.status = status
        self.description = description
        self.retry_after = retry_after


class _VerifyFailed(Exception):
    """인증서 검증 실패. 이 계층 밖으로 나가지 않는다 — 값을 싣지 않는 내부 신호다."""


def certifi_opener():
    """`certifi` 번들로 **검증하는** 오프너. 번들이 없으면 None을 준다(예외 안 올림).

    호출자가 매 호출 재시도하지 않도록, 실패를 예외가 아니라 None으로 알린다.
    """
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


def _is_verify_failure(exc):
    """예외 사슬에 인증서 검증 실패가 있는가. **문구가 아니라 타입으로 본다.**

    urllib은 TLS 오류를 `URLError(reason=SSLCertVerificationError(...))`로 감싼다.
    `reason`은 다시 문자열일 수 있으므로 예외가 아닌 값을 만나면 멈춘다.
    """
    for _ in range(4):
        if not isinstance(exc, BaseException):
            return False
        if isinstance(exc, ssl.SSLCertVerificationError):
            return True
        exc = getattr(exc, "reason", None)
    return False


class HttpTransport(object):
    def __init__(self, token, api_base=DEFAULT_API_BASE, timeout=70.0, opener=None,
                 fallback_opener=certifi_opener):
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._timeout = float(timeout)
        self._opener = opener or urllib.request.build_opener()
        self._fallback_opener = fallback_opener
        self._fallback = None
        self._fallback_tried = False
        self._said = set()

    def call(self, method, params=None):
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        try:
            payload = self._fetch(self._opener, method, body)
        except _VerifyFailed:
            payload = self._retry_with_certifi(method, body)
        if not payload.get("ok"):
            parameters = payload.get("parameters") or {}
            raise TelegramError(
                payload.get("error_code", 0),
                payload.get("description", ""),
                parameters.get("retry_after"),
            )
        return payload.get("result")

    # ------------------------------------------------------------------ 내부

    def _fetch(self, opener, method, body):
        request = urllib.request.Request(
            self._url(method),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise self._from_http_error(exc)
        except Exception as exc:  # URLError·소켓 타임아웃·JSON 깨짐 — 문구를 신뢰하지 않는다
            if _is_verify_failure(exc):
                raise _VerifyFailed()
            raise TelegramError(0, type(exc).__name__)

    def _retry_with_certifi(self, method, body):
        """검증 실패를 `certifi` 번들로 **한 번만** 되짚는다. 성공하면 그 오프너로 갈아탄다."""
        opener = self._take_fallback()
        if opener is None:
            # 여기가 002-N7 결함 1이 조용했던 자리다 — 원인을 반드시 말한다.
            self._say_once("missing",
                           "TLS 인증서 검증 실패 — certifi 번들이 없어 되짚지 못했다. "
                           "파이썬에 CA 번들을 설치하거나(Install Certificates.command) "
                           "%s 환경변수로 번들 경로를 지정하라.", CA_BUNDLE_ENV)
            raise TelegramError(0, "SSLCertVerificationError")
        try:
            payload = self._fetch(opener, method, body)
        except _VerifyFailed:
            self._say_once("rejected", "TLS 인증서 검증 실패 — certifi 번들로도 검증되지 "
                                       "않았다. 중간자 개입이나 번들 손상을 의심하라.")
            raise TelegramError(0, "SSLCertVerificationError")
        # 되짚기가 통했다. 다음 호출부터는 처음부터 이 오프너를 쓴다 — 매번 실패를 먼저
        # 겪게 두면 폴링 주기마다 헛된 핸드셰이크가 한 번씩 더 붙는다.
        self._opener = opener
        return payload

    def _say_once(self, key, message, *args):
        """같은 사유는 **한 번만 외친다.** 폴링은 초 단위라 매번 외치면 로그가 도배된다.

        두 번째부터 침묵하지는 않는다 — DEBUG로 낮춰 둔다. 사후에 "언제부터 못 닿았나"를
        보려면 반복 자체가 증거이기 때문이다.
        """
        if key in self._said:
            log.debug(message, *args)
            return
        self._said.add(key)
        log.error(message, *args)

    def _take_fallback(self):
        """폴백 오프너를 **한 번만** 만든다. 없는 환경에서 매 호출 다시 시도하지 않는다.

        만든 것은 들고 있는다 — 버리면 두 번째 실패가 "번들이 없다"는 엉뚱한 사유로 보고된다.
        """
        if self._fallback is not None:
            return self._fallback
        if self._fallback_tried:
            return None
        self._fallback_tried = True
        opener = self._fallback_opener() if self._fallback_opener else None
        self._fallback = opener
        if opener is not None:
            log.warning("TLS 인증서 검증 실패 — certifi 번들로 되짚는다. "
                        "영구 조치는 파이썬의 CA 번들 설치 또는 %s 지정이다.", CA_BUNDLE_ENV)
        return opener

    def _url(self, method):
        # 토큰이 들어가는 유일한 문자열. 로그·예외로 흘려보내지 않는다.
        return "%s/bot%s/%s" % (self._api_base, self._token, method)

    @staticmethod
    def _from_http_error(exc):
        description = ""
        retry_after = None
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            description = payload.get("description", "")
            retry_after = (payload.get("parameters") or {}).get("retry_after")
        except Exception:
            description = "http error"
        return TelegramError(exc.code, description, retry_after)
