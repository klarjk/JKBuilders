---
description: Execute an implementation plan with rigorous validation loops
argument-hint: <path/to/plan.md>
---

> Wirasm의 PRPs-agentic-eng에서 차용. PRP 워크플로우 시리즈의 일부.

# PRP Implement

계획 파일을 단계별로 실행하며 연속 검증한다. 모든 변경은 즉시 검증된다 — 깨진 상태를 누적하지 않는다.

**핵심 철학**: 검증 루프는 실수를 일찍 잡는다. 모든 변경 후 점검을 실행. 이슈는 즉시 수정.

**Golden Rule**: 검증이 실패하면 다음으로 넘어가기 전에 수정. 절대로 깨진 상태를 누적하지 말 것.

---

## Phase 0 — DETECT

### 패키지 매니저 감지

| 파일 존재 | 패키지 매니저 | Runner |
|----------|-------------|--------|
| `bun.lockb` | bun | `bun run` |
| `pnpm-lock.yaml` | pnpm | `pnpm run` |
| `yarn.lock` | yarn | `yarn` |
| `package-lock.json` | npm | `npm run` |
| `pyproject.toml` 또는 `requirements.txt` | uv / pip | `uv run` 또는 `python -m` |
| `Cargo.toml` | cargo | `cargo` |
| `go.mod` | go | `go` |

### 검증 스크립트

`package.json` (또는 동등 파일)에서 사용 가능한 스크립트 점검:

```bash
# Node.js 프로젝트의 경우
cat package.json | grep -A 20 '"scripts"'
```

다음에 대한 가용 명령을 메모: type-check, lint, test, build.

---

## Phase 1 — LOAD

계획 파일을 읽는다:

```bash
cat "$ARGUMENTS"
```

계획에서 다음 섹션 추출:
- **Summary** — 무엇을 만드는가
- **Patterns to Mirror** — 따라야 할 코드 컨벤션
- **Files to Change** — 만들거나 수정할 것
- **Step-by-Step Tasks** — 구현 순서
- **Validation Commands** — 정확성 검증 방법
- **Acceptance Criteria** — 완료 정의

파일이 없거나 유효한 계획이 아니면:
```
Error: Plan file not found or invalid.
먼저 /prp-plan <feature-description>를 실행하여 계획을 생성하시오.
```

**CHECKPOINT**: 계획 로드됨. 모든 섹션 식별. 태스크 추출 완료.

---

## Phase 2 — PREPARE

### Git 상태

```bash
git branch --show-current
git status --porcelain
```

### 브랜치 결정

| 현재 상태 | 동작 |
|---------|------|
| 기능 브랜치 위 | 현재 브랜치 사용 |
| main 위, 작업 트리 깨끗 | 기능 브랜치 생성: `git checkout -b feat/{plan-name}` |
| main 위, 작업 트리 더러움 | **STOP** — 사용자에게 stash 또는 commit 요청 |
| 이 기능을 위한 git worktree 안 | worktree 사용 |

### 원격 동기화

```bash
git pull --rebase origin $(git branch --show-current) 2>/dev/null || true
```

**CHECKPOINT**: 정확한 브랜치 위. 작업 트리 준비됨. 원격 동기화됨.

---

## Phase 3 — EXECUTE

계획의 태스크를 처리한다. 계획이 직렬 Task 나열이면 순차 처리, Phase/Track 분할이면 병렬 처리.

### 직렬 태스크 (기본)

**Step-by-Step Tasks**의 각 태스크에 대해:

1. **MIRROR 참조 읽기** — 태스크의 MIRROR 필드가 가리키는 패턴 파일을 연다. 코드를 작성하기 전에 컨벤션을 이해한다.

2. **구현(Implement)** — 패턴을 정확히 따라 코드를 작성. GOTCHA 경고 적용. 명시된 IMPORTS 사용.

3. **즉시 검증(Validate immediately)** — 모든 파일 변경 후:
   ```bash
   # type-check 실행 (프로젝트별 명령 조정)
   [Phase 0의 type-check 명령]
   ```
   type-check 실패 시 → 다음 파일로 넘어가기 전에 에러 수정.

4. **진행 추적** — 로그: `[done] Task N: [태스크명] — complete`

### 병렬 트랙 (계획에 Phase/Track 표기가 있을 때)

계획의 Step-by-Step Tasks가 Phase로 묶이고 각 Phase 안에 Track A/B로 분할된 경우:

1. **병렬 스폰** — Phase 내 모든 Track을 **1회 응답에 묶어** Agent 툴로 호출:
   - `subagent_type: "tdd-guide"`
   - `isolation: "worktree"` (워크트리 자동 생성·반환)
   - 프롬프트에 다음을 명시:
     - **계획 파일 경로** (`$ARGUMENTS`) — 워크트리에서 Read하여 Patterns to Mirror·Track Task 참조
     - **담당 Track 식별자** (예: "Phase 1 · Track A")
     - **검증 명령** — Phase 0에서 감지한 type-check·lint·test 실제 명령 (서브에이전트가 재감지하지 않도록)
     - **완료 규약** — Level 1·2 통과 후 변경분을 워크트리 브랜치에 커밋하고 경로·브랜치명 반환

2. **격리 작업** — 각 서브에이전트는 자체 워크트리에서 구현 + 즉시 검증(Level 1·2) 후 통과 변경분만 커밋. 검증 실패가 누적되면 미커밋 상태로 실패 보고

3. **반환 수집** — 각 트랙은 다음 중 하나로 반환:
   - **success**: 워크트리 경로 + 브랜치명 (변경 커밋됨)
   - **no-op**: 변경 없음 (스킵)
   - **failed**: 실패 사유 (미커밋)

4. **Convergence** — 메인이 success 트랙 브랜치를 모두 머지, 충돌 해소. 머지 충돌 자동 해소 불가 또는 failed 트랙 ≥1이면 사용자에게 보고하고 다음 Phase 진행 중단

5. **Phase 게이트** — Convergence 후 Phase 4 VALIDATE의 5단계 검증을 통과해야 다음 Phase로 진행

트랙 간 의존성이 발견되면 즉시 분할 취소, 직렬 모드로 회귀.

### 편차(Deviation) 처리

구현이 계획에서 벗어나야 할 때:
- **무엇(WHAT)**이 바뀌었는지 메모
- **왜(WHY)** 바뀌었는지 메모
- 수정된 접근으로 계속
- 이 편차들은 보고서에 포착됨

**CHECKPOINT**: 모든 태스크 실행됨. 편차 로깅됨.

---

## Phase 4 — VALIDATE

계획의 모든 검증 레벨을 실행한다. 각 레벨 진행 전에 이슈 수정.

### Level 1: Static Analysis

```bash
# 타입 체킹 — 에러 0건 필수
[프로젝트 type-check 명령]

# Linting — 가능한 부분 자동 수정
[프로젝트 lint 명령]
[프로젝트 lint-fix 명령]
```

자동 수정 후에도 lint 에러가 남으면 수동 수정.

### Level 2: Unit Tests

계획의 Testing Strategy에 명시된 대로 모든 새 함수에 대한 테스트 작성.

```bash
[프로젝트의 영향 영역 test 명령]
```

- 모든 함수는 최소 1개 테스트 필요
- 계획에 나열된 경계 케이스 커버
- 테스트 실패 시 → 구현 수정 (테스트가 잘못된 경우가 아니면 테스트는 수정하지 않음)

### Level 3: Build Check

```bash
[프로젝트 build 명령]
```

빌드는 에러 0건으로 성공해야 함.

### Level 4: Integration Testing (해당 시)

```bash
# 서버 시작, 테스트 실행, 서버 정지
[프로젝트 dev server 명령] &
SERVER_PID=$!

# 서버 준비 대기 (필요 시 포트 조정)
SERVER_READY=0
for i in $(seq 1 30); do
  if curl -sf http://localhost:PORT/health >/dev/null 2>&1; then
    SERVER_READY=1
    break
  fi
  sleep 1
done

if [ "$SERVER_READY" -ne 1 ]; then
  kill "$SERVER_PID" 2>/dev/null || true
  echo "ERROR: Server failed to start within 30s" >&2
  exit 1
fi

[통합 테스트 명령]
TEST_EXIT=$?

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true

exit "$TEST_EXIT"
```

### Level 5: Edge Case Testing

계획의 Testing Strategy 체크리스트에서 경계 케이스 실행.

**CHECKPOINT**: 5단계 검증 모두 통과. 에러 0건.

---

## Phase 5 — REPORT

### 구현 보고서 생성

```bash
mkdir -p .claude/PRPs/reports
```

`.claude/PRPs/reports/{plan-name}-report.md`에 보고서 작성:

```markdown
# Implementation Report: [기능명]

## Summary
[구현된 내용]

## Assessment vs Reality

| 지표 | 예측 (Plan) | 실제 |
|------|-----------|------|
| Complexity | [계획에서] | [실제] |
| Confidence | [계획에서] | [실제] |
| 변경된 파일 | [계획에서] | [실제 수] |

## 완료된 태스크

| # | 태스크 | Status | 노트 |
|---|-------|--------|------|
| 1 | [태스크명] | [done] Complete | |
| 2 | [태스크명] | [done] Complete | Deviated — [이유] |

## 검증 결과

| 레벨 | Status | 노트 |
|------|--------|------|
| Static Analysis | [done] Pass | |
| Unit Tests | [done] Pass | N개 테스트 작성 |
| Build | [done] Pass | |
| Integration | [done] Pass | 또는 N/A |
| Edge Cases | [done] Pass | |

## 변경된 파일

| 파일 | 동작 | 줄 |
|------|------|----|
| `path/to/file` | CREATED | +N |
| `path/to/file` | UPDATED | +N / -M |

## 계획으로부터의 편차
[WHAT·WHY와 함께 편차 나열 또는 "None"]

## 발생한 이슈
[발생한 문제와 해결 방법 나열 또는 "None"]

## 작성된 테스트

| 테스트 파일 | 테스트 | 커버리지 |
|-----------|-------|---------|
| `path/to/test` | N개 테스트 | [커버 영역] |

## 다음 단계
- [ ] `/code-review`로 코드 리뷰
- [ ] `/prp-pr`로 PR 생성
```

### PRD 갱신 (해당 시)

이 구현이 PRD 단계를 위한 것이었다면:
1. 단계 status를 `in-progress`에서 `complete`로 갱신
2. 보고서 경로를 참조로 추가

### 계획 아카이브

```bash
mkdir -p .claude/PRPs/plans/completed
mv "$ARGUMENTS" .claude/PRPs/plans/completed/
```

**CHECKPOINT**: 보고서 생성됨. PRD 갱신됨. 계획 아카이브됨.

---

## Phase 6 — OUTPUT

사용자에게 보고:

```
## Implementation Complete

- **Plan**: [계획 파일 경로] → completed/로 아카이브됨
- **Branch**: [현재 브랜치명]
- **Status**: [done] 모든 태스크 완료

### 검증 요약

| 점검 | Status |
|------|--------|
| Type Check | [done] |
| Lint | [done] |
| Tests | [done] (N개 작성) |
| Build | [done] |
| Integration | [done] 또는 N/A |

### 변경된 파일
- [N]개 파일 생성, [M]개 파일 갱신

### 편차
[요약 또는 "None — 계획대로 정확히 구현됨"]

### Artifacts
- Report: `.claude/PRPs/reports/{name}-report.md`
- Archived Plan: `.claude/PRPs/plans/completed/{name}.plan.md`

### PRD 진행 (해당 시)
| 단계 | Status |
|------|--------|
| Phase 1 | [done] Complete |
| Phase 2 | [next] |
| ... | ... |

> 다음: `/prp-pr`를 실행하여 pull request 생성, 또는 `/code-review`로 먼저 변경 리뷰.
```

---

## 실패 처리

### Type Check 실패
1. 에러 메시지 신중히 읽기
2. 소스 파일의 타입 에러 수정
3. type-check 재실행
4. clean 상태에서만 계속

### Tests 실패
1. 버그가 구현에 있는지 테스트에 있는지 식별
2. 근본 원인 수정 (대개 구현)
3. 테스트 재실행
4. green 상태에서만 계속

### Lint 실패
1. 자동 수정 먼저 실행
2. 에러가 남으면 수동 수정
3. lint 재실행
4. clean 상태에서만 계속

### Build 실패
1. 보통 타입·임포트 이슈 — 에러 메시지 확인
2. 문제 파일 수정
3. 빌드 재실행
4. 성공 상태에서만 계속

### Integration Test 실패
1. 서버가 정확히 시작됐는지 점검
2. 엔드포인트·라우트 존재 확인
3. 요청 형식이 예상과 일치하는지 점검
4. 수정 후 재실행

---

## 성공 기준

- **TASKS_COMPLETE**: 계획의 모든 태스크 실행됨
- **TYPES_PASS**: 타입 에러 0건
- **LINT_PASS**: lint 에러 0건
- **TESTS_PASS**: 모든 테스트 green, 새 테스트 작성됨
- **BUILD_PASS**: 빌드 성공
- **CONVERGENCE_CLEAN**: (병렬 트랙 적용 시) 모든 success 트랙 머지 완료 + Phase 4 VALIDATE Level 1~3 통과, failed 트랙 0건
- **REPORT_CREATED**: 구현 보고서 저장됨
- **PLAN_ARCHIVED**: 계획이 `completed/`로 이동됨

---

## 다음 단계

- `/code-review` 실행하여 커밋 전 변경 리뷰
- `/prp-commit` 실행하여 설명적 메시지로 커밋
- `/prp-pr` 실행하여 pull request 생성
- PRD에 단계가 더 있으면 `/prp-plan <next-phase>` 실행
