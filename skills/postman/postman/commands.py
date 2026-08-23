"""명령 파싱 — 닫힌 열거형 (ADR-002 D2).

열거형의 단일 출처는 `protocol/commands.py`다. 여기서 다시 적지 않는다.

명령 메뉴(`setMyCommands`)에는 **소문자 영문·숫자·밑줄만** 등록할 수 있으므로 메뉴는
영문으로 두고, 채팅에 친 한글 낱말은 여기서 같은 열거형으로 파싱한다.

열거형 밖은 무엇이든 `cmd=None`이 되고, 호출자는 그것을 어디로도 전달하지 않는다.
**수신 텍스트는 어떤 경로로도 셸에 닿지 않는다** — 여기서 나오는 것은 열거형 값·검증된
tmux 세션명·노드 ID·자유 텍스트뿐이다.

**노드 ID 인식기는 계획서 번호 접두를 받는다.** 001의 `_looks_like_node`는
`\\A[Nn]\\d{1,3}[A-Za-z]?\\Z`만 받아 `002-N4B` 형식을 거부했고, 증상은 노드 ID를 정확히
적었는데도 "노드 ID가 필요하다"가 되돌아오는 것이었다(2026-08-21 실측). 002는 노드 ID에
계획서 번호를 다는 것이 규약이므로 인식기가 그것을 받아야 한다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import re

from postman import addressing
from protocol import commands as protocol

# 채팅에 친 한글·영문 별칭 → 열거형. 키는 전부 소문자로 비교한다.
ALIASES = {
    "status": "status", "상태": "status", "현황": "status", "상황": "status",
    "done": "done", "완료": "done", "끝": "done", "마침": "done",
    "halt": "halt", "정지": "halt", "멈춰": "halt", "중지": "halt", "그만": "halt",
    "resume": "resume", "재개": "resume", "해제": "resume", "계속": "resume",
}

_SLASH_RE = re.compile(r"\A/([A-Za-z0-9_]{1,32})(?:@\S+)?\Z")

# `N4` · `N4B` · `002-N4B` · `007-N7`. 계획서 번호 접두는 선택이다.
_NODE_SHAPE_RE = re.compile(r"\A(?:\d{1,4}-)?[Nn]\d{1,3}[A-Za-z]?\Z")


class Parsed(object):
    """`cmd`는 `protocol.COMMANDS` 중 하나 또는 None(=버린다)."""

    def __init__(self, cmd=None, target=None, node=None, text=None, word=None):
        self.cmd = cmd
        self.target = target      # tmux 세션명 또는 `all`
        self.node = node
        self.text = text
        self.word = word

    def __repr__(self):
        return "Parsed(cmd=%r, target=%r, node=%r)" % (self.cmd, self.target, self.node)


def parse_command(text, sessions=()):
    """첫 낱말을 열거형으로 해석하고, 뒤따르는 낱말에서 대상 주소·노드 ID를 집는다.

    **대상 주소는 실재하는 세션 목록과 일치할 때만** 인정한다(`all` 예약어는 예외) —
    임의 문자열이 tmux 인자로 흘러들지 않게 한다.
    """
    if not isinstance(text, str):
        return Parsed()
    tokens = text.strip().split()
    if not tokens:
        return Parsed()

    head = tokens[0]
    match = _SLASH_RE.match(head)
    if match:
        head = match.group(1)
    word = head.lower()
    cmd = ALIASES.get(word)
    if cmd is None:
        return Parsed(word=word)

    target = None
    node = None
    rest = []
    for token in tokens[1:]:
        if node is None and looks_like_node(token):
            node = token
            continue
        if target is None and _looks_like_target(token, sessions):
            target = token
            continue
        rest.append(token)
    return Parsed(cmd=cmd, target=target, node=node,
                  text=" ".join(rest) or None, word=word)


def looks_like_node(token):
    """노드 ID 모양인가. 경로 조각 안전성(`addressing`)도 함께 본다."""
    return bool(_NODE_SHAPE_RE.match(token or "")) and addressing.is_node_id(token)


def _looks_like_target(token, sessions):
    if token == protocol.ALL_TARGET:
        return True
    return addressing.is_session_name(token) and token in (sessions or ())


def parse_button_action(action):
    """버튼의 `action` 문자열을 해석한다. 만드는 쪽과 **같은 함수**를 쓴다."""
    return protocol.parse_action(action)


def menu_commands():
    """`setMyCommands`에 등록할 목록. 영문 소문자만 쓴다(스펙 제약)."""
    return [
        {"command": "status", "description": "지휘·작업 세션 상태판"},
        {"command": "done", "description": "사용자 처리 노드 완료 신고 (노드 ID 필요)"},
        {"command": "halt", "description": "지정 세션 정지 (세션명 또는 all)"},
        {"command": "resume", "description": "발신 상한 해제"},
    ]
