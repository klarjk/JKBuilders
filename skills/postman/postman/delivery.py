"""우편함 → 텔레그램 배달 (ADR-002 D2, ADR-001 D1 승계).

세션들이 자기 우편함에 파일만 쓰고, 우체부가 훑어 보낸다. **세션은 텔레그램을 모른다** —
파일이 놓인 경로가 곧 출처 증명이라 다른 세션 사칭이 원천 차단된다.

지키는 것 넷.

- **알림(`notify-*.json`)은 텍스트만 싣는다.** `buttons`가 들어 있어도 버린다 — 비신뢰
  텍스트가 조작 버튼을 제시하지 못하게 한다. 버튼은 `question-*.json`의 `choices`에서만
  나온다(D2).
- **원본을 지우지도 고치지도 않는다.** 발신 완료는 `.sent` 표식으로만 남긴다. 우편함
  삭제 권한은 청소(`mailbox.cleanup`)에만 있다.
- **안정화 확인 후에만 읽는다.** 세션이 쓰는 중인 파일을 반쯤 읽지 않게, 갱신이 멈춘 지
  `settle_interval`이 지난 것만 소비한다. `settle_timeout`까지 파싱·필수 필드를 통과하지
  못하면 `corrupt/`로 격리한다 — 격리가 없으면 손상 파일이 매 순회 경고만 남기며 영원히
  재시도된다.
- **발신 실패면 표식을 남기지 않는다.** 지우거나 표식을 붙이면 세션이 쓴 질문·경보가
  사라지고, 세션에는 다시 보낼 수단이 없다.

**억제(발신 상한)는 파일당 한 번만 센다.** 매 순회마다 세면 한 시간 막힌 알림 하나가
수천 건의 억제로 불어 `resume` 요약이 무의미해진다. 첫 순회에 한 번 세고, 그 뒤로는
상한을 미리 보고 조용히 미룬다 — 파일은 남아 있으므로 해제되면 나간다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import time

from postman import addressing
from postman import eventlog
from postman import ledger as ledger_mod
from postman import limits as limits_mod
from postman import mailbox
from postman import paths
from postman import relay as relay_mod
from postman import sender as sender_mod

log = logging.getLogger("postman.delivery")

# 알림 파일이 스스로 고를 수 있는 발신 종류. 상한 면제 등급이 달라진다(`limits.py`).
# `alert`는 연성 면제라 창구의 재스폰 실패 통보가 상한에 막히지 않는다.
NOTIFY_KINDS = ("notify", "alert", "done_report")

# 한 질문에 붙일 수 있는 버튼 수. 넘치면 앞에서부터 자른다 — 화면을 덮는 키보드는
# 사람이 못 읽고, `callback_data` 레코드만 쌓인다.
MAX_BUTTONS = 8


class Delivery(object):
    def __init__(self, config, actions, messages, ledger=None, clock=time.time,
                 relay_reader=relay_mod.read):
        self.config = config
        self.actions = actions
        self.messages = messages
        self.ledger = ledger or ledger_mod.Ledger()
        self.clock = clock
        self.relay_reader = relay_reader

    # ------------------------------------------------------------------ 순회

    def deliver_all(self, sender, now=None):
        """보낸 건수. 한 파일의 실패가 다음 파일을 막지 않는다."""
        now = self.clock() if now is None else float(now)
        sent = 0
        for session, path in mailbox.all_unsent():
            try:
                if self._deliver_one(sender, session, path, now):
                    sent += 1
            except Exception as exc:      # 한 파일이 순회를 멈추지 않는다
                log.warning("배달 실패(%s): %s", path.name, type(exc).__name__)
        return sent

    def _deliver_one(self, sender, session, path, now):
        age = mailbox.age(path, now)
        if age is None:
            return False                              # 사라졌거나 stat 실패 — 다음 순회에
        if age <= -self.config.settle_timeout:
            # mtime이 한참 미래다(시계 이상·잘못된 쓰기). 기다려도 안정화되지 않는다.
            self._quarantine(session, path, "mtime이 미래")
            return False
        if age < self.config.settle_interval:
            return False                              # 아직 쓰는 중일 수 있다

        data = paths.read_json(path)
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            if age >= self.config.settle_timeout:
                self._quarantine(session, path, "파싱 또는 필수 필드 실패")
            return False

        if path.name.startswith("question-"):
            return self._deliver_question(sender, session, path, data, text, now)
        return self._deliver_notify(sender, session, path, data, text, now)

    # ------------------------------------------------------------------ 알림

    def _deliver_notify(self, sender, session, path, data, text, now):
        if data.get("buttons"):
            # 텍스트만이다 (D2). 비신뢰 텍스트가 조작 버튼을 제시하지 못하게 한다.
            log.warning("알림의 buttons 무시: %s", path.name)
        kind = data.get("kind")
        if kind not in NOTIFY_KINDS:
            kind = "notify"
        if self._held(sender, kind, path, now):
            return False
        # 출처 표시는 발신기가 단다(`sender._labeled`) — 여기서 또 붙이면 두 겹이 된다.
        result = sender.send_text(text, kind=kind, session=session)
        if result.status != sender_mod.SENT:
            return False                              # 표식을 남기지 않는다 — 다음 순회에 재시도
        mailbox.mark_sent(path, {"ts": now, "kind": kind})
        return True

    # ------------------------------------------------------------------ 질문

    def _deliver_question(self, sender, session, path, data, text, now):
        """질문은 선택지를 인라인 버튼으로 조립해 보내고, 답장 매칭 좌표를 남긴다."""
        generation, seq = mailbox.parse_question_name(path.name)
        if generation is None:
            # 이름이 규약 밖이다. 세대 접두가 없으면 전 세대 질문을 덮어쓸 수 있으므로
            # 좌표 없는 질문으로 취급해 본문만 보내고 매핑을 남기지 않는다.
            log.warning("질문 파일 이름이 규약 밖이다: %s", path.name)

        once_key = None
        if generation is not None:
            once_key = ledger_mod.question_key(session, generation, seq)
            if self.ledger.has(once_key):
                # 재기동으로 표식만 잃은 경우다. 같은 질문을 두 번 묻지 않는다 (D2).
                mailbox.mark_sent(path, {"ts": now, "kind": "question", "already": True})
                return False

        if self._held(sender, "question", path, now):
            return False

        relay = self.relay_reader()
        session_uuid = data.get("session_uuid")
        if session_uuid is None and session == relay.tmux:
            session_uuid = relay.uuid
        buttons = self._build_buttons(session, data, generation, session_uuid, seq)

        result = sender.send_text(text, kind="question", buttons=buttons, session=session)
        if result.status != sender_mod.SENT:
            return False

        if generation is not None:
            self.ledger.record_once(once_key, now=now)
        if result.message_ids:
            node = data.get("node")
            self.messages.remember(result.message_ids[-1], session,
                                   node=node if _is_node(node) else None,
                                   seq=seq, generation=generation,
                                   session_uuid=session_uuid, now=now)
        mailbox.mark_sent(path, {"ts": now, "kind": "question",
                                 "generation": generation, "seq": seq})
        return True

    def _build_buttons(self, session, data, generation, session_uuid, seq):
        """`choices`만 버튼이 된다. 라벨 마스킹은 발신기(`sender`)의 관문이 맡는다."""
        choices = data.get("choices")
        if not isinstance(choices, list):
            return None
        rows = []
        for choice in choices[:MAX_BUTTONS]:
            if not isinstance(choice, str) or not choice.strip():
                continue
            try:
                callback_data = self.actions.add(
                    session, "choice", choice=choice, node=_node_or_none(data.get("node")),
                    generation=generation, session_uuid=session_uuid, seq=seq,
                    now=self.clock(), ttl=self.config.action_ttl)
            except ValueError:
                log.warning("버튼 폐기 — 주소 또는 열거형 밖")
                continue
            rows.append([{"text": choice[:64], "callback_data": callback_data}])
        return rows or None

    # ------------------------------------------------------------------ 내부

    def _held(self, sender, kind, path, now):
        """상한에 걸려 미룰 것인가. **파일당 한 번만 센다.**"""
        limiter = getattr(sender, "limiter", None)
        if limiter is None or limiter.check(kind, now=now) == limits_mod.ALLOW:
            return False
        if self.ledger.record_once(ledger_mod.notice_key("held", path.name), now=now):
            limiter.consume(kind, now=now)      # 억제 1건으로 센다 — 요약에 남아야 한다
            eventlog.record("send_held", kind=kind, file=path.name, now=now)
            log.info("발신 상한으로 배달 보류: %s", path.name)
        return True

    def _quarantine(self, session, path, reason):
        moved = paths.quarantine(path, prefix=session)
        if moved is None:
            log.warning("우편함 격리 실패: %s", path.name)
        else:
            log.warning("우편함 격리(%s): %s", reason, path.name)
        eventlog.record("quarantine", session=session, file=path.name, reason=reason,
                        now=self.clock())


def _is_node(value):
    return addressing.is_node_id(value)


def _node_or_none(value):
    return value if _is_node(value) else None
