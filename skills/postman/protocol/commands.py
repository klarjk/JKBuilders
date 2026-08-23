"""닫힌 명령 열거형의 **단일 출처** (ADR-002 D2).

001에서는 같은 튜플이 세 파일에 수기 복제돼 있었고, 값이 어긋나면 조용히 깨졌다 —
러너가 만든 버튼을 봇이 버리거나 봇이 넣은 명령을 러너가 버렸다. 어느 쪽도 사용자에게는
"버튼을 눌렀는데 아무 일도 없다"로만 보인다. 그래서 선언 자체를 한 곳으로 묶고
`test_postman_layout.py`가 AST로 강제한다.

**002의 명령 집합은 4종이다.** 러너 상태기계 어휘(`pause`·`stop`·`kill`·`retry`·
`discard`·`approve`)는 러너와 함께 폐기했다. 답장과 버튼은 명령이 아니라 별도 경로다.

    status   진행 상태판
    done     사용자 처리 노드의 완료 신고 (노드 ID 필요)
    halt     지정 tmux 세션(지휘·작업)을 멈춘다 — 무인 지휘를 사람이 멈추는 유일한 수단
    resume   경성 발신 상한 해제 + 억제 요약 1건 발신

**만료 창의 분류도 여기 있다.** `SLOW_COMMANDS`는 사람의 답이 실려 오는 명령이라
`answer_window`(기본 하루)를 쓰고, 나머지는 조작 명령이라 `stale_window`(기본 5분)를 쓴다.
`halt`는 즉시 행동으로 옮기는 조작이므로 느린 쪽이 아니다 — 밤새 묵은 정지 명령이
뒤늦게 도착해 멀쩡히 도는 지휘를 죽이면 안 된다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""

COMMANDS = ("status", "done", "halt", "resume")

# 사람의 답이 실려 오는 명령 — 만료 창이 길다.
SLOW_COMMANDS = ("done",)

# 대상 노드 없이는 성립하지 않는 명령.
NODE_REQUIRED = ("done",)

# 대상 주소(tmux 세션명 또는 `all`) 없이는 성립하지 않는 명령.
TARGET_REQUIRED = ("halt",)

# 버튼 레코드가 실을 수 있는 종류. 명령 4종에 더해 질문 선택지(`choice`)가 있다 —
# 선택지는 명령이 아니라 세션에 그대로 주입될 답 문자열이다 (ADR-002 D2).
ACTION_KINDS = COMMANDS + ("choice",)

# 명령 대상 자리에 쓸 수 있는 예약어. tmux 세션명 이름공간과 겹치지 않게 여기 모아 둔다.
ALL_TARGET = "all"


def is_command(value):
    return isinstance(value, str) and value in COMMANDS


def is_action_kind(value):
    return isinstance(value, str) and value in ACTION_KINDS


def is_slow(cmd):
    """이 명령의 만료 창이 `answer_window`인가(아니면 `stale_window`)."""
    return cmd in SLOW_COMMANDS


def needs_node(cmd):
    return cmd in NODE_REQUIRED


def needs_target(cmd):
    return cmd in TARGET_REQUIRED


def parse_action(action):
    """버튼의 `action` 문자열을 해석한다. `"<kind>"` 또는 `"<kind>:<선택지>"`.

    열거형 밖이면 None. 만드는 쪽도 받는 쪽도 이 함수 하나로 검사한다 — 검사 규칙이
    둘로 갈리면 한쪽만 통과하는 버튼이 생긴다.
    """
    if not isinstance(action, str) or not action:
        return None
    head, _, choice = action.partition(":")
    kind = head.strip().lower()
    if kind not in ACTION_KINDS:
        return None
    return (kind, choice.strip() or None)
