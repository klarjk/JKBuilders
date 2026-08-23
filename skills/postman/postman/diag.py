"""중단 진단 — 주입이 중단된 순간의 화면을 `diag/`에 남긴다 (002-N7F ④).

**왜 남기는가.** 002-N7 인수 시험에서 `not_reflected` 2건이 났고, 그 답들은 **실제로는
화면에 들어가 있었다.** 그런데 캡처를 보존하지 않아 "대상이 바빠 화면이 늦었다"와
"반영 판정이 못 알아봤다"를 끝내 가르지 못했다. 사유 문자열만으로는 못 가른다 — 가르는
재료는 그 순간의 화면 두 장(`before`·`after`)뿐이다.

**마스킹 관문을 반드시 지난다.** 여기 실리는 것은 남의 세션 화면 원문이라 시크릿이 섞일
수 있다. "관문을 통과하지 않는 경로를 새로 만들지 않는다"(D2)는 발신뿐 아니라 **파일로
나가는 이 자리에도 그대로 걸린다.** `never_send`는 호출자가 설정에서 실어 준다 —
`sender.Sender`가 같은 값을 같은 방식으로 받는다.

**실패해도 예외를 올리지 않는다.** 진단을 못 남겼다고 중단 회신까지 사라지면 사용자는
답이 어떻게 됐는지조차 듣지 못한다 — `handler._write_answer_record`가 같은 이유로 예외를
삼키는 것과 같은 원칙이다.

보존 창은 이벤트 로그(`eventlog.py`)와 같은 14일이고, 봇의 청소 주기가 그 값을 실어 준다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import os
import re
import time

from postman import masking
from postman import paths

log = logging.getLogger("postman.diag")

MAX_AGE_DAYS = 14.0

# 파일 이름에 실리는 사유. 우체부가 정한 열거형만 오지만, 이름은 곧 경로 조각이라
# 값을 믿지 않고 한 번 걸러 쓴다 (주소 규약과 같은 태도).
_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def save(session, reason, before=None, after=None, generation=None, seq=None,
         never_send=(), now=None):
    """중단 한 건의 진단 파일. 경로 또는 None. **예외를 올리지 않는다.**

    **레코드 조립까지 통째로 감싼다.** 시각 변환(`float`·`localtime`)도 마스킹도 예외를
    올릴 수 있고, 그것이 밖으로 새면 `handler._keep_capture`를 타고 올라가 **중단 회신
    자체가 사라진다** — 진단을 남기려다 통보를 죽이는 꼴이다. 그래서 예외 종류를 열거해
    좁히지 않는다: 목록에서 하나 빠질 때마다 같은 사고가 되돌아온다.

    **정체는 종류 이름과 터진 자리(파일:줄)만 로그에 남긴다.** 이 로그는 관문 밖으로
    나가는 파일이고, 예외 문구와 스택에는 **관문을 못 지난 화면 조각**이 섞인다 — 디코딩
    계열 예외는 문제가 된 바이트를 메시지에 그대로 싣는다. 그래서 `exc_info`도
    `str(exc)`도, `traceback.format_exc` 같은 문자열 변환도 여기에 넣지 않는다. 종류와
    자리는 **소스 위치일 뿐 실행 중 값이 아니라** 화면이 섞일 여지가 없으면서,
    마스킹에서 터졌는지 경로 조립에서 터졌는지는 그 둘로 갈린다.

    실패는 언제나 **파일이 아예 안 써짐**이다. 마스킹이 터졌을 때 원문을 대신 남기는
    폴백은 없다 — 관문을 못 지난 화면은 디스크에도 올리지 않는다 (D2).
    """
    try:
        stamp = time.time() if now is None else float(now)
        record = {
            "ts": stamp,
            "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp)),
            "session": session,
            "generation": generation,
            "seq": seq,
            "reason": reason,
            "before": _masked(before, never_send),
            "after": _masked(after, never_send),
        }
        directory = paths.ensure_private_dir(paths.diag_dir())
        path = directory / ("capture-" + paths.mailbox_filename(_kind(reason)))
        paths.atomic_write_json(path, record, indent=2)
    except Exception as exc:
        log.info("중단 진단 캡처를 남기지 못했다 (%s / %s at %s) — 중단 회신은 그대로 나간다",
                 reason, type(exc).__name__, _where(exc))
        return None
    return path


def cleanup(now=None, max_age_days=MAX_AGE_DAYS):
    """보존 창이 지난 진단 파일을 지운다. 지운 개수 — 이벤트 로그와 같은 방식이다."""
    now = time.time() if now is None else float(now)
    cutoff = now - float(max_age_days) * 86400.0
    removed = 0
    try:
        entries = list(paths.diag_dir().iterdir())
    except OSError:
        return 0
    for path in entries:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _masked(capture, never_send):
    """캡처 한 장. **관문을 지나지 않은 문자열은 이 파일에 실리지 않는다.**"""
    if capture is None:
        return None
    return masking.mask(str(capture), never_send or ())


def _where(exc):
    """예외가 터진 **가장 안쪽** 자리 — `<파일이름>:<줄>`. 값은 한 톨도 싣지 않는다.

    줄 번호만으로는 `masking.py`의 것인지 `paths.py`의 것인지 못 가려 정작 알고 싶은
    갈림(마스킹이냐 경로 조립이냐)이 서지 않으므로 파일 이름을 붙인다. 디렉토리는
    떼어낸다 — 로그가 알아야 할 것은 어느 모듈인가지 이 기계의 경로가 아니다.
    """
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is None:
        return "?"
    return "%s:%s" % (os.path.basename(tb.tb_frame.f_code.co_filename), tb.tb_lineno)


def _kind(reason):
    kind = _SAFE_RE.sub("", str(reason or ""))
    return kind or "abort"
