"""우체부 본체 테스트 — 실제 텔레그램 API도 tmux도 부르지 않는다 (가짜 전송기·가짜 tmux).

덮는 것: 허용 상대 검증(메시지·버튼 둘 다), 오프셋 영속, 지연 명령 폐기, 명령 4종,
발신 마스킹·분할·상한, 중복 기동 차단, **SIGTERM 정상 종료**, 유휴 자동 종료.
"""
import json
import os
import signal
import stat
import time

import pytest

from postman import bot as bot_mod
from postman import ledger as ledger_mod
from postman import limits as limits_mod
from postman import masking
from postman import paths
from postman import sender as sender_mod
from postman import store
from postman.transport import TelegramError


# ---------------------------------------------------------------- 도구

class FakeTransport(object):
    """텔레그램 대역. 보낸 것과 받은 것만 기록한다."""

    def __init__(self):
        self.calls = []
        self.updates = []
        self._next_message_id = 1000

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "getUpdates":
            batch, self.updates = self.updates, []
            return batch
        if method == "sendMessage":
            self._next_message_id += 1
            return {"message_id": self._next_message_id, "text": params.get("text")}
        return True

    def sent(self):
        return [params for method, params in self.calls if method == "sendMessage"]

    def sent_texts(self):
        return [params.get("text", "") for params in self.sent()]

    def answered(self):
        return [params for method, params in self.calls if method == "answerCallbackQuery"]

    def polls(self):
        return [params for method, params in self.calls if method == "getUpdates"]


class DeadTransport(FakeTransport):
    """sendMessage가 계속 실패하는 대역."""

    def call(self, method, params=None):
        if method == "sendMessage":
            self.calls.append((method, params or {}))
            raise TelegramError(500, "Internal Server Error")
        return FakeTransport.call(self, method, params)


class SecondChunkFails(FakeTransport):
    """분할 발신의 두 번째 조각부터 영구 실패하는 대역."""

    def call(self, method, params=None):
        if method == "sendMessage":
            self.calls.append((method, params or {}))
            if len([c for c in self.calls if c[0] == "sendMessage"]) >= 2:
                raise TelegramError(400, "Bad Request")
            self._next_message_id += 1
            return {"message_id": self._next_message_id}
        return FakeTransport.call(self, method, params)


class RateLimitedOnce(FakeTransport):
    """첫 발신만 429로 튕기고 `retry_after`를 준다."""

    def __init__(self, retry_after=7):
        FakeTransport.__init__(self)
        self.retry_after = retry_after
        self._bounced = False

    def call(self, method, params=None):
        if method == "sendMessage" and not self._bounced:
            self._bounced = True
            self.calls.append((method, params or {}))
            raise TelegramError(429, "Too Many Requests", retry_after=self.retry_after)
        return FakeTransport.call(self, method, params)


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "postman"
    monkeypatch.setenv("POSTMAN_ROOT", str(base))
    monkeypatch.setenv("POSTMAN_CONFIG", str(base / "config.json"))
    monkeypatch.setenv("POSTMAN_TOKEN_FILE", str(base / "telegram-bot-token"))
    base.mkdir(parents=True)
    return base


@pytest.fixture
def restore_signals():
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


def make_config(allowed=(42,), **overrides):
    data = {
        "allowed_user_ids": list(allowed),
        "chat_id": 42,
        "min_send_interval": 0,
        "stale_window": 300,
    }
    data.update(overrides)
    return paths.Config(data)


class FakeTmux(object):
    def __init__(self, sessions=()):
        self.sessions = list(sessions)
        self.killed = []

    def list(self):
        return list(self.sessions)

    def kill(self, name):
        if name not in self.sessions:
            return False
        self.sessions.remove(name)
        self.killed.append(name)
        return True


def make_postman(transport, config=None, clock=None, tmux=None, handler=None, limiter=None):
    config = config or make_config()
    tmux = tmux or FakeTmux()
    clock = clock or time.time
    limiter = limiter if limiter is not None else limits_mod.SendLimiter(
        soft_limit=config.soft_send_limit, hard_limit=config.hard_send_limit)
    sender = sender_mod.Sender(transport, config.chat_id or 42, never_send=config.never_send,
                              limiter=limiter, min_interval=0, sleep=lambda _s: None,
                              now=clock)
    return bot_mod.Postman(transport, config, sender=sender, clock=clock,
                           limiter=limiter, handler=handler,
                           session_lister=tmux.list, killer=tmux.kill)


def message_update(update_id, text, user_id=42, chat_type="private", date=None, reply_to=None):
    message = {
        "message_id": 5,
        "date": int(time.time() if date is None else date),
        "chat": {"id": 42, "type": chat_type},
        "from": {"id": user_id},
        "text": text,
    }
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": update_id, "message": message}


def callback_update(update_id, data, user_id=42, chat_type="private"):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb-%d" % update_id,
            "from": {"id": user_id},
            "message": {"message_id": 7, "chat": {"id": 42, "type": chat_type}},
            "data": data,
        },
    }


def write_relay(state="running", tmux="dev-cmd-vault", generation=1, project="vault",
                updated_ts=None):
    paths.atomic_write_json(paths.relay_file(), {
        "project": project,
        "dev_plan": "docs/dev/plan/DEV_PLAN-002.md",
        "command": {"tmux": tmux, "uuid": "abc-123", "generation": generation},
        "state": state,
        "state_ts": updated_ts if updated_ts is not None else time.time(),
        "updated_ts": updated_ts if updated_ts is not None else time.time(),
    })


# ---------------------------------------------------------------- 허용 상대 (D2)

def test_unregistered_user_is_dropped_without_a_word(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(1, "status", user_id=999)]
    postman.poll_once()
    assert transport.sent() == []          # 무응답 폐기 — 존재조차 알리지 않는다


def test_group_chat_is_rejected_even_for_an_allowed_user(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(1, "status", chat_type="group")]
    postman.poll_once()
    assert transport.sent() == []


def test_callback_from_a_group_chat_is_rejected(root):
    """002-N1이 지적한 테스트 공백 — 버튼 경로의 그룹 채팅 거부에 직접 테스트가 없었다."""
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [callback_update(1, "v1|deadbeef", chat_type="group")]
    postman.poll_once()
    assert transport.answered() == []      # answerCallbackQuery조차 하지 않는다


def test_callback_from_an_unregistered_user_is_rejected(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [callback_update(1, "v1|deadbeef", user_id=999)]
    postman.poll_once()
    assert transport.answered() == []


def test_fail_closed_without_a_config(root):
    """설정이 없거나 허용 목록이 비면 전부 폐기한다."""
    config = paths.Config.load()
    assert config.fail_closed is True
    transport = FakeTransport()
    postman = make_postman(transport, config=config)
    transport.updates = [message_update(1, "status")]
    postman.poll_once()
    assert transport.sent() == []


# ---------------------------------------------------------------- 오프셋 (D2)

def test_fail_closed_sends_nothing_even_for_alerts(root):
    """보낼 상대가 확정되지 않았으면 경보도 내보내지 않는다 — chat_id가 비어 있다."""
    paths.ledger_file().write_text("{깨짐", encoding="utf-8")
    transport = FakeTransport()
    postman = make_postman(transport, config=paths.Config.load())
    postman.ledger.load()
    postman.tick()
    assert transport.sent() == []


def test_offset_advances_past_the_highest_handled_update(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(7, "status"), message_update(9, "status")]
    postman.poll_once()
    assert store.OffsetStore().get() == 10


def test_offset_is_sent_back_on_the_next_poll(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(7, "status")]
    postman.poll_once()
    postman.poll_once()
    assert transport.polls()[-1]["offset"] == 8


def test_offset_survives_a_new_process(root):
    transport = FakeTransport()
    make_postman(transport)
    transport.updates = [message_update(7, "status")]
    make_postman(transport).poll_once()
    assert make_postman(FakeTransport()).offsets.get() == 8


def test_a_failing_update_does_not_stop_the_batch(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [{"update_id": 1, "message": "이건 dict가 아니다"},
                         message_update(2, "status")]
    assert postman.poll_once() == 2
    assert store.OffsetStore().get() == 3


# ---------------------------------------------------------------- 지연 폐기 (D2)

def test_stale_operation_command_is_discarded(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(1, "status", date=time.time() - 4000)]
    postman.poll_once()
    assert "지연된 명령" in transport.sent_texts()[0]


def test_answer_window_is_much_longer_than_the_command_window(root):
    """자리를 비운 사이 온 질문에 하룻밤 뒤 답해도 그 답은 살아야 한다."""

    class Wired(bot_mod.Handler):
        def lookup_message(self, message_id):
            return {"session": "dev-cmd-vault", "seq": 1}

        def on_answer(self, text, record, message):
            return "받았습니다"

    transport = FakeTransport()
    postman = make_postman(transport, handler=Wired())
    transport.updates = [message_update(1, "네 진행하세요", date=time.time() - 4000, reply_to=7)]
    postman.poll_once()
    assert "받았습니다" in transport.sent_texts()[0]


# ---------------------------------------------------------------- 명령 4종

def test_unknown_text_gets_the_help_and_goes_nowhere(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(1, "rm -rf /")]
    postman.poll_once()
    assert "쓸 수 있는 명령" in transport.sent_texts()[0]


def test_status_reports_the_relay_and_live_sessions(root):
    write_relay()
    transport = FakeTransport()
    postman = make_postman(transport, tmux=FakeTmux(["dev-cmd-vault", "dev-vault-n4a"]))
    transport.updates = [message_update(1, "상태")]
    postman.poll_once()
    text = transport.sent_texts()[0]
    assert "dev-cmd-vault" in text and "세대 1" in text


def test_halt_without_a_target_does_not_kill_anything(root):
    """이름을 짐작하지 않는다 — 짐작하는 순간 남의 세션을 죽인다."""
    tmux = FakeTmux(["dev-cmd-vault"])
    transport = FakeTransport()
    postman = make_postman(transport, tmux=tmux)
    transport.updates = [message_update(1, "halt")]
    postman.poll_once()
    assert tmux.killed == []
    assert "대상" in transport.sent_texts()[0]


def test_halt_kills_only_the_named_session(root):
    write_relay(project="vault")
    tmux = FakeTmux(["dev-cmd-vault", "dev-vault-n4a"])
    transport = FakeTransport()
    postman = make_postman(transport, tmux=tmux)
    transport.updates = [message_update(1, "halt dev-vault-n4a")]
    postman.poll_once()
    assert tmux.killed == ["dev-vault-n4a"]


def test_halt_all_kills_only_the_managed_sessions(root):
    """`halt all`이 기계의 모든 tmux를 죽이면 개발과 무관한 세션까지 함께 나간다."""
    write_relay(project="vault")
    tmux = FakeTmux(["dev-cmd-vault", "dev-vault-n4a", "bob", "dev-view", "myshell"])
    transport = FakeTransport()
    postman = make_postman(transport, tmux=tmux)
    transport.updates = [message_update(1, "halt all")]
    postman.poll_once()
    assert sorted(tmux.killed) == ["dev-cmd-vault", "dev-vault-n4a"]


def test_halt_refuses_a_session_this_postman_does_not_manage(root):
    """이름을 정확히 적어도 남의 세션은 죽이지 않는다 — 오타 한 번이 채널을 끊는다."""
    write_relay(project="vault")
    tmux = FakeTmux(["dev-cmd-vault", "bob"])
    transport = FakeTransport()
    postman = make_postman(transport, tmux=tmux)
    transport.updates = [message_update(1, "halt bob")]
    postman.poll_once()
    assert tmux.killed == []
    assert "관리하는 세션이 아닙니다" in transport.sent_texts()[0]


def test_halt_is_not_replayed_when_the_same_update_arrives_twice(root):
    """오프셋이 손상돼 같은 업데이트를 다시 받아도 두 번 죽이지 않는다 — 장부가 막는다."""
    tmux = FakeTmux(["dev-cmd-vault"])
    transport = FakeTransport()
    postman = make_postman(transport, tmux=tmux)
    update = message_update(1, "halt dev-cmd-vault")
    postman.handle_update(update)
    tmux.sessions.append("dev-cmd-vault")       # 세션이 다시 떴다고 하자
    postman.handle_update(update)
    assert tmux.killed == ["dev-cmd-vault"]


def test_resume_releases_the_hard_block_and_reports(root):
    limiter = limits_mod.SendLimiter(soft_limit=1, hard_limit=1)
    transport = FakeTransport()
    postman = make_postman(transport, limiter=limiter)
    limiter.consume("question")
    limiter.consume("question")                  # 억제 1건
    transport.updates = [message_update(1, "재개")]
    postman.poll_once()
    assert "억제된 발신 1건" in transport.sent_texts()[-1]
    assert limiter.blocked() is False


def test_unwired_command_is_answered_instead_of_silently_dropped(root):
    """주입 계층이 붙기 전에도 받은 것을 조용히 버리지 않는다."""
    transport = FakeTransport()
    postman = make_postman(transport)
    transport.updates = [message_update(1, "done 002-N4A")]
    postman.poll_once()
    assert "주입 계층" in transport.sent_texts()[0]


# ---------------------------------------------------------------- 발신 (D2)

def test_outgoing_text_passes_the_masking_gate(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    postman.sender.send_text("토큰은 ghp_ABCDEFGHIJKLMNOPQRSTUV 입니다", kind="notify")
    assert "ghp_" not in transport.sent_texts()[0]
    assert masking.MASK in transport.sent_texts()[0]


def test_never_send_paths_are_stripped_from_outgoing_text(root, tmp_path):
    secret = tmp_path / "개인정보.md"
    secret.write_text("비번: 매우비밀한값입니다\n", encoding="utf-8")
    config = make_config(never_send=[str(secret)])
    transport = FakeTransport()
    postman = make_postman(transport, config=config)
    postman.sender.send_text("화면: 비번: 매우비밀한값입니다", kind="notify")
    assert "매우비밀한값입니다" not in transport.sent_texts()[0]


def test_button_labels_are_masked_too(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    postman.sender.send_text("고르세요", kind="question",
                             buttons=[[{"text": "ghp_ABCDEFGHIJKLMNOPQRSTUV",
                                        "callback_data": "v1|abcd"}]])
    label = transport.sent()[-1]["reply_markup"]["inline_keyboard"][0][0]["text"]
    assert "ghp_" not in label


def test_long_text_is_split_at_4096(root):
    transport = FakeTransport()
    postman = make_postman(transport)
    result = postman.sender.send_text("가" * 9000, kind="notify")
    assert len(result.message_ids) == 3
    assert all(len(params["text"]) <= 4096 for params in transport.sent())


def test_oversized_body_is_capped_and_says_so(root):
    """직렬 큐가 초당 1건이라 조각 200개면 큐가 200초 막힌다 — 자르되 잘랐다고 적는다."""
    transport = FakeTransport()
    sender = sender_mod.Sender(transport, 42, min_interval=0, sleep=lambda _s: None,
                               max_body=5000)
    sender.send_text("가" * 50000, kind="notify")
    joined = "".join(transport.sent_texts())
    assert "잘랐습니다" in joined
    assert len(joined) < 6000


def test_capping_happens_after_masking_not_before(root):
    """자르기가 먼저면 값 형태 최소 길이 바로 아래로 잘린 조각이 평문으로 남는다."""
    secret = "0123456789abcdef0123456789abcdef"      # 16진 32자 — 값 형태의 최소 길이
    transport = FakeTransport()
    sender = sender_mod.Sender(transport, 42, min_interval=0, sleep=lambda _s: None,
                               max_body=20000)
    sender.send_text("x" * (20000 - 32) + " " + secret, kind="notify")
    joined = "".join(transport.sent_texts())
    assert secret not in joined
    assert secret[:31] not in joined


def test_retry_after_is_honoured(root):
    slept = []
    transport = RateLimitedOnce(retry_after=7)
    config = make_config()
    limiter = limits_mod.SendLimiter()
    sender = sender_mod.Sender(transport, 42, limiter=limiter, min_interval=0,
                               sleep=slept.append)
    assert sender.send_text("본문", kind="notify")
    assert 7.0 in slept


def test_partial_split_failure_is_reported_as_failed_not_sent(root):
    """조각 하나라도 실패하면 전체 실패다 — 호출자가 원본을 지우면 잘린 채로 유실된다."""
    transport = SecondChunkFails()
    sender = sender_mod.Sender(transport, 42, min_interval=0, sleep=lambda _s: None,
                               max_retries=1)
    result = sender.send_text("가" * 9000, kind="notify")
    assert result.status == sender_mod.FAILED
    assert not result


def test_suppressed_send_is_distinguishable_from_a_failure(root):
    limiter = limits_mod.SendLimiter(soft_limit=0, hard_limit=100)
    transport = FakeTransport()
    sender = sender_mod.Sender(transport, 42, limiter=limiter, min_interval=0,
                               sleep=lambda _s: None)
    result = sender.send_text("알림", kind="notify")
    assert result.status == sender_mod.SUPPRESSED
    assert transport.sent() == []


def test_token_never_appears_in_an_error_message(root):
    """urllib 예외 문구에 URL이 섞이면 토큰이 그대로 흘러나온다 — 타입 이름만 남긴다."""
    from postman.transport import HttpTransport

    class Boom(object):
        def open(self, *_a, **_k):
            raise RuntimeError("https://api.telegram.org/bot12345:SECRETTOKEN/getUpdates")

    transport = HttpTransport("12345:SECRETTOKEN", opener=Boom())
    with pytest.raises(TelegramError) as excinfo:
        transport.call("getUpdates")
    assert "SECRETTOKEN" not in str(excinfo.value)


# ---------------------------------------------------------------- 잠금 (D8)

def test_second_postman_is_refused(root):
    bot_mod.acquire_lock()
    try:
        with pytest.raises(bot_mod.PostmanAlreadyRunning):
            _acquire_as_other_pid()
    finally:
        bot_mod.release_lock()


def _acquire_as_other_pid():
    """다른 살아 있는 프로세스가 잠금을 쥔 상태를 흉내낸다."""
    holder = os.getpid()
    paths.atomic_write_json(paths.lock_file(), {"pid": holder, "started_ts": time.time()})

    real_getpid = os.getpid
    try:
        os.getpid = lambda: holder + 1       # 우리가 '다른 프로세스'인 척한다
        return bot_mod.acquire_lock()
    finally:
        os.getpid = real_getpid


def test_stale_lock_from_a_dead_process_is_reclaimed(root):
    """SIGKILL이 남긴 잠금이 통로를 영영 막지 않는다."""
    paths.atomic_write_json(paths.lock_file(), {"pid": 999999999, "started_ts": 0})
    assert bot_mod.acquire_lock()
    bot_mod.release_lock()


def test_root_is_created_owner_only(tmp_path, monkeypatch):
    """뿌리는 만들어지는 그 순간에만 잠근다 — 이미 있는 남의 디렉토리 권한은 손대지 않는다."""
    fresh = tmp_path / "새뿌리"
    monkeypatch.setenv("POSTMAN_ROOT", str(fresh))
    assert stat.S_IMODE(os.stat(str(paths.root())).st_mode) == 0o700


def test_session_mailboxes_are_owner_only(root):
    """우편함 디렉토리 목록에는 세션 주소가 드러난다 — 같은 맥의 다른 사용자에게 보이지 않게."""
    box = paths.ensure_private_dir(paths.sessions_dir() / "dev-cmd-vault")
    assert stat.S_IMODE(os.stat(str(box)).st_mode) == 0o700


def test_startup_is_refused_when_another_project_is_running(root):
    """본 ADR은 단일 프로젝트 운용 전제다 — 둘이 돌면 유휴 종료가 남의 채널을 닫는다."""
    write_relay(project="other-project")
    with pytest.raises(bot_mod.ProjectConflict):
        bot_mod.check_project("vault")


def test_startup_allows_the_same_project(root):
    write_relay(project="vault")
    assert bot_mod.check_project("vault").project == "vault"


def test_the_project_env_name_has_one_source(root):
    """기동이 읽는 환경변수 이름은 `paths.PROJECT_ENV` 하나다 — 리터럴 재복제 금지.

    값이 같아도 두 곳에 적히면 한쪽만 고쳐지는 날이 온다. 이름을 바꾸는 변경이
    기동 경로만 비껴가면 "슬러그가 비어 출처 표시가 잠드는" 조용한 고장이 된다.
    """
    source = open(bot_mod.__file__, encoding="utf-8").read()
    assert paths.PROJECT_ENV == "POSTMAN_PROJECT"
    assert '"%s"' % paths.PROJECT_ENV not in source
    assert "'%s'" % paths.PROJECT_ENV not in source


# ---------------------------------------------------------------- 종료 (D8)

def test_sigterm_shuts_down_gracefully(root, restore_signals):
    """001의 봇은 SIGTERM을 무시해 SIGKILL로만 죽었다 — 그때 잠금·오프셋이 중간 상태였다."""

    class SignalOnPoll(FakeTransport):
        def call(self, method, params=None):
            if method == "getUpdates" and not self.updates:
                os.kill(os.getpid(), signal.SIGTERM)
                return []
            return FakeTransport.call(self, method, params)

    transport = SignalOnPoll()
    transport.updates = [message_update(11, "status")]
    postman = make_postman(transport)
    bot_mod.acquire_lock()
    postman.install_signal_handlers()

    cycles = postman.run(idle=0.01)

    assert cycles >= 1
    assert store.OffsetStore().get() == 12          # ② 오프셋 확정 기록
    assert not paths.lock_file().exists()           # ④ 잠금 해제


def test_shutdown_leaves_unfinished_injections_alone(root):
    """intent만 남은 주입은 재주입하지 않는다 — 화면 상태는 파일 복구로 되돌릴 수 없다."""
    postman = make_postman(FakeTransport())
    key = ledger_mod.inject_key("dev-cmd-vault", 1, 2)
    postman.ledger.begin(key)
    summary = postman.shutdown()
    assert summary["ambiguous"] == [key]


def test_stop_request_ends_the_batch_without_confirming_the_rest(root):
    """종료 신호가 오면 처리한 데까지만 확정한다 — 나머지는 서버에 남아 다음 기동에 온다."""
    transport = FakeTransport()
    postman = make_postman(transport)

    class StopAfterFirst(bot_mod.Handler):
        def on_command(self, cmd, parsed, pm):
            pm.request_stop("test")
            return None

    postman.handler = StopAfterFirst()
    transport.updates = [message_update(1, "done N1"), message_update(2, "done N2")]
    postman.poll_once()
    assert store.OffsetStore().get() == 2           # 2번은 확정하지 않았다


# ---------------------------------------------------------------- 유휴 종료 (D8)

def test_idle_exit_when_the_commander_has_been_absent_too_long(root):
    """001의 봇은 계획 동결 후 25시간을 살아 새 우체부의 수신을 막을 뻔했다."""
    write_relay(state="running", tmux="dev-cmd-vault")
    postman = make_postman(FakeTransport(), config=make_config(idle_grace=1800))
    now = time.time()
    assert postman.tick(now=now) is None            # 첫 부재 관측
    assert postman.tick(now=now + 1801) is not None
    assert postman._running is False


def test_idle_exit_fires_when_the_relay_file_never_appears(root):
    """부재가 아니라 **부존재**로도 좀비가 된다 — 창구가 등록 전에 죽으면 relay.json이 없다."""
    postman = make_postman(FakeTransport(), config=make_config(idle_grace=1800))
    now = postman._started_ts
    assert postman.tick(now=now) is None
    assert postman.tick(now=now + 1801) is not None


def test_idle_exit_fires_when_the_relay_file_is_corrupt(root):
    paths.relay_file().write_text("{깨짐", encoding="utf-8")
    postman = make_postman(FakeTransport(), config=make_config(idle_grace=60))
    now = postman._started_ts
    postman.tick(now=now)
    assert postman.tick(now=now + 61) is not None


def test_idle_exit_does_not_fire_while_the_commander_is_alive(root):
    write_relay(state="running", tmux="dev-cmd-vault")
    postman = make_postman(FakeTransport(), tmux=FakeTmux(["dev-cmd-vault"]))
    now = time.time()
    postman.tick(now=now)
    assert postman.tick(now=now + 999999) is None


def test_idle_exit_does_not_fire_during_a_replacement(root):
    """교체 중인 빈 자리를 유휴로 읽으면 교체가 통로를 닫는다 (D3 ④)."""
    write_relay(state="replacing", tmux="dev-cmd-vault")
    postman = make_postman(FakeTransport(), config=make_config(idle_grace=60))
    now = time.time()
    postman.tick(now=now)
    assert postman.tick(now=now + 600) is None


def test_a_stuck_replacing_state_does_not_keep_the_postman_alive_forever(root):
    """고착된 과도 상태는 과도로 쳐주지 않는다 — 그래야 통로가 영영 닫히지 않는다."""
    old = time.time() - 3 * 86400
    write_relay(state="replacing", tmux="dev-cmd-vault", updated_ts=old)
    postman = make_postman(FakeTransport(), config=make_config(idle_grace=60))
    now = time.time()
    postman.tick(now=now)
    assert postman.tick(now=now + 600) is not None


def test_undelivered_mail_holds_the_idle_exit_until_the_hard_grace(root):
    write_relay(state="running", tmux="dev-cmd-vault")
    box = paths.sessions_dir() / "dev-cmd-vault"
    box.mkdir(parents=True)
    (box / "notify-1-aaaaaa.json").write_text("{}", encoding="utf-8")
    postman = make_postman(FakeTransport(),
                           config=make_config(idle_grace=60, idle_hard_grace=86400))
    now = time.time()
    postman.tick(now=now)
    assert postman.tick(now=now + 600) is None           # 아직 보낼 것이 남았다
    assert postman.tick(now=now + 86401) is not None     # 그래도 부재가 길면 물러난다


# ---------------------------------------------------------------- 손상 통보 (D2)

def test_corrupt_state_file_raises_one_alert_only(root):
    paths.ledger_file().write_text("{깨짐", encoding="utf-8")
    transport = FakeTransport()
    postman = make_postman(transport)
    postman.ledger.load()
    postman.tick()
    postman.ledger.load()
    postman.tick()
    alerts = [t for t in transport.sent_texts() if "손상" in t]
    assert len(alerts) == 1


def test_heartbeat_is_touched_every_cycle(root):
    postman = make_postman(FakeTransport())
    postman.tick()
    assert paths.heartbeat_file().exists()


def test_selfcheck_runs_without_network(root, capsys):
    paths.atomic_write_json(paths.config_path(), {"allowed_user_ids": [42], "chat_id": 42})
    paths.token_path().write_text("12345:x", encoding="utf-8")
    assert bot_mod.main(["--check"]) == 0
    assert "점검 완료" in capsys.readouterr().out
