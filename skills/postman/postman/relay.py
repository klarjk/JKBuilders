"""중계 상태 파일 `relay.json` 읽기 (ADR-002 D3).

**쓰는 주체는 창구 하나뿐이고 우체부는 읽기만 한다** — D2의 「파일 하나에 쓰는 주체는
정확히 하나」 불변식이다. 그래서 이 모듈에는 쓰기 함수가 없다.

우체부가 이 파일에서 가져가는 것은 셋이다.

1. **현 지휘 주소와 세대** — 답장 라우팅의 최후 기본값(매핑이 우선), 버튼·재주입의 세대 대조
2. **상태(`state`)** — `replacing` 동안 신규 주입을 유예하고, 유휴 판정에서 지휘 부재를
   유휴로 세지 않는다(`replacing`·`failed`가 24시간 이내면). `replacing` 고착이 통로를
   닫아 **우체부가 자멸하는** 사고를 막는 장치다(D3 ④)
3. **프로젝트 슬러그** — 본 ADR은 단일 프로젝트 운용 전제다. 다른 프로젝트의 지휘가 살아
   있으면 우체부는 기동을 거부한다(D3, ADR-001 D1의 슬러그 충돌 기동 거부 축소 승계)

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import datetime
import time

from postman import addressing
from postman import paths

RUNNING = "running"
DRAINING = "draining"
REPLACING = "replacing"
FAILED = "failed"

# 지휘 부재를 유휴로 세지 않는 상태들 (D3 ④·D8).
TRANSIENT_STATES = (REPLACING, FAILED, DRAINING)


class Relay(object):
    def __init__(self, data=None, path=None):
        data = data if isinstance(data, dict) else {}
        self.path = path
        self.exists = bool(data)
        self.project = data.get("project")
        self.dev_plan = data.get("dev_plan")
        command = data.get("command") if isinstance(data.get("command"), dict) else {}
        self.tmux = command.get("tmux") if addressing.is_session_name(command.get("tmux")) else None
        self.uuid = command.get("uuid") if addressing.is_session_uuid(command.get("uuid")) else None
        try:
            self.generation = int(command.get("generation", 0))
        except (TypeError, ValueError):
            self.generation = 0
        self.state = data.get("state") if isinstance(data.get("state"), str) else None
        self.state_ts = _timestamp(data.get("state_ts"))
        self.updated_ts = _timestamp(data.get("updated_ts")) or self.state_ts
        self.replace_reason = data.get("replace_reason")

    @property
    def running(self):
        return self.state == RUNNING

    def transient(self, now=None, window=86400.0):
        """`replacing`·`failed`·`draining`이고 갱신이 `window` 이내인가 (D3 ④).

        고착된(오래된) 과도 상태는 과도로 쳐주지 않는다 — 그래야 통로가 영영 닫히지 않는다.
        """
        if self.state not in TRANSIENT_STATES:
            return False
        now = time.time() if now is None else float(now)
        stamp = self.updated_ts
        if stamp is None:
            return False
        return (now - stamp) <= float(window)

    def __repr__(self):
        return "Relay(project=%r, tmux=%r, g=%d, state=%r)" % (
            self.project, self.tmux, self.generation, self.state)


def read(path=None):
    """`relay.json`을 읽는다. 없거나 손상이면 빈 Relay — 우체부는 읽기만 하므로 격리하지 않는다."""
    path = path or paths.relay_file()
    return Relay(paths.read_json(path), path=path)


def _timestamp(value):
    """ISO8601 문자열 또는 epoch 숫자를 epoch 초로. 못 읽으면 None."""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    # 시간대가 없으면 로컬 시각으로 읽는다 — 창구가 이 기계에서 쓴 값이다.
    return parsed.timestamp()
