"""주입·세대 계층 — 코어가 확정한 것을 세션 화면에 넣는다 (ADR-002 D1·D2·D3·D7).

코어(`bot.py`)는 **누가 무엇을 말했는지까지만** 확정하고, 그것을 어느 화면에 넣을지와
넣었는지 확인하는 일이 여기 있다. `bot.Handler`가 그린 자리에 그대로 끼워진다.

경계 문구는 코어와 같다 (D1).

> **우체부는 프로젝트 상태를 해석하지 않는다 — 무엇을 넣을지는 결정하지 않고, 이미
> 결정된 문자열을 지정된 주소에 넣고 들어갔는지 확인한다.**

**라우팅의 1순위는 `messages.json` 매핑이고, 매핑이 없을 때만 현 지휘가 기본 대상이다**
(D2). 매핑에는 발급 시점의 세션·세대·`session_uuid`가 들어 있어, 답이 늦게 와도 그 답이
어느 세대의 어느 질문에 대한 것인지 남는다.

**세대가 바뀌면 답의 성격이 바뀐다.** 새 지휘 화면에 옛 질문이 열려 있을 리 없으므로
열림 확인을 요구하지 않고, 원 질문 요약을 동봉한 일반 주입으로 넣는다 (D7).

**교체 중(`replacing`)에는 그 지휘로 넣지 않는다** — 죽는 중인 pane에 쓰면 답이 허공으로
간다. 보관해 두었다가 `running`이 된 뒤에 넣는다 (D3 ②③).

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import time

from postman import commands as commands_mod
from postman import diag
from postman import eventlog
from postman import delivery as delivery_mod
from postman import inject as inject_mod
from postman import ledger as ledger_mod
from postman import mailbox
from postman import relay as relay_mod
from postman import store
from protocol import commands as protocol

log = logging.getLogger("postman.handler")

# 보관분 재주입을 몇 번까지 시도하는가. 넘으면 보류 표시를 달고 사람에게 알린다 —
# 매 순회 재시도는 같은 실패를 무한히 반복하며 로그만 채운다.
MAX_PENDING_ATTEMPTS = 3

# 세대가 바뀐 답에 동봉하는 원 질문 요약의 길이.
SUMMARY_CHARS = 80


class SessionHandler(object):
    """`bot.Handler`의 실물. 코어를 임포트하지 않는다 — 코어가 이쪽을 끼운다."""

    def __init__(self, config, ledger=None, actions=None, messages=None, deps=None,
                 clock=time.time, relay_reader=relay_mod.read, delivery=None):
        self.config = config
        self.clock = clock
        self.ledger = ledger or ledger_mod.Ledger()
        self.actions = actions or store.ActionStore(ttl=config.action_ttl)
        self.messages = messages or store.MessageMap()
        self.deps = deps or inject_mod.Deps(settle=config.settle_interval, now=clock)
        self.relay_reader = relay_reader
        self.delivery = delivery or delivery_mod.Delivery(
            config, self.actions, self.messages, ledger=self.ledger, clock=clock,
            relay_reader=relay_reader)

    # ------------------------------------------------------------------ 라우팅

    def lookup_message(self, message_id):
        return self.messages.lookup(message_id)

    def default_record(self, message_id=None):
        """매핑이 없는 답장의 기본 대상 — **현 지휘 하나뿐이다** (D2).

        매핑이 날아가는 경로는 실재한다(`messages.json` 손상 격리·트리밍). 그때 답장이
        갈 곳이 없다고 버리면, 사용자는 답을 보냈는데 아무 일도 없는 상태가 된다.
        """
        relay = self.relay_reader()
        if not relay.tmux:
            return None
        return {"session": relay.tmux, "generation": relay.generation,
                "session_uuid": relay.uuid, "node": None,
                "seq": "m%s" % message_id, "fallback": True}

    # ------------------------------------------------------------------ 답장

    def on_answer(self, text, record, message):
        """질문의 답장. 회신 문구를 돌려주면 코어가 보낸다."""
        record = record if isinstance(record, dict) else {}
        session = record.get("session")
        if not session:
            return "답이 어느 세션의 질문에 대한 것인지 확인하지 못했습니다."
        return self._deliver_answer(session, text, record)

    def _deliver_answer(self, session, answer, record, relay=None):
        # 호출자가 이미 읽은 `relay.json`이 있으면 **그 스냅샷을 쓴다.** 두 번 읽으면
        # 세대 대조와 실제 주입 사이에 창구의 갱신이 끼어드는 좁은 창이 생긴다.
        relay = self.relay_reader() if relay is None else relay
        is_command = (session == relay.tmux)
        record = self._with_question(session, record)

        if is_command and relay.state == relay_mod.REPLACING:
            # 교체 중이다. 죽는 중인 pane에 쓰지 않는다 (D3 ②).
            self._store_pending(session, answer, record, "replacing")
            return "지휘 세션 교체 중이라 답을 보관했습니다. 새 지휘가 서면 전달합니다."

        generation = record.get("generation")
        target_generation = relay.generation if is_command else generation
        changed = _generation_changed(generation, target_generation)

        # 새 화면에 옛 질문이 열려 있을 수 없다 — 요약을 동봉한 일반 주입이다 (D7).
        # **원 질문이 없으면 동봉하지 않는다** — `done` 같은 자기설명적 문자열에
        # "원문 없음"을 붙여 봐야 받는 쪽이 읽을 것만 늘어난다.
        payload = _envelope(answer, record.get("question")) if changed else answer

        key = ledger_mod.inject_key(session, target_generation, record.get("seq"))
        # 좌표는 **발급 세대**로 넘긴다 — 응답 표식은 질문 파일 옆에 붙고 그 이름은
        # 발급 시점의 세대다. 장부 열쇠의 `target_generation`을 넘기면 세대가 바뀐
        # 재주입이 있지도 않은 좌표를 보게 된다.
        result = inject_mod.inject_answer(
            session, payload, key, self.ledger, deps=self.deps,
            question=record.get("question"), choices=record.get("choices"),
            require_open=_require_open(record, changed),
            generation=record.get("generation"), seq=record.get("seq"))

        eventlog.record("inject", session=session, generation=target_generation,
                        seq=record.get("seq"), status=result.status, reason=result.reason,
                        now=self.clock())

        if result.status == inject_mod.INJECTED:
            self._write_answer_record(session, target_generation, record, result)
            return "전달했습니다: %s" % session
        if result.status == inject_mod.SKIPPED:
            return "이미 전달한 답입니다 — 두 번 넣지 않았습니다."
        if result.status == inject_mod.STORED:
            if result.reason == inject_mod.AMBIGUOUS:
                self._store_pending(session, answer, record, result.reason, blocked=True)
                return ("이전 주입이 완료 기록 없이 끊겨 다시 넣지 않았습니다. "
                        "화면을 확인해 주세요: tmux attach -t %s" % session)
            self._store_pending(session, answer, record, result.reason)
            return "대상 세션이 없어 답을 보관했습니다. 세션이 다시 서면 전달합니다."
        self._keep_capture(session, target_generation, record.get("seq"), result)
        return "%s — %s" % (_abort_headline(result.reason), inject_mod.attach_hint(session))

    def _with_question(self, session, record):
        """질문 원문·선택지를 우편함에서 되찾아 레코드에 채운다.

        매핑(`messages.json`)에는 좌표만 있고 본문이 없다. 본문이 없으면 **열림 확인이
        아무것도 못 본다** — 그러면 멀쩡히 열려 있는 질문에도 "닫혔다"고 중단한다.
        """
        if record.get("question") or record.get("fallback"):
            return record
        stored = mailbox.read_question(session, record.get("generation"), record.get("seq"))
        if not stored:
            return record
        record = dict(record)
        record["question"] = stored.get("question") or stored.get("text")
        if not record.get("choices"):
            record["choices"] = stored.get("choices")
        return record

    def _write_answer_record(self, session, generation, record, result):
        """주입 기록 파일. **실패해도 예외를 올리지 않는다** — 주입은 이미 성공한 뒤다.

        좌표가 숫자로 서지 않거나(매핑 없는 답장) 디스크가 막혀 못 써도, 장부에 done이
        있으므로 답이 되풀이되지는 않는다. 여기서 예외를 올리면 **성공한 주입에 대한
        회신만 사라져** 사용자는 답이 들어갔는지 알 수 없게 된다.
        """
        try:
            mailbox.write_answer(session, generation, record.get("seq"), result.payload,
                                 now=self.clock(), node=record.get("node"))
        except (TypeError, ValueError, OSError):
            log.info("주입 기록 파일을 남기지 못했다 — 주입 자체는 완료됐다")

    def _keep_capture(self, session, generation, seq, result):
        """중단한 주입의 화면 두 장을 진단 자리에 남긴다 (002-N7F ④).

        002-N7은 `not_reflected` 2건의 원인을 **캡처를 안 남겨** 확정하지 못했다. 사유
        문자열만으로는 "대상이 바빠 화면이 늦었다"와 "판정이 못 알아봤다"를 가를 수 없다.

        **캡처는 대상 세션의 화면 원문이라 마스킹 관문을 지나 저장한다** — `diag.save`가
        `never_send`까지 받아 그 일을 한다. 쓰기 실패는 그쪽에서 삼키므로 여기서 회신이
        끊기지 않는다.
        """
        if result.status != inject_mod.ABORTED:
            return None
        return diag.save(session, result.reason, before=result.before, after=result.after,
                         generation=generation, seq=seq,
                         never_send=self.config.never_send, now=self.clock())

    def _store_pending(self, session, answer, record, reason, blocked=False):
        """미주입분을 보관한다 (D7). `fallback`이 참이면 재주입도 열림 확인 없이 나간다."""
        return mailbox.store_pending(session, {
            "session": session,
            "answer": answer,
            "question": record.get("question"),
            "choices": record.get("choices"),
            "node": record.get("node"),
            "seq": record.get("seq"),
            "generation": record.get("generation"),
            "session_uuid": record.get("session_uuid"),
            "fallback": bool(record.get("fallback")),
            "reason": reason,
            "blocked": bool(blocked),
        }, now=self.clock())

    # ------------------------------------------------------------------ 버튼

    def on_callback(self, query, postman):
        """인라인 버튼. **1회 소진 + 세대 대조**가 전부다 (D2).

        레코드를 먼저 소진하고 나서 세대를 본다 — 순서를 뒤집으면 세대가 바뀐 버튼이
        소진되지 않은 채 남아 몇 번이고 다시 눌린다.
        """
        record = self.actions.take((query or {}).get("data"), now=self.clock())
        if record is None:
            return "이미 처리했거나 만료된 버튼입니다."

        session = record.get("session")
        if not self.deps.has_session(session):
            eventlog.record("button_void", reason="session_gone", now=self.clock())
            return "대상 세션이 없어 실행하지 않았습니다."

        relay = self.relay_reader()
        if session == relay.tmux and _stale_generation(record, relay):
            eventlog.record("button_void", reason="generation", now=self.clock())
            return "세대가 바뀌어 무효인 버튼입니다."

        kind = record.get("kind")
        if kind == "choice":
            reply = self._deliver_answer(session, record.get("choice") or "", {
                "session": session,
                "generation": record.get("generation"),
                "session_uuid": record.get("session_uuid"),
                "node": record.get("node"),
                "seq": record.get("seq"),
                "choices": [record.get("choice")],
            }, relay=relay)
            postman.reply(reply)
            return "선택을 전달했습니다."

        parsed = commands_mod.Parsed(cmd=kind, target=record.get("target"),
                                     node=record.get("node"))
        postman.dispatch(parsed, update_id="btn-%s" % record.get("id"))
        return "실행했습니다: %s" % kind

    # ------------------------------------------------------------------ 명령

    def on_command(self, cmd, parsed, postman):
        """코어가 처리하지 않는 명령 — 지금은 `done` 하나다.

        `done`은 **사용자가 손으로 처리한 노드의 완료 신고**라 지휘 세션이 알아야 한다.
        우체부는 그것을 해석하지 않고 열거형과 노드 ID를 그대로 실어 넣는다.
        """
        if not protocol.needs_node(cmd):
            # 코어가 `status`·`halt`·`resume`을 처리하므로 여기 오는 것은 `done`뿐이다.
            # 열거형이 늘어나면 판정도 열거형에게 묻는다 — 값을 여기 베껴 적지 않는다 (D1 ②).
            return "'%s'는 이 우체부가 처리하지 않습니다." % cmd
        node = parsed.node
        if not node:
            return "완료를 신고할 노드 ID를 함께 적어 주세요 — done 002-N4B"
        relay = self.relay_reader()
        if not relay.tmux:
            return "지휘 세션이 등록돼 있지 않아 전달하지 못했습니다."
        if relay.state == relay_mod.REPLACING:
            return "지휘 세션 교체 중입니다. 새 지휘가 선 뒤 다시 보내 주세요."

        seq = "done-%s" % node
        body = "[사용자] done %s" % node
        key = ledger_mod.inject_key(relay.tmux, relay.generation, seq)
        result = inject_mod.inject_answer(
            relay.tmux, body, key, self.ledger, deps=self.deps, require_open=False,
            generation=relay.generation, seq=seq)
        eventlog.record("inject", session=relay.tmux, generation=relay.generation,
                        seq=seq, status=result.status, reason=result.reason,
                        now=self.clock())
        if result.status == inject_mod.INJECTED:
            return "완료 신고를 전달했습니다: %s" % node
        if result.status == inject_mod.SKIPPED:
            return "이미 전달한 완료 신고입니다: %s" % node
        if result.status == inject_mod.STORED:
            if result.reason == inject_mod.AMBIGUOUS:
                return ("이전 완료 신고가 완료 기록 없이 끊겨 다시 넣지 않았습니다. "
                        "%s" % inject_mod.attach_hint(relay.tmux))
            # **완료 신고도 보관한다** (D7). 교체 창은 `relay.json`이 아직 옛 지휘를
            # 가리키는데 tmux는 이미 없는 상태를 만들고, 그 틈에 온 완료 신고를
            # "다시 보내 주세요"로 돌리면 자리를 비운 사용자에게는 유실과 같다.
            # 열림 확인은 애초에 없으므로(`fallback`) 재주입도 같은 형태로 나간다.
            self._store_pending(relay.tmux, body, {
                "seq": seq, "generation": relay.generation, "node": node,
                "session_uuid": relay.uuid, "fallback": True,
            }, result.reason)
            return "지휘 세션이 없어 완료 신고를 보관했습니다. 새 지휘가 서면 전달합니다."
        self._keep_capture(relay.tmux, relay.generation, seq, result)
        return "%s — %s" % (_abort_headline(result.reason), inject_mod.attach_hint(relay.tmux))

    # ------------------------------------------------------------------ 순회

    def deliver(self, postman, now=None):
        """우편함 → 텔레그램. 코어의 폴링 사이클마다 1회 (D2)."""
        return self.delivery.deliver_all(postman.sender, now=now)

    def retry_pending(self, postman, now=None):
        """보관분 재주입 (D7). 전달한 건수.

        **지휘 대상은 `running`이 된 뒤에만 넣는다** (D3 ③) — 창구가 준비 신호를 확인한
        뒤에야 `running`으로 올리므로, 그 전에 넣으면 TUI 초기화 중인 pane에 두 주체가 쓴다.
        """
        now = self.clock() if now is None else float(now)
        relay = self.relay_reader()
        delivered = 0
        for name, path in mailbox.all_pending():
            record = mailbox.load_pending(path)
            if record is None or record.get("blocked"):
                continue
            session = record.get("session") or name
            if not self.deps.has_session(session):
                continue
            if session == relay.tmux and not relay.running:
                continue
            try:
                reply = self._retry_one(session, dict(record), path, relay, now)
            except Exception as exc:
                # **한 보관분이 순회를 멈추지 않는다** — 배달(`delivery.py`)과 같은 원칙이다.
                # 필드가 손상된 파일 하나가 예외를 올리면, 사전순으로 뒤에 선 다른 세션의
                # 멀쩡한 보관분이 매 순회 시도조차 되지 못하고 무기한 갇힌다.
                log.warning("보관분 재주입 실패(%s): %s", path.name, type(exc).__name__)
                mailbox.update_pending(path, blocked=True, reason="corrupt")
                continue
            if reply is None:
                continue
            postman.sender.send_text(reply, kind="alert", session=session)
            delivered += 1
        return delivered

    def _retry_one(self, session, record, path, relay, now):
        """한 보관분. 회신할 말이 있으면 문자열, 없으면 None(다음 순회에 다시 본다)."""
        attempts = _attempts(record) + 1
        target_generation = relay.generation if session == relay.tmux else record.get("generation")
        changed = _generation_changed(record.get("generation"), target_generation)

        answer = record.get("answer") or ""
        payload = _envelope(answer, record.get("question")) if changed else answer

        key = ledger_mod.inject_key(session, target_generation, record.get("seq"))
        result = inject_mod.inject_answer(
            session, payload, key, self.ledger, deps=self.deps,
            question=record.get("question"), choices=record.get("choices"),
            require_open=_require_open(record, changed),
            generation=record.get("generation"), seq=record.get("seq"))
        eventlog.record("inject_retry", session=session, generation=target_generation,
                        status=result.status, reason=result.reason, attempts=attempts,
                        now=now)

        if result.status == inject_mod.INJECTED:
            self._write_answer_record(session, target_generation, record, result)
            mailbox.drop_pending(path)
            return "보관해 둔 답을 전달했습니다: %s" % session
        if result.status == inject_mod.SKIPPED:
            mailbox.drop_pending(path)
            return None                      # 이미 들어간 답이다 — 새삼 알릴 것이 없다
        if result.status == inject_mod.STORED and result.reason == inject_mod.AMBIGUOUS:
            mailbox.update_pending(path, attempts=attempts, blocked=True)
            return ("보관분 주입이 완료 기록 없이 끊겨 다시 넣지 않았습니다. "
                    "화면을 확인해 주세요: tmux attach -t %s" % session)
        if attempts >= MAX_PENDING_ATTEMPTS:
            mailbox.update_pending(path, attempts=attempts, blocked=True)
            self._keep_capture(session, target_generation, record.get("seq"), result)
            return ("보관해 둔 답을 %d회 넣어 봤습니다. %s — %s"
                    % (attempts, _abort_headline(result.reason),
                       inject_mod.attach_hint(session)))
        mailbox.update_pending(path, attempts=attempts)
        return None


# ---------------------------------------------------------------- 도우미

def _require_open(record, changed):
    """주입 직전 열림 확인을 걸 것인가.

    셋 중 하나면 걸지 않는다. ① **세대가 바뀌었다** — 새 지휘 화면에 옛 질문이 열려
    있을 수 없다(D7) ② **매핑 없는 답장·명령 중계다** — 대응하는 질문이 애초에 없다
    ③ **대조할 원문이 없다** — 질문 파일이 격리됐거나 세션이 본문을 안 적은 경우다.

    ③을 빠뜨리면 `question_open`이 볼 것 없이 항상 "닫혔다"를 돌려주고, 그 답은 세 번
    시도한 끝에 보류로 굳는다 — 사용자에게는 유실과 구별되지 않는다.
    """
    if changed or record.get("fallback"):
        return False
    return bool(record.get("question") or record.get("choices"))


def _attempts(record):
    """보관 레코드의 시도 횟수. 손상된 값은 0으로 읽는다 — 세다 말고 멈추지 않는다."""
    try:
        return int(record.get("attempts", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _generation_changed(issued, current):
    """발급 세대와 지금 세대가 다른가. 어느 한쪽을 모르면 **바뀌지 않은 것으로 본다.**

    모를 때 바뀌었다고 치면 멀쩡한 답에 요약이 덧붙고 열림 확인이 꺼진다 — 확인을 끄는
    쪽으로 기우는 기본값은 두지 않는다.
    """
    if issued is None or current is None:
        return False
    try:
        return int(issued) != int(current)
    except (TypeError, ValueError):
        return False


def _stale_generation(record, relay):
    """버튼 발급 시점의 지휘와 지금 지휘가 같은가 (D2).

    UUID가 1차 기준이다 — 세대는 창구가 올리는 값이고 UUID는 실제로 도는 프로세스다.
    """
    issued_uuid = record.get("session_uuid")
    if issued_uuid and relay.uuid and issued_uuid != relay.uuid:
        return True
    return _generation_changed(record.get("generation"), relay.generation)


def _envelope(answer, question):
    """세대가 바뀐 재주입의 겉봉 — 원 질문이 있을 때만 씌운다 (D7)."""
    if not question:
        return answer
    return "[보관된 답 · 원 질문: %s] %s" % (_summary(question), answer)


def _summary(question):
    text = " ".join(str(question or "").split())
    if not text:
        return "(원문 없음)"
    return text[:SUMMARY_CHARS] + ("…" if len(text) > SUMMARY_CHARS else "")


def _abort_headline(reason):
    """중단 사유별 머리말. **`not_reflected`만 성질이 다르다** (002-N7F ④).

    `not_open`·`send_failed`는 화면에 아무것도 안 들어갔음이 비교적 분명하다. 그러나
    `not_reflected`는 **`send-keys`가 성공한 뒤**의 상태라 "들어갔는데 못 알아봤다"가
    실재하는 갈래다 — 002-N7에서 실제로 전달된 결정 2건을 「안 닿았다」로 회신했고,
    사용자는 자기 결정이 무효가 된 줄 알았다. 확인 실패를 전달 실패로 말하지 않는다.

    같은 답을 그냥 다시 보내라고 권하지도 않는다 — 이미 들어간 답이면 두 번 들어간다.

    **화면을 보라는 당부는 여기서 하지 않는다.** 세 호출자 모두 뒤에 `attach_hint`를
    붙이므로, 머리말이 같은 말을 또 하면 구분자와 당부가 나란히 두 번 찍힌다. 머리말은
    "무엇이 확실하지 않은가"까지만 말하고 마무리는 안내에 넘긴다.
    """
    return {
        inject_mod.NOT_OPEN: "화면에 그 질문이 열려 있지 않아 넣지 않았습니다",
        inject_mod.SEND_FAILED: "주입 명령이 실패했습니다",
        inject_mod.NOT_REFLECTED: ("답을 넣었지만 화면에 반영됐는지 확인하지 못했습니다. "
                                   "이미 전달됐을 수 있으니 같은 답을 다시 보내기 전에"),
    }.get(reason, "주입을 중단했습니다")
