"""경계 불변식 — 구조로 강제해야 하는 것들 (ADR-002 D1·D5).

D1이 코드로 강제하라고 못박은 검사 둘이 여기 있다.

1. **우체부는 `skills/dev-run/`의 어떤 모듈도 임포트하지 않는다.** 001은 동결이고 부활 시
   자기 트리를 그대로 읽어야 한다. 임포트 한 줄이면 두 트리가 한 몸이 되고, 그때부터
   001을 되살리는 사람은 002의 변경분을 먼저 읽어야 한다.
2. **명령 열거형은 `protocol/commands.py` 한 곳에만 선언된다.** 001에서는 같은 튜플이 세
   곳에 수기 복제돼 있었고 어긋나면 조용히 깨졌다("버튼을 눌렀는데 아무 일도 없다").

**001의 `test_layout.py`는 고치지도 지우지도 않았다** — 동결 트리 무접촉이다(D5). 그래서
그쪽의 AST 검사는 돌리는 주체가 없어 001 부활 시점까지 실질 무효이고, 002의 실효 검사는
이 파일이다.

여기에 더해 진입점이 **스크립트로 직접 실행돼도 살아 있는지**를 실제로 돌려 본다. 창구가
`python3 postman/bot.py`로 띄우므로 `python -m`을 전제할 수 없고, 임포트 실패는 조용하다.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# 동결 트리(`skills/dev-run/`)의 최상위 패키지 이름. 이 중 하나라도 임포트하면 경계가 무너진다.
# `protocol`은 제외한다 — 우체부 트리에도 같은 이름의 **자기 패키지**가 있고, 그것을 쓰는
# 것이 D1 ②가 요구하는 단일 출처다. 동결 트리 쪽으로 새는지는 아래 sys.path 검사가 막는다.
FROZEN_PACKAGES = ("runner", "judge", "session", "bot")

ENUM_SOURCE = "protocol/commands.py"

# 열거형을 들고 있어야 하는 유일한 모듈 밖에서 이 이름들의 튜플 선언을 금지한다.
WATCHED_ENUM_NAMES = {"COMMANDS", "BUTTON_COMMANDS", "SLOW_COMMANDS", "NODE_REQUIRED",
                      "TARGET_REQUIRED", "ACTION_KINDS"}


def _python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _docstring_ids(tree):
    """모듈·클래스·함수의 독스트링 노드 id 집합. 설명문까지 경로로 읽지 않기 위함이다."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            found.add(id(body[0].value))
    return found


def test_postman_does_not_import_the_frozen_tree():
    """우체부가 001의 모듈을 임포트하지 않는다 (D1 ①·D5 동결 트리 무접촉)."""
    offenders = []
    for path in _python_files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:            # 상대 임포트는 아래 별도 검사가 잡는다
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in FROZEN_PACKAGES:
                    offenders.append("{}:{} — {}".format(
                        path.relative_to(ROOT), node.lineno, name))
    assert not offenders, "우체부가 동결 트리를 임포트한다 (ADR-002 D1 위반): {}".format(offenders)


def test_no_module_puts_the_frozen_tree_on_sys_path():
    """`sys.path`에 001 트리를 얹는 우회로도 막는다 — 임포트 이름만 검사하면 새어 나간다."""
    offenders = []
    for path in _python_files():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if not isinstance(target, ast.Attribute) or target.attr not in ("insert", "append"):
                continue
            source = ast.dump(target.value)
            if "sys" not in source or "path" not in source:
                continue
            literals = [n.value for n in ast.walk(node)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            if any("dev-run" in value for value in literals):
                offenders.append("{}:{}".format(path.relative_to(ROOT), node.lineno))
    assert not offenders, "sys.path에 동결 트리를 얹는다: {}".format(offenders)


def test_only_the_token_path_points_at_the_frozen_root():
    """001 뿌리를 가리켜도 되는 것은 **봇 토큰 파일 하나**뿐이다 (D2의 명시 예외).

    상태 파일까지 001 뿌리를 쓰면 부활 시 두 계획의 상태가 섞인다.
    """
    allowed = {"postman/paths.py"}
    offenders = []
    for path in _python_files():
        if path.name.startswith("test_"):
            continue
        rel = str(path.relative_to(ROOT))
        if rel in allowed:
            continue
        tree = _tree(path)
        docstrings = _docstring_ids(tree)     # 설명문은 검사 대상이 아니다 — 경로가 아니라 말이다
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and "dev-run" in node.value and id(node) not in docstrings:
                offenders.append("{}:{}".format(rel, node.lineno))
    assert not offenders, "동결 뿌리를 가리키는 문자열이 토큰 경로 밖에 있다: {}".format(offenders)


def test_command_enum_is_declared_in_exactly_one_place():
    """열거형의 튜플 리터럴이 `protocol/commands.py` 밖에 없다 (D1 ②).

    값 비교만으로는 **지금 우연히 같은 복제본**을 통과시키므로 선언 자체를 금지한다.
    """
    offenders = []
    for path in _python_files():
        if path.name.startswith("test_"):
            continue
        rel = str(path.relative_to(ROOT))
        if rel == ENUM_SOURCE:
            continue
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Assign):
                continue
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & WATCHED_ENUM_NAMES and isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                offenders.append("{}:{} — {}".format(
                    rel, node.lineno, sorted(names & WATCHED_ENUM_NAMES)))
    assert not offenders, "명령 열거형이 {} 밖에서 다시 선언됐다: {}".format(ENUM_SOURCE, offenders)


def test_enum_mirror_is_the_same_object_at_runtime():
    """임포트 경로가 갈리면 값도 갈린다 — 실제로 같은 객체인지 본다."""
    from postman import paths
    from protocol import commands as protocol

    assert paths.COMMANDS is protocol.COMMANDS


def test_no_relative_imports():
    """상대 임포트는 스크립트 직접 실행에서 원리적으로 실패한다(`__package__`가 비어 있다)."""
    offenders = [
        "{}:{}".format(path.relative_to(ROOT), node.lineno)
        for path in _python_files()
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom) and node.level
    ]
    assert not offenders, "상대 임포트가 있다: {}".format(offenders)


def _sandbox_env(tmp_path):
    """실제 `~/.claude/postman`을 건드리지 않게 뿌리를 임시로 돌린다."""
    child = dict(os.environ)
    child.pop("PYTHONPATH", None)   # 부트스트랩이 아니라 환경변수 덕에 풀리면 탐침이 무의미하다
    child["POSTMAN_ROOT"] = str(tmp_path / "postman")
    child["POSTMAN_CONFIG"] = str(tmp_path / "postman" / "config.json")
    child["POSTMAN_TOKEN_FILE"] = str(tmp_path / "없는토큰")
    return child


def test_entry_point_survives_direct_script_execution(tmp_path):
    """창구는 `python3 postman/bot.py`로 띄운다 — `python -m`을 전제할 수 없다."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "postman" / "bot.py"), "--check"],
        env=_sandbox_env(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "점검 완료" in proc.stdout


MODULES = ("addressing", "bot", "commands", "delivery", "diag", "discriminator",
           "eventlog", "handler", "inject", "ledger", "limits", "mailbox", "masking",
           "paths", "relay", "sender", "store", "tmuxq")


def test_every_module_imports_under_the_script_path_condition(tmp_path):
    """모듈 하나가 임포트에서 죽으면 진입점이 조용히 멈춘다 — 실제로 전부 불러 본다."""
    code = "import sys; sys.path.insert(0, %r)\n" % str(ROOT)
    code += "".join("import postman.%s\n" % name for name in MODULES)
    code += "import protocol.commands\nprint('ok')\n"
    proc = subprocess.run([sys.executable, "-c", code], env=_sandbox_env(tmp_path),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


@pytest.mark.parametrize("name", MODULES)
def test_modules_stay_python39_parseable(name):
    """시스템 파이썬(3.9)에서도 임포트되어야 한다 — 구문 자체를 3.9로 유지한다."""
    path = ROOT / "postman" / (name + ".py")
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
