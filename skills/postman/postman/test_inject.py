"""주입 절차 테스트 — `tmux`를 실호출하지 않는다 (가짜 화면).

덮는 것: 재캡처 3회 반영 확인(N12 결함 2 회귀), 장부 2단 기록과 미완 재주입 차단,
실패 갈래(살아 있으면 중단·사라졌으면 보관), 선택지 번호 식별, 주소 문자열 경계.
"""
import pytest

from postman import inject as inject_mod
from postman import ledger as ledger_mod
from postman import paths
from postman import tmuxq


# ---------------------------------------------------------------- 가짜 화면

class FakeScreen(object):
    """tmux 대역. 화면 문자열을 들고 캡처·주입을 흉내 낸다.

    `echo_after`는 **주입한 문자열이 몇 번째 캡처에서 화면에 나타나는가**다. 1이면 즉시
    반영, 3이면 두 번 더 봐야 보인다 — 001 N12에서 실제로 일어난 지연이다.
    """

    def __init__(self, sessions=None, echo_after=1, after_text=None):
        self.sessions = dict(sessions or {})
        self.echo_after = int(echo_after)
        # 반영이 일어나면 화면이 이렇게 바뀐다. 실제 세션은 답을 받으면 **질문을 닫고**
        # 진행하므로, 넣은 문자열이 화면에 덧붙는 것보다 이쪽이 실제에 가깝다.
        self.after_text = after_text
        self.sent = []
        self.captures = 0
        self.capture_fails = set()
        self.send_fails = set()
        self.vanish_on_send = False
        self.vanish_after_send = False
        self._echo = None

    # -- 손 --------------------------------------------------------------

    def has_session(self, name):
        return name in self.sessions

    def capture(self, name, lines=None):
        self.captures += 1
        if name in self.capture_fails or name not in self.sessions:
            return None
        if self._echo is not None:
            target, text, remaining = self._echo
            remaining -= 1
            if remaining <= 0:
                if self.after_text is None:
                    self.sessions[target] = self.sessions.get(target, "") + "\n" + text
                else:
                    self.sessions[target] = self.after_text
                self._echo = None
            else:
                self._echo = (target, text, remaining)
        return self.sessions.get(name, "")

    def send(self, name, text):
        self.sent.append((name, text))
        if self.vanish_on_send:
            self.sessions.pop(name, None)
            return False
        if name in self.send_fails or name not in self.sessions:
            return False
        if self.vanish_after_send:
            self.sessions.pop(name, None)
            return True
        self._echo = (name, text, self.echo_after)
        return True

    # -- 조립 ------------------------------------------------------------

    def deps(self, tries=inject_mod.SETTLE_TRIES):
        return inject_mod.Deps(has_session=self.has_session, capture=self.capture,
                               send=self.send, sleep=lambda _s: None, tries=tries,
                               settle=0)


QUESTION = "이 노드를 계속 진행할까요?"
SCREEN = "작업 중...\n%s\n1) 진행\n2) 중단" % QUESTION
# 답을 받은 뒤의 화면 — 질문이 닫히고 세션이 진행한다.
ANSWERED = "작업 중...\n진행합니다"


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / "postman"
    monkeypatch.setenv("POSTMAN_ROOT", str(base))
    monkeypatch.setenv("POSTMAN_CONFIG", str(base / "config.json"))
    base.mkdir(parents=True)
    return base


@pytest.fixture
def ledger(root):
    return ledger_mod.Ledger()


def key():
    return ledger_mod.inject_key("dev-cmd-vault", 2, 1)


# ---------------------------------------------------------------- 재캡처 3회 (D1)

def test_a_late_screen_update_is_still_counted_as_reflected(root, ledger):
    """**001 N12 결함 2의 회귀 테스트.** 한 장만 보면 정상 주입이 미반영으로 오판된다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=3, after_text=ANSWERED)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert result.status == inject_mod.INJECTED
    assert ledger.state(key()) == ledger_mod.DONE


def test_one_shot_confirmation_would_have_misjudged_the_same_screen(root, ledger):
    """같은 화면을 재캡처 1회로 보면 중단된다 — 재시도가 판정을 바꾼다는 것을 못 박는다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=3, after_text=ANSWERED)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(tries=1), question=QUESTION)
    assert result.status == inject_mod.ABORTED
    assert result.reason == inject_mod.NOT_REFLECTED


def test_the_answer_goes_in_exactly_once(root, ledger):
    """반영 확인이 여러 장이어도 **답은 한 번만 넣는다.**"""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=3, after_text=ANSWERED)
    inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                             deps=screen.deps(), question=QUESTION)
    assert len(screen.sent) == 1


def test_a_second_delivery_of_the_same_answer_is_refused(root, ledger):
    """장부에 done이 있으면 다시 넣지 않는다 — 재기동·오프셋 소실을 넘어 유지된다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, after_text=ANSWERED)
    inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                             deps=screen.deps(), question=QUESTION)
    again = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger_mod.Ledger(),
                                     deps=screen.deps(), question=QUESTION)
    assert again.status == inject_mod.SKIPPED
    assert len(screen.sent) == 1


# ---------------------------------------------------------------- 2단 기록 (D2)

def test_an_unfinished_injection_is_never_replayed(root, ledger):
    """intent만 있고 done이 없다 — 넣었는지 알 수 없으므로 재주입하지 않는다."""
    ledger.begin(key())
    screen = FakeScreen({"dev-cmd-vault": SCREEN})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.STORED, inject_mod.AMBIGUOUS)
    assert screen.sent == []


def test_the_intent_is_written_before_the_screen_is_touched(root, ledger):
    """기록이 주입에 선행한다 (D1) — send 시점에 장부가 이미 그 좌표를 알고 있다."""
    seen = {}
    screen = FakeScreen({"dev-cmd-vault": SCREEN})
    real_send = screen.send

    def spy(name, text):
        seen["state"] = ledger.state(key())
        return real_send(name, text)

    deps = screen.deps()
    deps.send = spy
    inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger, deps=deps,
                             question=QUESTION)
    assert seen["state"] == ledger_mod.INTENT


def test_an_abort_before_sending_gives_the_coordinate_back(root, ledger):
    """아무것도 넣지 않은 중단은 의도를 되돌린다 — 그러지 않으면 영영 다시 답할 수 없다."""
    screen = FakeScreen({"dev-cmd-vault": "다른 화면"})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.ABORTED, inject_mod.NOT_OPEN)
    assert ledger.state(key()) is None          # 모호로 남기지 않는다

    screen.sessions["dev-cmd-vault"] = SCREEN   # 질문이 다시 열렸다
    screen.after_text = ANSWERED
    again = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                     deps=screen.deps(), question=QUESTION)
    assert again.status == inject_mod.INJECTED


def test_a_failure_after_sending_keeps_the_intent(root, ledger):
    """`send-keys` 뒤의 실패는 **되돌리지 않는다** — 일부가 들어갔을 수 있다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert result.reason == inject_mod.NOT_REFLECTED
    assert ledger.state(key()) == ledger_mod.INTENT


# ---------------------------------------------------------------- 실패 갈래 (D1·D7)

def test_a_missing_session_is_stored_not_aborted(root, ledger):
    """대상이 없으면 보관이다 — attach 안내는 자리에 없는 사람에게 무의미하다."""
    screen = FakeScreen({})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.STORED, inject_mod.GONE)
    assert ledger.state(key()) is None


def test_a_session_that_vanishes_mid_procedure_joins_the_stored_branch(root, ledger):
    """교체 창이 정확히 이 실패를 만든다 — 주입 도중 소멸은 보관으로 합류한다 (D1)."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN})
    screen.vanish_on_send = True
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.STORED, inject_mod.GONE)


def test_a_live_session_that_does_not_reflect_is_aborted_with_a_hint(root, ledger):
    """살아 있는데 반영이 없으면 중단하고 화면을 사람에게 넘긴다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert result.status == inject_mod.ABORTED
    assert "tmux attach -t dev-cmd-vault" in inject_mod.attach_hint("dev-cmd-vault")


def test_a_capture_failure_before_injection_is_stored(root, ledger):
    """캡처 실패는 대상 소멸의 얼굴이다 — 보관하고 의도를 되돌린다."""
    screen = FakeScreen({"dev-cmd-vault": SCREEN})
    screen.capture_fails.add("dev-cmd-vault")
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.STORED, inject_mod.GONE)
    assert ledger.state(key()) is None
    assert screen.sent == []


# ---------------------------------------------------------------- 화면 판독

def test_a_closed_question_is_not_answered_again(root, ledger):
    screen = FakeScreen({"dev-cmd-vault": "이미 진행 중입니다"})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert result.reason == inject_mod.NOT_OPEN


def test_a_number_is_used_only_when_it_is_unambiguous():
    assert inject_mod.choice_number("1) 진행\n2) 중단", "진행") == "1"
    assert inject_mod.choice_number("1) 진행\n2) 진행", "진행") is None
    assert inject_mod.choice_number("진행하시겠습니까", "진행") is None


def test_the_label_is_the_default_payload(root, ledger):
    """번호가 정확히 식별되지 않으면 라벨 리터럴을 넣는다 (D1)."""
    screen = FakeScreen({"dev-cmd-vault": "%s\n- 진행\n- 중단" % QUESTION})
    inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                             deps=screen.deps(), question=QUESTION)
    assert screen.sent[0][1] == "진행"


def test_reflection_without_an_open_check_needs_the_payload_on_screen(root, ledger):
    """세대가 바뀐 재주입(`require_open=False`)은 **질문 닫힘을 반영으로 치지 않는다.**

    치면 아무 화면이나 반영으로 통과한다 — 질문이 애초에 열려 있지 않기 때문이다.
    """
    screen = FakeScreen({"dev-cmd-vault": "새 지휘가 막 떴습니다"}, echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), require_open=False)
    assert result.reason == inject_mod.NOT_REFLECTED

    screen2 = FakeScreen({"dev-cmd-vault": "새 지휘가 막 떴습니다"})
    result2 = inject_mod.inject_answer("dev-cmd-vault", "진행",
                                       ledger_mod.inject_key("dev-cmd-vault", 3, 1),
                                       ledger, deps=screen2.deps(), require_open=False)
    assert result2.status == inject_mod.INJECTED


# ---------------------------------------------------------------- 주소 경계 (D9)

class SpyRun(object):
    """`tmux`를 부르는 대신 argv만 받아 적는다."""

    def __init__(self, returncode=0, stdout=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        return type("Proc", (), {"returncode": self.returncode, "stdout": self.stdout})()


@pytest.mark.parametrize("name", [
    "dev-cmd-vault",
    "A" * 128,                       # tmux 폭의 상한 — 001의 봇은 64자에서 조용히 거부했다
])
def test_capture_and_send_accept_names_up_to_the_tmux_width(name):
    run = SpyRun(stdout="화면")
    assert tmuxq.capture(name, run=run) == "화면"
    assert tmuxq.send_literal(name, "답", run=run) is True


@pytest.mark.parametrize("name", [
    "A" * 129,                       # 상한 초과
    "dev.cmd.vault",                 # tmux가 `.`를 창·pane 구분자로 읽는다
    "-dev-cmd",                      # 첫 글자가 옵션처럼 보인다
    "dev cmd",
    "../../etc/passwd",
    "",
    None,
])
def test_capture_and_send_refuse_names_outside_the_convention(name):
    """어긋남의 증상은 **"버튼을 눌렀는데 아무 일도 없다"** 하나뿐이라 여기서 못 박는다."""
    run = SpyRun(stdout="화면")
    assert tmuxq.capture(name, run=run) is None
    assert tmuxq.send_literal(name, "답", run=run) is False
    assert tmuxq.press_enter(name, run=run) is False
    assert run.calls == []           # 규약 밖 이름은 tmux에 닿지도 않는다


def test_the_body_and_the_enter_key_are_two_separate_calls():
    """합치면 리터럴 모드가 깨져 본문이 키 이름으로 해석된다 (ADR-001 D6 승계)."""
    run = SpyRun()
    tmuxq.send_literal("dev-cmd-vault", "C-c 진행", run=run)
    assert len(run.calls) == 2
    assert run.calls[0][-3:] == ["-l", "--", "C-c 진행"]
    assert run.calls[1][-1] == "Enter"


def test_a_body_starting_with_a_dash_is_not_read_as_an_option():
    run = SpyRun()
    tmuxq.send_literal("dev-cmd-vault", "--force", run=run)
    assert "--" in run.calls[0] and run.calls[0][-1] == "--force"


def test_a_capture_failure_is_none_and_an_empty_screen_is_empty_string():
    """둘을 섞으면 대상 소멸(보관)과 미반영(중단)을 못 가른다."""
    assert tmuxq.capture("dev-cmd-vault", run=SpyRun(returncode=1, stdout="")) is None
    assert tmuxq.capture("dev-cmd-vault", run=SpyRun(returncode=0, stdout="")) == ""


def test_paths_are_not_reachable_through_a_session_name(root):
    """세션명은 경로 조각이 되므로 상위 탈출이 통하면 우편함 밖에 파일을 쓴다."""
    from postman import addressing

    with pytest.raises(addressing.InvalidAddress):
        paths.session_dir("../../etc")


# ---------------------------------------------------------------- 반영 오판 (리뷰 지적 1)

def test_a_word_already_on_screen_does_not_look_like_a_non_reflection(root, ledger):
    """**스크롤백에 같은 낱말이 떠 있어도 정상 주입은 반영으로 읽혀야 한다.**

    `payload not in before`를 요구하면 "네"·"확인" 같은 짧은 답이 이전 대화에 한 번이라도
    등장한 순간 정상 주입이 미반영으로 오판된다. 열림 확인이 꺼진 경로에는 두 번째 눈이
    없어 그 오판이 그대로 굳고, 장부에 intent가 남아 **그 좌표의 모든 후속 시도가 막힌다.**
    """
    screen = FakeScreen({"dev-cmd-vault": "이전 대화에서 진행이라고 답했습니다"})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), require_open=False)
    assert result.status == inject_mod.INJECTED
    assert ledger.state(key()) == ledger_mod.DONE


def test_an_unchanged_screen_is_still_a_non_reflection(root, ledger):
    """반대편도 지킨다 — 아무 일도 없는 화면이 반영으로 통과하면 안 된다."""
    screen = FakeScreen({"dev-cmd-vault": "이전 대화에서 진행이라고 답했습니다"},
                        echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), require_open=False)
    assert result.reason == inject_mod.NOT_REFLECTED


# -------------------------------------------------- 열림 확인 (002 FU1 항목 38)

def test_a_label_inside_a_longer_word_is_not_an_open_question():
    """**002-N7F가 좁힌 기전의 회귀 테스트.**

    라벨 「진행」이 답변 후 화면 「진행합니다」에 부분 문자열로 걸리면, 답이 들어간
    뒤에도 질문이 열린 것으로 읽혀 반영 확인의 두 번째 눈이 통째로 무력해진다.
    """
    assert inject_mod.question_open(ANSWERED, QUESTION, ["진행"]) is False
    assert inject_mod.question_open(SCREEN, QUESTION, ["진행"]) is True
    # 번호 없는 글머리표 선택지도 열린 것으로 읽는다 — 엄격화가 정상을 잡아먹지 않는다.
    assert inject_mod.question_open("- 진행\n- 중단", None, ["진행"]) is True


def test_the_second_eye_survives_a_late_echo_when_the_choices_are_known(root, ledger):
    """실물이 밟은 경로 — 선택지를 아는 주입에서 에코가 늦어도 **질문 닫힘**으로 읽는다.

    라벨이 부분 문자열로 걸리던 때에는 이 조합이 `not_reflected`로 굳었다.
    """
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=2, after_text=ANSWERED)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION,
                                      choices=["진행", "중단"])
    assert result.status == inject_mod.INJECTED


def test_a_question_not_drawn_yet_is_waited_for_instead_of_aborted(root, ledger):
    """**002-N7 결함 2의 회귀 테스트.** 열림 확인도 여러 장을 본다.

    한 장만 보면 "화면이 아직 안 그려진 것"이 "질문이 닫힌 것"으로 읽혀 `not_open`
    중단이 난다 — 사용자에게는 답이 유실된 것과 구별되지 않는다.
    """
    screen = FakeScreen({"dev-cmd-vault": "작업 중..."}, after_text=ANSWERED)
    real_capture = screen.capture
    shots = {"n": 0}

    def slow(name, lines=None):
        shots["n"] += 1
        if shots["n"] == 2:                      # 두 번째 장에야 질문이 그려진다
            screen.sessions[name] = SCREEN
        return real_capture(name, lines)

    deps = screen.deps()
    deps.capture = slow
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=deps, question=QUESTION, choices=["진행", "중단"])
    assert result.status == inject_mod.INJECTED
    assert shots["n"] >= 2                       # 한 장으로 끝내지 않았다


def test_a_session_that_vanishes_while_waiting_is_stored_not_aborted(root, ledger):
    """열림을 기다리는 사이 대상이 사라지면 중단이 아니라 보관이다 (D7).

    자리에 없는 사람에게 attach 안내를 보내 봐야 답만 잃는다.
    """
    screen = FakeScreen({"dev-cmd-vault": "작업 중..."})
    real_capture = screen.capture

    def vanishing(name, lines=None):
        shot = real_capture(name, lines)
        screen.sessions.pop(name, None)          # 첫 장을 읽자마자 사라진다
        return shot

    deps = screen.deps()
    deps.capture = vanishing
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=deps, question=QUESTION)
    assert (result.status, result.reason) == (inject_mod.STORED, inject_mod.GONE)
    assert ledger.state(key()) is None           # 모호로 남기지 않는다
    assert screen.sent == []


# ------------------------------------------- 응답 표식 (002 FU8) — 파일이 주, 화면이 보조

def question_file(root, session="dev-cmd-vault", generation=2, seq=1):
    """세션이 쓴 질문 파일. 응답 표식은 이 이름 뒤에 붙는다."""
    directory = root / "sessions" / session
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("question-g%d-%02d.json" % (generation, seq))
    path.write_text('{"text": "%s", "question": "%s", "choices": ["진행", "중단"]}'
                    % (QUESTION, QUESTION), encoding="utf-8")
    return path


def mark_answered(question_path):
    """세션이 답을 받아 처리했다고 남기는 표식."""
    marker = question_path.parent / (question_path.name + inject_mod.ANSWERED_SUFFIX)
    marker.write_text('{"ts": 1.0}', encoding="utf-8")
    return marker


def deps_that_mark_on_send(screen, question_path, seen):
    """주입을 받은 세션이 곧바로 표식을 남기는 대역. `seen`에 주입 시점 캡처 수를 적는다."""
    deps = screen.deps()
    inner = deps.send

    def send(name, text):
        ok = inner(name, text)
        seen.append(screen.captures)
        mark_answered(question_path)
        return ok

    deps.send = send
    return deps


def test_the_answered_marker_confirms_reflection_without_reading_the_screen(root, ledger):
    """**표식이 있으면 화면을 보지 않는다.** 에코가 영영 안 와도 정상 주입이 성립한다.

    같은 화면을 화면 판정으로만 보면 `not_reflected`로 굳는다(바로 아래 테스트) —
    갈리는 지점이 표식 하나임을 못 박는다.
    """
    path = question_file(root)
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=99)
    seen = []
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=deps_that_mark_on_send(screen, path, seen),
                                      question=QUESTION, choices=["진행", "중단"],
                                      generation=2, seq=1)
    assert result.status == inject_mod.INJECTED
    assert ledger.state(key()) == ledger_mod.DONE
    assert screen.captures == seen[0]     # 주입 뒤로는 화면을 한 장도 읽지 않았다


def test_without_the_marker_the_decision_falls_back_to_the_screen(root, ledger):
    """**화면 갈래는 남는다.** 세션이 표식을 빠뜨려도 종전 판정이 그대로 선다."""
    question_file(root)
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION,
                                      choices=["진행", "중단"], generation=2, seq=1)
    assert result.reason == inject_mod.NOT_REFLECTED
    assert screen.captures > len(screen.sent)   # 주입 뒤에도 화면을 봤다


def test_an_existing_marker_stops_the_injection_before_it_starts(root, ledger):
    """넣기 전 자리 — 이미 답을 받은 질문에는 두 번째 답을 넣지 않는다.

    표식이 있으면 화면을 보지 않고, 좌표도 장부에 잠그지 않는다.
    """
    mark_answered(question_file(root))
    screen = FakeScreen({"dev-cmd-vault": SCREEN})
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION,
                                      choices=["진행", "중단"], generation=2, seq=1)
    assert result.status == inject_mod.ABORTED
    assert result.reason == inject_mod.NOT_OPEN
    assert screen.sent == []
    assert screen.captures == 0
    assert ledger.state(key()) is None


def test_a_marker_from_before_the_injection_is_not_read_as_reflection(root, ledger):
    """**경계** — 시작부터 붙어 있던 표식은 이번 주입의 증거가 아니다.

    열림 확인이 꺼진 경로(세대가 바뀐 재주입·명령 중계)는 옛 좌표의 표식을 만나는데,
    그것을 반영으로 읽으면 **들어가지 않은 답이 들어갔다고 판정된다.**
    """
    mark_answered(question_file(root))
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=99)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), require_open=False,
                                      generation=2, seq=1)
    assert result.reason == inject_mod.NOT_REFLECTED


def test_an_injection_without_coordinates_never_looks_for_a_marker(root, ledger):
    """좌표는 선택 인자다 — 옛 호출부·우편함 없는 프로젝트는 화면 판정 그대로다."""
    mark_answered(question_file(root))
    screen = FakeScreen({"dev-cmd-vault": SCREEN}, echo_after=2, after_text=ANSWERED)
    result = inject_mod.inject_answer("dev-cmd-vault", "진행", key(), ledger,
                                      deps=screen.deps(), question=QUESTION)
    assert result.status == inject_mod.INJECTED
    assert screen.captures > 0
