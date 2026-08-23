"""주소 규약 — tmux 세션명이 1차 키 (ADR-002 D9).

001에서는 같은 주소 문자열을 **세 정규식이 서로 다른 폭으로** 검사했다(002-N1 2-3절).

    bot/botpaths.py:28        [A-Za-z0-9][A-Za-z0-9._-]{0,63}    64자·점 허용
    session/devrun_paths.py   [A-Za-z0-9][A-Za-z0-9._-]{0,127}   128자·점 허용
    runner/exec/tmuxsess.py   [A-Za-z0-9][A-Za-z0-9_-]{0,127}    128자·점 불허

어긋남의 증상은 **"버튼을 눌렀는데 아무 일도 없다"** 하나뿐이라 진단이 어렵다. 봇의 64자
상한이 tmux의 128자보다 좁아 긴 이름이 조용히 거부되고, 점이 든 이름은 봇은 통과시키고
tmux가 거부한다(tmux가 `.`·`:`를 창·pane 구분자로 읽는다).

**그래서 tmux 폭 하나로 합친다** — `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`, 점 불허.
가장 좁은 쪽에 맞춰야 통과한 이름이 모든 계층에서 살아남는다.

**통일의 범위는 tmux 세션명 이름공간뿐이다**(D5·D9). 클로드 세션 UUID 검증기와 노드 ID는
다른 이름공간이라 각자 정규식을 갖는다 — 다른 이름공간을 한 정규식으로 묶는 것은 002가
없애려는 실수의 반대편 실수다. 대신 셋 다 **이 파일 한 곳에** 모아 두어, 다음 사람이
폭을 비교하려고 세 디렉토리를 뒤지지 않게 한다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import re

# ① tmux 세션명 — 우체부의 1차 키. 점 불허·최대 128자·**순수 숫자 불허**.
#    숫자만으로 된 이름을 막는 이유(2026-08-22, 002-N6 판정): `tmux -t 123`의 대상 해석이
#    세션명과 인덱스 사이에서 모호하다. 증상은 D9가 없애려던 바로 그 형태 — "버튼을 눌렀는데
#    아무 일도 없다" — 로 나타나 진단이 어렵다. 현 이름 규칙(`dev-` 접두)에서는 도달하지
#    않지만, 규약이 막지 않으면 **다음 이름 규칙이 이 자리로 걸어 들어온다.**
SESSION_NAME_RE = re.compile(r"\A(?![0-9]+\Z)[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")

# ② 노드 ID — `N4`·`N4B`·`002-N4B`(계획서 번호 접두). 경로 조각으로도 쓰이므로 점 불허.
#    본문(`NODE_ID_BODY`)을 따로 노출하는 이유: 변별자 정규식(`discriminator.py`)이 이 폭을
#    문자 그대로 베껴 적으면 D9가 없애려던 "같은 주소를 두 정규식이 다르게 본다"가 재발한다.
NODE_ID_BODY = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
NODE_ID_RE = re.compile(r"\A" + NODE_ID_BODY + r"\Z")

# ③ 클로드 세션 UUID — `~/.claude/status/<session_id>.json`의 파일명이 된다.
#    별개 이름공간이라 통일 대상이 아니다(D5). 001의 `safe_session_id`와 같은 폭이다.
SESSION_UUID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# 노드 귀속이 없는 제어 메시지의 노드 ID 자리 (D10).
CONTROL_NODE = "cmd"


class InvalidAddress(ValueError):
    """주소 문자열이 규약을 벗어났다. 값은 예외 문구에 싣지 않는다 — 외부 입력이다."""


def _check(value, pattern, what):
    if not isinstance(value, str) or ".." in value or not pattern.match(value):
        raise InvalidAddress("invalid %s" % what)
    return value


def safe_session_name(value):
    """tmux 세션명. 부적합하면 `InvalidAddress`."""
    return _check(value, SESSION_NAME_RE, "session name")


def safe_node_id(value):
    """노드 ID. 부적합하면 `InvalidAddress`."""
    return _check(value, NODE_ID_RE, "node id")


def safe_session_uuid(value):
    """클로드 세션 UUID. 부적합하면 `InvalidAddress`."""
    return _check(value, SESSION_UUID_RE, "session uuid")


def is_session_name(value):
    try:
        safe_session_name(value)
    except InvalidAddress:
        return False
    return True


def is_node_id(value):
    try:
        safe_node_id(value)
    except InvalidAddress:
        return False
    return True


def is_session_uuid(value):
    try:
        safe_session_uuid(value)
    except InvalidAddress:
        return False
    return True
