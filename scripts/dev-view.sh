#!/bin/bash
# dev-view.sh — /dev-loop 작업 tmux 세션들을 한 창에 분할해 실시간으로 비춘다(읽기 전용 미러).
#
# 사용법:
#   dev-view.sh                 도는 dev-* 세션을 모두 비추고 창을 띄운다 (프로젝트 무관)
#   dev-view.sh --sync          창은 띄우지 않고 pane 구성만 맞춘다
#   dev-view.sh --close         뷰어 세션을 종료한다 (도는 작업 세션이 없을 때만)
#   dev-view.sh --solo SESSION  그 작업 세션에 직접 붙는(입력 가능한) 단독 창을 띄운다
#                               미러와 달리 attach이므로 승인·선택지에 사람이 답할 수 있다
#   dev-view.sh --solo-active   같되 대상을 뷰어의 활성 칸에서 읽는다 (바인딩 전용)
#                               뷰어 칸을 더블클릭하면 이쪽이 불린다
#   dev-view.sh --name N3 [DIR] 노드 N3용 작업 세션명을 출력한다 (DIR 생략 시 현재 위치)
#                               저장소 밖에서 부를 때는 DIR에 저장소 경로를 넘긴다
#   dev-view.sh --peer-name DIR [REPO] 이 프로젝트에서 DIR로 거는 협업 세션명을 출력한다
#                               저장소 밖에서 부를 때는 REPO에 요청자 저장소 경로를 넘긴다
#
# 작업 세션명에 프로젝트 슬러그가 들어가므로(dev-<프로젝트>-<노드>, peer-<대상>-<요청자>)
# 프로젝트 간 이름이 겹치지 않는다. 그래서 대상은 항상 tmux에 살아 있는 dev-*·peer-*
# 전부로 잡는다 — 어느 프로젝트에서 불러도 한 창에서 모든 작업·협업 세션이 보인다.
#
# 환경변수:
#   DEV_VIEW_SESSION  뷰어 tmux 세션명 (기본 dev-view)
#   DEV_VIEW_LAYOUT   tiled(기본, 바둑판) | even-vertical(위아래) | even-horizontal(좌우)
#   DEV_VIEW_INTERVAL 갱신 주기 초 (기본 1)
#   DEV_VIEW_TERM     auto(기본) | iterm | terminal | none
#   DEV_VIEW_COLS/ROWS  띄울 창 크기 (기본 180x48)
#
# 미러는 capture-pane 스냅샷 폴링이라 작업 세션에 attach하지 않는다 —
# 작업 세션의 화면 크기를 건드리지 않고, 실수로 키가 들어갈 일도 없다.

set -u

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
MIRROR="$(dirname "$SELF")/dev-view-mirror.py"
VIEW_SESSION="${DEV_VIEW_SESSION:-dev-view}"
LAYOUT="${DEV_VIEW_LAYOUT:-tiled}"
INTERVAL="${DEV_VIEW_INTERVAL:-1}"
TERM_APP="${DEV_VIEW_TERM:-auto}"
WIN_COLS="${DEV_VIEW_COLS:-180}"
WIN_ROWS="${DEV_VIEW_ROWS:-48}"

# tmux 3.7b의 기본 DoubleClick1Pane 동작(단어 선택·복사). 뷰어 바인딩이 이 키를 차지하므로
# 뷰어가 아닌 칸과 --close 뒤에는 이것으로 되돌린다. tmux를 올려 기본값이 바뀌면 함께 맞춘다.
DEFAULT_DBLCLICK='select-pane -t = ; if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } { copy-mode -H ; send-keys -X select-word ; run-shell -d 0.3 ; send-keys -X copy-pipe-and-cancel }'

# 뷰어 세션명(DEV_VIEW_SESSION)은 tmux 명령 문자열·AppleScript 소스에 삽입되므로
# 영숫자·`_`·`-`로 제한한다. 미러 대상 세션명은 tmux가 준 값이라 이 검사를 거치지 않는다.
valid_name() {
  case "$1" in
    ""|*[!A-Za-z0-9_-]*) return 1 ;;
    *) return 0 ;;
  esac
}

# 주어진 경로가 속한 저장소의 루트. 저장소가 아니면 빈 값을 낸다.
# 워크트리에서 불러도 --git-common-dir이 메인 저장소를 가리키므로 같은 값이 나온다.
repo_root() {
  ( cd "${1:-$PWD}" 2>/dev/null || exit 0
    gitdir="$(git rev-parse --git-common-dir 2>/dev/null || true)"
    [ -n "$gitdir" ] || exit 0
    cd "$(dirname "$gitdir")" 2>/dev/null && pwd )
}

# 경로를 세션명에 쓸 수 있는 슬러그로 만든다.
# 슬러그는 폴더명만 보므로, 경로가 다른 두 저장소가 같은 폴더명을 쓰면 세션명이 겹친다
# (그런 저장소를 동시에 돌리지 않는다는 전제다).
slug_of() {
  local root="$1"
  local slug
  slug="$(basename "$root" | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9][^a-z0-9]*/-/g; s/^-//; s/-$//' | cut -c1-16 | sed 's/-$//')"
  # 폴더명이 한글뿐이면 슬러그가 통째로 비므로 경로 해시로 대신한다.
  if [ -z "$slug" ]; then
    slug="p$(printf '%s' "$root" | { md5 -q 2>/dev/null || md5sum 2>/dev/null; } | cut -c1-6)"
  fi
  printf '%s' "$slug"
}

# 저장소면 저장소 루트로, 아니면 그 경로 자체로 슬러그를 만든다.
# 저장소 밖 폴백은 --peer-name 전용이다 — 협업 대상은 git 저장소가 아닐 수 있다.
# --name은 이 폴백을 쓰지 않는다("이름 모드" 참조).
project_slug() {
  local base="${1:-$PWD}"
  local root
  root="$(repo_root "$base")"
  [ -n "$root" ] || root="$(cd "$base" 2>/dev/null && pwd)"
  [ -n "$root" ] || root="$base"
  slug_of "$root"
}

# tmux가 pane 안에서 다시 셸로 파싱하는 문자열이라 각 인자를 이스케이프해 넘긴다.
mirror_cmd() {
  printf '%q %q %q %q' "$(command -v python3)" "$MIRROR" "$1" "$INTERVAL"
}

# 터미널 앱 새 창을 열어 주어진 tmux 세션에 attach한다.
# $1 대상 세션명 · $2 cols · $3 rows.
# DEV_VIEW_TERM이 iterm·terminal 중 하나가 아니면(none과 오타를 함께) 창을 띄우지 않고 1을 돌려준다.
open_term_window() {
  local target="$1" cols="$2" rows="$3" app tmux_bin
  app="$TERM_APP"
  if [ "$app" = "auto" ]; then
    if [ -d /Applications/iTerm.app ]; then app=iterm; else app=terminal; fi
  fi
  tmux_bin="$(command -v tmux)"
  case "$app" in
    iterm)
      osascript -e 'tell application "iTerm"
        set w to (create window with default profile command "'"$tmux_bin"' attach -t '"$target"'")
        tell current session of w
          set columns to '"$cols"'
          set rows to '"$rows"'
        end tell
        activate
      end tell' >/dev/null
      ;;
    terminal)
      osascript -e 'tell application "Terminal"
        do script "'"$tmux_bin"' attach -t '"$target"'"
        set number of columns of window 1 to '"$cols"'
        set number of rows of window 1 to '"$rows"'
        activate
      end tell' >/dev/null
      ;;
    *)
      return 1
      ;;
  esac
  return 0
}

# ---------------------------------------------------------------- 미러 모드
# 뷰어 pane 안에서 자기 자신이 이 모드로 실행된다.
if [ "${1:-}" = "--mirror" ]; then
  exec python3 "$MIRROR" "${2:?mirror target required}" "$INTERVAL"
fi

# ---------------------------------------------------------------- 이름 모드
# 뷰어 세션을 건드리지 않으므로 DEV_VIEW_SESSION 검사보다 앞에 둔다.
if [ "${1:-}" = "--name" ]; then
  node="$(printf '%s' "${2:-}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]//g')"
  if [ -z "$node" ]; then
    echo "노드 ID가 필요합니다 (영문·숫자 포함): dev-view.sh --name N3" >&2
    exit 2
  fi
  # 슬러그는 저장소에서만 뽑는다. 저장소 밖에서 cwd 폴더명으로 폴백하면 지휘처럼
  # 전용 폴더에서 도는 호출자에게 틀린 세션명을 조용히 내주므로, 폴백 대신 거절한다.
  name_repo="${3:-$PWD}"
  name_root="$(repo_root "$name_repo")"
  if [ -z "$name_root" ]; then
    echo "저장소가 아니라 세션명을 만들 수 없습니다: $name_repo" >&2
    echo "저장소 밖에서 부를 때는 저장소 경로를 함께 넘기십시오: dev-view.sh --name N3 /path/to/repo" >&2
    exit 2
  fi
  printf 'dev-%s-%s\n' "$(slug_of "$name_root")" "$node"
  exit 0
fi

# 협업 세션명 모드. 대상 프로젝트와 요청자를 모두 담아 상대가 같아도 요청자별로 갈린다.
if [ "${1:-}" = "--peer-name" ]; then
  target="${2:-}"
  if [ -z "$target" ] || [ ! -d "$target" ]; then
    echo "대상 프로젝트 디렉토리가 필요합니다: dev-view.sh --peer-name /path/to/project" >&2
    exit 2
  fi
  # 요청자 쪽 슬러그는 저장소에서만 뽑는다. --name과 같은 이유로, 저장소 밖에서
  # cwd 폴더명으로 폴백하면 지휘처럼 전용 폴더에서 도는 호출자에게 틀린 세션명을
  # 조용히 내주므로 폴백 대신 거절한다. 대상(target) 쪽은 협업 대상이 git 저장소가
  # 아닐 수 있어 의도적으로 project_slug의 폴백을 그대로 쓴다.
  peer_repo="${3:-$PWD}"
  peer_root="$(repo_root "$peer_repo")"
  if [ -z "$peer_root" ]; then
    echo "저장소가 아니라 세션명을 만들 수 없습니다: $peer_repo" >&2
    echo "저장소 밖에서 부를 때는 저장소 경로를 함께 넘기십시오: dev-view.sh --peer-name /path/to/target /path/to/repo" >&2
    exit 2
  fi
  printf 'peer-%s-%s\n' "$(project_slug "$target")" "$(slug_of "$peer_root")"
  exit 0
fi

# ---------------------------------------------------------------- 단독 창 모드
# 미러가 아니라 그 작업 세션에 직접 붙는 창을 띄운다 — 승인·선택지에 사람이 답하는 자리다.
# 뷰어 세션은 건드리지 않으므로 DEV_VIEW_SESSION 검사보다 앞에 둔다.
if [ "${1:-}" = "--solo" ] || [ "${1:-}" = "--solo-active" ]; then
  if [ "${1:-}" = "--solo-active" ]; then
    # 바인딩이 부르는 자리. 세션명을 인자로 받지 않고 뷰어의 활성 칸 이름표에서 직접 읽는다 —
    # 바인딩 문자열에 #{pane_title}을 실으면 run-shell이 클릭된 칸이 아니라
    # 자기 기본 타겟으로 다시 확장해 엉뚱한 값(호스트명)이 넘어간다.
    solo="$(tmux display-message -p -t "=$VIEW_SESSION:" '#{pane_title}' 2>/dev/null)"
  else
    solo="${2:-}"
  fi
  # 세션명이 AppleScript 소스에 그대로 삽입되므로 뷰어 세션명과 같은 제한을 건다.
  if ! valid_name "$solo"; then
    echo "붙을 세션 이름이 비었거나 쓸 수 없는 문자가 있습니다: ${solo:-(빈 이름)}" >&2
    exit 2
  fi
  if ! tmux has-session -t "=$solo" 2>/dev/null; then
    echo "붙을 세션이 없습니다: $solo" >&2
    # 바인딩으로 불리면 위 출력이 버려진다. run-shell -b에는 붙은 클라이언트가 없어
    # 대상 없는 display-message가 조용히 사라지므로, 뷰어에 붙은 클라이언트마다 지정해 띄운다.
    if [ "${1:-}" = "--solo-active" ]; then
      tmux list-clients -t "=$VIEW_SESSION" -F '#{client_name}' 2>/dev/null | while IFS= read -r c; do
        tmux display-message -c "$c" "끝난 작업이라 붙을 세션이 없습니다: $solo" 2>/dev/null
      done
    fi
    exit 2
  fi
  # 이미 붙은 창이 있으면 새로 열지 않는다. 창을 둘 열어도 크기만 더 작은 쪽으로 묶인다.
  if [ -n "$(tmux list-clients -t "=$solo" 2>/dev/null)" ]; then
    echo "이미 붙어 있는 창이 있습니다: $solo"
    exit 0
  fi
  if open_term_window "$solo" "$WIN_COLS" "$WIN_ROWS"; then
    echo "단독 창을 띄웠습니다: $solo — 입력이 들어갑니다. 답한 뒤 창을 닫으십시오"
  else
    echo "창 없이 종료. 직접 붙으려면: tmux attach -t $solo"
  fi
  exit 0
fi

if ! valid_name "$VIEW_SESSION"; then
  echo "DEV_VIEW_SESSION은 영문·숫자·_·-만 쓸 수 있습니다: $VIEW_SESSION" >&2
  exit 2
fi

# 지금 살아 있는 작업 세션 목록.
# 뷰어 세션에는 @dev-view 표식을 달아 두므로 그것으로 걸러 자기 화면을 되비추지 않는다
# (표식이 없던 예전 뷰어를 위해 기본 이름 dev-view도 함께 뺀다).
live_sessions() {
  tmux list-sessions -F '#{session_name}|#{@dev-view}' 2>/dev/null \
    | awk -F'|' '$2 == "" { print $1 }' \
    | grep -E '^(dev|peer)-' | grep -Fxv "$VIEW_SESSION" | grep -Fxv 'dev-view'
}

# ---------------------------------------------------------------- 종료 모드
if [ "${1:-}" = "--close" ]; then
  # 다른 프로젝트가 아직 세션을 돌리고 있으면 창은 그쪽 몫이다.
  # 지휘 세션(dev-cmd-*)은 미러 대상에는 포함하지만(live_sessions는 건드리지 않는다),
  # --close 판정에서는 뺀다 — 안 그러면 지휘가 스스로 --close를 불렀을 때
  # 자기 자신 때문에 거부된다.
  remaining="$(live_sessions | grep -Ev '^dev-cmd-')"
  if [ -n "$remaining" ]; then
    echo "도는 작업 세션이 있어 뷰어를 닫지 않습니다: $(printf '%s' "$remaining" | tr '\n' ' ')" >&2
    exit 1
  fi
  # 뷰어를 닫으면 자기가 차지한 더블클릭을 tmux 기본 동작으로 되돌린다.
  # unbind로 지우면 모든 세션에서 더블클릭 단어 선택이 사라진다.
  tmux bind-key -T root DoubleClick1Pane "$DEFAULT_DBLCLICK" 2>/dev/null
  tmux unbind-key -T root M-DoubleClick1Pane 2>/dev/null
  tmux kill-session -t "=$VIEW_SESSION" 2>/dev/null && echo "뷰어 세션 종료: $VIEW_SESSION" || echo "뷰어 세션 없음"
  exit 0
fi

OPEN_WINDOW=1
if [ "${1:-}" = "--sync" ]; then
  OPEN_WINDOW=0
  shift
fi

# ---------------------------------------------------------------- 대상 수집
# 대상은 언제나 "지금 살아 있는 dev-*·peer-* 세션 전부"다. 세션명이 프로젝트별로 갈리므로
# 목록을 받아 걸러낼 이유가 없고, 목록으로 거르면 다른 프로젝트 pane을 지우게 된다.
if [ $# -gt 0 ]; then
  echo "세션명 인자는 무시합니다 — 도는 dev-*·peer-* 세션을 모두 비춥니다: $*" >&2
fi
targets="$(live_sessions | sed '/^$/d')"

if [ -z "$targets" ]; then
  # 작업 세션이 잠시 비는 것은 오류가 아니다. 창은 마지막 화면을 띄운 채 두고,
  # 다음 노드가 뜰 때 갱신한다. 창을 접는 것은 --close의 몫이다.
  if [ "$OPEN_WINDOW" = "0" ]; then
    echo "비출 dev-*·peer-* 세션이 없습니다 — 뷰어는 마지막 화면으로 둡니다."
    exit 0
  fi
  echo "비출 dev-*·peer-* 세션이 없습니다." >&2
  exit 1
fi

# ---------------------------------------------------------------- 뷰어 구성
# 프로젝트별 메인 세션이 동시에 부를 수 있으므로 pane을 만들고 지우는 구간만 잠근다.
# 잠금이 남아 있어도 약 6초 뒤엔 그냥 진행한다 — 미러 창 때문에 멈춰 설 이유는 없다.
LOCK="${TMPDIR:-/tmp}/dev-view.lock"
HELD=0
tries=0
while [ "$HELD" = 0 ] && [ "$tries" -lt 20 ]; do
  if mkdir "$LOCK" 2>/dev/null; then
    HELD=1
  else
    # 잠금을 쥔 채 죽은 프로세스가 남긴 고아 잠금은 30초 뒤 회수한다.
    # 그러지 않으면 이후 모든 호출이 영영 잠금을 못 얻는다.
    age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || date +%s) ))
    [ "$age" -gt 30 ] && rmdir "$LOCK" 2>/dev/null
    tries=$((tries + 1))
    sleep 0.3
  fi
done
[ "$HELD" = 1 ] || echo "뷰어 잠금을 얻지 못해 그대로 진행합니다 — pane이 겹쳐 보이면 다시 실행하세요." >&2
trap '[ "$HELD" = 1 ] && rmdir "$LOCK" 2>/dev/null' EXIT

if ! tmux has-session -t "=$VIEW_SESSION" 2>/dev/null; then
  first="$(printf '%s\n' "$targets" | head -1)"
  tmux new-session -d -s "$VIEW_SESSION" -x 200 -y 50 "$(mirror_cmd "$first")"
  tmux select-pane -t "=$VIEW_SESSION:" -T "$first"
  # pane-border-*는 window 옵션, status-left·mouse는 세션 옵션이라 지정 방식이 다르다.
  tmux set-option -w -t "=$VIEW_SESSION:" pane-border-status top >/dev/null
  tmux set-option -w -t "=$VIEW_SESSION:" pane-border-format ' #{pane_title} ' >/dev/null
  tmux set-option -t "=$VIEW_SESSION:" status-left " $VIEW_SESSION (읽기 전용) " >/dev/null
  tmux set-option -t "=$VIEW_SESSION:" mouse on >/dev/null
fi

# 뷰어 표식. 예전 이름으로 떠 있던 뷰어에도 매번 다시 달아 둔다.
tmux set-option -t "=$VIEW_SESSION:" @dev-view 1 >/dev/null 2>&1

# 칸을 더블클릭하면 그 작업 세션에 직접 붙는 단독 창이 뜬다(--solo).
# Option·Ctrl 조합은 쓰지 않는다 — iTerm은 Option을 누른 동안 마우스 보고를 꺼 tmux에 닿지 않고,
# Ctrl+클릭은 기본값에서 우클릭 메뉴가 먹는다. 뷰어 칸은 읽기 전용 미러라 단어 선택을 잃어도 무방하다.
# 키 바인딩은 tmux 서버 전역이므로 위 @dev-view 표식으로 갈라, 다른 세션에서는 기본 동작을 그대로 돈다.
# select-pane을 먼저 걸어야 --solo-active가 읽는 활성 칸이 방금 클릭한 칸이 된다.
# 옛 판이 걸어 둔 Option+더블클릭 바인딩은 떠 있는 서버에 남아 있으므로 여기서 거둔다.
# run-shell은 명령 출력과 0이 아닌 종료코드("returned 2")를 클릭한 칸에 보기 모드로 덮어
# 미러를 멈추므로, 출력을 버리고 `; true`로 끝낸다 — 실패 안내는 --solo-active가 직접 띄운다.
tmux unbind-key -T root M-DoubleClick1Pane 2>/dev/null
tmux bind-key -T root DoubleClick1Pane if-shell -F -t = '#{@dev-view}' \
  "select-pane -t = ; run-shell -b 'DEV_VIEW_SESSION=$VIEW_SESSION $SELF --solo-active >/dev/null 2>&1; true'" \
  "$DEFAULT_DBLCLICK" >/dev/null 2>&1

# 사라진 대상의 pane 제거 (pane이 2개 이상일 때만 — 마지막 하나는 남긴다)
tmux list-panes -t "=$VIEW_SESSION:" -F '#{pane_title}' 2>/dev/null | while IFS= read -r s; do
  [ -z "$s" ] && continue
  if ! printf '%s\n' "$targets" | grep -Fxq "$s"; then
    if [ "$(tmux list-panes -t "=$VIEW_SESSION:" | wc -l | tr -d ' ')" -gt 1 ]; then
      pid="$(tmux list-panes -t "=$VIEW_SESSION:" -F '#{pane_id}	#{pane_title}' \
        | awk -F'\t' -v s="$s" '$2==s{print $1; exit}')"
      [ -n "$pid" ] && tmux kill-pane -t "$pid"
    fi
  fi
done

# 새 대상의 pane 추가
printf '%s\n' "$targets" | while IFS= read -r s; do
  [ -z "$s" ] && continue
  if ! tmux list-panes -t "=$VIEW_SESSION:" -F '#{pane_title}' | grep -Fxq "$s"; then
    pid="$(tmux split-window -t "=$VIEW_SESSION:" -P -F '#{pane_id}' "$(mirror_cmd "$s")")"
    tmux select-pane -t "$pid" -T "$s"
  fi
done

tmux select-layout -t "=$VIEW_SESSION:" "$LAYOUT" >/dev/null

# pane 조작이 끝났으니 창을 띄우기 전에 잠금을 놓는다.
[ "$HELD" = 1 ] && { rmdir "$LOCK" 2>/dev/null; HELD=0; }

[ "$OPEN_WINDOW" = "0" ] && { echo "뷰어 동기화 완료: $VIEW_SESSION"; exit 0; }

# ---------------------------------------------------------------- 창 띄우기
# 이미 붙어 있는 클라이언트가 있으면 창을 새로 열지 않는다.
if [ -n "$(tmux list-clients -t "=$VIEW_SESSION" 2>/dev/null)" ]; then
  echo "뷰어 창이 이미 열려 있습니다: $VIEW_SESSION"
  exit 0
fi

if open_term_window "$VIEW_SESSION" "$WIN_COLS" "$WIN_ROWS"; then
  echo "뷰어 창을 띄웠습니다: $VIEW_SESSION ($(printf '%s\n' "$targets" | grep -c '')개 세션)"
else
  echo "창 없이 구성만 완료. 직접 붙으려면: tmux attach -t $VIEW_SESSION"
fi
