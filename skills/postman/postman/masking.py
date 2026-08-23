"""마스킹 관문 — 나가는 모든 문자열이 지나는 **단 하나의 문** (ADR-002 D2).

001에서는 값 형태 마스킹이 봇(`bot/sender.py`)과 러너(`runner/exec/sendout.py`) **두 벌로
갈라져** 있었다. 둘이면 하나만 고쳐지는 날이 온다 — 실제로 `never_send`(파일 내용 제거)는
러너 쪽에만 있었고, 러너를 떼면 그대로 사라질 참이었다(002-N1 5-3절).

**그래서 관문을 하나로 합친다. 이 함수를 지나지 않는 발신 경로를 새로 만들지 않는다.**
텔레그램 발신도, 이벤트 기록도 전부 여기를 지난다.

두 겹으로 본다 (승계 규약 「마스킹」).

1. **값 형태** — `sk-`·`ghp_`·`Bearer `·`AKIA`·32자 이상 16진·텔레그램 봇 토큰 형태.
   형태를 아는 시크릿만 잡는다.
2. **이름 계층** ⚠️ **신규 작성분** — 플래그·환경변수·JSON 키의 이름이 값을 밀고하는 계층.
   `--api-key=…`·`GITHUB_TOKEN=…`·`"password": "…"`처럼 **이름이 말해 주면 형태를 몰라도
   가린다.** ADR-001 개정 2가 요구했으나 001에는 구현이 없었다.

세 번째로 `never_send` 파일 내용 제거가 있다. 설정에 적힌 경로의 내용이 본문에 섞여 있으면
지운다 — 볼트 루트의 평문 개인정보 파일이 화면 캡처에 실려 나가는 것을 막는 유일한 장치다.

**완전하지 않다.** 형태를 모르고 이름도 안 붙은 시크릿은 지나간다(ADR Negative 잔존).
관문의 값어치는 완전성이 아니라 **우회 불가**에 있다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import re
from pathlib import Path

MASK = "[가림]"
NEVER_SEND_MASK = "[제외]"

_MASK_TAIL_RE = re.compile(re.escape(MASK) + r"\]+")

# ---------------------------------------------------------------- ① 값 형태

VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    # 이 시스템 자신의 열쇠 — 텔레그램 봇 토큰(`<봇id>:<35자>`). 자기 필터가 못 잡으면
    # 세션이 실수로 실은 토큰이 그대로 대화창에 찍힌다.
    re.compile(r"\b\d{5,16}:[A-Za-z0-9_\-]{35}(?![A-Za-z0-9_\-])"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)

# ---------------------------------------------------------------- ② 이름 계층

# 이름을 **낱말로 끊어 읽는다.** `api_key`·`GITHUB_TOKEN`·`db-password`·`clientSecret`은
# 잡고 `monkey`·`keyboard`는 잡지 않는다 — 붙어 있는 글자는 다른 낱말이다.
#
# 그 판정을 **정규식이 아니라 함수로** 한다. 처음에는
# `(?:[A-Za-z0-9]+[_-])*<시크릿낱말>(?:[_-][A-Za-z0-9]+)*`로 썼는데, 중첩 반복이라
# "하이픈으로 이어지다 시크릿 낱말로 끝나지 않는" 입력에서 시작 위치마다 되짚기가 일어나
# **전체가 O(n²)**가 됐다(실측: 20KB에 1.8초, 200KB면 분 단위). 우체부는 단일 폴링
# 루프라 그 시간 동안 수신도 발신도 통째로 멈춘다. 정규식은 이름을 **한 덩어리로만**
# 집고, 그것이 시크릿 이름인지는 아래 `_is_secret_name`이 문자열 분해로 판정한다.
_SECRET_WORDS = frozenset((
    "key", "keys", "apikey", "apikeys", "token", "tokens", "secret", "secrets",
    "password", "passwords", "passwd", "pwd", "credential", "credentials",
    "auth", "authorization", "accesskey", "accesskeys", "privatekey", "privatekeys",
    "cookie", "cookies", "signature", "bearer", "otp", "passphrase",
))

# 낱말 경계 둘. **낙타등 표기를 끊지 않으면 `clientSecret`·`refreshToken`이 통째로 한
# 낱말이 되어 그대로 새어 나간다**(재검에서 실측 누출). 구분자만 보던 판정의 구멍이었다.
_CAMEL_BOUNDARIES = (
    re.compile(r"(?<=[a-z0-9])(?=[A-Z])"),      # clientSecret → client_Secret
    re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])"),    # AWSAccessKey → AWS_Access_Key
)
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _is_secret_name(name):
    """이름을 낱말로 끊어 시크릿 낱말이 한 조각이라도 있는지 본다.

    구분자(`_`·`-`·`.`·공백)와 낙타등 경계를 모두 끊는다. 과잉 마스킹은 허용되는
    방향이므로 애매하면 넓게 잡는다 — 못 가린 시크릿은 되돌릴 수 없지만 지나치게 가린
    로그는 사람이 다시 물어보면 된다.
    """
    spaced = name
    for pattern in _CAMEL_BOUNDARIES:
        spaced = pattern.sub("_", spaced)
    return any(part in _SECRET_WORDS for part in _SPLIT_RE.split(spaced.lower()) if part)


# 이름 한 덩어리. 중첩 반복이 없어 되짚기가 이름 길이(64자) 안에서 끝난다.
_NAME = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"

# 따옴표 안의 키는 점·공백도 낀다(`"credentials.apiKey"`·`"api key"`). 따옴표가 경계를
# 잡아 주므로 넓혀도 안전하다 — 따옴표 없는 자리에 이 폭을 쓰면 문장을 통째로 문다.
_QUOTED_NAME = r"[A-Za-z0-9][A-Za-z0-9_.\- ]{0,63}"

# 값 쪽은 **한 낱말**만 가린다. 뒤따르는 문장까지 삼키면 로그가 통째로 [가림]이 되어
# 사람이 무슨 일이 있었는지 읽을 수 없다. **여는 대괄호로 시작하는 값은 잡지 않는다** —
# 이미 `[가림]`으로 바뀐 자리를 다음 패턴이 다시 물어 `[가림]]]`이 되는 것을 막는다.
_VALUE = r"[^\s,;)\]}'\"\[][^\s,;)\]}'\"]*"

# `Authorization: Bearer <토큰>`처럼 값 앞에 인증 방식이 한 낱말 더 붙는 형태. 이것을
# 값에 포함하지 않으면 이름 계층이 `Bearer`만 가리고 **정작 토큰을 남긴다.**
_SCHEME = r"(?:(?:Bearer|Basic|Token)\s+)?"

# 따옴표로 감싼 값. **이스케이프된 따옴표를 값의 일부로 읽는다** — 그러지 않으면
# `{"api_key": "abc\"tail"}`에서 마스크가 `abc\`에서 끊기고 **`tail`이 평문으로 나간다**
# (실제로 재현됐다). 풀어 쓴 형태(unrolled loop)라 되짚기가 폭주하지 않는다.
# 곧은 따옴표 두 종에 더해 굽은 따옴표도 본다(편집기를 거친 붙여넣기).
_QUOTED = (r'"(?:[^"\\]|\\.)*"'
           r"|'(?:[^'\\]|\\.)*'"
           u"|“(?:[^”\\\\]|\\\\.)*”")

# `token = "sk-" + "실제값"`처럼 **값이 이어 붙는 형태.** 앞 조각만 가리면 미끼만 가리고
# 진짜 값이 그대로 나간다(재검에서 실측). 이어지는 조각까지 한 덩어리로 문다.
_QUOTED_CHAIN = r"(?:%s)(?:\s*\+\s*(?:%s))*" % (_QUOTED, _QUOTED)

_CLOSERS = {u"“": u"”"}


def _mask_value(value):
    """값 한 덩어리를 마스크로 바꾼다. 따옴표로 시작하면 따옴표는 남긴다(형태 보존)."""
    if value and value[0] in ("\"", "'", u"“"):
        opener = value[0]
        return opener + MASK + _CLOSERS.get(opener, opener)
    return MASK


# `"credentials.apiKey": "값"` · `"api key": 값` — **따옴표 붙은 키.** 점·공백이 껴도 잡는다.
_QUOTED_KEY_RE = re.compile(
    u"(['\"“])(%s)['\"”](\\s*[=:]\\s*)(%s|%s%s)"
    % (_QUOTED_NAME, _QUOTED_CHAIN, _SCHEME, _VALUE))

# `--api-key="값"` · `TOKEN='값'` — 따옴표 없는 키 + 따옴표 붙은 값.
_QUOTED_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(--?)?(%s)(\s*[=:]\s*)(%s)" % (_NAME, _QUOTED_CHAIN))

# `--api-key=값` · `--token 값` · `-token=값`
_FLAG_RE = re.compile(
    r"(?<![A-Za-z0-9])(--?)(%s)([=:]\s*|\s+)(%s%s)" % (_NAME, _SCHEME, _VALUE),
    re.IGNORECASE)

# `GITHUB_TOKEN=값` · `export API_KEY=값`
_ENV_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(%s)(\s*=\s*)(['\"]?)(%s%s)" % (_NAME, _SCHEME, _VALUE),
    re.IGNORECASE)

# `token: 값` (YAML·평문 로그)
_KV_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(['\"]?)(%s)\1(\s*:\s*)(['\"]?)(%s%s)" % (_NAME, _SCHEME, _VALUE),
    re.IGNORECASE)


def _mask_quoted_key(match):
    if not _is_secret_name(match.group(2)):
        return match.group(0)
    return match.group(0)[:match.start(4) - match.start(0)] + _mask_value(match.group(4))


def _mask_quoted_value(match):
    if not _is_secret_name(match.group(2)):
        return match.group(0)
    return ((match.group(1) or "") + match.group(2) + match.group(3)
            + _mask_value(match.group(4)))


def _mask_flag(match):
    if not _is_secret_name(match.group(2)):
        return match.group(0)
    return match.group(1) + match.group(2) + match.group(3) + MASK


def _mask_env(match):
    if not _is_secret_name(match.group(1)):
        return match.group(0)
    return match.group(1) + match.group(2) + match.group(3) + MASK


def _mask_kv(match):
    if not _is_secret_name(match.group(2)):
        return match.group(0)
    return (match.group(1) + match.group(2) + match.group(1)
            + match.group(3) + match.group(4) + MASK)


NAME_RULES = (
    # 따옴표 규칙이 **먼저**다 — 따옴표 안을 통째로 집어야 이스케이프 우회가 닫힌다.
    (_QUOTED_KEY_RE, _mask_quoted_key),
    (_QUOTED_VALUE_RE, _mask_quoted_value),
    (_FLAG_RE, _mask_flag),
    (_ENV_RE, _mask_env),
    (_KV_RE, _mask_kv),
)

# `never_send` 파일의 **줄 단위** 대조 최소 길이. 화면 캡처에는 파일 전문이 아니라 몇 줄만
# 실리는 것이 보통이라 전문 대조만으로는 아무것도 못 잡는다. 너무 짧은 줄까지 대조하면
# 흔한 낱말이 전부 가려지므로 하한을 둔다.
MIN_NEVER_SEND_LINE = 12


def mask(text, never_send=()):
    """나가는 문자열의 유일한 관문. 이름 계층 → 값 형태 → `never_send` 순으로 지운다."""
    if not isinstance(text, str):
        return text
    # 이름 계층을 먼저 건다. 값 형태를 먼저 걸면 `--api-key=[가림]`의 마스크 자리를
    # 이름 계층이 다시 물어 마스크가 겹쳐 쌓인다.
    for pattern, rule in NAME_RULES:
        text = pattern.sub(rule, text)
    # 앞 규칙이 남긴 마스크를 뒤 규칙이 값의 일부로 물면 닫는 괄호가 겹쳐 `[가림]]`이 된다.
    # 누출은 아니고 눈에 거슬리는 것뿐이라 마지막에 한 번 눌러 준다.
    text = _MASK_TAIL_RE.sub(MASK, text)
    for pattern in VALUE_PATTERNS:
        text = pattern.sub(MASK, text)
    return strip_never_send(text, never_send)


def strip_never_send(text, never_send=()):
    """`never_send` 경로의 내용이 본문에 있으면 지운다 (D2).

    전문 일치와 **줄 단위** 일치를 모두 본다. 읽을 수 없는 경로는 조용히 건너뛴다 —
    항목 하나의 문제로 발신 전체가 죽으면 안 된다(그러면 루프가 조용히 멈춘다).
    """
    if not isinstance(text, str):
        return text
    for raw_path in never_send or ():
        content = _read_text(raw_path)
        if not content:
            continue
        if content in text:
            text = text.replace(content, NEVER_SEND_MASK)
        for line in content.splitlines():
            line = line.strip()
            if len(line) >= MIN_NEVER_SEND_LINE and line in text:
                text = text.replace(line, NEVER_SEND_MASK)
    return text


def _read_text(raw_path):
    try:
        return Path(raw_path).expanduser().read_text(encoding="utf-8")
    except (OSError, ValueError):
        # ValueError는 UnicodeDecodeError(비-UTF8 파일)를 포함한다.
        return None


def truncate_capture(text, lines=40):
    """화면 캡처는 마지막 `lines`줄로 자른다 (승계 규약 「발신」)."""
    if not isinstance(text, str):
        return text
    parts = text.splitlines()
    if len(parts) <= lines:
        return text
    return "\n".join(parts[-lines:])
