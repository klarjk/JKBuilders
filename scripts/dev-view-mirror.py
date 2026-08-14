#!/usr/bin/env python3
"""dev-view.sh의 미러 pane 본체 — tmux 세션 화면을 스냅샷으로 폴링해 그대로 비춘다.

원본 세션 폭이 미러 pane보다 넓으면 줄이 접혀 화면이 깨지므로,
ANSI 색 시퀀스는 보존하면서 표시 폭 기준으로 각 줄을 잘라낸다
(한글·전각 문자는 2칸으로 센다).
"""

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def clip(line: str, limit: int) -> str:
    """표시 폭이 limit을 넘지 않도록 자른다. ANSI 시퀀스는 폭 0으로 통과시킨다."""
    out = []
    width = 0
    pos = 0
    for m in ANSI.finditer(line):
        for ch in line[pos:m.start()]:
            w = char_width(ch)
            if width + w > limit:
                return "".join(out) + "\x1b[0m"
            out.append(ch)
            width += w
        out.append(m.group())
        pos = m.end()
    for ch in line[pos:]:
        w = char_width(ch)
        if width + w > limit:
            return "".join(out) + "\x1b[0m"
        out.append(ch)
        width += w
    return "".join(out)


TMUX = os.environ.get("DEV_VIEW_TMUX") or shutil.which("tmux") or "tmux"


def run(args):
    """tmux 호출. 바이너리를 못 찾거나 소켓 오류면 None — pane이 죽지 않게 흡수한다."""
    try:
        return subprocess.run([TMUX, *args], capture_output=True, text=True)
    except OSError:
        return None


def capture(session: str):
    r = run(["capture-pane", "-pet", f"{session}:"])
    return r.stdout if (r is not None and r.returncode == 0) else None


def session_alive(session: str) -> bool:
    r = run(["has-session", "-t", f"={session}"])
    return r is not None and r.returncode == 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: dev-view-mirror.py <tmux-session> [interval]", file=sys.stderr)
        return 2
    session = sys.argv[1]
    try:
        interval = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    except ValueError:
        interval = 1.0
    interval = max(interval, 0.1)

    sys.stdout.write("\x1b[?25l")  # 커서 숨김
    alive = True
    last_size = None
    try:
        while True:
            snapshot = capture(session)
            if snapshot is None:
                # 캡처 실패가 곧 세션 종료는 아니다 — 일시적 오류면 다음 주기에 다시 시도한다.
                if alive and not session_alive(session):
                    alive = False
                    sys.stdout.write(
                        f"\x1b[H\x1b[1;33m[{session}] 세션 종료됨 — 마지막 화면\x1b[0m\x1b[K\n"
                    )
                    sys.stdout.flush()
                time.sleep(interval)
                continue
            alive = True
            try:
                cols, rows = os.get_terminal_size()
            except OSError:
                cols, rows = 80, 24
            cols, rows = max(cols, 1), max(rows, 1)
            lines = snapshot.split("\n")[-rows:]
            # pane 크기가 바뀌면 접힌 잔상이 남으므로 한 번 비운다.
            buf = ["\x1b[2J"] if (cols, rows) != last_size else []
            last_size = (cols, rows)
            buf.append("\x1b[H")
            for line in lines:
                buf.append(clip(line, cols) + "\x1b[K\n")
            buf.append("\x1b[J")
            sys.stdout.write("".join(buf))
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
