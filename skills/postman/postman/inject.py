"""답 주입 절차 — 기록 → 열림 확인 → 리터럴 주입 → 반영 확인 (ADR-002 D1·D7).

**우체부가 이 절차 전체를 소유한다.** 지휘 세션에 맡기지 않는 이유는 셋이다(D1).
① 무상태 규정은 "러너가 있다"는 전제 위에 세워졌고 그 소유자가 사라졌다 ② 캡처→주입→
재캡처는 원자적이라 쪼갤 수 없다 — 지휘에 맡기면 **지휘 교체 순간 절차가 반토막 난다**
③ 대안이 더 나쁘다(지휘 자기주입의 자기참조, 별도 데몬의 다섯 번째 참여자 부활).

절차의 순서가 곧 안전장치다.

1. **장부에 의도(intent) 기록** — 기록이 주입에 선행한다(D1). 프로세스가 어디서 죽든
   "넣었을 수도 있다"가 파일에 남는다.
2. **캡처** — 화면을 읽는다. 실패는 대상 소멸일 수 있다.
3. **질문 열림 확인** — 이미 답했거나 세션이 진행했으면 넣지 않는다.
4. **리터럴 주입 + 별도 호출 Enter**
5. **반영 확인** — 들어갔는지 본다.
6. **장부에 완료(done) 기록** — 답은 한 번만 넣는다. 이 2단 기록 덕에 그 불변식이
   **프로세스 경계를 넘어** 유지된다.

**3·5의 판정은 같은 순서를 쓴다: 응답 표식이 1차, 화면이 보조다.** 세션이 답을 처리하고
남긴 `question-….json.answered`가 있으면 화면을 보지 않는다. 표식이 없을 때만 화면으로
내려서고, 거기서는 **한 장으로 가리지 않는다** — 화면 한 장은 "갱신이 늦은 것"과 "질문이
닫힌 것"·"주입이 안 먹은 것"을 못 가른다(001 N12 결함 2·002-N7 결함 2가 그 오판이었다).
그래서 화면 갈래는 양쪽 다 재캡처 3회를 쓴다. 표식은 상대의 협조에 기대므로 **화면 갈래를
걷어내지 않는다** — 세션이 표식을 빠뜨려도 통로는 종전대로 선다.

**실패 처분은 대상의 생사로 가른다**(D1).

| 갈래 | 판정 | 처분 |
|---|---|---|
| 대상이 살아 있는데 반영이 없다 | `not_reflected`·`send_failed` | **중단 + attach 안내** — 화면을 사람이 봐야 한다 |
| ↑ 중 `not_reflected` | **확인 실패이지 전달 실패가 아니다** | 회신에 「전달 실패」를 쓰지 않고, 화면 두 장을 진단 자리에 남긴다 (002-N7F ④) |
| 대상이 절차 도중 소멸했다 | `gone` | **pending 보관(D7)** — attach 안내는 자리에 없는 사람에게 무의미하고, 교체 창이 정확히 이 실패를 만든다 |
| 장부에 done이 있다 | `duplicate` | 아무것도 하지 않는다 |
| 장부에 intent만 있다 | `ambiguous` | **재주입하지 않는다.** 보관하고 사람에게 확인을 청한다 |

**아무것도 넣지 않았음이 확실한 중단은 의도 기록을 되돌린다**(`ledger.release`) — 그러지
않으면 그 좌표가 영구히 모호로 남아 같은 질문에 다시 답할 수 없다. 되돌리는 자리는
네 곳뿐이고(캡처 실패·열림 확인 중 소멸·질문 닫힘·전송 실패 + 대상 소멸 확인) **`send-keys`를 부른 뒤에는
어떤 이유로도 되돌리지 않는다.**

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import re
import time

from postman import ledger as ledger_mod
from postman import mailbox
from postman import tmuxq

log = logging.getLogger("postman.inject")

# 재캡처 횟수. 한 장으로는 "화면이 늦은 것"과 "안 먹은 것"을 못 가른다 (N12 결함 2).
SETTLE_TRIES = 3
SETTLE_INTERVAL = 2.0

# 결과 상태.
INJECTED = "injected"     # 화면에 반영된 것을 확인했다
ABORTED = "aborted"       # 대상은 살아 있다 — 중단하고 attach를 안내한다
STORED = "stored"         # 대상이 없거나 사라졌다 — 보관한다 (D7)
SKIPPED = "skipped"       # 이미 넣었다 — 답은 한 번만 들어간다

# 사유.
NOT_OPEN = "not_open"
SEND_FAILED = "send_failed"
NOT_REFLECTED = "not_reflected"
GONE = "gone"
AMBIGUOUS = "ambiguous"
DUPLICATE = "duplicate"

# 세션이 답을 받아 처리했다고 신고하는 표식. 질문 파일 이름 뒤에 붙인다(`.sent`와 같은 자리).
ANSWERED_SUFFIX = ".answered"

# 화면에서 선택지 번호를 읽는 눈 (ADR-001 승계). 앞에 커서·글머리표가 붙어도 읽는다.
_CHOICE_RE = r"^[^\S\n]*[>❯\-\*]?[^\S\n]*(\d+)[.)][^\S\n]*%s[^\S\n]*$"

# 라벨이 **선택지 줄로 서 있는가**. 번호는 있어도 없어도 되지만 줄은 라벨에서 끝나야 한다.
_LABEL_LINE_RE = r"^[^\S\n]*[>❯\-\*•]?[^\S\n]*(?:\d+[.)][^\S\n]*)?%s[^\S\n]*$"


class InjectResult(object):
    """`status` + `reason`. 호출자는 이 둘만 보고 회신·보관을 정한다.

    **중단(`ABORTED`)에는 화면 두 장을 함께 싣는다** (002-N7F ④). 사유 문자열만으로는
    "대상이 바빴다"와 "판정이 못 알아봤다"를 사후에 가를 수 없기 때문이다. 여기 실린
    캡처는 **아직 관문을 지나지 않은 원문**이라, 파일·발신 어디로든 내보내는 쪽이
    `masking`을 통과시킬 책임을 진다(`handler._keep_capture`).
    """

    def __init__(self, status, reason=None, payload=None, detail="", before=None, after=None):
        self.status = status
        self.reason = reason
        self.payload = payload
        self.detail = detail
        self.before = before
        self.after = after

    @property
    def ok(self):
        return self.status == INJECTED

    def __repr__(self):
        return "InjectResult(%r, %r)" % (self.status, self.reason)


class Deps(object):
    """외부에 닿는 손. 테스트는 여기를 갈아끼워 **`tmux`를 실호출하지 않는다.**"""

    def __init__(self, has_session=None, capture=None, send=None, sleep=None, now=None,
                 settle=SETTLE_INTERVAL, tries=SETTLE_TRIES):
        self.has_session = has_session or tmuxq.has_session
        self.capture = capture or tmuxq.capture
        self.send = send or tmuxq.send_literal
        self.sleep = sleep or time.sleep
        self.now = now or time.time
        self.settle = float(settle)
        self.tries = int(tries)


# ---------------------------------------------------------------- 응답 표식

def answered_marker(session, generation, seq):
    """그 좌표의 응답 표식 경로. 질문 파일이 없거나 좌표가 서지 않으면 None.

    질문 파일 이름 뒤에 붙이므로 **이름을 조립하지 않는다** — 좌표에 해당하는 질문 파일을
    찾아 그 이름에 접미사만 얹는다(`mailbox.find_question`과 같은 이유: `-3`으로 쓸지
    `-03`으로 쓸지를 규약이 정하지 않았다).
    """
    if generation is None or seq is None:
        return None
    path = mailbox.find_question(session, generation, seq)
    if path is None:
        return None
    return path.parent / (path.name + ANSWERED_SUFFIX)


def answered(session, generation, seq):
    """세션이 그 질문의 답을 받아 처리했다고 신고했는가.

    **답 반영 판정의 1차 근거다.** 화면 한 장은 "늦은 것"과 "안 먹은 것"을 못 가르지만
    표식은 세션 자신이 남긴 사실이라 흐려지지 않는다. 다만 **상대의 협조에 기대므로**
    없다고 답이 안 들어간 것은 아니다 — 없으면 화면 판정으로 내려선다. 좌표를 모르는
    호출자(옛 호출부·명령 중계)와 우편함이 없는 프로젝트에서는 항상 False다.
    """
    try:
        marker = answered_marker(session, generation, seq)
        return marker is not None and marker.exists()
    except (OSError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 화면 판독

def question_open(capture, question, choices=None):
    """화면에 그 질문이 아직 열려 있는가. 본문 한 줄 또는 선택지 라벨로 본다.

    **주입 가능성 확인이지 내용 해석이 아니다**(D1의 경계 문구) — 무엇을 넣을지는
    여기서 정하지 않는다.

    라벨은 **줄 형태로 서 있을 때만** 읽는다. 부분 문자열 포함을 열림으로 치면 라벨
    「진행」이 답을 받은 뒤의 화면 「진행합니다」에 걸려 **답이 들어간 뒤에도 질문이
    열린 것으로 판정된다**(002-N7F가 실물로 밟았다). 그러면 반영 확인의 두 번째 눈
    (`not question_open(after)`)이 통째로 무력해져 화면 에코가 유일한 눈으로 남고,
    에코가 늦은 정상 주입이 `not_reflected`로 굳는다.
    """
    text = capture or ""
    for label in (choices or []):
        label = str(label or "").strip()
        if label and re.search(_LABEL_LINE_RE % re.escape(label), text, re.MULTILINE):
            return True
    for line in str(question or "").splitlines():
        line = line.strip()
        if len(line) >= 4 and line in text:
            return True
    return False


def choice_number(capture, label):
    """화면에서 그 라벨의 선택지 번호를 **정확히** 식별했을 때만 그 번호. 아니면 None.

    라벨 리터럴 입력이 기본이고 번호는 예외다(D1) — 후보가 둘 이상이면 포기한다.
    엉뚱한 번호를 넣으면 세션이 다른 갈래로 확정해 버린다.
    """
    if not capture or not label:
        return None
    found = re.findall(_CHOICE_RE % re.escape(str(label)), capture, re.MULTILINE)
    unique = sorted(set(found))
    return unique[0] if len(unique) == 1 else None


# ---------------------------------------------------------------- 절차

def inject_answer(session, answer, key, ledger, deps=None, question=None, choices=None,
                  require_open=True, generation=None, seq=None):
    """한 답을 한 세션에 넣는다. `InjectResult`를 돌려준다 — 예외를 올리지 않는다.

    `require_open=False`는 **세대가 바뀐 재주입**과 명령 중계에 쓴다(D7) — 새 지휘 화면에
    그 질문이 열려 있을 수 없으므로 열림 확인을 요구하지 않는다. 이때 반영 판정은
    "넣은 문자열이 새로 나타났는가" 하나로만 한다.

    `generation`·`seq`는 **질문 파일의 좌표**(발급 세대·일련번호)다. 주면 그 옆의 응답
    표식을 열림 확인과 반영 확인 양쪽의 1차 근거로 읽고, 안 주면 종전대로 화면만 본다 —
    선택 인자인 것이 의도다. 표식 유무는 **절차 시작 시점에 한 번 기억한다**: 시작부터
    붙어 있던 표식(옛 세대의 답 등)을 이번 주입의 반영으로 읽으면 안 들어간 답이
    들어갔다고 판정된다.
    """
    deps = deps or Deps()
    answer = "" if answer is None else str(answer)

    state = ledger.state(key)
    if state == ledger_mod.DONE:
        return InjectResult(SKIPPED, DUPLICATE, detail="이미 전달한 답이다")
    if state == ledger_mod.INTENT:
        # 넣었는지 알 수 없다. 화면 상태는 파일 복구로 되돌릴 수 없으므로 재주입하지 않는다.
        return InjectResult(STORED, AMBIGUOUS,
                            detail="이전 주입이 완료 기록 없이 끊겼다 — 사람 확인이 필요하다")

    # **파일이 주, 화면이 보조다.** 표식이 있으면 세션이 이미 답을 받아 처리한 것이므로
    # 화면을 볼 것도 없이 넣지 않는다 — 지금 열려 있는 것은 그 질문이 아니다.
    answered_before = answered(session, generation, seq)
    if require_open and answered_before:
        return InjectResult(ABORTED, NOT_OPEN,
                            detail="질문에 응답 표식이 붙어 있다 — 세션이 이미 답을 받았다")

    if not deps.has_session(session):
        return InjectResult(STORED, GONE, detail="대상 세션이 없다")

    if not ledger.begin(key, now=deps.now()):
        # 같은 좌표가 방금 다른 경로로 기록됐다. 두 번 넣지 않는다.
        return InjectResult(SKIPPED, DUPLICATE)

    # **열림 확인도 화면을 여러 장 본다.** 한 장으로는 "화면 갱신이 늦은 것"과 "질문이
    # 정말 닫힌 것"을 가릴 수 없다 — 반영 확인이 재캡처 3회를 쓰는 것과 같은 이유이고,
    # 002-N7 결함 2의 `not_open` 중단이 정확히 이 오판이었다. 첫 장에 보이면 기다리지
    # 않으므로 정상 경로의 속도는 그대로다.
    before = None
    opened = not require_open
    vanished = False
    for attempt in range(deps.tries):
        if attempt:
            deps.sleep(deps.settle)
        shot = deps.capture(session)
        if shot is None:
            if not deps.has_session(session):
                vanished = True          # 대상이 사라졌다 — 보관 갈래로 합류한다 (D7)
                break
            continue                     # 살아 있는데 못 읽었다 — 다시 본다
        before = shot
        if opened or question_open(shot, question, choices):
            opened = True
            break

    if before is None:
        ledger.release(key)              # 캡처 단계 — 화면에 아무것도 넣지 않았다
        return InjectResult(STORED, GONE, detail="주입 직전 캡처가 실패했다")

    if vanished and not opened:
        ledger.release(key)              # 역시 아무것도 넣지 않았다
        return InjectResult(STORED, GONE, detail="열림 확인 도중 대상 세션이 사라졌다")

    if not opened:
        ledger.release(key)              # 확인 단계 — 역시 아무것도 넣지 않았다
        return InjectResult(ABORTED, NOT_OPEN, before=before,
                            detail="주입 직전 화면 %d장에 질문이 없다 — 이미 답했거나 "
                                   "세션이 진행했다" % deps.tries)

    payload = choice_number(before, answer) or answer

    if not deps.send(session, payload):
        if not deps.has_session(session):
            # 절차 도중 소멸했다. 화면이 통째로 사라졌으므로 들어간 것도 없다 (D7 합류).
            ledger.release(key)
            return InjectResult(STORED, GONE, payload=payload,
                                detail="주입 도중 대상 세션이 사라졌다")
        # 살아 있는데 실패했다 — 일부가 들어갔을 수 있으므로 **의도를 남긴 채** 중단한다.
        return InjectResult(ABORTED, SEND_FAILED, payload=payload, before=before,
                            detail="send-keys가 실패했다")

    reflected = False
    last_after = None            # 마지막으로 실제로 읽힌 화면. 중단 진단의 뒷장이다.
    for attempt in range(deps.tries):
        if attempt:
            deps.sleep(deps.settle)
        # 표식을 먼저 본다. 새로 붙었으면 화면은 보지 않는다 — 화면 에코가 늦어 정상
        # 주입이 `not_reflected`로 굳는 갈래가 여기서 끊긴다 (002-N7 실물 2건).
        if not answered_before and answered(session, generation, seq):
            reflected = True
            break
        after = deps.capture(session)
        if after is None:
            if not deps.has_session(session):
                # 넣은 뒤 사라졌다. 들어갔는지 알 수 없으니 **의도를 남긴 채** 보관한다.
                return InjectResult(STORED, GONE, payload=payload,
                                    detail="주입 직후 대상 세션이 사라졌다")
            continue
        last_after = after
        # **등장 횟수가 늘었는가**로 본다. `payload in after`만 보면 번호를 넣은 경우 그
        # 숫자가 선택지 목록에 이미 있어 아무 일도 없는 화면이 반영으로 오판되고,
        # 거꾸로 `payload not in before`를 요구하면 **스크롤백에 같은 낱말("네"·"확인")이
        # 떠 있다는 이유만으로 정상 주입이 미반영으로 오판된다.** 뒤쪽 오판은 열림 확인이
        # 꺼진 경로(`require_open=False`)에 두 번째 눈이 없어 그대로 굳는다.
        reflected = after.count(payload) > before.count(payload)
        if not reflected and require_open:
            reflected = not question_open(after, question, choices)
        if reflected:
            break

    if not reflected:
        # **전달 실패가 아니라 확인 실패다** (002-N7F ④). `send-keys`가 성공한 뒤의
        # 상태라 "들어갔는데 못 알아봤다"가 실재하는 갈래이고, 002-N7에서 실제로 그
        # 갈래가 났다. 화면 두 장을 실어 보내 사후에 원인을 가릴 수 있게 한다.
        return InjectResult(ABORTED, NOT_REFLECTED, payload=payload,
                            before=before, after=last_after,
                            detail="주입 후 재캡처 %d회에 반영을 확인하지 못했다" % deps.tries)

    ledger.complete(key, now=deps.now())
    return InjectResult(INJECTED, payload=payload)


def attach_hint(session):
    """중단 회신에 붙이는 안내. 사람이 화면을 봐야 풀리는 상태다."""
    return "화면을 직접 확인해 주세요: tmux attach -t %s" % session
