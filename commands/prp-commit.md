---
description: "Quick commit with natural language file targeting — describe what to commit in plain English"
argument-hint: "[target description] (blank = all changes)"
---

# Smart Commit

> Wirasm의 PRPs-agentic-eng에서 차용. PRP 워크플로우 시리즈의 일부.

**Input**: $ARGUMENTS

---

## Phase 1 — ASSESS

```bash
git status --short
```

출력이 비었으면 → 정지: "Nothing to commit."

사용자에게 변경 요약(추가·수정·삭제·untracked)을 보여준다.

---

## Phase 2 — INTERPRET & STAGE

`$ARGUMENTS`를 해석하여 무엇을 stage할지 결정한다:

| Input | 해석 | Git 명령 |
|-------|------|---------|
| *(빈 입력)* | 전체 stage | `git add -A` |
| `staged` | 이미 stage된 것 사용 | *(git add 없음)* |
| `*.ts` 또는 `*.py` 등 | 매칭 glob stage | `git add '*.ts'` |
| `except tests` | 전체 stage 후 테스트 unstage | `git add -A && git reset -- '**/*.test.*' '**/*.spec.*' '**/test_*' 2>/dev/null \|\| true` |
| `only new files` | untracked 파일만 stage | `git ls-files --others --exclude-standard \| grep . && git ls-files --others --exclude-standard \| xargs git add` |
| `the auth changes` | status·diff에서 해석 — auth 관련 파일 찾기 | `git add <매칭 파일>` |
| 구체 파일명 | 해당 파일 stage | `git add <files>` |

자연어 입력(예: "the auth changes")의 경우 `git status` 출력과 `git diff`를 교차 참조하여 관련 파일을 식별. 사용자에게 어떤 파일을 왜 stage하는지 보여준다.

```bash
git add <결정된 파일>
```

Stage 후 검증:
```bash
git diff --cached --stat
```

Stage된 게 없으면 정지: "No files matched your description."

---

## Phase 3 — COMMIT

명령형 어조의 단일 라인 커밋 메시지 작성:

```
{type}: {description}
```

유형:
- `feat` — 새 기능·역량
- `fix` — 버그 수정
- `refactor` — 동작 변화 없는 코드 재구성
- `docs` — 문서 변경
- `test` — 테스트 추가·갱신
- `chore` — 빌드·설정·의존성
- `perf` — 성능 개선
- `ci` — CI/CD 변경

규칙:
- 명령형 ("add feature" — "added feature"가 아님)
- type prefix 뒤는 소문자
- 끝에 마침표 없음
- 72자 미만
- HOW가 아니라 WHAT을 설명

```bash
git commit -m "{type}: {description}"
```

---

## Phase 4 — OUTPUT

사용자에게 보고:

```
Committed: {hash_short}
Message:   {type}: {description}
Files:     {count}개 파일 변경

다음 단계:
  - git push           → 원격에 푸시
  - /prp-pr            → pull request 생성
  - /code-review       → 푸시 전 리뷰
```

---

## 예시

| 입력 | 동작 |
|------|------|
| `/prp-commit` | 전체 stage, 메시지 자동 생성 |
| `/prp-commit staged` | 이미 stage된 것만 커밋 |
| `/prp-commit *.ts` | 모든 TypeScript 파일 stage, 커밋 |
| `/prp-commit except tests` | 테스트 파일 제외 전체 stage |
| `/prp-commit the database migration` | status에서 DB 마이그레이션 파일 찾아 stage |
| `/prp-commit only new files` | untracked 파일만 stage |
