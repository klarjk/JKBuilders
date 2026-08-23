"""발신 상한 2단 — 시간당 연 30 / 경 60 (ADR-002 D2, ADR-001 D9 승계).

장부(`ledger.py`)가 1차 선이고 **이것이 2차 선**이다. 장부가 손상돼 날아가도 발신이
무한히 나가지는 않는다 — 001 N12 결함 6(같은 질문 12회 발신)의 진짜 대가는 토큰이
아니라 사용자 신뢰였다.

두 단의 성격이 다르다.

| 단 | 값 | 넘으면 | 면제 |
|---|---:|---|---|
| 연성 | 30/시간 | 그 발신만 억제 | **완료 보고·`question`·`alert`** |
| 경성 | 60/시간 | 자동 발신 전면 중단 | **사용자 명령에 대한 응답** |

연성 면제를 원문대로 옮기는 이유: 대기 해제성·인수인계성 발신을 막으면 **루프가 조용히
멈춘다.** 002에서 `question`·`alert`는 지휘·창구가 사람에게 닿는 유일한 수단이라 더
절실하다.

경성 중단은 창이 굴러도 **저절로 풀리지 않는다.** 해제는 `resume` 명령 하나뿐이고, 해제
시 억제된 건수를 요약 1건으로 알린다 — 조용히 재개하면 그 사이 무엇이 사라졌는지 아무도
모른다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import time

from postman import paths
from postman.store import JsonStore

# 발신 종류. 명령 열거형과 다른 이름공간이다 — 명령은 들어오는 것, 이것은 나가는 것이다.
SEND_KINDS = ("notify", "question", "alert", "done_report", "reply", "system")

# 연성 상한 면제 — 대기 해제성·인수인계성 발신. **사용자 명령 응답(`reply`)도 여기 있다** —
# 상한이 다스리는 것은 *자동* 발신이고, 사용자가 방금 친 명령에 대한 답은 자동 발신이 아니다.
# 이것까지 세면 사용자가 `status`를 쳐도 아무 반응이 없어 우체부가 죽은 것과 구별되지 않는다.
SOFT_EXEMPT = ("question", "alert", "done_report", "reply")

# 경성 상한 면제 — 사용자가 방금 친 명령에 대한 응답. 이것까지 막으면 사용자는 우체부가
# 죽었는지 막힌 것인지 구별할 수 없고, `resume`을 쳐도 아무 반응이 없다.
HARD_EXEMPT = ("reply",)

ALLOW = "allow"
SOFT_BLOCKED = "soft"
HARD_BLOCKED = "hard"


class SendLimiter(JsonStore):
    def __init__(self, path=None, soft_limit=30, hard_limit=60, window=3600.0):
        JsonStore.__init__(self, path or paths.counters_file())
        self.soft_limit = int(soft_limit)
        self.hard_limit = int(hard_limit)
        self.window = float(window)

    # ------------------------------------------------------------------ 판정

    def check(self, kind, now=None):
        """`allow` · `soft` · `hard`. **세지 않는다** — 판정만 본다."""
        now = time.time() if now is None else float(now)
        state = self._state(now)
        if state.get("hard_blocked") and kind not in HARD_EXEMPT:
            return HARD_BLOCKED
        sent = int(state.get("sent", 0))
        if sent >= self.hard_limit and kind not in HARD_EXEMPT:
            return HARD_BLOCKED
        if sent >= self.soft_limit and kind not in SOFT_EXEMPT:
            return SOFT_BLOCKED
        return ALLOW

    def consume(self, kind, now=None):
        """판정 + 계수 갱신을 한 번에. 허용이면 True, 억제면 False."""
        now = time.time() if now is None else float(now)
        state = self._state(now)
        verdict = self.check(kind, now=now)
        if verdict == ALLOW:
            state["sent"] = int(state.get("sent", 0)) + 1
        else:
            state["suppressed"] = int(state.get("suppressed", 0)) + 1
            if verdict == HARD_BLOCKED:
                state["hard_blocked"] = True
        state["last_kind"] = kind if kind in SEND_KINDS else "system"
        self.save(state)
        return verdict == ALLOW

    # ------------------------------------------------------------------ 해제

    def release(self, now=None):
        """`resume` — 경성 중단을 풀고 창을 새로 연다. 억제된 건수를 돌려준다."""
        now = time.time() if now is None else float(now)
        state = self._state(now)
        suppressed = int(state.get("suppressed", 0))
        self.save({"window_start": now, "sent": 0, "suppressed": 0, "hard_blocked": False})
        return suppressed

    def suppressed(self, now=None):
        now = time.time() if now is None else float(now)
        return int(self._state(now).get("suppressed", 0))

    def blocked(self, now=None):
        now = time.time() if now is None else float(now)
        return bool(self._state(now).get("hard_blocked"))

    # ------------------------------------------------------------------ 내부

    def _state(self, now):
        data = self.load()
        try:
            window_start = float(data.get("window_start", 0) or 0)
        except (TypeError, ValueError):
            window_start = 0.0
        if now - window_start >= self.window:
            # 창이 굴렀다. **억제 건수와 경성 중단은 남긴다** — 해제는 `resume`뿐이고,
            # 억제된 것이 있었다는 사실은 사람이 볼 때까지 지워지면 안 된다.
            data = {
                "window_start": now,
                "sent": 0,
                "suppressed": int(data.get("suppressed", 0) or 0),
                "hard_blocked": bool(data.get("hard_blocked")),
            }
        else:
            data.setdefault("window_start", window_start or now)
            data.setdefault("sent", 0)
            data.setdefault("suppressed", 0)
            data.setdefault("hard_blocked", False)
        return data
