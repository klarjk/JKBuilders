"""우체부 — 머신 전역 1개의 텔레그램 중계 프로그램 (ADR-002 D1·D2·D8).

경계 문구는 이것 하나다 (D1).

> **우체부는 프로젝트 상태를 해석하지 않는다 — 무엇을 넣을지는 결정하지 않고, 이미
> 결정된 문자열을 지정된 주소에 넣고 들어갔는지 확인한다.**

이 파일이 소유하는 것은 **코어**다.

1. 수신 폴링 — 오프셋 영속·허용 상대 검증·지연 명령 폐기
2. 발신 — 마스킹 관문 단일화·직렬 큐·상한 2단
3. 1회 한정 장부 — 부작용이 교체·재기동을 넘어 되풀이되지 않게
4. 생사 — 중복 기동 차단·heartbeat·유휴 자동 종료·**SIGTERM 정상 종료**

캡처→주입→재캡처, 보관분 재주입, 버튼 세대, 알림 파일 배달, 중계 라우팅은 **주입·세대
계층**(`handler.py`·`inject.py`·`delivery.py`) 몫이고, `Handler`(아래) 자리에 끼워진다.
`main()`이 `handler.SessionHandler`를 끼운다 — 아무것도 끼우지 않고 띄운 우체부(코어
단독 시험)는 받은 것을 조용히 버리지 않고 사실대로 회신한다.

**종료 신호 처리가 001의 재발 방지 핵심이다.** 001의 봇은 SIGTERM을 무시해 SIGKILL로만
죽었고(2026-08-21 실측), 강제 종료는 잠금·오프셋 파일을 중간 상태로 남긴다. 여기서는
신호를 받으면 ① 폴링 루프를 빠져나오고 ② 오프셋을 확정 기록하고 ③ 미완 주입을 장부에
남기고 ④ 잠금을 풀고 exit 0이다. **두 번째 신호는 즉시 종료**다 — 정상 종료가 막혀도
사람이 SIGKILL까지 가지 않게 한다.

    python3 postman/bot.py            # 창구가 /dev-loop 시작 시 띄운다
    python3 postman/bot.py --check    # 설정·경로 자가 점검만 하고 종료 (네트워크 안 씀)

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import json
import logging
import os
import signal
import stat
import sys
import time
from pathlib import Path

# 스크립트로 직접 실행돼도 패키지 임포트가 성립하게 우체부 루트를 얹는다.
_POSTMAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # postman/ -> skills/postman/
if _POSTMAN_ROOT not in sys.path:
    sys.path.insert(0, _POSTMAN_ROOT)

from postman import commands as commands_mod  # noqa: E402
from postman import diag                      # noqa: E402
from postman import eventlog                  # noqa: E402
from postman import handler as handler_mod    # noqa: E402
from postman import ledger as ledger_mod      # noqa: E402
from postman import limits as limits_mod      # noqa: E402
from postman import mailbox                   # noqa: E402
from postman import paths                     # noqa: E402
from postman import relay as relay_mod        # noqa: E402
from postman import store                     # noqa: E402
from postman import tmuxq                     # noqa: E402
from postman.sender import Sender             # noqa: E402
from postman.transport import HttpTransport, TelegramError  # noqa: E402
from protocol import commands as protocol     # noqa: E402

log = logging.getLogger("postman.bot")

HELP_TEXT = (
    "쓸 수 있는 명령: status · done · halt · resume\n"
    "한글도 됩니다(상태·완료·정지·재개).\n"
    "halt는 대상을 함께 적어 주세요 — halt <세션명> 또는 halt all\n"
    "done은 노드 ID를 함께 적어 주세요 — done 002-N4A\n"
    "질문에 대한 답은 그 질문 메시지에 **답장**으로 보내 주세요."
)


# 화면 미러 세션. 죽여도 아무것도 멈추지 않으므로 `halt all`의 대상이 아니다.
VIEW_SESSION = "dev-view"


class PostmanAlreadyRunning(RuntimeError):
    pass


class ProjectConflict(RuntimeError):
    """다른 프로젝트의 지휘가 살아 있다 — 본 ADR은 단일 프로젝트 운용 전제다 (D3)."""


class Handler(object):
    """주입·세대 계층(002-N4B)이 끼워지는 자리.

    코어는 **누가 무엇을 말했는지까지만** 확정하고, 그것을 세션 화면에 넣는 일은 이
    인터페이스 뒤에 있다. 기본 구현은 받은 것을 사실대로 되돌려 준다 — 조용히 버리는
    것보다 "아직 안 붙었다"고 말하는 쪽이 언제나 낫다.
    """

    def on_answer(self, text, record, message):
        return "답을 받았지만 주입 계층이 연결되지 않아 전달하지 못했습니다."

    def on_callback(self, query, postman):
        return "버튼 처리 계층이 연결되지 않았습니다."

    def on_command(self, cmd, parsed, postman):
        """`status`·`halt`·`resume`은 코어가 직접 처리하고 여기 오지 않는다."""
        return "'%s'는 주입 계층이 연결돼야 전달됩니다." % cmd

    def lookup_message(self, message_id):
        """답장이 어느 세션·질문에 걸린 것인지 — 매핑은 `messages.json` 소유."""
        return None

    def default_record(self, message_id=None):
        """매핑이 없는 답장의 기본 대상 (D2). 코어는 이것을 만들 재료를 갖지 않는다."""
        return None

    def deliver(self, postman, now=None):
        """우편함 → 텔레그램 배달. 폴링 사이클마다 코어가 부른다 (D2)."""
        return 0

    def retry_pending(self, postman, now=None):
        """보관분 재주입 (D7). 폴링 사이클마다 코어가 부른다."""
        return 0


class Postman(object):
    def __init__(self, transport, config, sender=None, offsets=None, ledger=None,
                 limiter=None, handler=None, clock=time.time, session_lister=None,
                 killer=None):
        self.transport = transport
        self.config = config
        self.clock = clock
        self.limiter = limiter if limiter is not None else limits_mod.SendLimiter(
            soft_limit=config.soft_send_limit, hard_limit=config.hard_send_limit,
            window=config.send_window)
        self.sender = sender or Sender(transport, config.chat_id,
                                       never_send=config.never_send,
                                       limiter=self.limiter,
                                       min_interval=config.min_send_interval,
                                       now=clock)
        self.offsets = offsets or store.OffsetStore()
        self.ledger = ledger or ledger_mod.Ledger()
        self.handler = handler or Handler()
        self.session_lister = session_lister or tmuxq.list_sessions
        self.killer = killer or tmuxq.kill

        self._running = False
        self._stopping = False
        self._stop_reason = None
        self._highest_offset = None
        self._absent_since = None        # 지휘 tmux 부재를 처음 관측한 시각 (D8)
        self._mailbox_absent_since = {}  # 우편함별 부재 관측 — 청소 판정 (D2)
        self._cleaned_at = None
        self._started_ts = clock()

    # ------------------------------------------------------------------ 수신

    def poll_once(self, timeout=None):
        """한 번 `getUpdates`. 처리한 업데이트 수를 돌려준다."""
        params = {
            "timeout": self.config.poll_timeout if timeout is None else timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        offset = self.offsets.get()
        if offset is not None:
            params["offset"] = offset
        try:
            updates = self.transport.call("getUpdates", params)
        except TelegramError as exc:
            if exc.status == 409:
                # 같은 토큰으로 다른 프로세스가 폴링 중이다. 텔레그램은 봇 하나당 수신자가
                # 하나뿐이라 이 상태에서는 메시지가 무작위로 갈린다.
                log.error("수신 충돌(409) — 같은 토큰으로 다른 프로세스가 폴링 중입니다")
            else:
                log.warning("getUpdates 실패: status=%s", exc.status)
            return 0
        if not isinstance(updates, list) or not updates:
            return 0

        handled = 0
        for update in updates:
            update_id = update.get("update_id") if isinstance(update, dict) else None
            try:
                self.handle_update(update)
            except Exception as exc:  # 한 건의 실패가 폴링을 멈추지 않는다
                log.warning("업데이트 처리 실패: %s", type(exc).__name__)
            handled += 1
            if isinstance(update_id, int):
                self._highest_offset = (update_id if self._highest_offset is None
                                        else max(self._highest_offset, update_id))
            if self._stopping:
                # 종료 신호가 들어왔다. **처리한 데까지만** 확정하고 나머지는 서버에 남긴다
                # (오프셋을 올리지 않은 업데이트는 다음 기동에서 다시 온다).
                break
        self.commit_offset()
        return handled

    def commit_offset(self):
        """처리한 데까지 오프셋을 확정한다. 종료 절차 ②이기도 하다 (D8)."""
        if self._highest_offset is None:
            return None
        self.offsets.set(self._highest_offset + 1)
        committed = self._highest_offset
        self._highest_offset = None
        return committed

    def handle_update(self, update):
        if not isinstance(update, dict):
            return
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message, update.get("update_id"))
        # edited_message는 처리하지 않는다 — 지난 메시지를 고쳐 명령을 재생하지 못하게 한다.

    def _handle_message(self, message, update_id=None):
        if not self._allowed(message.get("chat"), message.get("from")):
            return
        text = message.get("text")
        if not isinstance(text, str):
            return
        eventlog.record("recv", kind="message", update=update_id, text=text, now=self.clock())

        reply_to = message.get("reply_to_message") or {}
        reply_id = reply_to.get("message_id")
        record = None
        if reply_id:
            # 매핑이 1순위, 매핑이 없을 때만 현 지휘가 기본 대상이다 (D2). 매핑이 날아가는
            # 경로는 실재하고(손상 격리·트리밍), 그때 답장을 버리면 사용자는 답을 보냈는데
            # 아무 일도 일어나지 않는 상태에 놓인다.
            record = (self.handler.lookup_message(reply_id)
                      or self.handler.default_record(reply_id))
        if record:
            # 자유 답변 — 원 질문의 세션·질문으로 그대로 잇는다. 만료 창은 조작 명령보다
            # 훨씬 길다(만료 대상은 조작 명령이다). 자리를 비운 사이 온 질문에 나중에
            # 답해도 그 답이 세션에 닿아야 루프가 멈추지 않는다.
            if self._stale(message.get("date"), window=self.config.answer_window):
                log.info("만료된 답변 폐기")
                self.reply("답변이 너무 늦어 폐기했습니다. 질문이 아직 유효하면 다시 물어보겠습니다.")
                return
            reply = self.handler.on_answer(text, record, message)
            if reply:
                self.reply(reply)
            return

        if self._stale(message.get("date")):
            log.info("지연된 명령 폐기")
            self.reply("지연된 명령이라 폐기했습니다. 다시 보내 주세요.")
            return

        parsed = commands_mod.parse_command(text, sessions=self.live_sessions())
        if parsed.cmd is None:
            log.info("열거형 밖 입력 폐기")
            self.reply(HELP_TEXT)
            return
        self.dispatch(parsed, update_id=update_id)

    def _handle_callback(self, query):
        if not isinstance(query, dict):
            return
        message = query.get("message") or {}
        if not self._allowed(message.get("chat"), query.get("from")):
            return  # 무응답 폐기 — answerCallbackQuery조차 하지 않는다 (D2)
        eventlog.record("recv", kind="callback", now=self.clock())
        answer = self.handler.on_callback(query, self)
        if answer:
            self.sender.answer_callback(query.get("id"), answer)

    def _allowed(self, chat, user):
        """① 1:1 개인 채팅 ② `from.id`가 허용 목록 — **둘 다** 만족해야 한다 (D2).

        `callback_query.from.id`도 같은 검사를 지난다 — 버튼은 다른 문이 아니다.
        """
        chat = chat if isinstance(chat, dict) else {}
        user = user if isinstance(user, dict) else {}
        if chat.get("type") != "private" or not self.config.is_allowed(user.get("id")):
            log.info("허용되지 않은 업데이트 폐기 (chat_type=%s)", chat.get("type"))
            eventlog.record("rejected", chat_type=chat.get("type"), now=self.clock())
            return False
        return True

    def _stale(self, date, window=None):
        if not isinstance(date, (int, float)):
            return False
        window = self.config.stale_window if window is None else float(window)
        return (self.clock() - float(date)) > window

    # ------------------------------------------------------------------ 명령

    def dispatch(self, parsed, update_id=None):
        """닫힌 열거형 4종. `status`·`halt`·`resume`은 코어가 직접 처리한다."""
        cmd = parsed.cmd
        if cmd == "status":
            self.reply(self.status_text())
            return True
        if cmd == "resume":
            return self._do_resume(update_id)
        if cmd == "halt":
            return self._do_halt(parsed, update_id)
        answer = self.handler.on_command(cmd, parsed, self)
        if answer:
            self.reply(answer)
        return False

    def _do_resume(self, update_id):
        """경성 발신 상한 해제 + 억제 요약 1건 (D2). 장부로 1회 한정."""
        if update_id is None:
            log.warning("update_id 없는 명령 — 1회 한정 장부를 걸 수 없다")
        if update_id is not None and not self.ledger.record_once(
                ledger_mod.command_key("resume", update_id), now=self.clock()):
            return False
        suppressed = self.limiter.release(now=self.clock())
        eventlog.record("resume", suppressed=suppressed, now=self.clock())
        self.reply("발신을 재개합니다. 그동안 억제된 발신 %d건이 있었습니다." % suppressed)
        return True

    def _do_halt(self, parsed, update_id):
        """지정 세션(지휘·작업)을 멈춘다 — 무인 지휘를 사람이 멈추는 유일한 수단 (D2).

        대상이 없으면 실행하지 않는다. **이름을 짐작하지 않는다** — 비슷한 이름으로
        갈아타는 순간 남의 세션을 죽인다(D9의 오배송 차단과 같은 원칙).
        """
        target = parsed.target
        if not target:
            self.reply("멈출 대상을 함께 적어 주세요 — halt <세션명> 또는 halt all")
            return False
        if update_id is None:
            log.warning("update_id 없는 명령 — 1회 한정 장부를 걸 수 없다")
        if update_id is not None and not self.ledger.record_once(
                ledger_mod.command_key("halt:%s" % target, update_id), now=self.clock()):
            return False

        managed = self.managed_sessions()
        if target == protocol.ALL_TARGET:
            targets = managed
        elif target in managed:
            targets = [target]
        else:
            self.reply("이 우체부가 관리하는 세션이 아닙니다: %s" % target)
            return False
        killed = [name for name in targets if self.killer(name)]
        eventlog.record("halt", target=target, killed=len(killed), now=self.clock())
        if not killed:
            self.reply("멈출 세션을 찾지 못했습니다: %s" % target)
            return False
        self.reply("정지: %s" % ", ".join(killed))
        return True

    def status_text(self):
        """코어가 아는 것만 적는다 — 중계 상태·살아 있는 주소·발신 상한.

        노드 진행 상황은 우체부가 **해석하지 않는 것**이라 여기 없다(D1). 그것은 지휘
        세션이 자기 입으로 말한다.
        """
        relay = relay_mod.read()
        lines = ["우체부 가동 %d분" % int((self.clock() - self._started_ts) / 60)]
        if relay.exists:
            lines.append("지휘: %s (세대 %d, %s)" % (
                relay.tmux or "-", relay.generation, relay.state or "-"))
            if relay.project:
                lines.append("프로젝트: %s" % relay.project)
        else:
            lines.append("지휘: 등록된 중계 상태가 없습니다")
        sessions = self.live_sessions()
        lines.append("살아 있는 세션 %d개%s" % (
            len(sessions), (": " + ", ".join(sessions[:10])) if sessions else ""))
        if self.limiter.blocked(now=self.clock()):
            lines.append("⚠️ 발신 상한(경성)에 걸려 자동 발신을 멈춘 상태입니다 — resume으로 해제")
        suppressed = self.limiter.suppressed(now=self.clock())
        if suppressed:
            lines.append("억제된 발신 %d건" % suppressed)
        return "\n".join(lines)

    def reply(self, text):
        """사용자 명령에 대한 응답 — 경성 상한 면제 대상이다 (D2)."""
        return self.sender.send_text(text, kind="reply")

    def managed_sessions(self):
        """이 우체부가 멈춰도 되는 세션 — 현 지휘와 작업 세션뿐이다.

        `halt all`이 기계의 **모든** tmux 세션을 죽이면 개발과 무관한 세션(텔레그램 채널
        세션·사람이 띄워 둔 작업창)까지 함께 나간다. 대상은 이름으로 한정한다 (D9의
        이름 규칙): 지휘 `dev-cmd-<슬러그>`, 작업 `dev-<슬러그>-<노드id>`.

        프로젝트 슬러그를 알면 그 접두사만 본다. 모르면 `dev-`로 넓히되 화면 미러
        (`dev-view`)는 뺀다 — 미러를 죽여도 아무것도 멈추지 않고 사람만 눈이 먼다.
        """
        live = self.live_sessions()
        relay = relay_mod.read()
        names = set()
        if relay.tmux and relay.tmux in live:
            names.add(relay.tmux)
        if relay.project:
            prefixes = ("dev-cmd-%s" % relay.project, "dev-%s-" % relay.project)
        else:
            prefixes = ("dev-",)
        for name in live:
            if name == VIEW_SESSION:
                continue
            if any(name.startswith(prefix) for prefix in prefixes):
                names.add(name)
        return sorted(names)

    def live_sessions(self):
        try:
            return self.session_lister()
        except Exception as exc:
            log.warning("세션 목록 조회 실패: %s", type(exc).__name__)
            return []

    # ------------------------------------------------------------------ 유지

    def tick(self, now=None):
        """폴링 사이클마다 1회: heartbeat → 손상 통보 → **배달 → 재주입** → 청소 → 유휴 판정.

        배달·재주입이 유휴 판정보다 **앞에 선다** — 뒤에 두면 물러나기로 정한 순회에서
        나갈 수 있었던 알림이 한 번 덜 나간다.
        """
        now = self.clock() if now is None else float(now)
        self._touch_heartbeat()
        self._report_recovery()
        self._run_handler("deliver", now)
        self._run_handler("retry_pending", now)
        self._maybe_cleanup(now)
        return self._check_idle(now)

    def _run_handler(self, name, now):
        """주입 계층의 순회 작업. **실패해도 폴링을 멈추지 않는다** — 통로가 먼저다."""
        try:
            return getattr(self.handler, name)(self, now=now)
        except Exception as exc:
            log.warning("%s 실패: %s", name, type(exc).__name__)
            return 0

    def _touch_heartbeat(self):
        """지휘·창구가 우체부 생존을 판정하는 신호 (D2). 갱신 실패는 치명이 아니다."""
        path = paths.heartbeat_file()
        try:
            paths.ensure_private_dir(path.parent)
            path.touch()
        except OSError:
            log.warning("heartbeat 갱신 실패")

    def _report_recovery(self):
        """상태 파일 손상을 격리했으면 alert 1건. 장부로 1회 한정한다 (D2).

        **보낼 상대가 확정되지 않았으면(fail-closed) 아무것도 내보내지 않는다** — 그 상태의
        `chat_id`는 비어 있고, 비운 채로 부르면 텔레그램이 무엇을 할지는 우리 소관이 아니다.
        """
        if self.config.fail_closed:
            return
        for name, target in (("offset", self.offsets), ("ledger", self.ledger)):
            if not target.take_recovery_flag():
                continue
            if self.ledger.record_once(
                    ledger_mod.notice_key("corrupt", name), now=self.clock()):
                self.sender.send_text(
                    "%s 상태 파일이 손상돼 격리하고 빈 파일로 다시 시작했습니다." % name,
                    kind="alert")

    def _maybe_cleanup(self, now):
        """기동 시 1회 + 24시간 이상 연속 생존 시 하루 1회 (D2).

        유휴 종료 아래에서 "하루 1회"만 적으면 7일을 사는 우체부가 없어 청소가 영영 안
        돈다 — **기동 시 청소가 기본 경로다.**
        """
        if self._cleaned_at is not None and (now - self._cleaned_at) < self.config.cleanup_interval:
            return None
        live = self.live_sessions()
        for name in paths.list_session_mailboxes():
            if name in live:
                self._mailbox_absent_since.pop(name, None)
            else:
                self._mailbox_absent_since.setdefault(name, now)
        removed = mailbox.cleanup(now=now, max_age_days=self.config.max_age_days,
                                  live_sessions=live,
                                  absent_since=self._mailbox_absent_since)
        eventlog.cleanup(now=now, max_age_days=self.config.log_max_age_days)
        # 중단 진단 캡처도 같은 보존 창을 쓴다 — 남의 화면 원문이라 오래 쌓아 두지 않는다.
        diag.cleanup(now=now, max_age_days=self.config.log_max_age_days)
        self._cleaned_at = now
        paths.atomic_write_json(paths.cleanup_stamp_file(), {"last_ts": now, "removed": removed})
        log.info("청소: 알림 %s · 우편함 %s", removed.get("notify"), removed.get("mailboxes"))
        return removed

    def _check_idle(self, now):
        """유휴 자동 종료 (D8). 종료하기로 하면 사유 문자열, 아니면 None.

        001의 봇은 계획이 동결된 뒤에도 **25시간째 살아** `getUpdates`를 두드리고 있었다.
        텔레그램은 봇 하나당 수신자가 하나뿐이라 좀비가 남으면 새 우체부가 메시지를 받지
        못한다 — 그래서 스스로 물러난다.

        `replacing`·`failed`(24시간 이내)는 부재로 세지 않는다 — 교체 중인 빈 자리를 유휴로
        읽으면 **교체가 통로를 닫는다**(D3 ④).
        """
        relay = relay_mod.read()
        if relay.transient(now=now):
            self._absent_since = None
            return None
        if not relay.exists or not relay.tmux:
            # **지휘가 등록조차 되지 않은 상태다.** 창구가 우체부를 띄운 직후의 짧은 공백일
            # 수도 있고, `relay.json`이 지워졌거나 깨진 것일 수도 있다. 여기서 타이머를
            # 멈추면 001의 25시간 좀비가 "부재"가 아니라 "부존재"라는 다른 문으로 되돌아온다
            # — 기동 시각을 부재 시작으로 삼아 같은 유예를 준다.
            if self._absent_since is None:
                self._absent_since = self._started_ts
            if (now - self._absent_since) < self.config.idle_grace:
                return None
            reason = "지휘 미등록 %d분 (relay.json 부재 또는 손상)" % int(
                (now - self._absent_since) / 60)
            log.info("유휴 자동 종료: %s", reason)
            eventlog.record("idle_exit", reason=reason, now=now)
            self.request_stop(reason)
            return reason
        if relay.tmux in self.live_sessions():
            self._absent_since = None
            return None

        if self._absent_since is None:
            self._absent_since = now
            return None
        absent = now - self._absent_since
        if mailbox.has_undelivered():
            # 보관분·미발신이 남아 있어도 부재가 아주 길면 물러난다 — 파일은 남아 재기동
            # 시 재시도되고, 좀비로 남아 통로를 막는 쪽이 더 나쁘다.
            if absent < self.config.idle_hard_grace:
                return None
            reason = "지휘 부재 %d분 (미발신 잔여)" % int(absent / 60)
        elif absent < self.config.idle_grace:
            return None
        else:
            reason = "지휘 부재 %d분" % int(absent / 60)
        log.info("유휴 자동 종료: %s", reason)
        eventlog.record("idle_exit", reason=reason, now=now)
        self.request_stop(reason)
        return reason

    def register_menu(self):
        """명령 메뉴 등록. 실패해도 우체부는 계속 돈다 — 메뉴는 편의일 뿐이다."""
        try:
            self.transport.call("setMyCommands", {
                "commands": commands_mod.menu_commands(),
                "scope": {"type": "all_private_chats"},
            })
        except TelegramError as exc:
            log.warning("setMyCommands 실패: status=%s", exc.status)

    # ------------------------------------------------------------------ 루프·종료

    def request_stop(self, reason=None, *_args):
        """종료 요청. 신호 처리기이자 유휴 판정의 출구다."""
        self._stopping = True
        self._running = False
        if reason and self._stop_reason is None:
            self._stop_reason = reason if isinstance(reason, str) else "signal"

    def install_signal_handlers(self):
        """SIGTERM·SIGINT → 정상 종료. **두 번째 신호는 즉시 종료.**

        001의 봇은 SIGTERM으로 죽지 않아 SIGKILL을 맞았고, 그때 잠금·오프셋이 중간 상태로
        남았다. 정상 종료가 어떤 이유로 막히더라도 사람이 SIGKILL까지 가지 않게 두 번째
        신호에 곧바로 나간다 — 그 경로도 잠금 해제는 하고 나간다.
        """
        def handle(signum, _frame):
            if self._stopping:
                log.warning("두 번째 종료 신호 — 즉시 종료합니다")
                try:
                    release_lock()
                finally:
                    os._exit(0)
            log.info("종료 신호 수신 — 마무리 중")
            self.request_stop("signal:%d" % signum)

        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, handle)

    def shutdown(self):
        """정상 종료 절차 (D8). ① 루프 탈출 ② 오프셋 확정 ③ 미완 주입 기록 ④ 잠금 해제."""
        committed = self.commit_offset()
        ambiguous = self.ledger.ambiguous_keys()
        eventlog.record("shutdown", reason=self._stop_reason, offset=committed,
                        ambiguous=len(ambiguous), now=self.clock())
        if ambiguous:
            # intent만 있고 done이 없다 — 넣었는지 알 수 없으므로 **재주입하지 않는다**.
            log.warning("미완 주입 %d건 — 재주입하지 않고 남깁니다", len(ambiguous))
        release_lock()
        return {"offset": committed, "ambiguous": ambiguous, "reason": self._stop_reason}

    def run(self, max_cycles=None, idle=1.0):
        """폴링 루프. 종료 요청이 들어오면 **다음 대기 없이** 빠져나온다."""
        self._running = True
        cycles = 0
        while self._running:
            try:
                self.tick()
                handled = self.poll_once() if self._running else 0
            except Exception as exc:
                log.warning("순회 실패: %s", type(exc).__name__)
                handled = 0
                self._sleep(idle)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if not handled:
                self._sleep(idle)
        self.shutdown()
        return cycles

    def _sleep(self, seconds):
        """토막 잠. 종료 신호가 긴 잠에 갇히지 않게 조각내어 깨어난다."""
        remaining = float(seconds)
        while remaining > 0 and not self._stopping:
            step = 0.25 if remaining > 0.25 else remaining
            time.sleep(step)
            remaining -= step


# ---------------------------------------------------------------------- 잠금

def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, TypeError):
        return False
    return True


def _lock_holder(path):
    data = paths.read_json(path)
    pid = data.get("pid") if isinstance(data, dict) else None
    return pid if isinstance(pid, int) else None


def acquire_lock(path=None):
    """이중 기동 차단. 같은 토큰 이중 폴링은 409를 부르고 메시지가 무작위로 갈린다.

    죽은 프로세스가 남긴 잠금(stale)은 회수한다 — SIGKILL이 남긴 중간 상태를 여기서 흡수한다.
    """
    path = Path(path) if path else paths.lock_file()
    paths.ensure_private_dir(path.parent)
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = _lock_holder(path)
            if holder is not None and holder != os.getpid() and _pid_alive(holder):
                raise PostmanAlreadyRunning("우체부가 이미 실행 중입니다 (pid=%s)" % holder)
            try:
                path.unlink()   # 죽은 프로세스의 잔재
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump({"pid": os.getpid(), "started_ts": time.time()}, fp)
        return path
    raise PostmanAlreadyRunning("잠금 파일을 확보하지 못했습니다")


def release_lock(path=None):
    path = Path(path) if path else paths.lock_file()
    if _lock_holder(path) == os.getpid():
        try:
            path.unlink()
        except OSError:
            pass


def check_project(project=None, relay=None):
    """다른 프로젝트의 지휘가 살아 있으면 기동을 거부한다 (D3 단일 프로젝트 전제).

    `relay.json`은 지휘 하나만 담는다. 프로젝트 둘이 동시에 돌면 두 창구가 같은 파일을
    다투고(D2 불변식 위반) 유휴 종료가 남의 채널을 닫는다.
    """
    relay = relay if relay is not None else relay_mod.read()
    if project is None or not relay.exists or not relay.project:
        return relay
    if relay.project != project and relay.running:
        raise ProjectConflict(
            "다른 프로젝트의 지휘가 실행 중입니다: %s" % relay.project)
    return relay


# ---------------------------------------------------------------------- 진입점

# 우편함 권한 주의를 낱개로 찍는 상한. 표식은 청소 대상이 아니라 오래 사는 우편함에 쌓이고,
# 전부 찍으면 **조치 가능한 항목(설정·토큰)이 잡음에 묻힌다.**
MAILBOX_PROBLEM_LIMIT = 10


def _capped(problems, limit=MAILBOX_PROBLEM_LIMIT):
    """상한을 넘는 주의는 건수로 접는다. 접힌 건도 같은 종류임을 문구에 남긴다."""
    if len(problems) <= limit:
        return problems
    return problems[:limit] + ["우편함 권한 주의 %d건이 더 있습니다 — 위와 같은 종류입니다"
                               % (len(problems) - limit,)]


def _mode_problems(targets):
    """[(라벨, 경로, 요구 권한)] → 요구보다 열린 것만 문구로. `stat` 실패는 건너뛴다.

    **어긋난 것을 고쳐 쓰지 않는다.** 우편함·응답 표식을 쓰는 주체는 세션이라, 우체부가
    권한을 손대면 한 파일에 두 주체가 쓰게 된다 — 여기서는 검출과 통보까지다.
    """
    problems = []
    for label, path, want in targets:
        try:
            mode = stat.S_IMODE(os.stat(str(path)).st_mode)
        except OSError:
            continue
        if mode & ~want:
            problems.append("%s 권한이 %o입니다 — %o이어야 합니다 (%s)" % (label, mode, want, path))
    return problems


def selfcheck():
    """`--check` — 설정·경로·토큰·우편함 권한을 훑고 결과를 stdout에 적는다. 네트워크를 쓰지 않는다."""
    config = paths.Config.load()
    problems = []
    if config.fail_closed:
        problems.append("allowed_user_ids 또는 chat_id가 비었습니다 (fail-closed)")
    try:
        paths.read_token()
    except paths.TokenUnavailable as exc:
        problems.append(str(exc))
    if not config.never_send:
        problems.append("never_send가 비었습니다 — 평문 개인정보 파일이 발신문에 실릴 수 있습니다")
    problems.extend(_mode_problems([("config.json", paths.config_path(), 0o600),
                                    ("토큰 파일", paths.token_path(), 0o600)]))
    problems.extend(_capped(_mode_problems(mailbox.permission_targets())))
    print("설정: %s" % config.source)
    print("뿌리: %s" % paths.root())
    print("토큰 파일: %s" % paths.token_path())
    for problem in problems:
        print("주의: %s" % problem)
    print("점검 완료 (%d건 주의)" % len(problems))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if "--check" in argv:
        return selfcheck()

    config = paths.Config.load()
    if config.fail_closed:
        log.error("허용 목록이 비었거나 config.json이 없습니다 — 모든 업데이트를 폐기합니다 (%s)",
                  config.source)
    check_project(os.environ.get(paths.PROJECT_ENV))
    transport = HttpTransport(paths.read_token())
    acquire_lock()
    try:
        # 잠금을 쥔 뒤부터는 어떤 예외가 나도 잠금을 놓고 나간다 — 남기면 다음 기동이
        # stale 회수에 기대야 하고, 그 사이 사람이 "이미 실행 중"이라는 오해를 산다.
        postman = Postman(transport, config,
                          handler=handler_mod.SessionHandler(config))
        postman.install_signal_handlers()
        postman.register_menu()
        postman.run()
    finally:
        release_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
