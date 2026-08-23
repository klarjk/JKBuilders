"""우체부의 영속 상태 — 오프셋과 그 아래 공용 JSON 저장소 (ADR-002 D2).

담는 것은 셋이다 — `getUpdates` 오프셋, **버튼 행동 레코드**(`actions.json`), **질문
메시지 매핑**(`messages.json`). 뒤 둘은 주입·세대 계층(002-N4B)이 붙으면서 들어왔다.

전부 파일에 즉시 반영한다(읽기도 매번 파일에서). 우체부가 재시작해도 상태가 살아남아야
하고, 메모리 캐시는 재기동과 함께 사라지기 때문이다. **지휘 세션이 교체를 전제로 하는
설계이므로**(002의 핵심 기능) 프로세스 수명에 기대는 상태는 하나도 두지 않는다.

**손상 처분은 fail-open이다** (D2). `offset.json`·`actions.json`·`messages.json`·
`ledger.json`은 손상 시 `corrupt/`로 격리하고 빈 파일로 다시 시작한 뒤 alert 1건을 낸다.
오프셋 소실로 답장·버튼을 다시 받더라도 **장부(주입·발신 키)와 버튼 1회 소진이 재실행을
막는다** — 손상 복구의 안전망이 장부이므로 장부 자신도 같은 규칙을 따른다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import secrets
import time
from pathlib import Path

from postman import addressing
from postman import paths
from protocol import commands as protocol

log = logging.getLogger("postman.store")


class JsonStore(object):
    """dict 하나를 파일에 담는 저장소. 손상은 격리 후 빈 상태로 재시작한다."""

    def __init__(self, path):
        self.path = Path(path)
        self.recovered = False   # 이번 프로세스에서 손상을 격리했는가 (alert 1건의 근거)

    def load(self):
        if not self.path.exists():
            return {}
        data = paths.read_json(self.path)
        if isinstance(data, dict):
            return data
        # 파일은 있는데 dict로 읽히지 않는다 — 부분 쓰기가 아니라 손상이다.
        moved = paths.quarantine(self.path, prefix="corrupt")
        self.recovered = True
        log.warning("상태 파일 손상 격리: %s -> %s", self.path.name, moved)
        return {}

    def save(self, data):
        paths.ensure_private_dir(self.path.parent)
        paths.atomic_write_json(self.path, data, indent=2)

    def take_recovery_flag(self):
        """손상 격리가 있었으면 True를 **한 번만** 돌려준다 — alert 중복 발신을 막는다."""
        if not self.recovered:
            return False
        self.recovered = False
        return True


class OffsetStore(JsonStore):
    """`getUpdates` 오프셋. 영속하지 않으면 재기동 시 몇 시간 전 명령이 뒤늦게 실행된다."""

    def __init__(self, path=None):
        JsonStore.__init__(self, path or paths.offset_file())

    def get(self):
        value = self.load().get("offset")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def set(self, offset):
        self.save({"offset": int(offset), "ts": time.time()})


# ---------------------------------------------------------------- 버튼 행동 레코드

CALLBACK_PREFIX = "v1|"

MAX_ACTIONS = 500
MAX_MESSAGES = 300


class ActionStore(JsonStore):
    """`callback_data` ↔ 행동 레코드 (ADR-002 D2, ADR-001 D1·D6 승계).

    `callback_data`가 64바이트라 세션명·노드ID를 직접 싣지 못한다. 레코드를 파일에
    영속하고 `v1|<id>`만 싣는다.

    **1회 소진이다.** 같은 버튼을 두 번 눌러도 한 번만 실행한다.

    **발급 시점의 `session_uuid`와 세대를 함께 적는다**(D2의 신규 요구). 버튼 처리 시
    현 `relay.json`과 대조해 불일치면 **소진 처리하되 실행하지 않는다** — 어제 버튼이
    오늘 눌려도 세대가 바뀌었으면 주입되지 않는다. `action_ttl` 24시간과 조작 명령
    `stale_window` 5분의 비대칭은 이 세대 검사로 실질 무해화된다.
    """

    def __init__(self, path=None, ttl=86400.0):
        JsonStore.__init__(self, path or paths.actions_file())
        self.ttl = float(ttl)

    def add(self, session, kind, choice=None, node=None, target=None, generation=None,
            session_uuid=None, seq=None, now=None, ttl=None):
        """행동 레코드를 저장하고 `callback_data`를 돌려준다. 열거형·주소 밖이면 ValueError."""
        if not protocol.is_action_kind(kind):
            raise ValueError("unknown action kind")
        addressing.safe_session_name(session)
        if node is not None:
            addressing.safe_node_id(node)
        if target is not None and target != protocol.ALL_TARGET:
            addressing.safe_session_name(target)
        now = time.time() if now is None else float(now)
        data = self.load()
        # 8바이트. 위조는 형식 검사·소진·만료·세대 대조가 이미 막지만, 추측 비용을
        # 올려 두는 값이 싸다 — `callback_data` 64바이트 한도에 한참 못 미친다.
        action_id = secrets.token_hex(8)
        while action_id in data:
            action_id = secrets.token_hex(8)
        data[action_id] = {
            "id": action_id,
            "session": session,
            "kind": kind,
            "choice": choice,
            "node": node,
            "target": target,
            "seq": seq,
            "generation": generation,
            "session_uuid": session_uuid,
            "expires": now + (self.ttl if ttl is None else float(ttl)),
            "consumed": False,
        }
        self.save(_trim_actions(_drop_dead(data, now)))
        return CALLBACK_PREFIX + action_id

    def take(self, callback_data, now=None):
        """소진 처리하고 레코드를 돌려준다. 모르는·이미 소진된·만료된 값이면 None."""
        action_id = parse_callback(callback_data)
        if action_id is None:
            return None
        now = time.time() if now is None else float(now)
        data = self.load()
        record = data.get(action_id)
        if not isinstance(record, dict) or record.get("consumed"):
            return None
        if float(record.get("expires", 0)) < now:
            return None
        record["consumed"] = True
        record["consumed_ts"] = now
        self.save(_trim_actions(_drop_dead(data, now)))
        return dict(record)


def parse_callback(callback_data):
    """`v1|<16진 id>` 형식만 받는다. 그 외는 None — 외부 입력이 그대로 키가 되지 않게 한다."""
    if not isinstance(callback_data, str) or not callback_data.startswith(CALLBACK_PREFIX):
        return None
    action_id = callback_data[len(CALLBACK_PREFIX):]
    if not action_id or len(action_id) > 32 or not all(c in "0123456789abcdef" for c in action_id):
        return None
    return action_id


def _drop_dead(data, now):
    """만료 뒤 하루가 더 지난 레코드만 버린다 — 소진 직후 재클릭도 '이미 처리됨'으로 답해야 한다."""
    return dict((k, v) for k, v in data.items()
                if isinstance(v, dict) and float(v.get("expires", 0)) + 86400 >= now)


def _trim_actions(data, limit=MAX_ACTIONS):
    if len(data) <= limit:
        return data
    items = sorted(data.items(), key=lambda kv: float(kv[1].get("expires", 0)))
    return dict(items[len(items) - limit:])


class MessageMap(JsonStore):
    """질문 message_id ↔ {세션(tmux명), session_uuid, 노드, 세대, seq} (ADR-002 D2).

    자유 답변이 그 질문의 **답장**으로 돌아오면 여기서 원 좌표를 되찾는다. 매핑이
    라우팅의 1순위이고, 매핑이 없을 때만 현 지휘가 기본 대상이다.
    """

    def __init__(self, path=None):
        JsonStore.__init__(self, path or paths.messages_file())

    def remember(self, message_id, session, node=None, seq=None, generation=None,
                 session_uuid=None, now=None):
        addressing.safe_session_name(session)
        if node is not None:
            addressing.safe_node_id(node)
        data = self.load()
        data[str(int(message_id))] = {
            "session": session,
            "node": node,
            "seq": seq,
            "generation": generation,
            "session_uuid": session_uuid,
            "ts": time.time() if now is None else float(now),
        }
        if len(data) > MAX_MESSAGES:
            items = sorted(data.items(), key=lambda kv: float((kv[1] or {}).get("ts", 0)))
            data = dict(items[len(items) - MAX_MESSAGES:])
        self.save(data)
        return data

    def lookup(self, message_id):
        try:
            record = self.load().get(str(int(message_id)))
        except (TypeError, ValueError):
            return None
        return dict(record) if isinstance(record, dict) else None
