"""우체부 코어 단위 테스트 — 주소·마스킹·장부·상한·변별자·우편함.

여기서 덮는 것은 **틀리면 조용히 깨지는 것들**이다. 주소 폭이 어긋나면 "버튼을 눌렀는데
아무 일도 없다"로만 보이고, 마스킹이 새면 아무도 모르는 채로 제3자 서버에 남고, 장부가
없으면 같은 질문이 교체마다 다시 나간다.
"""
import json
import os
import time

import pytest

from postman import addressing
from postman import ledger as ledger_mod
from postman import limits as limits_mod
from postman import mailbox
from postman import masking
from postman import paths
from postman import store
from postman import discriminator as disc
from postman import eventlog


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "postman"
    monkeypatch.setenv("POSTMAN_ROOT", str(base))
    monkeypatch.setenv("POSTMAN_CONFIG", str(base / "config.json"))
    monkeypatch.setenv("POSTMAN_TOKEN_FILE", str(base / "telegram-bot-token"))
    base.mkdir(parents=True)
    return base


# ------------------------------------------------------- 주소 정규식 통일 (D9)

def test_session_name_accepts_the_tmux_width():
    """tmux 폭 그대로 — 첫 글자는 영숫자, 최대 128자."""
    assert addressing.is_session_name("dev-cmd-vault")
    assert addressing.is_session_name("A")
    assert addressing.is_session_name("A" + "b" * 127)          # 정확히 128자


def test_session_name_rejects_one_character_over_the_boundary():
    """129자는 거부한다. 001에서는 봇 64자·tmux 128자가 어긋나 긴 이름이 조용히 죽었다."""
    assert not addressing.is_session_name("A" + "b" * 128)


def test_session_name_rejects_digits_only():
    """숫자만으로 된 이름은 `tmux -t`에서 인덱스와 모호하다 (002-N6 판정)."""
    assert not addressing.is_session_name("123")
    assert not addressing.is_session_name("0")
    assert addressing.is_session_name("1a")          # 숫자로 시작하는 것 자체는 막지 않는다
    assert addressing.is_session_name("dev-002")


def test_session_name_rejects_dots():
    """tmux가 `.`·`:`를 창·pane 구분자로 읽는다 — 점이 든 이름은 봇만 통과시켰다."""
    assert not addressing.is_session_name("dev.cmd.vault")


@pytest.mark.parametrize("bad", [
    "", "-lead", "_lead", "dev/cmd", "..", "dev-..-vault", "dev cmd", "dev:1", None, 42,
])
def test_session_name_rejects_path_escapes_and_junk(bad):
    assert not addressing.is_session_name(bad)


def test_session_name_raises_without_leaking_the_value():
    """예외 문구에 값을 싣지 않는다 — 외부 입력이다."""
    with pytest.raises(addressing.InvalidAddress) as excinfo:
        addressing.safe_session_name("../../etc/passwd")
    assert "passwd" not in str(excinfo.value)


def test_node_id_accepts_the_plan_number_prefix():
    """002는 노드 ID에 계획서 번호를 단다 — `002-N4B`가 경로 검증을 통과해야 한다."""
    assert addressing.is_node_id("002-N4B")
    assert addressing.is_node_id("N4")
    assert not addressing.is_node_id("002.N4B")


def test_session_uuid_stays_a_separate_namespace():
    """클로드 세션 UUID는 점을 허용한다 — 통일 대상이 아니다 (D5)."""
    assert addressing.is_session_uuid("a.b-c_d")
    assert not addressing.is_session_name("a.b-c_d")


# ------------------------------------------------------------ 마스킹 2계층 (D2)

@pytest.mark.parametrize("text, leaked", [
    ("키는 sk-abcdefghijklmnopqrstuv 입니다", "sk-abcdefghijklmnopqrstuv"),
    ("ghp_ABCDEFGHIJKLMNOPQRSTUV", "ghp_ABCDEFGHIJKLMNOPQRSTUV"),
    ("Authorization: Bearer abcdefghijklmnopqrst", "abcdefghijklmnopqrst"),
    ("AKIA1234567890ABCDEF", "AKIA1234567890ABCDEF"),
    ("0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
    ("12345678:AAEEbbCCddEEffGGhhIIjjKKllMMnnOOppQ", "12345678:AAEEbbCCddEEffGGhhIIjjKKllMMnnOOppQ"),
])
def test_value_layer_masks_known_secret_shapes(text, leaked):
    assert leaked not in masking.mask(text)
    assert masking.MASK in masking.mask(text)


@pytest.mark.parametrize("text, leaked", [
    ("claude --api-key=zzzQQQ111 실행", "zzzQQQ111"),
    ("claude --token zzzQQQ111", "zzzQQQ111"),
    ("export GITHUB_TOKEN=zzzQQQ111", "zzzQQQ111"),
    ('{"password": "zzzQQQ111"}', "zzzQQQ111"),
    ("db-password: zzzQQQ111", "zzzQQQ111"),
    ("aws_secret_access_key = zzzQQQ111", "zzzQQQ111"),
])
def test_name_layer_masks_by_the_name_even_when_the_shape_is_unknown(text, leaked):
    """⚠️ 001에 없던 계층. 형태를 모르는 시크릿은 **이름이 밀고할 때만** 잡힌다."""
    assert leaked not in masking.mask(text)


@pytest.mark.parametrize("text", [
    "monkey=banana",
    "keyboard: qwerty",
    "노드 002-N4A 완료 — 검증: 통과",
    "session dev-cmd-vault: running",
])
def test_name_layer_does_not_eat_ordinary_sentences(text):
    """붙어 있는 글자는 다른 낱말이다 — `monkey`를 `key`로 읽으면 로그가 전부 [가림]이 된다."""
    assert masking.mask(text) == text


@pytest.mark.parametrize("text, leaked", [
    ('{"api_key": "abc\\"secretDEF123456"}', "secretDEF123456"),
    ("{'password': 'abc\\'tailXYZ'}", "tailXYZ"),
    ('--api-key="sk-abc\\"tail999"', "tail999"),
])
def test_name_layer_masks_a_value_containing_an_escaped_quote(text, leaked):
    """따옴표 안의 이스케이프를 값의 끝으로 오인하면 **뒷부분이 평문으로 나간다** (실측 누출)."""
    assert leaked not in masking.mask(text)


@pytest.mark.parametrize("name", [
    "clientSecret", "refreshToken", "accessToken", "secretKey", "authToken",
    "apiToken", "AWSAccessKey", "myPassword",
])
def test_name_layer_reads_camel_case_compounds(name):
    """구분자만 보고 낱말을 끊으면 `clientSecret`이 통째로 한 낱말이 되어 그대로 샌다."""
    assert "abcSECRETVALUE123" not in masking.mask('{"%s": "abcSECRETVALUE123"}' % name)


@pytest.mark.parametrize("key", ["credentials.apiKey", "api key", "db.password"])
def test_name_layer_reads_quoted_keys_with_dots_and_spaces(key):
    """따옴표가 경계를 잡아 주는 자리에서는 점·공백이 낀 키도 이름으로 읽어야 한다."""
    assert "abcSECRETVALUE123" not in masking.mask('{"%s": "abcSECRETVALUE123"}' % key)


def test_name_layer_masks_a_concatenated_value():
    """앞 조각만 가리면 미끼만 가리고 진짜 값이 그대로 나간다."""
    masked = masking.mask('token = "sk-" + "abcdefghijklmno456"')
    assert "abcdefghijklmno456" not in masked


def test_name_layer_reads_curly_quotes():
    """편집기를 거친 붙여넣기에는 굽은 따옴표가 섞인다."""
    assert "abcSECRET789" not in masking.mask(u'{\u201capi_key\u201d: \u201cabcSECRET789\u201d}')


def test_name_layer_masks_cookie_values():
    assert "abcSECRETVALUE123" not in masking.mask("Set-Cookie: cookie=abcSECRETVALUE123; Path=/")


def test_mask_is_idempotent():
    """관문을 두 번 지나도 마스크가 겹쳐 쌓이지 않는다."""
    once = masking.mask("claude --api-key=sk-abcdefghijklmnopqrst")
    assert masking.mask(once) == once


def test_masking_stays_fast_on_a_hostile_name_like_string():
    """이름 계층이 중첩 반복이던 시절 20KB에 1.8초가 걸렸다 — 그 사이 폴링·발신이 멈춘다.

    우체부는 단일 루프라 마스킹 한 번이 곧 통로 정지다. 80KB를 1초 안에 끝내지 못하면
    되짚기 폭주가 되돌아온 것이다.
    """
    import time as _time
    hostile = "-".join(["word"] * 16000)      # 약 80KB, 시크릿 낱말로 끝나지 않는다
    started = _time.time()
    masking.mask(hostile)
    assert _time.time() - started < 1.0


def test_never_send_removes_the_whole_file_content(tmp_path):
    secret = tmp_path / "개인정보.md"
    secret.write_text("계정: someone\n비번: 매우비밀한값입니다\n", encoding="utf-8")
    text = "화면:\n" + secret.read_text(encoding="utf-8")
    masked = masking.mask(text, never_send=[str(secret)])
    assert "매우비밀한값입니다" not in masked
    assert masking.NEVER_SEND_MASK in masked


def test_never_send_removes_a_single_line_from_a_screen_capture(tmp_path):
    """화면 캡처에는 전문이 아니라 몇 줄만 실린다 — 전문 대조만으로는 하나도 못 잡는다."""
    secret = tmp_path / "개인정보.md"
    secret.write_text("계정: someone\n비번: 매우비밀한값입니다\n다른줄\n", encoding="utf-8")
    text = "$ cat 개인정보.md\n비번: 매우비밀한값입니다\n$ "
    masked = masking.mask(text, never_send=[str(secret)])
    assert "매우비밀한값입니다" not in masked


def test_never_send_skips_unreadable_paths(tmp_path):
    """항목 하나의 문제로 발신 전체가 죽으면 안 된다 — 그러면 루프가 조용히 멈춘다."""
    assert masking.mask("본문", never_send=[str(tmp_path / "없는파일")]) == "본문"


def test_truncate_capture_keeps_the_last_lines():
    text = "\n".join(str(i) for i in range(100))
    assert masking.truncate_capture(text, lines=40).splitlines()[0] == "60"


# ------------------------------------------------------- 1회 한정 장부 (D2)

def test_ledger_records_a_key_exactly_once(root):
    book = ledger_mod.Ledger()
    key = ledger_mod.question_key("dev-cmd-vault", 2, 3)
    assert book.record_once(key) is True
    assert book.record_once(key) is False


def test_ledger_survives_a_restart(root):
    """001의 1회 한정은 프로세스 메모리였다 — 죽으면 같은 질문이 다시 나갔다."""
    key = ledger_mod.question_key("dev-cmd-vault", 2, 3)
    assert ledger_mod.Ledger().record_once(key) is True
    assert ledger_mod.Ledger().record_once(key) is False     # 새 인스턴스 = 재기동


def test_ledger_generation_is_part_of_the_key(root):
    """세대가 바뀌면 같은 번호의 질문을 다시 물을 수 있어야 한다."""
    book = ledger_mod.Ledger()
    assert book.record_once(ledger_mod.question_key("s", 1, 1)) is True
    assert book.record_once(ledger_mod.question_key("s", 2, 1)) is True


def test_injection_intent_without_done_blocks_reinjection(root):
    """intent만 있고 done이 없으면 **재주입하지 않는다** — 넣었는지 알 수 없다."""
    key = ledger_mod.inject_key("dev-cmd-vault", 1, 4)
    first = ledger_mod.Ledger()
    assert first.begin(key) is True
    # 여기서 프로세스가 죽었다고 하자.
    reborn = ledger_mod.Ledger()
    assert reborn.is_ambiguous(key) is True
    assert reborn.begin(key) is False
    assert reborn.ambiguous_keys() == [key]


def test_completed_injection_is_not_ambiguous(root):
    key = ledger_mod.inject_key("dev-cmd-vault", 1, 4)
    book = ledger_mod.Ledger()
    book.begin(key)
    book.complete(key)
    assert ledger_mod.Ledger().is_ambiguous(key) is False
    assert ledger_mod.Ledger().ambiguous_keys() == []


def test_trimming_never_drops_an_unfinished_injection(root, monkeypatch):
    """미완(intent) 기록이 정리에 휩쓸리면 재기동한 우체부가 답을 두 번 넣는다."""
    monkeypatch.setattr(ledger_mod, "MAX_ENTRIES", 10)
    book = ledger_mod.Ledger()
    key = ledger_mod.inject_key("dev-cmd-vault", 1, 1)
    book.begin(key, now=0)                       # 가장 오래된 항목이 미완이다
    for n in range(50):
        book.record_once(ledger_mod.question_key("s", 1, n), now=100 + n)
    assert ledger_mod.Ledger().is_ambiguous(key) is True


def test_corrupt_ledger_is_quarantined_and_restarts_empty(root):
    """fail-open — 장부가 깨졌다고 통로를 닫지 않는다. 상한이 2차 선이다."""
    paths.ledger_file().write_text("{망가진 JSON", encoding="utf-8")
    book = ledger_mod.Ledger()
    assert book.record_once("q:x") is True
    assert book.take_recovery_flag() is True
    assert book.take_recovery_flag() is False        # alert는 한 번만
    assert list(paths.corrupt_dir().iterdir())


# ------------------------------------------------------------- 발신 상한 (D2)

def test_soft_limit_suppresses_ordinary_sends(root):
    limiter = limits_mod.SendLimiter(soft_limit=3, hard_limit=10)
    now = 1000.0
    for _ in range(3):
        assert limiter.consume("notify", now=now) is True
    assert limiter.consume("notify", now=now) is False
    assert limiter.suppressed(now=now) == 1


def test_soft_limit_exempts_question_alert_and_done_report(root):
    """대기 해제성·인수인계성 발신을 막으면 루프가 조용히 멈춘다."""
    limiter = limits_mod.SendLimiter(soft_limit=1, hard_limit=100)
    now = 1000.0
    limiter.consume("notify", now=now)
    for kind in ("question", "alert", "done_report"):
        assert limiter.consume(kind, now=now) is True


def test_hard_limit_stops_everything_but_user_replies(root):
    limiter = limits_mod.SendLimiter(soft_limit=1, hard_limit=3)
    now = 1000.0
    for _ in range(3):
        limiter.consume("question", now=now)
    assert limiter.consume("question", now=now) is False
    assert limiter.consume("reply", now=now) is True     # 사용자 명령 응답은 면제
    assert limiter.blocked(now=now) is True


def test_hard_block_does_not_expire_with_the_window(root):
    """경성 중단은 창이 굴러도 저절로 풀리지 않는다 — 해제는 `resume`뿐이다."""
    limiter = limits_mod.SendLimiter(soft_limit=1, hard_limit=2, window=3600.0)
    now = 1000.0
    limiter.consume("question", now=now)
    limiter.consume("question", now=now)
    assert limiter.consume("question", now=now) is False
    later = now + 4000.0
    assert limiter.blocked(now=later) is True
    assert limiter.consume("question", now=later) is False


def test_resume_releases_the_hard_block_and_reports_the_suppressed_count(root):
    limiter = limits_mod.SendLimiter(soft_limit=1, hard_limit=2)
    now = 1000.0
    limiter.consume("question", now=now)
    limiter.consume("question", now=now)
    limiter.consume("question", now=now)     # 억제 1
    limiter.consume("notify", now=now)       # 억제 2
    assert limiter.release(now=now) == 2
    assert limiter.blocked(now=now) is False
    assert limiter.consume("question", now=now) is True


# --------------------------------------------------------------- 오프셋 (D2)

def test_offset_survives_a_restart(root):
    store.OffsetStore().set(4242)
    assert store.OffsetStore().get() == 4242


def test_corrupt_offset_is_quarantined_and_restarts_empty(root):
    paths.offset_file().write_text("[깨짐", encoding="utf-8")
    offsets = store.OffsetStore()
    assert offsets.get() is None
    assert offsets.take_recovery_flag() is True
    assert list(paths.corrupt_dir().iterdir())


# ------------------------------------------------------------ 회신 변별자 (D10)

class DedupBus(object):
    """세션 간 메신저의 실측 거동 대역 — **같은 본문 회신을 조용히 버린다.**

    002-N2 1-5절에서 동일 본문 회신 1건이 실제로 사라졌고, 발신자에게는 실패로 보고되지
    않았다. 그 거동을 그대로 흉내낸다.
    """

    def __init__(self):
        self.delivered = []
        self._seen = set()

    def send(self, text):
        if text in self._seen:
            return True          # ← 성공이라 답하고 버린다. 이것이 사고의 형태다.
        self._seen.add(text)
        self.delivered.append(text)
        return True


def test_identical_replies_are_silently_dropped_without_a_discriminator():
    """변별자가 없으면 두 번째 회신이 사라지고 **발신자는 성공으로 안다**."""
    bus = DedupBus()
    body = "회수 완료 — 이상 없음"
    assert bus.send(body) is True
    assert bus.send(body) is True          # 성공이라고 답한다
    assert bus.delivered == [body]         # 그런데 하나만 도착했다


def test_discriminator_makes_identical_replies_survive():
    bus = DedupBus()
    body = "회수 완료 — 이상 없음"
    seq = disc.SeqCounter()
    for _ in range(2):
        bus.send(disc.stamp(body, "002-N4A", 2, seq.next()))
    assert len(bus.delivered) == 2
    assert bus.delivered[0].startswith("[002-N4A g2#1]")
    assert bus.delivered[1].startswith("[002-N4A g2#2]")


def test_control_messages_use_cmd_and_survive_across_generations():
    """`[cmd #1] 교체 요청`은 세대마다 같은 본문이 된다 — 세대가 붙어야 삼켜지지 않는다."""
    bus = DedupBus()
    for generation in (1, 2):
        bus.send(disc.stamp("교체 요청", None, generation, 1))
    assert len(bus.delivered) == 2
    assert bus.delivered[0].startswith("[cmd g1#1]")


def test_stamp_does_not_double_prefix():
    once = disc.stamp("완료", "N4", 1, 1)
    assert disc.stamp(once, "N4", 1, 2) == once


def test_parse_reads_back_what_stamp_wrote():
    parsed = disc.parse(disc.stamp("완료", "002-N4A", 3, 7))
    assert (parsed.node, parsed.generation, parsed.seq) == ("002-N4A", 3, 7)


def test_missing_seqs_detects_a_gap():
    seen = [disc.Discriminator("N4", 2, 1), disc.Discriminator("N4", 2, 3)]
    assert disc.missing_seqs(seen, 2) == [2]


def test_reply_without_a_discriminator_is_not_trusted():
    assert disc.has_discriminator("완료했습니다") is False
    assert disc.has_discriminator("[002-N4A g1#1] 완료했습니다") is True


# ------------------------------------------------------------- 우편함 (D2)

def _write(path, text="{}"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_unsent_lists_notifications_without_a_sent_marker(root):
    box = paths.sessions_dir() / "dev-cmd-vault"
    first = _write(box / "notify-1-aaaaaa.json")
    _write(box / "notify-2-bbbbbb.json")
    mailbox.mark_sent(first)
    assert [p.name for p in mailbox.unsent("dev-cmd-vault")] == ["notify-2-bbbbbb.json"]
    assert first.exists()          # 원본은 건드리지 않는다


def test_cleanup_keeps_pending_and_the_counter_mailbox(root):
    box = paths.sessions_dir() / "dev-cmd-vault"
    pending = _write(box / "pending-1.json")
    counter = _write(paths.counter_dir() / "notify-1-cccccc.json")
    mailbox.mark_sent(counter)
    old = time.time() - 30 * 86400
    import os
    os.utime(str(mailbox.sent_marker(counter)), (old, old))
    mailbox.cleanup(max_age_days=7, live_sessions=(),
                    absent_since={"dev-cmd-vault": old, paths.COUNTER_MAILBOX: old})
    assert pending.exists()
    assert counter.exists()        # 창구 우편함은 청소 대상이 아니다


def test_cleanup_removes_old_sent_notifications(root):
    box = paths.sessions_dir() / "dev-cmd-vault"
    note = _write(box / "notify-1-aaaaaa.json")
    marker = mailbox.mark_sent(note)
    old = time.time() - 30 * 86400
    import os
    os.utime(str(marker), (old, old))
    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))
    assert removed["notify"] == 1
    assert not note.exists()


# ------------------------------------------- 끝난 질문 교환의 청소 (002-N14)

def _finished_exchange(box, generation=1, seq=1, answered_age=None):
    """질문 한 벌을 세운다 — 본문·`.sent`·(선택) 응답 표식·`answer-…`."""
    question = _write(box / ("question-g%d-%02d.json" % (generation, seq)), '{"text": "q"}')
    mailbox.mark_sent(question)
    answer = _write(box / ("answer-g%d-%02d.json" % (generation, seq)))
    marker = None
    if answered_age is not None:
        marker = _write(box / (question.name + mailbox.ANSWERED_SUFFIX), '{"ts": 1.0}')
        stamp = time.time() - answered_age
        os.utime(str(marker), (stamp, stamp))
    return question, marker, answer


def test_cleanup_removes_a_question_exchange_the_session_finished(root):
    """응답 표식이 붙고 기한이 지난 교환은 **네 파일이 함께** 사라진다 — 무한 누적을 끊는다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    question, marker, answer = _finished_exchange(box, answered_age=30 * 86400)

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 1
    assert not question.exists()
    assert not marker.exists()
    assert not answer.exists()
    assert not mailbox.sent_marker(question).exists()


def test_cleanup_never_removes_a_question_without_an_answered_marker(root):
    """표식이 없으면 **아무리 오래돼도 남는다** — 미답 질문이 조용히 사라지면 안 된다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    question, _marker, _answer = _finished_exchange(box, answered_age=None)
    old = time.time() - 365 * 86400
    os.utime(str(question), (old, old))
    os.utime(str(mailbox.sent_marker(question)), (old, old))

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 0
    assert question.exists()


def test_cleanup_counts_the_age_from_the_marker_not_the_question(root):
    """기한은 **끝난 시각부터** 센다. 하룻밤 넘겨 온 답을 방금 처리한 교환은 남는다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    question, marker, _answer = _finished_exchange(box, answered_age=60)
    old = time.time() - 365 * 86400
    os.utime(str(question), (old, old))          # 발급은 아주 오래전, 답 처리는 방금

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 0
    assert question.exists() and marker.exists()


def test_cleanup_leaves_a_finished_exchange_inside_the_window(root):
    """기한 안이면 표식이 붙었어도 남는다 — 답을 되짚을 재료가 곧바로 사라지지 않는다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    question, marker, answer = _finished_exchange(box, answered_age=3 * 86400)

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 0
    assert question.exists() and marker.exists() and answer.exists()


def test_cleanup_sweeps_only_the_finished_coordinate(root):
    """한 우편함에 섞여 있어도 **좌표별로** 갈린다 — 곁의 미답 질문을 끌고 가지 않는다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    done, _m1, _a1 = _finished_exchange(box, seq=1, answered_age=30 * 86400)
    open_one, _m2, open_answer = _finished_exchange(box, seq=2, answered_age=None)

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 1
    assert not done.exists()
    assert open_one.exists() and open_answer.exists()


def test_cleanup_sweeps_a_question_whose_name_breaks_the_coordinate_rule(root):
    """좌표를 못 읽는 이름이어도 본문·표식은 치운다 — `answer-…` 조립만 건너뛴다.

    이름을 지어내지 않는 자리다. 규약 밖 이름에 좌표를 붙여 지우면 **남의 좌표 파일을
    지운다.**
    """
    box = paths.sessions_dir() / "dev-cmd-vault"
    question = _write(box / "question-bad.json", '{"text": "q"}')
    mailbox.mark_sent(question)
    marker = _write(box / (question.name + mailbox.ANSWERED_SUFFIX), '{"ts": 1.0}')
    old = time.time() - 30 * 86400
    os.utime(str(marker), (old, old))
    neighbour = _write(box / "answer-g1-01.json")     # 좌표가 겹칠 뻔한 남의 파일

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 1
    assert not question.exists() and not marker.exists()
    assert neighbour.exists()


def test_cleanup_retries_a_sweep_that_could_not_finish(root):
    """도중에 못 지운 곁다리는 **다음 순회가 마저 치운다** — 표식을 맨 마지막에 지우므로.

    본문을 기준으로 훑으면 본문이 먼저 사라진 좌표를 다시 집지 못해 곁다리가 영구
    고아가 된다. 없애려던 누적이 파일 종류만 바꿔 되살아나는 자리다.
    """
    box = paths.sessions_dir() / "dev-cmd-vault"
    question, marker, answer = _finished_exchange(box, answered_age=30 * 86400)
    question.unlink()                    # 앞선 순회가 본문까지만 지우고 끊긴 상태

    removed = mailbox.cleanup(max_age_days=7, live_sessions=("dev-cmd-vault",))

    assert removed["answered"] == 1
    assert not marker.exists()
    assert not answer.exists()
    assert not mailbox.sent_marker(question).exists()


def test_cleanup_does_not_touch_the_answered_markers_of_the_counter_mailbox(root):
    """창구 우편함은 통째로 청소 대상이 아니다 — 새 규칙도 그 예외를 넘지 않는다."""
    box = paths.counter_dir()
    question, marker, _answer = _finished_exchange(box, answered_age=30 * 86400)

    removed = mailbox.cleanup(max_age_days=7, live_sessions=(),
                              absent_since={paths.COUNTER_MAILBOX: time.time() - 30 * 86400})

    assert removed["answered"] == 0
    assert question.exists() and marker.exists()


def test_has_undelivered_sees_pending(root):
    _write(paths.sessions_dir() / "dev-cmd-vault" / "pending-1.json")
    assert mailbox.has_undelivered() is True


def test_mailbox_paths_reject_addresses_that_escape(root):
    """우편함 이름은 경로 조각이 된다 — 규약을 못 지나면 아무것도 돌려주지 않는다."""
    assert mailbox.unsent("../../etc") == []
    assert mailbox.pending("dev.cmd.vault") == []
    assert mailbox.unsent(paths.COUNTER_MAILBOX) == []   # 창구 우편함은 명시 예외로 통과


# ------------------------------------------------- 로그 파일 권한 (002 FU1 항목 41)

def test_a_new_log_file_is_never_world_readable(root):
    """umask가 넓어도 로그는 0600이다 — 본문 길이·좌표가 실리는 파일이다."""
    old = os.umask(0o022)
    try:
        path = eventlog.record("inject", session="dev-cmd-vault", seq=1)
    finally:
        os.umask(old)
    assert path is not None and path.exists()
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)


def test_the_log_file_is_private_before_the_first_line_is_written(root, monkeypatch):
    """**권한이 생성에 선행한다.** 만든 뒤에 조이면 그 사이가 열린 창이다.

    쓰기 직전의 권한을 재서 창의 유무를 본다 — 기록 전에 이미 0600이어야 한다.
    구현이 fd 경유(`os.open` → `os.fdopen`)를 버리면 이 관찰점도 함께 옮겨야 한다.
    """
    seen = {}
    real_fdopen = os.fdopen

    def spy(fd, *args, **kwargs):
        seen["mode"] = os.fstat(fd).st_mode & 0o777
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(eventlog.os, "fdopen", spy)
    old = os.umask(0o022)
    try:
        eventlog.record("inject", session="dev-cmd-vault", seq=1)
    finally:
        os.umask(old)
    assert oct(seen.get("mode", 0)) == oct(0o600)


def test_a_log_file_left_open_by_an_older_run_is_tightened(root):
    """옛 실행이 남긴 넓은 파일도 다음 기록에서 조인다 — chmod가 하던 몫이다."""
    path = eventlog.log_path()
    paths.ensure_private_dir(path.parent)
    path.write_text("", encoding="utf-8")
    os.chmod(str(path), 0o644)
    eventlog.record("inject", session="dev-cmd-vault", seq=1)
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)


def test_a_line_that_cannot_be_encoded_never_reaches_the_caller(root):
    """인코딩 불가 문자도 `OSError`처럼 삼킨다 — 로그가 없다고 통로가 멈추면 안 된다.

    터지는 자리는 `json.dumps`가 아니라 `fp.write`라, 예외가 `UnicodeError` 계열로 나온다.
    삼킨 뒤에도 다음 기록이 살아 있어야 실패가 한 줄로 끝난다.
    """
    assert eventlog.record("inject", session="dev-cmd-\ud800") is None
    assert eventlog.log_path().read_text(encoding="utf-8") == ""   # 반쪽 줄도 남지 않는다
    path = eventlog.record("inject", session="dev-cmd-vault", seq=2)
    assert path is not None and len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_the_log_records_meta_and_drops_the_body(root):
    """정상 경로 — 본문 자리는 길이만 남는다."""
    path = eventlog.record("inject", session="dev-cmd-vault", answer="비밀 본문")
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert line["event"] == "inject" and line["session"] == "dev-cmd-vault"
    assert line["answer_len"] == len("비밀 본문")
    assert "answer" not in line


# ------------------------------------- 우편함 열거·부모 생성 (002 FU16 N26·N27)

def test_a_symlink_is_never_counted_as_a_mailbox(root):
    """세션명 규칙에 맞는 심링크가 놓여도 우편함이 아니다 (N26).

    여기서 나온 이름은 점검뿐 아니라 청소(`mailbox.cleanup`)의 입력이라, 추종하면
    뿌리 밖 디렉토리의 파일이 지워진다. 진짜 디렉토리는 그대로 나와야 한다.
    """
    outside = root.parent / "somewhere-else"
    outside.mkdir()
    (paths.sessions_dir()).mkdir(parents=True, exist_ok=True)
    os.symlink(str(outside), str(paths.sessions_dir() / "dev-cmd-vault"))
    (paths.sessions_dir() / "dev-cmd-real").mkdir()
    assert paths.list_session_mailboxes() == ["dev-cmd-real"]


def test_a_missing_parent_is_created_owner_only(root):
    """`ensure_private_dir`를 앞세우지 않은 호출자여도 부모는 0700이다 (N27).

    umask를 넓혀도 0755로 서지 않아야, 자가 점검이 자기 프로그램의 실수를 잡는
    모양이 되지 않는다.
    """
    box = paths.sessions_dir() / "dev-cmd-vault"
    old = os.umask(0o022)
    try:
        paths.atomic_write_json(box / "pending-1.json", {"x": 1})
    finally:
        os.umask(old)
    assert oct(box.stat().st_mode & 0o777) == oct(0o700)
    assert oct(paths.sessions_dir().stat().st_mode & 0o777) == oct(0o700)


def test_an_existing_parent_keeps_its_permissions(root):
    """이미 있는 디렉토리는 손대지 않는다 — 남의 디렉토리를 매번 잠그면 001의 사고다."""
    box = paths.sessions_dir() / "dev-cmd-vault"
    box.mkdir(parents=True)
    os.chmod(str(box), 0o755)
    paths.atomic_write_json(box / "pending-1.json", {"x": 1})
    assert oct(box.stat().st_mode & 0o777) == oct(0o755)
