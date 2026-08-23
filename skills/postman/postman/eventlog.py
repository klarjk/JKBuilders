"""우체부 자기 증언 — `log/postman-YYYYMMDD.jsonl` (ADR-002 D2).

**이벤트 메타만 남긴다. 본문은 기록하지 않는다.** 수신·주입 intent/done·발신·억제·halt가
언제 무엇에 대해 일어났는지만 적는다.

001의 근거("본문 원본은 노드 파일·러너 기록이 맡는다")에서 러너 기록이 사라졌으므로 002의
근거를 다시 세운다: **본문 원본은 우편함 파일(notify·question·answer·pending)이 맡되 7일
청소 전까지이고, 판단·결과의 영속 기록은 git의 DEV_PLAN·노드 문서다.** 7일이 지난 본문은
소실될 수 있다 — 로그 보존(14일)보다 짧은 이 창은 수용한다. 자기 증언의 대상은 **우체부의
행동**이지 본문 전문이 아니다.

기록이 실패해도 예외를 올리지 않는다 — 로그가 없다고 통로가 멈추면 안 된다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import json
import os
import time

from postman import paths

# 본문이 실릴 수 있는 자리. 실수로 넘어와도 여기서 떨군다 — 관문을 못 지난 문자열이
# 파일로 새는 유일한 경로가 로그다.
_BODY_FIELDS = ("text", "body", "answer", "capture", "choice", "message")

MAX_AGE_DAYS = 14.0


def log_path(now=None):
    stamp = time.localtime(time.time() if now is None else float(now))
    return paths.log_dir() / ("postman-%s.jsonl" % time.strftime("%Y%m%d", stamp))


def record(event, now=None, **fields):
    """이벤트 한 줄. 본문 자리는 길이만 남기고 값은 버린다."""
    now = time.time() if now is None else float(now)
    entry = {"ts": now, "event": event}
    for key, value in fields.items():
        if key in _BODY_FIELDS:
            entry[key + "_len"] = len(value) if isinstance(value, str) else None
            continue
        entry[key] = value
    path = log_path(now)
    try:
        paths.ensure_private_dir(path.parent)
        # **권한이 생성에 선행한다.** 만든 뒤에 `chmod`를 걸면 새 파일이 그 사이 umask
        # 기본 권한으로 존재한다 — 본문 길이·좌표가 실리는 파일에 남길 창이 아니다.
        # `O_CREAT`의 mode는 umask가 비트를 빼기만 하므로 0600보다 넓어지지 않는다.
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)         # 옛 실행이 남긴 넓은 파일도 여기서 조인다
        except OSError:
            pass
        try:
            fp = os.fdopen(fd, "a", encoding="utf-8")
        except OSError:
            os.close(fd)
            raise
        with fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # 인코딩 불가 문자(단독 서로게이트 등)가 섞이면 터지는 자리는 `json.dumps`가 아니라
    # `fp.write`이고, 그 예외는 `UnicodeError` 계열이라 `OSError`에 걸리지 않는다.
    # 모듈 머리말의 약속("기록이 실패해도 예외를 올리지 않는다")은 이 경로에도 걸린다.
    except (OSError, UnicodeError):
        return None
    return path


def cleanup(now=None, max_age_days=MAX_AGE_DAYS):
    """14일 지난 로그 파일을 지운다. 지운 개수."""
    now = time.time() if now is None else float(now)
    cutoff = now - float(max_age_days) * 86400.0
    removed = 0
    try:
        entries = list(paths.log_dir().iterdir())
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
