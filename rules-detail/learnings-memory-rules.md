# Learnings 메모리 규칙

Claude의 학습 데이터에 없거나 컷오프 이후 변경된 **외부 사실**을 세션 중에 검증한 경우 메모리에 누적한다. 코드·git만 봐도 알 수 있는 정보, 사용자 선호(=`feedback`), 프로젝트 코드 quirk(=`project_known_issue_*`)는 대상이 아니다.

## 저장 트리거 (다음 중 하나 충족 시에만)

1. **공식 문서·릴리스 노트 직접 확인** — `WebFetch`로 1차 출처 URL을 본 세션에서 열람 (예: docs.claude.com, GitHub release notes).
2. **세션 내 직접 실험·실행** — 재현 가능한 명령/입력으로 결과를 직접 관찰
3. **2차 출처 다중 확인** — 신뢰 가능한 블로그·이슈 트래커 등에서 동일 사실이 2건 이상 일치할 때만 (단독 인용 불가)

추측·일반 통념·1회성 관찰만으로는 저장하지 않는다. **저장은 수동 트리거 전용** — 자동 저장 엔진이 `type: learning`과 신규 메타 필드를 인식하지 않을 수 있으므로, Claude가 명시적으로 Write 호출로 기록한다.

## 저장 위치 분기

| 정보 성격 | 위치 |
|----------|------|
| 도구·SDK·공식 문서 사실 (모든 프로젝트에서 유효) | `~/.claude/memory/learning_<topic>.md` + `~/.claude/memory/MEMORY.md` 인덱스 |
| 특정 프로젝트의 라이브러리·환경에서만 검증된 사실 | `~/.claude/projects/<slug>/memory/learning_<topic>.md` + 해당 `MEMORY.md` 인덱스 |

`<topic>`은 영문 소문자·숫자·`_`만 사용 (예: `cc_hooks_sessionstart`, `langchain_0_3_streaming`). 전역 디렉토리·`MEMORY.md`가 없으면 신규 생성한다.

**분기 예시:**
- 전역: Claude Code CLI 동작·플래그, Anthropic SDK API 변경, MCP 사양, Obsidian 플러그인 표준 동작
- 프로젝트: 해당 프로젝트가 핀한 langchain 0.3 특정 quirk, 프로젝트 빌드 환경에서만 재현되는 도구 동작
- **Do:** 동일 도구라도 "버전 무관 일반 동작" → 전역, "프로젝트가 사용하는 특정 버전 quirk" → 프로젝트
- **Don't:** 프로젝트 코드 자체의 재발성 quirk·설계 맥락은 본 섹션이 아니라 `rules/memory-rules.md`의 `project_known_issue_*` 패턴 사용

## 파일 구조

```markdown
---
name: 학습 사실 이름
description: 한 줄 요약 — MEMORY.md 인덱스 hook으로 사용
type: learning
source: official_docs | experiment | research
source_url: https://...           # source가 official_docs/research일 때 필수
verified_date: 2026-04-25         # 저장·재검증 시점 (ISO date, 필수)
reproduce: |                       # source가 experiment일 때 필수
  실제 재현 명령 또는 입력
---

검증된 사실 본문 (1~5문장)

**Why:** 왜 이 사실이 향후 세션에서 중요한지

**How to apply:** 어떤 상황에서 어떻게 활용할지 (구체 예시·명령 포함)
```

## MEMORY.md 인덱스 등록 (필수)

```markdown
- [간단 제목](learning_<topic>.md) — YYYY-MM 확인, 한 줄 요약
```

`확인 날짜`를 hook에 포함하여 stale 판별을 돕는다.

## 사용 전 검증 (필수)

learning 메모리를 사용자 답변·구현에 반영하기 전:

- `verified_date`가 **6개월 이상 경과**한 항목은 `source_url` 재확인 또는 `reproduce` 재실행
- 공식 docs 항목이 사용자가 보는 현재 동작과 충돌하면 메모리를 업데이트(또는 삭제)하고 재확인 결과를 우선

## 저장 제외

- 학습 데이터 컷오프(2026-01) **이전**부터 존재한 일반 프로그래밍 지식
- 프로젝트 코드/구조에서 derive 가능한 정보
- 사용자 의견·선호 (→ `feedback`)
- 1회성 실험 결과로 일반화 불가한 케이스
- 시크릿·개인정보 (전역 위치는 모든 프로젝트 세션에 노출됨)
