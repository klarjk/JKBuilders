"""배달·라우팅·버튼 테스트 — 텔레그램도 tmux도 실호출하지 않는다.

덮는 것: 알림 파일 스캔의 라우팅(D2), 질문 버튼 조립과 답장 매칭 좌표, 버튼 1회 소진과
**세대가 지난 버튼의 무효화**(D2), 보관과 재주입(D7), 교체 중 주입 유예(D3), `done` 중계.
"""
import json
import logging
import os
import time

import pytest

from postman import bot as bot_mod
from postman import diag as diag_mod
from postman import handler as handler_mod
from postman import inject as inject_mod
from postman import ledger as ledger_mod
from postman import limits as limits_mod
from postman import mailbox
from postman import paths
from postman import sender as sender_mod
from postman import store
from postman.test_inject import ANSWERED, FakeScreen, QUESTION, SCREEN


COMMAND = "dev-cmd-vault"
WORKER = "dev-vault-n4b"


class FakeTransport(object):
    """텔레그램 대역. 보낸 것만 기록한다."""

    def __init__(self):
        self.calls = []
        self._next_message_id = 1000

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "getUpdates":
            return []
        if method == "sendMessage":
            self._next_message_id += 1
            return {"message_id": self._next_message_id}
        return True

    def sent(self):
        return [params for method, params in self.calls if method == "sendMessage"]

    def sent_texts(self):
        return [params.get("text", "") for params in self.sent()]


class DeadTransport(FakeTransport):
    def call(self, method, params=None):
        if method == "sendMessage":
            self.calls.append((method, params or {}))
            from postman.transport import TelegramError
            raise TelegramError(500, "Internal Server Error")
        return FakeTransport.call(self, method, params)


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "postman"
    monkeypatch.setenv("POSTMAN_ROOT", str(base))
    monkeypatch.setenv("POSTMAN_CONFIG", str(base / "config.json"))
    base.mkdir(parents=True)
    return base


def make_config(**overrides):
    data = {"allowed_user_ids": [42], "chat_id": 42, "min_send_interval": 0,
            "settle_interval": 0, "settle_timeout": 30}
    data.update(overrides)
    return paths.Config(data)


def write_relay(state="running", tmux=COMMAND, generation=2, uuid="uuid-g2",
                project="vault", now=None):
    now = time.time() if now is None else now
    paths.atomic_write_json(paths.relay_file(), {
        "project": project, "dev_plan": "docs/dev/plan/DEV_PLAN-002.md",
        "command": {"tmux": tmux, "uuid": uuid, "generation": generation},
        "state": state, "state_ts": now, "updated_ts": now,
    })


class Rig(object):
    """우체부 + 주입 계층 한 벌. 화면과 전송기만 갈아끼운다."""

    def __init__(self, screen, transport=None, config=None, sessions=None):
        self.screen = screen
        self.transport = transport or FakeTransport()
        self.config = config or make_config()
        self.limiter = limits_mod.SendLimiter(soft_limit=self.config.soft_send_limit,
                                              hard_limit=self.config.hard_send_limit)
        self.sender = sender_mod.Sender(self.transport, 42, limiter=self.limiter,
                                        min_interval=0, sleep=lambda _s: None)
        self.handler = handler_mod.SessionHandler(self.config, deps=screen.deps())
        self.postman = bot_mod.Postman(
            self.transport, self.config, sender=self.sender, limiter=self.limiter,
            handler=self.handler,
            session_lister=lambda: sorted(screen.sessions),
            killer=lambda name: screen.sessions.pop(name, None) is not None)

    def texts(self):
        return self.transport.sent_texts()

    def last_message_id(self):
        """방금 보낸 메시지의 id — 답장이 걸리는 자리다."""
        return self.transport._next_message_id


def write_notify(session, text, **extra):
    directory = paths.ensure_private_dir(paths.session_dir(session))
    path = directory / ("notify-" + paths.mailbox_filename("notify"))
    payload = {"text": text}
    payload.update(extra)
    paths.atomic_write_json(path, payload)
    return path


def write_question(session, text, generation=2, seq=1, choices=None, **extra):
    directory = paths.ensure_private_dir(paths.session_dir(session))
    path = directory / ("question-g%d-%02d.json" % (generation, seq))
    payload = {"text": text, "question": extra.pop("question", text)}
    if choices is not None:
        payload["choices"] = choices
    payload.update(extra)
    paths.atomic_write_json(path, payload)
    return path


def screen_with(*sessions, **kwargs):
    text = kwargs.pop("text", SCREEN)
    return FakeScreen(dict((name, text) for name in sessions),
                      after_text=kwargs.pop("after_text", ANSWERED), **kwargs)


# ---------------------------------------------------------------- 알림 배달 (D2)

def test_a_notice_is_delivered_with_the_mailbox_it_came_from(root):
    """**파일이 놓인 경로가 곧 출처 증명이다** — 세션이 자기 이름을 주장하지 않는다."""
    write_relay()
    rig = Rig(screen_with(COMMAND, WORKER))
    path = write_notify(WORKER, "노드 002-N4B 완료")
    assert rig.postman.tick() is None
    assert rig.texts() == ["[%s] 노드 002-N4B 완료" % WORKER]
    assert mailbox.is_sent(path)
    assert paths.read_json(path)["text"] == "노드 002-N4B 완료"    # 원본 불변


def test_the_counter_mailbox_is_scanned_too(root):
    """창구는 tmux 세션이 아니라 주소가 없다 — 고정 우편함이 사용자에게 닿는 유일한 통로다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    paths.ensure_private_dir(paths.counter_dir())
    write_notify(paths.COUNTER_MAILBOX, "재스폰에 실패했습니다", kind="alert")
    rig.postman.tick()
    assert "[counter] 재스폰에 실패했습니다" in rig.texts()


def test_a_notice_may_not_carry_buttons(root):
    """비신뢰 텍스트가 조작 버튼을 제시하지 못하게 한다 (D2)."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    write_notify(COMMAND, "확인해 주세요",
                 buttons=[{"label": "전부 정지", "action": "halt"}])
    rig.postman.tick()
    assert rig.transport.sent()[0].get("reply_markup") is None


def test_a_failed_send_leaves_no_sent_marker(root):
    """표식을 붙이면 세션이 쓴 경보가 사라지고, 세션에는 다시 보낼 수단이 없다."""
    write_relay()
    rig = Rig(screen_with(COMMAND), transport=DeadTransport())
    path = write_notify(COMMAND, "경보")
    rig.postman.tick()
    assert not mailbox.is_sent(path)


def test_an_unsettled_file_waits_for_the_next_cycle(root):
    """세션이 쓰는 중인 파일을 반쯤 읽지 않는다."""
    write_relay()
    rig = Rig(screen_with(COMMAND), config=make_config(settle_interval=60))
    path = write_notify(COMMAND, "쓰는 중")
    rig.postman.tick()
    assert rig.texts() == [] and not mailbox.is_sent(path)


def test_a_corrupt_file_is_quarantined_instead_of_retried_forever(root):
    """격리가 없으면 손상 파일이 매 순회 경고만 남기며 영원히 재시도된다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    directory = paths.ensure_private_dir(paths.session_dir(COMMAND))
    path = directory / "notify-broken.json"
    path.write_text("{쓰다 만 파일", encoding="utf-8")
    os.utime(str(path), (time.time() - 3600, time.time() - 3600))
    rig.postman.tick()
    assert not path.exists()
    assert list(paths.corrupt_dir().iterdir())


def test_delivery_is_held_once_when_the_limit_is_hit(root):
    """억제는 **파일당 한 번만** 센다 — 매 순회 세면 요약이 무의미해진다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    for _ in range(rig.config.hard_send_limit):
        rig.limiter.consume("notify")
    before = rig.limiter.suppressed()
    write_notify(COMMAND, "밀린 알림")
    for _ in range(5):
        rig.postman.tick()
    assert rig.texts() == []
    assert rig.limiter.suppressed() == before + 1


# ---------------------------------------------------------------- 질문·버튼 (D2)

def test_choices_become_inline_buttons_and_the_answer_maps_back(root):
    write_relay()
    rig = Rig(screen_with(COMMAND))
    write_question(COMMAND, QUESTION, choices=["진행", "중단"], node="002-N4B")
    rig.postman.tick()

    params = rig.transport.sent()[0]
    rows = params["reply_markup"]["inline_keyboard"]
    assert [row[0]["text"] for row in rows] == ["진행", "중단"]
    assert all(row[0]["callback_data"].startswith("v1|") for row in rows)

    record = store.MessageMap().lookup(rig.last_message_id())
    assert record["session"] == COMMAND and record["generation"] == 2
    assert record["seq"] == 1 and record["node"] == "002-N4B"


def test_a_question_is_not_asked_twice_after_a_lost_marker(root):
    """표식만 잃은 재기동에서 같은 질문을 다시 묻지 않는다 (1회 한정 장부)."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    path = write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    mailbox.sent_marker(path).unlink()
    rig.postman.tick()
    assert len(rig.texts()) == 1


def test_a_button_is_consumed_exactly_once(root):
    """같은 버튼을 두 번 눌러도 한 번만 실행한다 (D2)."""
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    data = rig.transport.sent()[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    first = rig.handler.on_callback({"data": data}, rig.postman)
    second = rig.handler.on_callback({"data": data}, rig.postman)
    assert "전달" in first and "이미 처리" in second
    assert len(screen.sent) == 1


def test_a_button_from_a_previous_generation_is_void(root):
    """어제 버튼이 오늘 눌려도 **세대가 바뀌었으면 주입되지 않는다** (D2).

    `action_ttl` 24시간과 조작 명령 `stale_window` 5분의 비대칭을 무해화하는 검사다.
    """
    write_relay(generation=2, uuid="uuid-g2")
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    data = rig.transport.sent()[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    write_relay(generation=3, uuid="uuid-g3")          # 교체가 일어났다
    answer = rig.handler.on_callback({"data": data}, rig.postman)
    assert "세대가 바뀌어 무효" in answer
    assert screen.sent == []                            # 실행하지 않았다
    assert store.ActionStore().take(data) is None       # 그래도 소진은 됐다


def test_a_button_whose_target_is_gone_does_nothing(root):
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    data = rig.transport.sent()[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]

    screen.sessions.clear()
    assert "대상 세션이 없어" in rig.handler.on_callback({"data": data}, rig.postman)


def test_a_forged_callback_value_is_refused(root):
    """`v1|<16진>` 밖은 받지 않는다 — 외부 입력이 그대로 키가 되지 않게 한다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    for forged in ("v1|../../etc", "v2|abcd", "abcd", "v1|" + "f" * 64, ""):
        assert "이미 처리" in rig.handler.on_callback({"data": forged}, rig.postman)


# ---------------------------------------------------------------- 답장 라우팅 (D2)

def reply_update(update_id, text, reply_to):
    return {"update_id": update_id, "message": {
        "message_id": 5, "date": int(time.time()), "chat": {"id": 42, "type": "private"},
        "from": {"id": 42}, "text": text, "reply_to_message": {"message_id": reply_to}}}


def test_a_reply_goes_to_the_session_that_asked(root):
    """매핑이 라우팅의 1순위다 — 질문한 세션으로 돌아간다."""
    write_relay()
    screen = screen_with(COMMAND, WORKER)
    rig = Rig(screen)
    write_question(WORKER, QUESTION, choices=["진행"])
    rig.postman.tick()
    rig.postman.handle_update(reply_update(1, "진행", rig.last_message_id()))
    assert screen.sent[0][0] == WORKER


def test_a_reply_to_a_question_the_session_already_answered_is_refused(root):
    """**좌표가 주입 절차까지 닿아야 표식이 읽힌다** — 라우팅에서 끊기면 무력해진다.

    표식은 세션이 자기 질문 파일 옆에 남긴다. 그 뒤에 온 답장을 넣으면 지금 열려 있는
    **다른** 프롬프트에 들어간다.
    """
    write_relay()
    screen = screen_with(COMMAND, WORKER)
    rig = Rig(screen)
    path = write_question(WORKER, QUESTION, choices=["진행"])
    rig.postman.tick()
    marker = path.parent / (path.name + inject_mod.ANSWERED_SUFFIX)
    paths.atomic_write_json(marker, {"ts": 1.0})
    rig.postman.handle_update(reply_update(1, "진행", rig.last_message_id()))
    assert screen.sent == []
    assert "열려 있지 않아" in rig.texts()[-1]


def test_a_reply_without_a_mapping_falls_back_to_the_commander(root):
    """매핑이 날아가도 답장을 버리지 않는다 — 없을 때만 현 지휘가 기본 대상이다 (D2)."""
    write_relay()
    screen = screen_with(COMMAND, text="아무 화면")
    rig = Rig(screen)
    rig.postman.handle_update(reply_update(1, "네 진행하세요", 999))
    assert screen.sent and screen.sent[0][0] == COMMAND


def test_a_reply_with_no_relay_and_no_mapping_is_answered_not_swallowed(root):
    rig = Rig(screen_with(COMMAND))
    rig.postman.handle_update(reply_update(1, "네", 999))
    assert rig.texts()                      # 무엇이든 회신한다


# ---------------------------------------------------------------- 보관·재주입 (D7)

def test_an_answer_for_a_dead_session_is_stored_and_replayed(root):
    """죽은 주소로의 발신은 보관해 주는 계층이 없다 — 우체부가 들고 있는다 (D7)."""
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    message_id = rig.last_message_id()

    screen.sessions.clear()                                  # 지휘가 죽었다
    rig.postman.handle_update(reply_update(1, "진행", message_id))
    stored = mailbox.pending(COMMAND)
    assert len(stored) == 1
    assert "보관했습니다" in rig.texts()[-1]

    write_relay(generation=3, uuid="uuid-g3")                # 새 지휘가 섰다
    screen.sessions[COMMAND] = "새 지휘 대기 중"
    screen.after_text = None                                 # 새 화면에는 넣은 글자가 뜬다
    rig.postman.tick()
    assert screen.sent and screen.sent[0][0] == COMMAND
    assert mailbox.pending(COMMAND) == []
    assert "보관해 둔 답을 전달했습니다" in rig.texts()[-1]


def test_a_replayed_answer_carries_the_original_question_when_the_generation_changed(root):
    """새 화면에 옛 질문이 열려 있을 수 없다 — 요약을 동봉한 일반 주입이다 (D7)."""
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    write_question(COMMAND, QUESTION, choices=["진행"])
    rig.postman.tick()
    message_id = rig.last_message_id()
    screen.sessions.clear()
    rig.postman.handle_update(reply_update(1, "진행", message_id))

    write_relay(generation=3, uuid="uuid-g3")
    screen.sessions[COMMAND] = "새 지휘 대기 중"
    screen.after_text = None
    rig.postman.tick()
    assert QUESTION[:20] in screen.sent[0][1] and "진행" in screen.sent[0][1]


def test_no_replay_into_a_commander_that_is_not_running_yet(root):
    """준비 신호와 `running` 이후에만 넣는다 — TUI 초기화 중인 pane에 두 주체가 쓰지 않게 (D3 ③)."""
    write_relay(state="replacing")
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    mailbox.store_pending(COMMAND, {"session": COMMAND, "answer": "진행",
                                    "question": QUESTION, "generation": 2, "seq": 1})
    rig.postman.tick()
    assert screen.sent == []
    assert len(mailbox.pending(COMMAND)) == 1


def test_an_answer_during_a_replacement_is_stored_instead_of_injected(root):
    """교체 중인 지휘에 쓰면 답이 허공으로 간다 (D3 ②)."""
    write_relay(state="replacing")
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    reply = rig.handler.on_answer("진행", {"session": COMMAND, "generation": 2, "seq": 1}, {})
    assert "교체 중" in reply
    assert screen.sent == [] and len(mailbox.pending(COMMAND)) == 1


def test_an_ambiguous_injection_is_blocked_and_reported(root):
    """intent만 남은 좌표는 다시 넣지 않고 사람에게 확인을 청한다 (D2)."""
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    rig.handler.ledger.begin(ledger_mod.inject_key(COMMAND, 2, 1))
    reply = rig.handler.on_answer("진행", {"session": COMMAND, "generation": 2, "seq": 1}, {})
    assert "화면을 확인해" in reply and screen.sent == []

    stored = mailbox.pending(COMMAND)
    assert mailbox.load_pending(stored[0])["blocked"] is True
    rig.postman.tick()
    assert screen.sent == []            # 보류된 보관분은 다시 시도하지 않는다


def test_a_stuck_pending_stops_retrying_after_a_few_attempts(root):
    """같은 실패를 무한히 되풀이하지 않는다 — 보류로 바꾸고 사람에게 알린다."""
    write_relay()
    screen = FakeScreen({COMMAND: "질문이 없는 화면"})
    rig = Rig(screen)
    mailbox.store_pending(COMMAND, {"session": COMMAND, "answer": "진행",
                                    "question": QUESTION, "generation": 2, "seq": 1})
    for _ in range(handler_mod.MAX_PENDING_ATTEMPTS + 2):
        rig.postman.tick()
    record = mailbox.load_pending(mailbox.pending(COMMAND)[0])
    assert record["blocked"] is True
    assert record["attempts"] == handler_mod.MAX_PENDING_ATTEMPTS


def test_pending_files_survive_the_cleanup(root):
    """청소가 보관분을 지우면 D7이 무너진다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))
    mailbox.store_pending(WORKER, {"session": WORKER, "answer": "진행"})
    mailbox.cleanup(now=time.time() + 30 * 86400, live_sessions=[],
                    absent_since={WORKER: 0})
    assert len(mailbox.pending(WORKER)) == 1


# ---------------------------------------------------------------- done 중계 (D2)

def test_done_is_relayed_to_the_commander(root):
    write_relay()
    screen = FakeScreen({COMMAND: "지휘 대기 중"})
    rig = Rig(screen)
    rig.postman.handle_update({"update_id": 1, "message": {
        "message_id": 5, "date": int(time.time()), "chat": {"id": 42, "type": "private"},
        "from": {"id": 42}, "text": "done 002-N4B"}})
    assert screen.sent and "002-N4B" in screen.sent[0][1]
    assert "완료 신고를 전달했습니다" in rig.texts()[-1]


def test_done_needs_a_node_id_in_the_plan_number_form(root):
    """001의 인식기는 `002-N4B`를 거부했다 — 복사본은 받는다(002-N4A 선반영 확인)."""
    write_relay()
    screen = FakeScreen({COMMAND: "지휘 대기 중"})
    rig = Rig(screen)
    rig.postman.handle_update({"update_id": 1, "message": {
        "message_id": 5, "date": int(time.time()), "chat": {"id": 42, "type": "private"},
        "from": {"id": 42}, "text": "done"}})
    assert "노드 ID를 함께" in rig.texts()[-1]
    assert screen.sent == []


def test_the_same_done_is_not_relayed_twice(root):
    write_relay()
    screen = FakeScreen({COMMAND: "지휘 대기 중"})
    rig = Rig(screen)
    for update_id in (1, 2):
        rig.postman.handle_update({"update_id": update_id, "message": {
            "message_id": 5, "date": int(time.time()),
            "chat": {"id": 42, "type": "private"}, "from": {"id": 42},
            "text": "done 002-N4B"}})
    assert len(screen.sent) == 1
    assert "이미 전달한" in rig.texts()[-1]


# ---------------------------------------------------------------- 순회 견고성

def test_a_broken_injection_layer_does_not_stop_the_polling_loop(root):
    """통로가 먼저다 — 배달이 죽어도 우체부는 계속 받는다."""
    write_relay()
    rig = Rig(screen_with(COMMAND))

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    rig.handler.deliver = explode
    assert rig.postman.tick() is None      # 예외가 새어 나오지 않는다


# ---------------------------------------------------------------- 리뷰 지적 회귀

def send_done(rig, node="002-N4B", update_id=1):
    rig.postman.handle_update({"update_id": update_id, "message": {
        "message_id": 5, "date": int(time.time()), "chat": {"id": 42, "type": "private"},
        "from": {"id": 42}, "text": "done %s" % node}})


def test_a_done_report_for_a_missing_commander_is_stored_and_replayed(root):
    """**교체 창에 온 완료 신고를 잃지 않는다** (D7).

    `relay.json`이 아직 옛 지휘를 가리키는데 tmux는 이미 없는 순간이 실재한다. 그 틈의
    완료 신고를 "다시 보내 주세요"로 돌리면, 자리를 비운 사용자에게는 유실과 같다.
    """
    write_relay()
    screen = FakeScreen({})                       # 지휘 tmux가 없다
    rig = Rig(screen)
    send_done(rig)
    assert "보관했습니다" in rig.texts()[-1]
    assert len(mailbox.pending(COMMAND)) == 1

    write_relay(generation=3, uuid="uuid-g3")     # 새 지휘가 섰다
    screen.sessions[COMMAND] = "새 지휘 대기 중"
    rig.postman.tick()
    assert screen.sent and "002-N4B" in screen.sent[0][1]
    assert mailbox.pending(COMMAND) == []


def test_a_corrupt_attempts_field_does_not_stop_the_retry(root):
    """시도 횟수가 손상돼도 세다 말고 멈추지 않는다."""
    write_relay()
    screen = FakeScreen({COMMAND: "새 지휘 대기 중"})
    rig = Rig(screen)
    path = mailbox.store_pending(COMMAND, {
        "session": COMMAND, "answer": "진행", "generation": 2, "seq": 1,
        "fallback": True, "attempts": "망가진 값"})
    rig.postman.tick()
    assert screen.sent and mailbox.load_pending(path) is None


def test_one_failing_pending_does_not_block_the_ones_behind_it(root):
    """한 보관분의 예외가 뒤 순번을 무기한 가두지 않는다 — 배달과 같은 원칙이다."""
    write_relay()
    first, second = "dev-vault-n4a", "dev-vault-n4b"
    screen = FakeScreen({first: "화면", second: "화면"})
    rig = Rig(screen)
    for name in (first, second):
        mailbox.store_pending(name, {"session": name, "answer": "진행",
                                     "generation": 2, "seq": 1, "fallback": True})

    real_retry = rig.handler._retry_one

    def explode_on_first(session, record, path, relay, now):
        if session == first:
            raise RuntimeError("손상된 보관분")
        return real_retry(session, record, path, relay, now)

    rig.handler._retry_one = explode_on_first
    rig.postman.tick()
    assert [name for name, _text in screen.sent] == [second]        # 뒤 순번이 나갔다
    assert mailbox.load_pending(mailbox.pending(first)[0])["blocked"] is True


def test_a_stored_answer_without_its_question_is_still_delivered(root):
    """대조할 원문이 없으면 열림 확인을 걸지 않는다.

    걸면 `question_open`이 볼 것 없이 항상 "닫혔다"가 되어, 질문 파일이 격리된 답은
    세 번 시도한 끝에 보류로 굳는다 — 사용자에게는 유실과 구별되지 않는다.
    """
    write_relay()
    screen = FakeScreen({WORKER: "질문이 사라진 화면"})
    rig = Rig(screen)
    mailbox.store_pending(WORKER, {"session": WORKER, "answer": "네"})
    rig.postman.tick()
    assert [name for name, _text in screen.sent] == [WORKER]
    assert mailbox.pending(WORKER) == []


# ------------------------------------------------- 반영 확인의 오판·진단 보존 (002-N7F ④)

# 화면에 섞여 들어온 시크릿. 진단 파일은 **대상 세션 화면의 원문**이라 이런 것이 실린다.
SECRET = "sk-practice0123456789abcdefgh"
SECRET_SCREEN = "%s\n1) 진행\n2) 중단\n$ export OPENAI_API_KEY=%s" % (QUESTION, SECRET)

# 선택지를 싣지 않는다 — 가짜 화면의 답변 후 문구("진행합니다")가 라벨 "진행"을 품고 있어
# 열림 확인이 질문이 아직 열린 것으로 읽는다. 이 테스트가 볼 것은 그 판정이 아니다.
ANSWER_RECORD = {"session": COMMAND, "generation": 2, "seq": 1, "question": QUESTION}

# 회신에 있으면 안 되는 말 — 확인 실패를 전달 실패로 단정하는 표현들.
VERDICT_WORDS = ("전달 실패", "전달하지 못했", "닿지 않았", "반영되지 않았", "실패했습니다")


def diag_files():
    try:
        return sorted(p for p in paths.diag_dir().iterdir() if p.is_file())
    except OSError:
        return []


def read_diag(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_confirmed_injection_leaves_no_diagnostic(root):
    """정상 경로 — 확인된 주입은 진단 자리에 아무것도 남기지 않는다.

    중단 진단은 사후 검시용이다. 성공한 주입까지 남기면 남의 화면 원문이 계속 쌓인다.
    """
    write_relay()
    screen = screen_with(COMMAND)
    rig = Rig(screen)
    reply = rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})
    assert "전달했습니다" in reply
    assert diag_files() == []


def test_an_unconfirmed_reflection_is_not_reported_as_a_failed_delivery(root):
    """**002-N7 결함 ④의 회귀 테스트.** 확인 실패를 「안 닿았다」로 회신하지 않는다.

    `not_reflected`는 `send-keys`가 성공한 **뒤**의 상태라 답이 이미 들어갔을 수 있다 —
    002-N7에서 실제로 들어간 결정 2건을 무효로 회신했다. 회신은 ⓐ 확인하지 못했다
    ⓑ 같은 답을 다시 보내기 전에 화면부터 확인하라 ⓒ attach 안내를 담는다.
    """
    write_relay()
    screen = FakeScreen({COMMAND: SCREEN}, echo_after=99)
    rig = Rig(screen)
    reply = rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    assert "확인하지 못했" in reply                       # ⓐ
    assert "다시 보내기 전에" in reply                     # ⓑ
    assert "tmux attach -t %s" % COMMAND in reply         # ⓒ
    for word in VERDICT_WORDS:
        assert word not in reply, "확인 실패를 전달 실패로 단정한다: %s" % word


def test_an_unconfirmed_reflection_keeps_both_screens_for_the_postmortem(root):
    """중단 시 `before`/`after`를 남긴다 — 002-N7은 캡처가 없어 원인을 못 잡았다."""
    write_relay()
    screen = FakeScreen({COMMAND: SCREEN}, echo_after=99)
    rig = Rig(screen)
    rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    saved = diag_files()
    assert len(saved) == 1
    record = read_diag(saved[0])
    assert record["reason"] == "not_reflected"
    assert (record["session"], record["generation"], record["seq"]) == (COMMAND, 2, 1)
    assert QUESTION in record["before"]
    assert QUESTION in record["after"]                    # 뒷장이 비면 가릴 것이 없다
    assert record["when"] and record["ts"]
    assert oct(saved[0].stat().st_mode & 0o777) == "0o600"


def test_a_closed_question_keeps_the_screen_it_judged_on(root):
    """`not_open`은 주입 전이라 뒷장이 없다 — 판정에 쓴 화면 한 장만 남긴다."""
    write_relay()
    screen = FakeScreen({COMMAND: "질문이 밀려난 화면"})
    rig = Rig(screen)
    rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    record = read_diag(diag_files()[0])
    assert record["reason"] == "not_open"
    assert "질문이 밀려난 화면" in record["before"]
    assert record["after"] is None


def test_a_captured_secret_is_masked_before_it_lands_in_the_diagnostic(root):
    """진단 파일도 **마스킹 관문을 지난다** — 관문 밖 경로를 새로 만들지 않는다 (D2).

    캡처는 대상 세션 화면의 원문이라 시크릿이 섞여 들어온다. 여기서 새면 발신은 막고
    디스크에는 평문으로 쌓아 두는 꼴이 된다.
    """
    write_relay()
    screen = FakeScreen({COMMAND: SECRET_SCREEN}, echo_after=99)
    rig = Rig(screen)
    rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    saved = diag_files()
    raw = saved[0].read_text(encoding="utf-8")
    assert SECRET not in raw                     # 원문 값이 파일 어디에도 없다
    assert "[가림]" in raw
    record = read_diag(saved[0])
    assert QUESTION in record["before"]          # 가릴 것만 가리고 화면은 남는다


def test_the_giveup_reply_for_a_stored_answer_uses_the_same_headline(root):
    """보관분을 포기할 때도 **같은 잣대의 문구**로 회신한다.

    이 경로는 `_abort_headline`을 거치는 두 번째 자리다. 회신을 세는 단언이 여기 없으면
    ⓐ 옛 「반영되지 않았습니다」 단정이 이 경로로만 되돌아오거나 ⓑ 머리말과 attach 안내를
    잇는 이음쇠가 어긋나 문장이 끊겨도(「…다시 보내기 전에. 화면을…」) 아무도 못 잡는다.
    """
    write_relay()
    screen = FakeScreen({COMMAND: SCREEN}, echo_after=99)
    rig = Rig(screen)
    # 이미 두 번 시도한 보관분 — 이번 순회가 마지막이라 포기 회신이 나간다. 되풀이해서
    # 세 번 돌리지 않는 이유: `not_reflected`는 장부에 의도를 남긴 채 끝나므로 두 번째
    # 시도부터는 모호(`ambiguous`) 갈래로 갈라져 이 문구에 닿지 못한다.
    mailbox.store_pending(COMMAND, {"session": COMMAND, "answer": "진행",
                                    "question": QUESTION, "generation": 2, "seq": 1,
                                    "attempts": handler_mod.MAX_PENDING_ATTEMPTS - 1})
    rig.postman.tick()

    giveup = [t for t in rig.texts() if "넣어 봤습니다" in t]
    assert len(giveup) == 1
    reply = giveup[0]
    assert "확인하지 못했" in reply                                    # ⓐ
    assert "이미 전달됐을 수 있으니" in reply                           # ⓑ
    assert "다시 보내기 전에 — 화면을 직접 확인해 주세요" in reply       # ⓒ 이음쇠까지 한 문장
    assert "tmux attach -t %s" % COMMAND in reply
    for word in VERDICT_WORDS:
        assert word not in reply, "확인 실패를 전달 실패로 단정한다: %s" % word


def test_the_never_send_file_list_reaches_the_diagnostic_gate(root, tmp_path):
    """설정의 **개인정보 파일 목록**이 진단 저장 경로까지 실려 가는가 (D2).

    시크릿은 생김새(`sk-…`)만으로 값 규칙에 걸리지만, 이 목록에 적힌 볼트 루트 평문
    파일의 내용은 아무 형태도 없는 보통 문장이라 **목록을 넘겨야만 가려진다.** 그래서
    `_keep_capture`가 `config.never_send` 대신 빈 값을 넘기도록 되돌아가도 다른 마스킹
    테스트는 전부 초록으로 남는다 — 그 회귀를 잡는 것이 이 테스트 하나뿐이다.
    """
    secret_file = tmp_path / "개인정보.md"
    leaked = "창고 열쇠는 세 번째 화분 밑에 있다"
    secret_file.write_text(leaked + "\n", encoding="utf-8")

    write_relay()
    screen = FakeScreen({COMMAND: "%s\n1) 진행\n$ cat 개인정보.md\n%s" % (QUESTION, leaked)},
                        echo_after=99)
    rig = Rig(screen, config=make_config(never_send=[str(secret_file)]))
    rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    raw = diag_files()[0].read_text(encoding="utf-8")
    assert leaked not in raw                     # 원문 값이 파일 어디에도 없다
    assert "[제외]" in raw                        # 지운 자리가 표시된다
    assert QUESTION in raw                       # 가릴 것만 가리고 화면은 남는다


def test_a_diagnostic_that_cannot_be_written_does_not_swallow_the_reply(root):
    """진단을 못 남겨도 중단 회신은 그대로 나간다 — 기록이 통보를 죽이면 안 된다."""
    write_relay()
    # 진단 자리에 파일이 앉아 있다 — 디렉토리를 만들 수 없는 상태(디스크 오류 대역).
    paths.diag_dir().write_text("진단 자리를 막은 파일", encoding="utf-8")
    screen = FakeScreen({COMMAND: SCREEN}, echo_after=99)
    rig = Rig(screen)
    reply = rig.handler.on_answer("진행", dict(ANSWER_RECORD), {})

    assert "확인하지 못했" in reply and "tmux attach -t %s" % COMMAND in reply
    assert paths.diag_dir().is_file()            # 조용히 지우거나 덮지 않았다


class ExplodingCapture(object):
    """문자열로 만들려는 순간 터지는 캡처. 마스킹 이전 단계의 사고를 흉내 낸다."""

    def __str__(self):
        raise RuntimeError("캡처를 문자열로 못 만든다")


def test_a_swallowed_exception_is_logged_by_kind_and_place_only(root, caplog):
    """삼킨 예외의 **문구는 로그에 싣지 않는다** — 이 로그는 마스킹 관문 밖이다.

    예외 메시지에는 원인 값이 실리고, 진단이 다루는 값의 출처가 하필 **대상 세션 화면
    원문**이다. 종류 이름과 소스 위치(파일:줄)는 실행 중 값이 아니라 안전하지만,
    `exc_info`나 `str(exc)`를 선의로 되넣는 순간 관문을 우회하는 경로가 새로 열린다.
    """
    caplog.set_level(logging.INFO, logger="postman.diag")
    assert diag_mod.save(COMMAND, "not_reflected", before=ExplodingCapture()) is None

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged                      # 무엇이 터졌는지는 남는다
    assert "test_routing.py:" in logged                  # 어디서 터졌는지도 (여기서는 대역의 __str__)
    assert "캡처를 문자열로 못 만든다" not in logged        # 예외 문구는 새지 않는다
    assert not any(record.exc_info for record in caplog.records)   # 스택도 싣지 않는다


def test_a_record_that_cannot_be_built_is_swallowed_and_writes_nothing(root):
    """레코드 조립이 터져도 **예외가 아니라 None**이고, 파일은 아예 안 생긴다.

    조립이 `try` 밖에 서 있던 동안에는 시각 환산·마스킹 중 무엇이 터져도 예외가
    `handler._keep_capture`를 타고 올라가 **중단 회신이 통째로 사라졌다** — 진단을
    남기려다 통보를 죽이는 갈래다. 그리고 실패는 언제나 '아예 안 씀'이어야 한다:
    가리지 못한 화면을 원문으로 대신 남기는 폴백은 없다.
    """
    assert diag_mod.save(COMMAND, "not_reflected", before=ExplodingCapture()) is None
    assert diag_files() == []
