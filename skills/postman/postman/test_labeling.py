"""발신문 출처 표시 — 다중 프로젝트 알림 접두사 규칙 (002 후속 항목 59).

덮는 것은 **조용히 헷갈리는 것**이다. 한 채팅에 여러 세션의 우편함이 몰리는데,
질문(`question-*.json`)에는 출처가 아예 없었고 창구 우편함은 이름이 `counter` 고정이라
프로젝트가 둘이면 어느 쪽 창구인지 화면에서 갈리지 않았다. 여기서 단언하는 것은
「누가 말했는지가 언제나 첫 글자에 있다」와 「그 표시가 두 겹이 되지 않는다」 둘이다.
"""
import time

import pytest

from postman import paths
from postman import sender as sender_mod
from postman.test_routing import (COMMAND, WORKER, FakeTransport, Rig, screen_with,
                                  write_notify, write_question, write_relay)

PROJECT = "vault"


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "postman"
    monkeypatch.setenv("POSTMAN_ROOT", str(base))
    monkeypatch.setenv("POSTMAN_CONFIG", str(base / "config.json"))
    monkeypatch.setenv("POSTMAN_TOKEN_FILE", str(base / "telegram-bot-token"))
    monkeypatch.delenv(paths.PROJECT_ENV, raising=False)
    base.mkdir(parents=True)
    return base


def make_sender(transport=None, project=None):
    return sender_mod.Sender(transport or FakeTransport(), 42, project=project,
                             min_interval=0, sleep=lambda _s: None, clock=time.monotonic)


# ------------------------------------------------------- 표시 규칙 (paths)

def test_a_session_name_that_already_carries_the_slug_is_left_alone():
    """`[vault/dev-vault-fu2]`는 같은 말을 두 번 하는 것이다."""
    assert paths.display_label("dev-vault-fu2", project=PROJECT) == "dev-vault-fu2"
    assert paths.display_label("dev-cmd-vault", project=PROJECT) == "dev-cmd-vault"


def test_the_counter_mailbox_gets_the_project_in_front():
    """창구는 이름이 고정이라 프로젝트가 둘이면 `[counter]`끼리 구별되지 않는다."""
    assert paths.display_label(paths.COUNTER_MAILBOX, project=PROJECT) == "vault/counter"


def test_a_slug_with_hyphens_is_still_recognised_inside_the_session_name():
    """토막 단위로 대조하면 `dev-run-practice` 같은 슬러그를 놓친다."""
    label = paths.display_label("dev-cmd-dev-run-practice", project="dev-run-practice")
    assert label == "dev-cmd-dev-run-practice"


def test_without_a_project_the_session_name_stands_alone():
    """프로젝트를 모르면 예전 그대로다 — 표시가 나빠지는 방향으로는 절대 안 간다."""
    assert paths.display_label(WORKER, project=None) == WORKER
    assert paths.display_label(paths.COUNTER_MAILBOX, project=None) == "counter"


def test_a_send_without_a_session_is_labelled_with_the_project_alone():
    """봇이 명령에 직접 답하는 자리 — 어느 프로젝트의 우체부가 답했는지는 남아야 한다."""
    assert paths.display_label(None, project=PROJECT) == PROJECT
    assert paths.display_label("", project=PROJECT) == PROJECT


def test_a_session_name_outside_the_address_convention_is_not_shown():
    """표시는 마스킹 관문 뒤에 붙는다 — 규약 밖 문자열이 관문을 건너뛰는 통로가 된다."""
    for bad in ("no-such\nnewline", "../etc/passwd", "has space", "a" * 200, 42):
        assert paths.display_label(bad, project=PROJECT) == PROJECT
        assert paths.display_label(bad, project=None) is None


def test_a_project_slug_outside_the_convention_is_not_shown_either():
    """명시 인자도 환경변수와 같은 폭을 지난다 — 한쪽만 검사하면 그 비대칭이 구멍이다."""
    assert paths.display_label(paths.COUNTER_MAILBOX, project="../etc") == "counter"
    assert paths.display_label(paths.COUNTER_MAILBOX, project="has space") == "counter"
    assert paths.display_label(None, project="../etc") is None


def test_nothing_to_say_yields_no_label():
    assert paths.display_label(None, project=None) is None
    assert paths.display_label("", project=None) is None


# ------------------------------------------------------- 슬러그 출처 (환경변수)

def test_the_project_slug_comes_from_the_same_variable_the_startup_check_reads(monkeypatch):
    monkeypatch.setenv(paths.PROJECT_ENV, "vault")
    assert paths.project_slug() == "vault"
    assert paths.display_label(paths.COUNTER_MAILBOX) == "vault/counter"


def test_a_slug_outside_the_session_name_width_is_refused(monkeypatch):
    """세션명이 못 받는 값은 여기서도 받지 않는다 — 슬러그는 세션명 안에 박혀 나간다 (D9)."""
    for bad in ("", "   ", "../etc", "has space", "-leading", "123", "a" * 200):
        monkeypatch.setenv(paths.PROJECT_ENV, bad)
        assert paths.project_slug() is None


def test_an_unset_variable_is_not_an_error(monkeypatch):
    monkeypatch.delenv(paths.PROJECT_ENV, raising=False)
    assert paths.project_slug() is None


# ------------------------------------------------------- 발신기 관문

def test_every_send_carries_the_label_including_questions(root):
    """질문에 출처가 없던 것이 후속 59의 알맹이다."""
    transport = FakeTransport()
    sender = make_sender(transport, project=PROJECT)

    sender.send_text("답이 필요합니다", kind="question", session=WORKER)
    sender.send_text("재스폰 실패", kind="alert", session=paths.COUNTER_MAILBOX)
    sender.send_text("상태입니다", kind="reply")

    assert transport.sent_texts() == [
        "[dev-vault-n4b] 답이 필요합니다",
        "[vault/counter] 재스폰 실패",
        "[vault] 상태입니다",
    ]


def test_an_empty_body_does_not_become_a_bare_label(root):
    """접두만 남은 발신을 만들지 않는다 — 사람은 그것을 보고 무엇도 알 수 없다."""
    transport = FakeTransport()
    sender = make_sender(transport, project=PROJECT)

    assert sender.send_text("", session=WORKER).status == sender_mod.EMPTY
    assert sender.send_text(None, session=WORKER).status == sender_mod.EMPTY
    assert transport.sent_texts() == []


def test_the_label_survives_the_body_cap(root):
    """상한에 걸려 잘려도 **누가 말했는지**는 남는다 — 표시를 자르기 앞에 붙이는 이유다."""
    transport = FakeTransport()
    sender = make_sender(transport, project=PROJECT)
    sender.max_body = 50
    sender.max_chars = 4096

    sender.send_text("가" * 500, session=paths.COUNTER_MAILBOX)

    assert transport.sent_texts()[0].startswith("[vault/counter] ")
    assert "잘랐습니다" in transport.sent_texts()[0]


def test_masking_still_reaches_the_body_after_the_label_is_added(root, tmp_path):
    """표시를 붙였다고 마스킹 관문이 느슨해지지 않는다 (D2)."""
    secret = tmp_path / "비밀.md"
    secret.write_text("계좌번호 110-1234-5678", encoding="utf-8")
    transport = FakeTransport()
    sender = sender_mod.Sender(transport, 42, never_send=(str(secret),), project=PROJECT,
                               min_interval=0, sleep=lambda _s: None)

    sender.send_text("화면: 계좌번호 110-1234-5678", session=WORKER)

    text = transport.sent_texts()[0]
    assert text.startswith("[dev-vault-n4b] ")
    assert "110-1234-5678" not in text


# ------------------------------------------------------- 배달 경로 통합

def test_a_notice_is_labelled_once_not_twice(root, monkeypatch):
    """배달이 접두를 따로 조립하지 않는다 — 두 겹이면 `[vault] [dev-…]`가 된다."""
    monkeypatch.setenv(paths.PROJECT_ENV, PROJECT)
    write_relay()
    rig = Rig(screen_with(COMMAND, WORKER))
    write_notify(WORKER, "노드 002-N4B 완료")

    rig.postman.tick()

    assert rig.texts() == ["[dev-vault-n4b] 노드 002-N4B 완료"]


def test_a_counter_notice_says_which_project_it_came_from(root, monkeypatch):
    monkeypatch.setenv(paths.PROJECT_ENV, PROJECT)
    write_relay()
    rig = Rig(screen_with(COMMAND))
    paths.ensure_private_dir(paths.counter_dir())
    write_notify(paths.COUNTER_MAILBOX, "재스폰에 실패했습니다", kind="alert")

    rig.postman.tick()

    assert "[vault/counter] 재스폰에 실패했습니다" in rig.texts()


def test_a_delivered_question_now_says_who_is_asking(root, monkeypatch):
    """후속 59 이전에는 질문 본문만 나가 **누가 묻는지 화면에 없었다.**"""
    monkeypatch.setenv(paths.PROJECT_ENV, PROJECT)
    write_relay()
    rig = Rig(screen_with(COMMAND, WORKER))
    write_question(WORKER, "A로 갈까요?", choices=["A", "B"])

    rig.postman.tick()

    assert rig.texts() == ["[dev-vault-n4b] A로 갈까요?"]


def test_the_original_mailbox_file_is_not_rewritten_with_the_label(root, monkeypatch):
    """표시는 발신문에만 붙는다 — 우편함 원본은 세션이 쓴 그대로다."""
    monkeypatch.setenv(paths.PROJECT_ENV, PROJECT)
    write_relay()
    rig = Rig(screen_with(COMMAND, WORKER))
    path = write_notify(WORKER, "노드 002-N4B 완료")

    rig.postman.tick()

    assert paths.read_json(path)["text"] == "노드 002-N4B 완료"
