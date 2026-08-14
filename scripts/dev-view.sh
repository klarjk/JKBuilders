#!/bin/bash
# dev-view.sh — /dev-loop 작업 tmux 세션들을 한 창에 분할해 실시간으로 비춘다(읽기 전용 미러).
#
# 사용법:
#   dev-view.sh                 대상 세션(dev-*)을 자동 수집해 뷰어를 구성하고 창을 띄운다
#   dev-view.sh dev-n1 dev-n2   대상 세션을 직접 지정
#   dev-view.sh --sync [세션…]  창은 띄우지 않고 pane 구성만 맞춘다. 대상이 없으면 뷰어를 닫는다
#   dev-view.sh --close         뷰어 세션을 종료한다
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

# 세션명은 tmux 명령 문자열·AppleScript 소스에 삽입되므로 영숫자·`_`·`-`로 제한한다.
valid_name() {
  case "$1" in
    ""|*[!A-Za-z0-9_-]*) return 1 ;;
    *) return 0 ;;
  esac
}

# tmux가 pane 안에서 다시 셸로 파싱하는 문자열이라 각 인자를 이스케이프해 넘긴다.
mirror_cmd() {
  printf '%q %q %q %q' "$(command -v python3)" "$MIRROR" "$1" "$INTERVAL"
}

# ---------------------------------------------------------------- 미러 모드
# 뷰어 pane 안에서 자기 자신이 이 모드로 실행된다.
if [ "${1:-}" = "--mirror" ]; then
  exec python3 "$MIRROR" "${2:?mirror target required}" "$INTERVAL"
fi

if ! valid_name "$VIEW_SESSION"; then
  echo "DEV_VIEW_SESSION은 영문·숫자·_·-만 쓸 수 있습니다: $VIEW_SESSION" >&2
  exit 2
fi

# ---------------------------------------------------------------- 종료 모드
if [ "${1:-}" = "--close" ]; then
  tmux kill-session -t "=$VIEW_SESSION" 2>/dev/null && echo "뷰어 세션 종료: $VIEW_SESSION" || echo "뷰어 세션 없음"
  exit 0
fi

OPEN_WINDOW=1
if [ "${1:-}" = "--sync" ]; then
  OPEN_WINDOW=0
  shift
fi

# ---------------------------------------------------------------- 대상 수집
targets=""
if [ $# -gt 0 ]; then
  for t in "$@"; do
    if valid_name "$t"; then
      targets="$targets$t
"
    else
      echo "세션명으로 쓸 수 없어 건너뜁니다: $t" >&2
    fi
  done
else
  targets="$(tmux list-sessions -F '#{session_name}' 2>/dev/null \
    | grep -E '^dev-' | grep -Fxv "$VIEW_SESSION")"
fi
targets="$(printf '%s' "$targets" | sed '/^$/d')"

if [ -z "$targets" ]; then
  # 작업 세션이 잠시 비는 것은 오류가 아니다. 창은 마지막 화면을 띄운 채 두고,
  # 다음 노드가 뜰 때 갱신한다. 창을 접는 것은 --close의 몫이다.
  if [ "$OPEN_WINDOW" = "0" ]; then
    echo "비출 dev-* 세션이 없습니다 — 뷰어는 마지막 화면으로 둡니다."
    exit 0
  fi
  echo "비출 dev-* 세션이 없습니다." >&2
  exit 1
fi

# ---------------------------------------------------------------- 뷰어 구성
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

[ "$OPEN_WINDOW" = "0" ] && { echo "뷰어 동기화 완료: $VIEW_SESSION"; exit 0; }

# ---------------------------------------------------------------- 창 띄우기
# 이미 붙어 있는 클라이언트가 있으면 창을 새로 열지 않는다.
if [ -n "$(tmux list-clients -t "=$VIEW_SESSION" 2>/dev/null)" ]; then
  echo "뷰어 창이 이미 열려 있습니다: $VIEW_SESSION"
  exit 0
fi

app="$TERM_APP"
if [ "$app" = "auto" ]; then
  if [ -d /Applications/iTerm.app ]; then app=iterm; else app=terminal; fi
fi

TMUX_BIN="$(command -v tmux)"

case "$app" in
  iterm)
    osascript -e 'tell application "iTerm"
      set w to (create window with default profile command "'"$TMUX_BIN"' attach -t '"$VIEW_SESSION"'")
      tell current session of w
        set columns to '"$WIN_COLS"'
        set rows to '"$WIN_ROWS"'
      end tell
      activate
    end tell' >/dev/null
    ;;
  terminal)
    osascript -e 'tell application "Terminal"
      do script "'"$TMUX_BIN"' attach -t '"$VIEW_SESSION"'"
      set number of columns of window 1 to '"$WIN_COLS"'
      set number of rows of window 1 to '"$WIN_ROWS"'
      activate
    end tell' >/dev/null
    ;;
  none)
    echo "창 없이 구성만 완료. 직접 붙으려면: tmux attach -t $VIEW_SESSION"
    exit 0
    ;;
esac

echo "뷰어 창을 띄웠습니다: $VIEW_SESSION ($(printf '%s\n' "$targets" | grep -c '')개 세션)"
