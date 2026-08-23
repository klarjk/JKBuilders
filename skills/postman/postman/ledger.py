"""부작용 1회 한정 장부 (ADR-002 D2, ADR-001 D9 승계).

⚠️ **001에 구현이 0건이던 신규 작성분이다.** 001의 1회 한정은 러너 프로세스의 메모리
집합(`notified_user_nodes`·`asked_seq`)뿐이었고 **프로세스가 죽으면 함께 사라졌다.**
002의 지휘 세션은 교체를 전제로 하므로(핵심 기능이다) 그 상태는 반드시 파일로 나가야
한다 — 그러지 않으면 001 N12 결함 6(같은 질문 12회 발신)이 **교체할 때마다** 재현된다.

대상 넷: 질문 발신, 안내·경보 1회 한정, `halt`·`resume` 처리, 그리고 **주입**.

**주입만 2단 기록이다.** 실행 전 의도(intent) → 주입 → 완료(done). 재기동한 우체부가
intent만 있고 done이 없는 항목을 만나면 **재주입하지 않는다** — 본문은 들어갔는데 Enter
전에 죽었거나(입력창에 문자열이 걸린 채) 기록 전에 죽었을 수 있고, 화면 상태는 파일
복구로 되돌릴 수 없다. 해당 답은 보관분으로 옮기고 사용자에게 모호 상태를 알린다.
"답은 한 번만 넣는다"(N12 결함 2 회귀)가 **프로세스 경계를 넘어** 유지되는 것은 이 2단
기록 덕이다.

장부 손상은 fail-open(격리 후 빈 장부 재시작 + alert 1건)이고, **상한(`limits.py`)이 2차
선**이다 — 장부가 날아가도 발신이 무한히 나가지는 않는다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import time

from postman import paths
from postman.store import JsonStore

MAX_ENTRIES = 2000

INTENT = "intent"
DONE = "done"


# ---------------------------------------------------------------- 키 조립

def question_key(session, generation, seq):
    """질문 발신 — 세션·세대·일련번호. 세대가 키에 있어야 교체 후 같은 질문을 다시 묻는다."""
    return "q:%s:g%s:%s" % (session, generation, seq)


def inject_key(session, generation, seq):
    """답 주입 — 질문과 같은 좌표. 답은 질문 하나당 한 번만 들어간다."""
    return "inject:%s:g%s:%s" % (session, generation, seq)


def command_key(cmd, update_id):
    """조작 명령 — 업데이트 id가 곧 1회성이다. 오프셋이 날아가 재수신돼도 두 번 돌지 않는다."""
    return "cmd:%s:%s" % (cmd, update_id)


def notice_key(name, subject=""):
    """안내·경보 1회 한정 — 같은 사유의 알림을 되풀이하지 않는다."""
    return "notice:%s:%s" % (name, subject)


# ---------------------------------------------------------------- 장부

class Ledger(JsonStore):
    def __init__(self, path=None):
        JsonStore.__init__(self, path or paths.ledger_file())

    # -- 1단 기록 (질문·안내·명령) ---------------------------------------

    def record_once(self, key, now=None):
        """처음 보는 키면 기록하고 True. 이미 있으면 아무것도 하지 않고 False.

        호출자는 **True일 때만** 그 부작용을 실행한다.
        """
        now = time.time() if now is None else float(now)
        data = self.load()
        if key in data:
            return False
        data[key] = {"state": DONE, "ts": now}
        self.save(_trim(data))
        return True

    def has(self, key):
        return key in self.load()

    # -- 2단 기록 (주입) --------------------------------------------------

    def begin(self, key, now=None):
        """주입 의도를 먼저 남긴다. **기록이 주입에 선행한다** (D1).

        처음이면 True. 이미 intent나 done이 있으면 False — 호출자는 주입하지 않는다.
        """
        now = time.time() if now is None else float(now)
        data = self.load()
        if key in data:
            return False
        data[key] = {"state": INTENT, "ts": now}
        self.save(_trim(data))
        return True

    def complete(self, key, now=None):
        """주입이 화면에 반영된 것을 확인한 뒤 완료로 올린다."""
        now = time.time() if now is None else float(now)
        data = self.load()
        record = data.get(key)
        if not isinstance(record, dict):
            record = {"ts": now}
        record["state"] = DONE
        record["done_ts"] = now
        data[key] = record
        self.save(_trim(data))
        return True

    def release(self, key):
        """**아직 화면에 아무것도 넣지 않은** 의도를 지운다. `done`은 절대 지우지 않는다.

        2단 기록의 안전성은 "죽으면 intent가 남는다"에서 나온다. 이 함수는 프로세스가
        **살아서 "보내지 않았음"을 아는** 경로에서만 부른다 — 캡처 실패, 질문이 이미
        닫힘, 대상 소멸 확인. 죽는 경로는 여기 오지 않으므로 crash-safety는 그대로다.

        지우지 않으면 그 좌표가 영구히 모호(ambiguous)로 남아, 아무것도 넣지 않았음이
        확실한데도 사람이 손으로 확인해 줄 때까지 그 질문에 다시 답할 수 없다.
        """
        data = self.load()
        record = data.get(key)
        if not isinstance(record, dict) or record.get("state") != INTENT:
            return False
        del data[key]
        self.save(data)
        return True

    def state(self, key):
        """`intent` · `done` · None."""
        record = self.load().get(key)
        return record.get("state") if isinstance(record, dict) else None

    def is_ambiguous(self, key):
        """intent만 있고 done이 없다 — 넣었는지 알 수 없으므로 **재주입하지 않는다**."""
        return self.state(key) == INTENT

    def ambiguous_keys(self):
        """재기동 직후 훑는다. 여기 걸린 답은 보관분으로 옮기고 사람에게 확인을 청한다."""
        data = self.load()
        return sorted(k for k, v in data.items()
                      if isinstance(v, dict) and v.get("state") == INTENT)


def _trim(data, limit=MAX_ENTRIES):
    """오래된 것부터 버리되 **미완(intent) 주입 기록은 버리지 않는다.**

    intent 레코드가 정리에 휩쓸리면 `is_ambiguous`가 None을 돌려주고, 재기동한 우체부가
    "안 넣었다"고 오판해 재주입한다 — 이 모듈이 막으려던 001 N12 결함 2(중복 주입)가
    장부 안에서 되살아나는 경로다. 미완은 완료되거나 사람이 처분할 때까지 남는다.
    """
    if len(data) <= limit:
        return data
    keep = dict((k, v) for k, v in data.items()
                if isinstance(v, dict) and v.get("state") == INTENT)
    rest = sorted(((k, v) for k, v in data.items() if k not in keep),
                  key=lambda kv: float((kv[1] or {}).get("ts", 0)))
    room = max(limit - len(keep), 0)
    keep.update(dict(rest[len(rest) - room:] if room else ()))
    return keep
