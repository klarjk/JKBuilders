# 디버깅 노트·프로젝트 메모리 규칙

디버깅 완료 후, **재발 가능성이 있는 패턴**만 추출해 프로젝트별 메모리에 저장한다.

## 저장 위치

`~/.claude/projects/<cwd-slug>/memory/project_known_issue_<topic-slug>.md`

- `<cwd-slug>`: 현재 작업 디렉토리 절대경로의 `/`를 `-`로 치환한 값
- `<topic-slug>`: 이슈를 식별하는 짧은 영문 소문자 슬러그 (예: `sqlite_alter_table`)

## 엔트리 파일 구조

```markdown
---
name: 이슈/quirk 이름
description: 한 줄 요약 — MEMORY.md 인덱스 hook으로 사용
metadata:
  type: project
---

본문 (증상·원인·맥락)

**Why:** 왜 이 패턴이 중요한지, 어떤 상황에서 재발하는지 (1~3문장)

**How to apply:** 어떻게 대응·회피할지 구체 절차 (명령어·코드·파일 경로 포함)
```

## MEMORY.md 인덱스 등록

엔트리 1개당 같은 `memory/` 디렉토리의 `MEMORY.md`에 1줄 추가:

```markdown
- [간단 제목](project_known_issue_<topic-slug>.md) — 한 줄 요약
```

## 저장 대상·제외

- 저장 대상: 특정 API·라이브러리의 quirks, 코드만 봐서는 알 수 없는 "왜 이렇게 짰는지"의 맥락, 리팩토링 중 실수로 제거될 위험이 있는 설계 이유
- 저장 제외: 일회성 버그, 단순 오타, DEBUG.md 내용 전체
