#!/usr/bin/env python3
"""상태줄 기록기 — 클로드가 상태줄에 넘기는 JSON을 세션별 파일로 남긴다.

`/dev-loop`의 **지휘 세션은 자기 컨텍스트 포화도를 스스로 재서** 임계에 닿으면 교체를
요청한다. 그 계측의 유일한 재료가 `~/.claude/status/<session_id>.json`이고, 이 파일을
만드는 것은 클로드가 아니라 **사용자의 상태줄 명령**이다. 상태줄이 이 파일을 쓰지
않으면 지휘는 자기 포화도를 못 재고, 못 재는 지휘는 교체 시점을 놓친다.

머신의 모든 클로드 세션이 상태줄 명령 하나를 공유하므로 기록 파일은 반드시
`session_id`로 가른다.

## 쓰는 법 — 두 가지

**① 상태줄이 아직 없다면** 이 파일을 그대로 상태줄 명령으로 지정한다. 기록과 함께
모델·컨텍스트·디렉토리를 한 줄로 찍는다.

    // ~/.claude/settings.json
    {"statusLine": {"type": "command",
                    "command": "python3 ~/.claude/scripts/status-writer.py"}}

**② 이미 쓰는 상태줄 스크립트가 있다면** 그 스크립트 맨 앞(표준입력을 읽기 **전**)에
아래 네 줄을 얹는다. 표준입력을 대신 읽어 기록하고 같은 내용을 되돌려 놓으므로,
기존 스크립트는 평소대로 payload를 받는다 — 텍스트로 읽든(`sys.stdin.read()`)
바이트로 읽든(`sys.stdin.buffer.read()`) 둘 다 그대로 동작한다.

    import sys, os
    sys.path.insert(0, os.path.expanduser("~/.claude/scripts"))
    import importlib
    importlib.import_module("status-writer").tap_stdin()

## 원칙

**이 모듈은 어떤 경우에도 예외를 밖으로 내지 않는다.** 상태줄이 깨지면 모든 세션의
화면이 깨진다 — 관측은 그보다 덜 중요하다.

시스템 파이썬(3.9)에서 실행될 수 있으므로 3.9 문법만 쓴다.
"""
import io
import json
import os
import re
import sys
import tempfile

STATUS_DIR = os.path.join(os.path.expanduser("~"), ".claude", "status")
_SAFE_ID = re.compile(r"\A[0-9a-zA-Z._-]{1,128}\Z")


def _safe_session_id(value):
    """파일명이 될 값이므로 경로 조작 문자를 통과시키지 않는다."""
    if isinstance(value, str) and _SAFE_ID.match(value) and value not in (".", ".."):
        return value
    return "unknown"


def _atomic_write_json(path, data):
    """같은 디렉토리에 임시 파일로 쓴 뒤 rename한다 — 읽는 쪽이 반쪽 파일을 보지 않게."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(data):
    """payload를 `~/.claude/status/<session_id>.json`에 원자적으로 남긴다.

    반환값은 성공 여부(bool) — 호출자는 무시해도 된다. 예외는 절대 올리지 않는다.
    """
    try:
        session_id = _safe_session_id((data or {}).get("session_id"))
        _atomic_write_json(os.path.join(STATUS_DIR, session_id + ".json"), data)
        return True
    except Exception:
        return False


def tap_stdin():
    """표준입력을 대신 읽어 기록하고, 같은 내용을 표준입력에 되돌려 놓는다.

    되돌려 놓기를 기록보다 **먼저** 한다 — 기록이 실패해도 상태줄 본체는 평소대로
    payload를 받는다. 반환값은 파싱된 payload(실패하면 `None`).

    **되돌려 놓는 것은 `StringIO`가 아니라 `TextIOWrapper`다.** ②번 방식으로 얹는
    기존 스크립트가 `sys.stdin.buffer.read()`로 원시 바이트를 읽을 수도 있는데,
    `StringIO`에는 `buffer`가 없어 그 스크립트가 `AttributeError`로 죽는다 — 이 도구가
    막으려던 사고를 이 도구가 일으키는 셈이다. `TextIOWrapper`는 텍스트 읽기와
    `.buffer` 양쪽을 모두 준다.
    """
    try:
        source = getattr(sys.stdin, "buffer", None)
        raw = source.read() if source is not None else sys.stdin.read().encode("utf-8")
    except Exception:
        return None
    try:
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    except Exception:
        pass
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    record(data)
    return data


def _line(data):
    """단독 실행 시 찍는 최소 상태줄. 모델 · 컨텍스트 사용률 · 현재 디렉토리."""
    model = (data.get("model") or {}).get("display_name") or "claude"
    used = (data.get("context_window") or {}).get("used_percentage")
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or ""
    parts = [model]
    if isinstance(used, (int, float)):
        parts.append("%.0f%%" % used)
    if cwd:
        parts.append(os.path.basename(cwd.rstrip("/")) or cwd)
    return "  ".join(parts)


def main():
    data = tap_stdin()
    if data is None:
        return 0
    try:
        sys.stdout.write(_line(data))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
