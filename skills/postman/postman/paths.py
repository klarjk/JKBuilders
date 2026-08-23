"""우편함 경로·설정·토큰 읽기 (ADR-002 D2).

**뿌리는 `~/.claude/postman/`이다.** 001의 `~/.claude/dev-run/`을 재사용하지 않는다 —
001이 부활할 때 상태 파일이 섞이는 것을 막는다. 예외는 하나, **봇 토큰**이다.

    POSTMAN_ROOT        기본 ~/.claude/postman
    POSTMAN_CONFIG      기본 <root>/config.json
    POSTMAN_TOKEN_FILE  기본 ~/.claude/dev-run/telegram-bot-token   ← 001에서 그대로 읽는다

토큰 파일만 001의 뿌리를 가리키는 것은 규약이다(D2) — **새 봇을 만들지 않으며, 값은
코드·로그·오류문·발신문 어디에도 싣지 않는다.** 001 트리의 *파일을 읽는 것*이지 001의
*코드를 임포트하는 것*이 아니다(D1의 임포트 경계는 그대로 지킨다).

경로는 호출 시점에 읽는다 — 임포트 시각에 굳히면 테스트가 환경변수를 갈아끼워도
반영되지 않는다.

원자적 쓰기·읽기 헬퍼를 001의 `session/devrun_paths.py`에서 임포트하지 않고 여기 복제한
것도 같은 이유다(D5의 새 트리 복제). 사본 분화는 ADR이 수용한 비용이다.

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from postman import addressing
from protocol import commands as protocol  # noqa: F401  (열거형 단일 출처 — D1 검사 대상)

# 봇이 받아들이는 명령의 전부다. **값을 여기서 다시 적지 않는다** (D1 ②).
COMMANDS = protocol.COMMANDS

DEFAULT_TOKEN_PATH = Path.home() / ".claude" / "dev-run" / "telegram-bot-token"


# ---------------------------------------------------------------- 뿌리·파일

def root():
    path = Path(os.environ.get("POSTMAN_ROOT") or (Path.home() / ".claude" / "postman"))
    _lock_root_once(path)
    return path


def _lock_root_once(path):
    """뿌리가 없으면 만들면서 **그 순간에만** 0700으로 잠근다.

    이미 있으면 손대지 않는다 — 남의 디렉토리 권한을 매 호출마다 강제하면 워크트리·
    `~/.claude/status/`까지 잠가버린 001의 사고를 되풀이한다.
    """
    try:
        path.mkdir(parents=True, exist_ok=False)
    except OSError:
        return
    try:
        os.chmod(str(path), 0o700)
    except OSError:
        pass


def config_path():
    override = os.environ.get("POSTMAN_CONFIG")
    return Path(override) if override else root() / "config.json"


def token_path():
    override = os.environ.get("POSTMAN_TOKEN_FILE")
    return Path(override) if override else DEFAULT_TOKEN_PATH


def lock_file():
    return root() / "lock"


def heartbeat_file():
    return root() / "heartbeat"


def offset_file():
    return root() / "offset.json"


def actions_file():
    return root() / "actions.json"


def messages_file():
    return root() / "messages.json"


def ledger_file():
    return root() / "ledger.json"


def counters_file():
    return root() / "counters.json"


def relay_file():
    return root() / "relay.json"


def cleanup_stamp_file():
    return root() / "cleanup.json"


def log_dir():
    return root() / "log"


def sessions_dir():
    return root() / "sessions"


def session_dir(name):
    """세션별 우편함. 러너 2단(`runners/<slug>/nodes/<노드>/`)을 1단으로 축소했다 (D2)."""
    return sessions_dir() / addressing.safe_session_name(name)


COUNTER_MAILBOX = "counter"


def counter_dir():
    """창구 전용 우편함 — tmux명 규칙의 명시 예외인 고정 이름 (D2).

    창구는 tmux 세션이 아니라 주소가 없다. 재스폰 실패·계측 불능 통보가 여기로 나간다.
    """
    return sessions_dir() / COUNTER_MAILBOX


# ---------------------------------------------------------------- 출처 표시 (후속 59)

PROJECT_ENV = "POSTMAN_PROJECT"


def project_slug():
    """이 우체부가 맡은 프로젝트 슬러그(`POSTMAN_PROJECT`). 없거나 규약 밖이면 None.

    `bot.check_project`가 기동 거부에 쓰는 것과 **같은 출처**다 — 두 곳이 다른 값을 보면
    "다른 프로젝트라 기동을 거부했는데 화면에는 이 프로젝트로 적히는" 어긋남이 생긴다.

    폭 검사에 세션명 규정을 그대로 쓴다. 슬러그는 어차피 tmux 세션명 안에 박혀 나가므로
    (`dev-<슬러그>-<노드>`), 세션명이 못 받는 슬러그는 여기서도 받으면 안 된다 (D9).
    """
    value = os.environ.get(PROJECT_ENV)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if addressing.is_session_name(value) else None


def display_label(session=None, project=None):
    """발신문 앞에 서는 출처 표시. 붙일 것이 없으면 None.

    한 채팅에 여러 세션의 우편함이 몰리므로 **누가 말하는지가 화면에서 갈려야 한다**
    (후속 59). 규칙은 셋뿐이다.

    - 세션명에 프로젝트 슬러그가 이미 들어 있으면(`dev-<슬러그>-<노드>`·`dev-cmd-<슬러그>`)
      세션명만 적는다 — `[vault/dev-vault-fu2]`는 같은 말을 두 번 하는 것이다.
    - 슬러그가 안 든 이름에는 `<프로젝트>/<세션>`으로 붙인다. **창구 우편함(`counter`)이
      바로 그 경우다** — 창구는 tmux 세션이 아니라 이름이 고정이라, 프로젝트가 둘이면
      화면의 `[counter]`가 어느 쪽 창구인지 구별되지 않는다.
    - 세션이 없는 발신(봇이 명령에 직접 답하는 자리)은 `<프로젝트>`만 적는다.

    슬러그 포함 판정을 부분 문자열로 하는 이유: 슬러그에 `-`가 들어갈 수 있어
    (`dev-run-practice`) 토막 단위 대조로는 못 잡는다. 단일 프로젝트 전제(D3)에서는 다른
    프로젝트의 세션명이 이 함수에 오지 않으므로 오검출의 실해가 없다.

    **주소 규약을 통과하지 못한 이름은 표시하지 않는다.** 이 표시는 마스킹 관문을 지난
    뒤에 붙으므로(`sender._labeled`), 검사 없이 실으면 규약 밖 문자열이 관문을 건너뛰고
    발신문에 실리는 통로가 된다. 지금은 모든 호출자가 검증된 이름만 넘기지만
    (`mailbox.all_unsent`·`tmuxq.has_session`), 그 전제가 깨져도 새지 않게 여기서 막는다.
    """
    project = project if project is not None else project_slug()
    if project and not addressing.is_session_name(project):
        project = None          # 명시 인자도 환경변수와 같은 폭을 지난다 — 비대칭이 구멍이다
    if session and session != COUNTER_MAILBOX and not addressing.is_session_name(session):
        session = None
    if not session:
        return project or None
    if not project or project in session:
        return session
    return "%s/%s" % (project, session)


def corrupt_dir():
    return root() / "corrupt"


def diag_dir():
    """중단 진단 캡처 (002-N7F ④). `corrupt/`와 같은 층에 둔다 — 둘 다 사후 검시용이다.

    통로가 아니다. 여기 있는 파일을 읽고 무언가를 다시 넣는 코드를 만들지 않는다.
    """
    return root() / "diag"


def list_session_mailboxes():
    """우편함 디렉토리 이름 목록(사전순). 창구 우편함도 포함한다.

    **심링크는 우편함으로 세지 않는다** (002-N26). `is_dir()`는 심링크를 따라가므로,
    세션명 규칙에 맞는 심링크가 `sessions/` 안에 놓이면 그 대상 디렉토리가 여기서
    나온 이름을 타고 점검·청소 대상이 된다. 청소는 파일을 지우는 자리라
    (`mailbox.cleanup`), 정보 노출로 끝나지 않고 뿌리 밖으로 손이 나간다.
    """
    try:
        entries = list(sessions_dir().iterdir())
    except OSError:
        return []
    names = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.name == COUNTER_MAILBOX or addressing.is_session_name(entry.name):
            names.append(entry.name)
    return sorted(names)


# ---------------------------------------------------------------- 디렉토리·격리

def ensure_private_dir(path):
    """없는 디렉토리만 **소유자 전용(0700)으로** 만든다. 이미 있으면 권한을 손대지 않는다."""
    path = Path(path)
    missing = []
    probe = path
    while not probe.is_dir() and probe.parent != probe:
        missing.append(probe)
        probe = probe.parent
    for target in reversed(missing):
        try:
            target.mkdir(mode=0o700)   # umask는 비트를 빼기만 하므로 chmod 없이 안전하다
        except OSError:
            pass
    return path


def quarantine(path, prefix=None):
    """손상 파일을 `corrupt/`로 옮긴다 (D2). 격리 경로 또는 None.

    덮어쓰지 않는다 — 이름이 겹치면 뒤에 난수를 붙인다. 사후 검시가 목적이므로 내용은
    그대로 둔다.
    """
    path = Path(path)
    target_dir = ensure_private_dir(corrupt_dir())
    name = ("%s-%s" % (prefix, path.name)) if prefix else path.name
    target = target_dir / name
    if target.exists():
        target = target_dir / ("%s-%s%s" % (target.stem, secrets.token_hex(3), target.suffix))
    try:
        os.replace(str(path), str(target))
    except OSError:
        return None
    return target


# ---------------------------------------------------------------- 원자적 입출력

def atomic_write_json(path, obj, mode=0o600, indent=None):
    """같은 디렉토리에 임시 파일로 쓴 뒤 rename. 읽는 쪽은 점으로 시작하는 이름을 무시한다.

    없는 부모는 **0700으로** 만든다 (002-N27). 호출자가 앞서 `ensure_private_dir`를
    부르는 것이 관례지만, 그 관례를 빠뜨린 새 호출자가 우편함을 0755로 세우면 자가
    점검이 자기 프로그램의 실수를 잡는 모양이 된다. 이미 있는 디렉토리의 권한은
    손대지 않는다 — 남의 디렉토리를 매번 잠그는 것은 별개의 사고다.
    """
    path = Path(path)
    ensure_private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(obj, fp, ensure_ascii=False, indent=indent)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def read_json(path):
    """읽기·파싱 실패는 전부 None. 부분 쓰기 중인 파일에 걸려도 호출자를 깨지 않는다."""
    try:
        with open(str(path), "r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return None


_last_mailbox_ms = 0


def mailbox_filename(kind):
    """`<ts_ms>-<rand6>-<종류>.json` (D2). 사전순이 곧 시간순이고 재기동 후에도 겹치지 않는다.

    같은 밀리초에 둘을 발급하면 정렬이 뒤의 난수로 갈려 **발급 순서가 뒤집힌다**(001 N12
    결함 7). 밀리초를 단조 증가시켜 사전순과 발급순을 붙여 둔다.
    """
    global _last_mailbox_ms
    now_ms = int(time.time() * 1000)
    if now_ms <= _last_mailbox_ms:
        now_ms = _last_mailbox_ms + 1
    _last_mailbox_ms = now_ms
    return "%d-%s-%s.json" % (now_ms, secrets.token_hex(3), kind)


# ---------------------------------------------------------------- 토큰

class TokenUnavailable(RuntimeError):
    pass


def read_token(path=None):
    """토큰은 읽기만 한다. 값은 반환값 외 어디에도 남기지 않는다 — 로그·예외 문구 금지."""
    path = Path(path) if path else token_path()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise TokenUnavailable("토큰 파일을 읽을 수 없습니다: %s" % path)
    if not token:
        raise TokenUnavailable("토큰 파일이 비어 있습니다: %s" % path)
    return token


# ---------------------------------------------------------------- 설정

class Config(object):
    """`config.json`. 기동 시 1회만 읽는다 — 실행 중 재적재 없음 (D2, ADR-001 D6 승계).

    파일이 없거나 허용 목록이 비면 **fail-closed**: 모든 업데이트를 폐기한다.
    """

    def __init__(self, data=None, source=None):
        data = data if isinstance(data, dict) else {}
        self.source = source
        self.allowed_user_ids = frozenset(
            int(v) for v in data.get("allowed_user_ids", [])
            if isinstance(v, (int, str)) and str(v).lstrip("-").isdigit()
        )
        chat_id = data.get("chat_id")
        if chat_id is None and self.allowed_user_ids:
            chat_id = min(self.allowed_user_ids)
        self.chat_id = chat_id

        # 발신문에서 통째로 지울 파일 경로. 볼트 운용이므로 루트 평문 개인정보 파일을
        # 반드시 넣는다 (D2). 비워 두면 화면 캡처에 실려 제3자 서버로 나간다.
        self.never_send = tuple(str(p) for p in data.get("never_send", []) if isinstance(p, str))

        self.stale_window = float(data.get("stale_window", 300))
        # 조작 명령과 달리 **질문의 답변**에는 훨씬 긴 창을 준다 — 자리를 비워도 돌아가는
        # 것이 이 시스템의 목적이라, 하룻밤을 넘겨 온 답도 받아야 한다.
        self.answer_window = float(data.get("answer_window", 86400))
        self.poll_timeout = int(data.get("poll_timeout", 25))
        self.settle_interval = float(data.get("settle_interval", 2))
        self.settle_timeout = float(data.get("settle_timeout", 30))
        self.action_ttl = float(data.get("action_ttl", 86400))
        self.min_send_interval = float(data.get("min_send_interval", 1.0))
        self.cleanup_interval = float(data.get("cleanup_interval", 86400))
        self.max_age_days = float(data.get("max_age_days", 7))

        # 유휴 자동 종료 (D8). 지휘 tmux가 이만큼 부재하면 정상 종료한다.
        self.idle_grace = float(data.get("idle_grace", 1800))
        # 보관분이 남아 있어도 이만큼 부재하면 종료한다(파일은 남아 재기동 시 재시도).
        self.idle_hard_grace = float(data.get("idle_hard_grace", 86400))
        # 지휘·창구가 우체부 생존을 판정하는 창 (D2 「우체부 생존 감시」). 우체부는 이 값을
        # 설정에 실어 두기만 한다 — 판정 주체는 세션이다.
        self.heartbeat_stale = float(data.get("heartbeat_stale", 900))

        # 발신 상한 2단 (D2, ADR-001 D9 승계). 시간당 연 30 / 경 60.
        self.soft_send_limit = int(data.get("soft_send_limit", 30))
        self.hard_send_limit = int(data.get("hard_send_limit", 60))
        self.send_window = float(data.get("send_window", 3600))

        self.log_max_age_days = float(data.get("log_max_age_days", 14))

    @property
    def fail_closed(self):
        return not self.allowed_user_ids or self.chat_id is None

    def is_allowed(self, user_id):
        """① 허용 목록 대조. 1:1 개인 채팅 여부는 호출자가 함께 확인한다 (D2)."""
        if self.fail_closed:
            return False
        try:
            return int(user_id) in self.allowed_user_ids
        except (TypeError, ValueError):
            return False

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path else config_path()
        return cls(read_json(path), source=path)
