---
description: "Create a GitHub PR from current branch with unpushed commits — discovers templates, analyzes changes, pushes"
argument-hint: "[base-branch] (default: main)"
---

# Pull Request 생성

> Wirasm의 PRPs-agentic-eng에서 차용. PRP 워크플로우 시리즈의 일부.

**Input**: `$ARGUMENTS` — 선택, base 브랜치명·플래그(예: `--draft`) 포함 가능.

**`$ARGUMENTS` 파싱**:
- 인식된 플래그(`--draft`) 추출
- 나머지 비-플래그 텍스트는 base 브랜치명으로 취급
- 미지정 시 base 브랜치는 `main`으로 기본 설정

---

## Phase 1 — VALIDATE

전제 조건 점검:

```bash
git branch --show-current
git status --short
git log origin/<base>..HEAD --oneline
```

| 점검 | 조건 | 실패 시 동작 |
|------|------|------------|
| base 브랜치가 아님 | 현재 브랜치 ≠ base | 정지: "기능 브랜치로 먼저 전환하시오." |
| 작업 디렉토리 깨끗 | 커밋 안 된 변경 없음 | 경고: "커밋 안 된 변경이 있습니다. 먼저 커밋 또는 stash. `/prp-commit`을 사용하여 커밋." |
| 앞선 커밋 존재 | `git log origin/<base>..HEAD` 비어있지 않음 | 정지: "`<base>` 앞 커밋 없음. PR할 게 없음." |
| 기존 PR 없음 | `gh pr list --head <branch> --json number`가 비어있음 | 정지: "PR이 이미 존재합니다: #<number>. 열기: `gh pr view <number> --web`." |

모든 점검 통과 시 진행.

---

## Phase 2 — DISCOVER

### PR 템플릿

다음 순서로 PR 템플릿 검색:

1. `.github/PULL_REQUEST_TEMPLATE/` 디렉토리 — 존재 시 파일 나열 후 사용자가 선택 (또는 `default.md` 사용)
2. `.github/PULL_REQUEST_TEMPLATE.md`
3. `.github/pull_request_template.md`
4. `docs/pull_request_template.md`

찾으면 읽어서 PR body 구조에 사용.

### 커밋 분석

```bash
git log origin/<base>..HEAD --format="%h %s" --reverse
```

커밋을 분석하여 결정:
- **PR 제목**: conventional commit 형식 + 타입 prefix — `feat: ...`, `fix: ...` 등
  - 여러 타입이면 지배적인 것 사용
  - 단일 커밋이면 메시지 그대로 사용
- **변경 요약**: 타입·영역별 커밋 그룹화

### 파일 분석

```bash
git diff origin/<base>..HEAD --stat
git diff origin/<base>..HEAD --name-only
```

변경된 파일 분류: 소스·테스트·문서·설정·마이그레이션.

### PRP 아티팩트

관련 PRP 아티팩트 점검:
- `.claude/PRPs/reports/` — 구현 보고서
- `.claude/PRPs/plans/` — 실행된 계획
- `.claude/PRPs/prds/` — 관련 PRD

존재 시 PR body에 참조.

---

## Phase 3 — PUSH

```bash
git push -u origin HEAD
```

divergence로 push 실패 시:
```bash
git fetch origin
git rebase origin/<base>
git push -u origin HEAD
```

rebase 충돌 발생 시 정지하고 사용자에게 알린다.

---

## Phase 4 — CREATE

### 템플릿 사용

Phase 2에서 PR 템플릿이 발견되면 커밋·파일 분석으로 각 섹션 채움. 모든 템플릿 섹션 보존 — 해당 안 되면 제거하지 말고 "N/A"로 표시.

### 템플릿 없음

다음 기본 형식 사용:

```markdown
## Summary

<이 PR이 하는 일과 이유의 1~2 문장 설명>

## Changes

<영역별로 그룹화된 변경 목록>

## Files Changed

<변경 유형(Added/Modified/Deleted)과 함께 변경 파일 목록·표>

## Testing

<변경 사항이 어떻게 테스트됐는지 설명, 또는 "Needs testing">

## Related Issues

<Closes/Fixes/Relates to #N으로 연결된 이슈, 또는 "None">
```

### PR 생성

```bash
gh pr create \
  --title "<PR 제목>" \
  --base <base-branch> \
  --body "<PR body>"
  # $ARGUMENTS에서 --draft 플래그가 파싱됐으면 추가
```

---

## Phase 5 — VERIFY

```bash
gh pr view --json number,url,title,state,baseRefName,headRefName,additions,deletions,changedFiles
gh pr checks --json name,status,conclusion 2>/dev/null || true
```

---

## Phase 6 — OUTPUT

사용자에게 보고:

```
PR #<number>: <title>
URL: <url>
Branch: <head> → <base>
Changes: +<additions> -<deletions> across <changedFiles> files

CI Checks: <상태 요약 또는 "pending" 또는 "none configured">

참조된 아티팩트:
  - <PR body에 링크된 PRP 보고서·계획>

다음 단계:
  - gh pr view <number> --web   → 브라우저에서 열기
  - /code-review <number>       → PR 리뷰
  - gh pr merge <number>        → 준비되면 머지
```

---

## 경계 케이스

- **`gh` CLI 없음**: 정지: "GitHub CLI (`gh`) 필요. 설치: <https://cli.github.com/>"
- **인증 안 됨**: 정지: "먼저 `gh auth login` 실행."
- **force push 필요**: 원격이 분기됐고 rebase가 완료됐다면 `git push --force-with-lease` 사용 (절대 `--force` 사용 안 함).
- **여러 PR 템플릿**: `.github/PULL_REQUEST_TEMPLATE/`에 여러 파일이 있으면 나열 후 사용자 선택.
- **큰 PR (>20 파일)**: PR 크기에 대해 경고. 논리적으로 분리 가능하면 분할 제안.
