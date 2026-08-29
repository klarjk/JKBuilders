#!/bin/bash
# dev-loop 결함·관측 기록 — 무인 세션이 발견한 것을 그 자리에서 한 줄 덧붙인다.
# 규약: <스킬 디렉토리>/dev-loop/protocol.md 「결함 기록」
# 기록 실패는 본업을 세우지 않는다 — 어떤 경로로도 exit 0으로 끝난다.
set -u

DIR="$HOME/.claude/dev-loop"
LOG="$DIR/incidents.jsonl"
RESOLVED="$DIR/incidents-resolved.txt"
SEEN="$DIR/.seen"

warn() { printf 'dl-incident: %s\n' "$1" >&2; }
quit() { warn "$1"; exit 0; }

sanitize() {  # 개행·제어문자 제거, 봇 토큰 가림. 길이 절단은 jq가 유니코드 안전하게 한다
  printf '%s' "${1-}" | tr '\n\r\t' '   ' | tr -d '\000-\010\013\014\016-\037' \
    | sed -E -e 's/[0-9]{6,12}:[A-Za-z0-9_-]{30,}/<redacted>/g' \
             -e 's/(sk|pk|rk)-[A-Za-z0-9_-]{16,}/<redacted>/g' \
             -e 's/(gh[pousr]|xox[abposr])_[A-Za-z0-9_-]{16,}/<redacted>/g' \
             -e 's/AKIA[0-9A-Z]{16}/<redacted>/g' \
             -e 's/[Bb]earer [A-Za-z0-9._~+/=-]{16,}/Bearer <redacted>/g' \
             -e 's#://[^/@:[:space:]]+:[^/@[:space:]]+@#://<redacted>@#g'
}

hash() { printf '%s' "$1" | { md5 -q 2>/dev/null || md5sum | cut -d' ' -f1; }; }

mkdir -p "$DIR" "$SEEN" 2>/dev/null || quit "기록 디렉토리를 만들 수 없다"
command -v jq >/dev/null 2>&1 || quit "jq 없음"

# ── 조회 모드 ────────────────────────────────────────────────
tally() {
  [ -f "$LOG" ] || { echo "사건 기록 없음"; exit 0; }
  jq -R 'fromjson? // empty' "$LOG" 2>/dev/null | jq -rs --rawfile res <(cat "$RESOLVED" 2>/dev/null; echo) '
    ($res | split("\n") | map(select(length > 0))) as $r
    | map(select(.fp as $f | any($r[]; . == $f) | not))
    | group_by(.fp)
    | map({fp: .[0].fp, n: length, kind: (map(.kind) | unique | join("/")),
           doc: .[0].doc, last: (map(.ts) | max),
           where: (map(.slug) | unique | join(","))})
    | sort_by(-.n)[]
    | "\(.n)건  \(.fp)  [\(.kind)]  \(.doc)  최근 \(.last)  프로젝트 \(.where)"
  ' || quit "집계 실패"
  exit 0
}

count() {
  [ -f "$LOG" ] || { echo 0; exit 0; }
  jq -R 'fromjson? // empty' "$LOG" 2>/dev/null | jq -rs --rawfile res <(cat "$RESOLVED" 2>/dev/null; echo) '
    ($res | split("\n") | map(select(length > 0))) as $r
    | map(select(.fp as $f | any($r[]; . == $f) | not)) | map(.fp) | unique | length
  ' || quit "집계 실패 — 건수를 알 수 없다"
  exit 0
}

case "${1-}" in
  --tally) tally ;;
  --count) count ;;
  --resolve)
    [ -n "${2-}" ] || quit "--resolve에 지문이 없다"
    printf '%s\n' "$(sanitize "$2")" >> "$RESOLVED" || quit "처리 표시 실패"
    echo "resolved: $2"; exit 0 ;;
esac

# ── 기록 모드 ────────────────────────────────────────────────
layer=""; kind=""; fp=""; expected=""; observed=""; doc=""
slug=""; unit=""; evidence=""; action=""; session="${CLAUDE_CODE_SESSION_ID-}"

while [ $# -gt 0 ]; do
  opt="$1"; shift
  # 값은 다음 인자가 플래그가 아닐 때만 가져간다 — 값 없는 플래그가 다음 플래그를 삼키지 않는다
  case "${1-}" in ''|--*) val="" ;; *) val="$1"; shift ;; esac
  case "$opt" in
    --layer)    layer="$val" ;;
    --kind)     kind="$val" ;;
    --fp)       fp="$val" ;;
    --expected) expected="$val" ;;
    --observed) observed="$val" ;;
    --doc)      doc="$val" ;;
    --slug)     slug="$val" ;;
    --unit)     unit="$val" ;;
    --evidence) evidence="$val" ;;
    --action)   action="$val" ;;
    --session)  session="$val" ;;
    *) warn "모르는 인자: $opt" ;;
  esac
  [ -n "$val" ] || case "$opt" in --*) warn "$opt 에 값이 없다" ;; esac
done

case "$layer" in 창구|지휘|작업) ;; *) warn "layer 어휘 밖: '$layer' → 미상"; layer="미상" ;; esac
case "$kind" in 규약이탈|지시모순|규약공백|도구실패|관측) ;; *) warn "kind 어휘 밖: '$kind' → 기타"; kind="기타" ;; esac
[ -n "$fp" ] || { fp="unfingerprinted"; warn "지문이 비었다 — 집계에서 뭉친다"; }

fp=$(sanitize "$fp"); doc=$(sanitize "$doc"); slug=$(sanitize "$slug"); unit=$(sanitize "$unit")
expected=$(sanitize "$expected"); observed=$(sanitize "$observed")
evidence=$(sanitize "$evidence"); action=$(sanitize "$action")

# 같은 지문은 한 세션에 한 번만 — 감시 루프가 같은 증상을 매 라운드 쏟아내는 것을 막는다
if [ -n "$session" ] && [ "$kind" != "관측" ]; then
  find "$SEEN" -type f -mtime +7 -delete 2>/dev/null
  marker="$SEEN/$(hash "$session|$fp")"
  [ -e "$marker" ] && { echo "dup: $fp"; exit 0; }
  : > "$marker" 2>/dev/null
fi

build() {  # $1 = evidence 절단 길이
  jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg slug "$slug" --arg layer "$layer" --arg unit "$unit" --arg kind "$kind" \
    --arg fp "$fp" --arg expected "$expected" --arg observed "$observed" \
    --arg evidence "$evidence" --arg action "$action" --arg doc "$doc" --argjson ev "$1" \
    '{ts:$ts, slug:$slug, layer:$layer, unit:$unit, kind:$kind, fp:($fp[0:80]),
      expected:($expected[0:300]), observed:($observed[0:300]),
      evidence:($evidence[0:$ev]), action:($action[0:200]), doc:($doc[0:120])}'
}

line=$(build 500) || quit "조립 실패"
[ "${#line}" -gt 4000 ] && line=$(build 100)
[ "${#line}" -gt 4000 ] && quit "4KB 초과 — 기록하지 않는다"

printf '%s\n' "$line" >> "$LOG" || quit "덧붙이기 실패"
echo "logged: $fp"
