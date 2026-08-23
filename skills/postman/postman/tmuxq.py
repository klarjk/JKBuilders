"""tmux 조회와 화면 조작 — 주소 확인·캡처·리터럴 주입 (ADR-002 D1·D8·D9).

**우체부가 tmux 주입 절차 전체를 소유한다**(D1). 이 파일은 그 절차가 쓰는 손이고,
절차 자체(장부 2단 기록·질문 열림 확인·재캡처 3회)는 `inject.py`가 짠다. 여기 있는
함수 하나하나는 판단하지 않는다 — 시키는 대로 화면을 읽고 문자열을 넣는다.

**`send-keys -l`과 Enter를 한 호출로 합치지 않는다**(ADR-001 D6 승계). 합치면 리터럴
모드가 깨져 본문이 키 이름으로 해석된다.

**캡처 실패(None)와 빈 화면(`""`)을 가른다.** 001은 둘 다 `""`로 돌려줬고 그 자리에서는
판정이 "질문이 안 열렸다" 하나뿐이라 괜찮았지만, 002는 **대상 소멸(보관)과 미반영(중단)**
을 갈라야 한다(D1의 실패 갈래·D7).

외부 명령은 `run=` 인자로 주입 가능하다. **테스트는 `tmux`를 실호출하지 않는다.**

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import subprocess

from postman import addressing

DEFAULT_TIMEOUT = 20

# 판정용 캡처 폭. 발신문에 실을 때 마지막 40줄로 줄이는 것(`masking.truncate_capture`)과는
# 목적이 다르다 — 이쪽은 "질문이 아직 열려 있나"를 보는 눈이라 조금 넓게 본다.
CAPTURE_LINES = 80


def run_command(argv, timeout=DEFAULT_TIMEOUT):
    """외부 명령 실행 기본 구현. 테스트는 `run=`으로 가짜를 넣어 이 함수를 타지 않는다."""
    return subprocess.run(
        list(argv), timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def list_sessions(run=None):
    """살아 있는 tmux 세션명. tmux가 없거나 서버가 안 떠 있으면 빈 목록."""
    run = run or run_command
    try:
        proc = run(["tmux", "list-sessions", "-F", "#{session_name}"])
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def has_session(name, run=None):
    """그 이름의 세션이 실재하는가. **이름 규약(D9)을 통과하지 못하면 무조건 False.**

    실패문의 "Did you mean" 대안을 따르지 않는 것과 같은 원칙이다 — 대상 판별은 이름
    문자열 하나로만 하고, 비슷한 이름으로 갈아타지 않는다(오배송 차단, D9).
    """
    if not addressing.is_session_name(name):
        return False
    run = run or run_command
    try:
        proc = run(["tmux", "has-session", "-t", name])
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def kill(name, run=None):
    """세션을 멈춘다 — `halt` 명령의 실행부 (D2).

    조회 전용 파일에 **유일하게** 들어 있는 쓰기 조작이다. 그럼에도 주입 계층이 아니라
    여기 두는 이유: 이것은 화면에 무엇을 넣는 절차가 아니라 프로세스를 세우는 한 수이고,
    `bypassPermissions`로 머지·커밋하는 무인 지휘를 **사용자가 멈출 유일한 수단**이라
    코어(폴링·명령)와 생사를 같이해야 한다.
    """
    if not addressing.is_session_name(name):
        return False
    run = run or run_command
    try:
        proc = run(["tmux", "kill-session", "-t", name])
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def capture(name, lines=CAPTURE_LINES, run=None):
    """화면을 읽는다. **실패는 `None`, 빈 화면은 `""`.**

    둘을 섞으면 절차가 갈래를 못 고른다 — 대상이 사라진 것이면 보관(D7)이고, 살아 있는데
    반영이 없는 것이면 중단·attach 안내다(D1).
    """
    if not addressing.is_session_name(name):
        return None
    run = run or run_command
    argv = ["tmux", "capture-pane", "-p", "-t", name]
    if lines:
        argv += ["-S", "-%d" % int(lines)]
    try:
        proc = run(argv)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "") if proc.returncode == 0 else None


def send_literal(name, text, run=None):
    """본문을 리터럴로 넣고 **별도 호출로** Enter를 친다 (ADR-001 D6 승계).

    `--`를 붙이는 이유: 본문이 `-`로 시작하면 tmux가 그것을 옵션으로 읽는다.
    """
    if not addressing.is_session_name(name):
        return False
    run = run or run_command
    try:
        proc = run(["tmux", "send-keys", "-t", name, "-l", "--", text])
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return press_enter(name, run=run)


def press_enter(name, run=None):
    """Enter만 친다. 본문 주입과 **합치지 않는다.**"""
    if not addressing.is_session_name(name):
        return False
    run = run or run_command
    try:
        return run(["tmux", "send-keys", "-t", name, "Enter"]).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
