"""세션별 우편함의 파일 규약과 청소 (ADR-002 D2).

    sessions/<tmux세션명>/
      notify-<ts_ms>-<rand6>.json   세션이 쓰는 일방 알림 — 텍스트만, 버튼 불허
      notify-<...>.sent             우체부의 발신 완료 표식 — **원본은 건드리지 않는다**
      question-g<세대>-NN.json       세션이 쓰는 텔레그램행 질문
      question-<...>.answered       세션이 쓰는 응답 표식 — 우체부는 **읽기만 한다**
      answer-g<세대>-NN.json         우체부가 쓰는 주입 기록 — **답 도착의 증거가 아니다**
      pending-<ts>.json             우체부가 쓰는 미주입 보관분 — **청소 대상 제외**

**세대 접두(`g<세대>`)를 강제하는 이유**: 지휘 tmux명은 세대 불변(D9)이라 세대가 같은
디렉토리를 공유하는데, 문맥 없는 새 지휘가 NN을 1부터 다시 매기면 **전 세대의 미해결
질문을 덮어쓴다.** 세대 접두가 그 충돌을 이름 수준에서 없앤다.

이 파일이 하는 일은 **경로 규약·미발신 판정·보관·청소**다. 실제로 훑어 발신하고
라우팅하는 배달 계층은 `delivery.py`, 화면에 넣는 절차는 `inject.py`가 맡는다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import re
import time

from postman import addressing
from postman import paths

SENT_SUFFIX = ".sent"

# 세션이 답을 처리했다고 신고하는 표식. 질문 파일 이름 뒤에 붙는다 — 읽는 쪽은 `inject`지만
# **우편함 이름 규약의 단일 출처는 이 파일이다.**
ANSWERED_SUFFIX = ".answered"

NOTIFY_GLOB = "notify-*.json"
QUESTION_GLOB = "question-*.json"
PENDING_GLOB = "pending-*.json"
ANSWERED_GLOB = QUESTION_GLOB + ANSWERED_SUFFIX

DAY = 86400.0

# `question-g<세대>-NN.json` / `answer-g<세대>-NN.json`의 이름 규약 (D2).
# **세대와 일련번호의 정본은 파일 이름이다** — 본문 필드가 이름과 어긋나면 이름을 믿는다.
# 이름이 곧 충돌 회피 장치라, 본문을 믿으면 그 장치가 무력해진다.
_QUESTION_NAME_RE = re.compile(r"\Aquestion-g(?P<generation>\d{1,6})-(?P<seq>\d{1,6})\.json\Z")


def sent_marker(path):
    """발신 완료 표식 경로. 원본 이름 뒤에 붙인다 — 원본을 지우거나 고치지 않는다."""
    return path.parent / (path.name + SENT_SUFFIX)


def is_sent(path):
    return sent_marker(path).exists()


def mark_sent(path, meta=None):
    """표식만 남긴다. 본문은 원본 그대로 둔다 (D2, ADR-001 D1 승계)."""
    marker = sent_marker(path)
    paths.ensure_private_dir(marker.parent)   # 0700 보장은 한 자리에서만 — 여기를 건너뛰면
    paths.atomic_write_json(marker, meta or {"ts": time.time()})   # 0755로 만들어질 수 있다
    return marker


def _glob(session, pattern):
    directory = _mailbox_dir(session)
    if directory is None:
        return []
    try:
        return sorted(p for p in directory.glob(pattern) if not p.name.startswith("."))
    except OSError:
        return []


def _mailbox_dir(name):
    """우편함 경로. **주소 규약을 통과하지 못하면 None** — 경로 조각이 되는 자리다.

    창구 우편함(`counter`)은 tmux명 규칙의 명시 예외라 이름으로 따로 허용한다 (D2).
    """
    if name == paths.COUNTER_MAILBOX:
        return paths.counter_dir()
    if not addressing.is_session_name(name):
        return None
    return paths.sessions_dir() / name


def unsent(session):
    """아직 발신되지 않은 알림·질문 파일(사전순=발급순)."""
    found = []
    for pattern in (NOTIFY_GLOB, QUESTION_GLOB):
        found.extend(p for p in _glob(session, pattern) if not is_sent(p))
    return sorted(found)


def pending(session):
    """미주입 보관분 (D7). 청소가 지우면 D7이 무너지므로 **대상에서 제외**한다."""
    return _glob(session, PENDING_GLOB)


def answered_markers(session):
    """세션이 남긴 응답 표식 파일(사전순). 우체부는 이 파일을 쓰지도 고치지도 않는다."""
    return _glob(session, ANSWERED_GLOB)


def permission_targets():
    """[(라벨, 경로, 요구 권한)] — 자가 점검이 권한을 볼 자리 (우편함 0700 · 응답 표식 0600).

    표식을 쓰는 주체는 세션이라 `mark_sent`의 `ensure_private_dir`를 타지 않는다. **어긋난
    것을 고쳐 쓰지 않고 열거만 한다** — 한 파일에 쓰는 주체는 하나여야 하므로, 처분은
    검출과 통보까지다.
    """
    targets = []
    for name in paths.list_session_mailboxes():
        directory = _mailbox_dir(name)
        if directory is None:
            continue
        targets.append(("우편함 %s/" % name, directory, 0o700))
        for marker in answered_markers(name):
            targets.append(("응답 표식 %s/%s" % (name, marker.name), marker, 0o600))
    return targets


def has_undelivered(sessions=None):
    """어느 우편함에든 미발신 또는 보관분이 남아 있는가 — 유휴 종료의 전제 검사 (D8)."""
    names = sessions if sessions is not None else paths.list_session_mailboxes()
    for name in names:
        if unsent(name) or pending(name):
            return True
    return False


def cleanup(now=None, max_age_days=7.0, live_sessions=(), absent_since=None):
    """`.sent` 표식이 붙고 오래된 알림과, tmux가 오래 부재한 우편함을 치운다 (D2).

    시점은 **기동 시 1회 + 24시간 이상 연속 생존 시 하루 1회**다 — 유휴 종료(D8) 아래에서
    "하루 1회"만 적으면 7일을 사는 우체부가 없어 청소가 영영 안 돈다. 호출 시점 판단은
    `bot.py`가 하고 여기서는 실제 삭제만 한다.

    `pending-*.json`과 창구 우편함(`sessions/counter/`)은 **건드리지 않는다.**
    `absent_since`는 `{세션명: 최초 부재 관측 시각}`이며, 없으면 부재 판정을 하지 않는다
    (모르는 것을 오래됐다고 치지 않는다).
    """
    now = time.time() if now is None else float(now)
    cutoff = now - float(max_age_days) * DAY
    removed = {"notify": 0, "mailboxes": 0}
    live = set(live_sessions or ())
    absent_since = absent_since or {}

    for name in paths.list_session_mailboxes():
        if name == paths.COUNTER_MAILBOX:
            continue        # 창구 우편함은 청소 대상이 아니다 — 통보가 사라지면 안 된다
        directory = _mailbox_dir(name)
        if directory is None:
            continue
        for path in _glob(name, NOTIFY_GLOB):
            marker = sent_marker(path)
            if not marker.exists():
                continue
            try:
                if marker.stat().st_mtime > cutoff:
                    continue
                path.unlink()
                marker.unlink()
            except OSError:
                continue
            removed["notify"] += 1

        if name in live:
            continue
        first_absent = absent_since.get(name)
        if first_absent is None or (now - float(first_absent)) < float(max_age_days) * DAY:
            continue
        if unsent(name) or pending(name):
            continue        # 아직 할 일이 남은 우편함은 치우지 않는다
        try:
            for leftover in directory.iterdir():
                leftover.unlink()
            directory.rmdir()
        except OSError:
            continue
        removed["mailboxes"] += 1
    return removed


# ---------------------------------------------------------------- 질문·답 파일

def parse_question_name(name):
    """`question-g2-03.json` → `(2, 3)`. 규약 밖 이름이면 `(None, None)`."""
    match = _QUESTION_NAME_RE.match(str(name))
    if not match:
        return (None, None)
    return (int(match.group("generation")), int(match.group("seq")))


def find_question(session, generation, seq):
    """그 좌표의 질문 파일 경로. 없으면 None.

    이름을 조립하지 않고 **훑어서 좌표를 맞춘다** — 세션이 `question-g2-3.json`으로 쓸지
    `question-g2-03.json`으로 쓸지는 규약이 정하지 않았고, 조립하면 한쪽에서 못 찾는다.
    """
    if generation is None or seq is None:
        return None
    try:
        want = (int(generation), int(seq))
    except (TypeError, ValueError):
        return None
    for path in _glob(session, QUESTION_GLOB):
        if parse_question_name(path.name) == want:
            return path
    return None


def read_question(session, generation, seq):
    """질문 원문·선택지를 되찾는다 — 주입 직전 **열림 확인의 재료**다 (D1).

    발신 뒤에도 원본을 지우지 않으므로(표식만 남긴다) 하룻밤 뒤 온 답도 이 재료를 얻는다.
    """
    path = find_question(session, generation, seq)
    if path is None:
        return None
    data = paths.read_json(path)
    return data if isinstance(data, dict) else None


def answer_path(session, generation, seq):
    """우체부가 주입 사실을 남기는 자리. 질문과 같은 좌표를 이름에 그대로 쓴다.

    ⚠️ **답 도착의 증거가 아니라 사후 기록이다** (002-N7F ⑤). 주입이 실제로 들어갔어도
    반영 확인이 실패하면 안 써지고(`not_reflected`), 쓰기 자체가 실패해도 예외를 삼킨다
    (`handler._write_answer_record`). **이 파일에 대기를 거는 세션은 영영 안 깨어난다** —
    답 도착의 정본은 대상 세션의 화면이다.
    """
    directory = _mailbox_dir(session)
    if directory is None:
        return None
    return directory / ("answer-g%d-%02d.json" % (int(generation), int(seq)))


def write_answer(session, generation, seq, payload, now=None, **extra):
    """주입 기록. 좌표가 숫자로 서지 않으면 쓰지 않는다 — 이름 규약 밖 파일을 만들지 않는다."""
    try:
        path = answer_path(session, generation, seq)
    except (TypeError, ValueError):
        return None
    if path is None:
        return None
    record = {"ts": time.time() if now is None else float(now),
              "session": session, "generation": int(generation), "seq": int(seq),
              "sent": payload}
    record.update(extra)
    paths.ensure_private_dir(path.parent)
    paths.atomic_write_json(path, record)
    return path


# ---------------------------------------------------------------- 보관분 (D7)

def pending_path(session):
    """`pending-<ts_ms>-<rand6>-answer.json`. 사전순이 곧 보관순이다."""
    directory = _mailbox_dir(session)
    if directory is None:
        return None
    return directory / ("pending-" + paths.mailbox_filename("answer"))


def store_pending(session, record, now=None):
    """미주입 답을 보관한다 (D7의 발신자 보관 책임).

    죽은 주소로의 발신은 **큐잉 없이 즉시 실패하고 보관해 주는 계층이 없다**(002-N2 실측).
    보관 책임이 전적으로 발신자에게 있으므로, 우체부가 받아 둔 답은 우체부가 들고 있는다.
    """
    path = pending_path(session)
    if path is None:
        return None
    payload = dict(record or {})
    payload.setdefault("session", session)
    payload.setdefault("ts", time.time() if now is None else float(now))
    payload.setdefault("attempts", 0)
    paths.ensure_private_dir(path.parent)
    paths.atomic_write_json(path, payload)
    return path


def load_pending(path):
    data = paths.read_json(path)
    return data if isinstance(data, dict) else None


def update_pending(path, **fields):
    """보관 레코드의 일부를 고쳐 쓴다(시도 횟수·보류 표시). 읽지 못하면 아무것도 하지 않는다."""
    data = load_pending(path)
    if data is None:
        return None
    data.update(fields)
    paths.atomic_write_json(path, data)
    return data


def drop_pending(path):
    """전달을 마친 보관분만 지운다."""
    try:
        path.unlink()
    except OSError:
        return False
    return True


def all_pending():
    """[(세션명, 경로)] — 모든 우편함의 보관분. 재주입 순회의 입력이다."""
    found = []
    for name in paths.list_session_mailboxes():
        for path in pending(name):
            found.append((name, path))
    return found


def all_unsent():
    """[(세션명, 경로)] — 모든 우편함의 미발신 알림·질문. 창구 우편함도 포함한다."""
    found = []
    for name in paths.list_session_mailboxes():
        for path in unsent(name):
            found.append((name, path))
    return found


def age(path, now=None):
    """마지막 갱신 뒤 흐른 초. `stat` 실패면 None — 다음 순회에서 다시 본다."""
    now = time.time() if now is None else float(now)
    try:
        return now - path.stat().st_mtime
    except OSError:
        return None
