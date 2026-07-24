---
description: Create comprehensive feature implementation plan with codebase analysis and pattern extraction
argument-hint: <feature description | path/to/prd.md>
---

> Wirasm의 PRPs-agentic-eng에서 차용. PRP 워크플로우 시리즈의 일부.

# PRP Plan

기능을 한 번에 구현하는 데 필요한 모든 코드베이스 패턴·컨벤션·컨텍스트를 담은, 상세하고 자기완결적인(self-contained) 구현 계획을 생성한다.

**핵심 철학**: 좋은 계획은 추가 질문 없이 구현하는 데 필요한 모든 것을 담는다. 모든 패턴·컨벤션·주의점(GOTCHA)을 한 번 포착하여 전체에서 참조한다.

**Golden Rule**: 구현 중 코드베이스를 검색해야 한다면, 그 지식은 지금 계획에 포착해야 한다.

---

## Phase 0 — DETECT

`$ARGUMENTS`에서 입력 유형을 결정한다:

| 입력 패턴 | 감지 | 동작 |
|----------|------|------|
| `.prd.md`로 끝나는 경로 | PRD 파일 경로 | PRD 파싱, 다음 pending 단계 찾기 |
| "Implementation Phases" 포함된 `.md` 경로 | PRD 유사 문서 | 단계 파싱, 다음 pending 찾기 |
| 그 외 파일 경로 | 참조 파일 | 컨텍스트용으로 읽기, free-form 취급 |
| 자유 텍스트 | 기능 설명 | Phase 1로 직진 |
| 빈 입력 | 입력 없음 | 사용자에게 계획할 기능 묻기 |

### PRD 파싱 (입력이 PRD일 때)

1. PRD 파일을 `cat "$PRD_PATH"`로 읽기
2. **Implementation Phases** 섹션 파싱
3. 상태별로 단계 찾기:
   - `pending` 단계 검색
   - 의존 체인 점검 (선행 단계가 `complete`여야 할 수 있음)
   - **다음 적격 pending 단계** 선택
4. 선택된 단계에서 추출:
   - 단계명·설명
   - 수용 기준(Acceptance Criteria)
   - 선행 단계 의존
   - 범위 노트·제약
5. 단계 설명을 계획할 기능으로 사용

남은 pending 단계가 없으면 모든 단계 완료를 보고한다.

---

## Phase 1 — PARSE

기능 요구사항을 추출·명확화한다.

### 기능 이해

입력(PRD 단계 또는 자유 설명)에서 식별한다:

- **무엇(What)**을 만드는가 (구체 제공물)
- **왜(Why)** 중요한가 (사용자 가치)
- **누가(Who)** 사용하는가 (대상 사용자·시스템)
- **어디(Where)**에 들어가는가 (코드베이스의 어느 부분)

### 사용자 스토리

다음 형식으로:
```
As a [type of user],
I want [capability],
So that [benefit].
```

### 복잡도 평가

| 레벨 | 지표 | 일반 범위 |
|------|------|----------|
| **Small** | 단일 파일, 격리된 변경, 새 의존성 없음 | 1~3개 파일, <100줄 |
| **Medium** | 다중 파일, 기존 패턴 준수, 작은 새 개념 | 3~10개 파일, 100~500줄 |
| **Large** | 횡단 관심사, 새 패턴, 외부 통합 | 10+ 파일, 500+ 줄 |
| **XL** | 아키텍처 변경, 새 서브시스템, 마이그레이션 | 20+ 파일, 분할 고려 |

### Ambiguity Gate

다음 중 하나라도 불명확하면 진행 전 **STOP하고 사용자에게 묻는다**:

- 핵심 제공물이 모호
- 성공 기준이 미정의
- 여러 유효한 해석이 가능
- 기술 접근에 주요 미지

추측하지 말 것. 묻기. 가정 위에 세운 계획은 구현 중에 무너진다.

---

## Phase 2 — EXPLORE

깊은 코드베이스 지능을 수집한다. 아래 카테고리별로 코드베이스를 직접 검색한다.

### 코드베이스 검색 (8 카테고리)

각 카테고리에 대해 grep·find·파일 읽기로 검색한다:

1. **유사 구현(Similar Implementations)** — 계획된 것과 닮은 기존 기능을 찾는다. 유사 패턴·엔드포인트·컴포넌트·모듈.

2. **네이밍 컨벤션(Naming Conventions)** — 관련 영역에서 파일·함수·변수·클래스·export가 어떻게 명명되는지 식별.

3. **에러 핸들링(Error Handling)** — 유사 코드 경로에서 에러가 어떻게 잡히고·전파되고·로깅되고·사용자에게 반환되는지 확인.

4. **로깅 패턴(Logging Patterns)** — 무엇이 어느 레벨로·어떤 형식으로 로깅되는지 식별.

5. **타입 정의(Type Definitions)** — 관련 타입·인터페이스·스키마와 조직 방식 찾기.

6. **테스트 패턴(Test Patterns)** — 유사 기능이 어떻게 테스트되는지 찾기. 테스트 파일 위치·명명·setup/teardown 패턴·assertion 스타일.

7. **설정(Configuration)** — 관련 설정 파일·환경 변수·기능 플래그 찾기.

8. **의존성(Dependencies)** — 유사 기능이 사용하는 패키지·임포트·내부 모듈 식별.

### 코드베이스 분석 (5 추적)

관련 파일을 읽어 다음을 추적한다:

1. **진입 지점(Entry Points)** — 요청·동작이 어떻게 시스템에 진입하고 수정 영역에 도달하는가?
2. **데이터 흐름(Data Flow)** — 데이터가 관련 코드 경로를 어떻게 이동하는가?
3. **상태 변경(State Changes)** — 어떤 상태가 어디서 변경되는가?
4. **계약(Contracts)** — 어떤 인터페이스·API·프로토콜을 준수해야 하는가?
5. **패턴(Patterns)** — 어떤 아키텍처 패턴이 사용되는가 (repository·service·controller 등)?

### 통합 발견 표

발견을 단일 참조로 정리한다:

| 카테고리 | File:Lines | 패턴 | 핵심 스니펫 |
|---------|-----------|-----|------------|
| Naming | `src/services/userService.ts:1-5` | camelCase services, PascalCase types | `export class UserService` |
| Error | `src/middleware/errorHandler.ts:10-25` | Custom AppError class | `throw new AppError(...)` |
| ... | ... | ... | ... |

---

## Phase 3 — RESEARCH

기능이 외부 라이브러리·API·익숙치 않은 기술을 포함하면:

1. 공식 문서를 웹에서 검색
2. 사용 예시·모범 사례 찾기
3. 버전별 주의점(gotcha) 식별

각 발견을 다음 형식으로 정리:

```
KEY_INSIGHT: [학습한 내용]
APPLIES_TO: [계획의 어느 부분에 적용]
GOTCHA: [경고·버전별 이슈]
```

기능이 잘 이해된 내부 패턴만 사용하면 이 단계를 건너뛰고 다음을 메모: "외부 조사 불필요 — 기능이 확립된 내부 패턴 사용."

---

## Phase 4 — DESIGN

### UX 전환(해당 시)

사용자 경험 전후를 문서화한다:

**Before:**
```
┌─────────────────────────────┐
│  [현재 사용자 경험]          │
│  현재 흐름·사용자가 보는 것  │
│  ·하는 것 표시               │
└─────────────────────────────┘
```

**After:**
```
┌─────────────────────────────┐
│  [새 사용자 경험]            │
│  개선된 흐름·사용자에게      │
│  바뀌는 것 표시              │
└─────────────────────────────┘
```

### 상호작용 변경

| Touchpoint | Before | After | 노트 |
|------------|--------|-------|------|
| ... | ... | ... | ... |

기능이 순수 백엔드·내부 변경으로 UX 변경이 없으면 다음을 메모: "Internal change — no user-facing UX transformation."

---

## Phase 5 — ARCHITECT

### 전략 설계

구현 접근을 정의한다:

- **Approach**: 고수준 전략 (예: "기존 repository 패턴을 따르는 새 서비스 레이어 추가")
- **Alternatives Considered**: 평가된 다른 접근·기각 이유
- **Scope**: 만들 것의 구체 경계
- **NOT Building**: 범위 외(OUT OF SCOPE) 명시 목록 (구현 중 scope creep 방지)

### 병렬화 분석

Step-by-Step Tasks를 작성하기 전 태스크 간 의존성 그래프를 점검해 병렬 트랙 가능성을 판별한다.

**적용 제외**:
- Complexity가 Small (1-3 파일, <100줄)
- 단일 파일 내 작업

**적용 조건**:
- 의존성 그래프에서 동시에 시작 가능한 태스크 2개 이상
- 각 트랙이 독립 파일·모듈에 국한

트랙 간 의존성이 발견되면 즉시 분할 취소하고 직렬화한다.

---

## Phase 6 — GENERATE

아래 템플릿으로 완전한 계획 문서를 작성한다. `.claude/PRPs/plans/{kebab-case-feature-name}.plan.md`에 저장한다.

디렉토리가 없으면 생성:
```bash
mkdir -p .claude/PRPs/plans
```

### Plan 템플릿

````markdown
# Plan: [기능명]

## Summary
[2~3문장 개요]

## User Story
As a [user], I want [capability], so that [benefit].

## Problem → Solution
[현재 상태] → [원하는 상태]

## Metadata
- **Complexity**: [Small | Medium | Large | XL]
- **Source PRD**: [경로 또는 "N/A"]
- **PRD Phase**: [단계명 또는 "N/A"]
- **Estimated Files**: [개수]

---

## UX Design

### Before
[ASCII 다이어그램 또는 "N/A — internal change"]

### After
[ASCII 다이어그램 또는 "N/A — internal change"]

### Interaction Changes
| Touchpoint | Before | After | 노트 |
|------------|--------|-------|------|

---

## Mandatory Reading

구현 전 반드시 읽어야 할 파일:

| 우선순위 | 파일 | 줄 | 이유 |
|---------|-----|----|------|
| P0 (critical) | `path/to/file` | 1-50 | 따라야 할 핵심 패턴 |
| P1 (important) | `path/to/file` | 10-30 | 관련 타입 |
| P2 (reference) | `path/to/file` | all | 유사 구현 |

## External Documentation

| 주제 | 출처 | 핵심 |
|------|------|------|
| ... | ... | ... |

---

## Patterns to Mirror

코드베이스에서 발견된 코드 패턴. 정확히 따른다.

### NAMING_CONVENTION
// SOURCE: [file:lines]
[네이밍 패턴을 보여주는 실제 코드 스니펫]

### ERROR_HANDLING
// SOURCE: [file:lines]
[에러 핸들링을 보여주는 실제 코드 스니펫]

### LOGGING_PATTERN
// SOURCE: [file:lines]
[로깅을 보여주는 실제 코드 스니펫]

### REPOSITORY_PATTERN
// SOURCE: [file:lines]
[데이터 접근을 보여주는 실제 코드 스니펫]

### SERVICE_PATTERN
// SOURCE: [file:lines]
[서비스 레이어를 보여주는 실제 코드 스니펫]

### TEST_STRUCTURE
// SOURCE: [file:lines]
[테스트 setup을 보여주는 실제 코드 스니펫]

---

## Files to Change

| 파일 | 동작 | 근거 |
|------|------|------|
| `path/to/file.ts` | CREATE | 기능을 위한 새 서비스 |
| `path/to/existing.ts` | UPDATE | 새 메서드 추가 |

## NOT Building

- [범위 외 명시 항목 1]
- [범위 외 명시 항목 2]

---

## Step-by-Step Tasks

**(직렬일 때)**

### Task 1: [이름]
- **ACTION**: [무엇을 할지]
- **IMPLEMENT**: [작성할 구체 코드·로직]
- **MIRROR**: [Patterns to Mirror 섹션에서 따를 패턴]
- **IMPORTS**: [필요한 임포트]
- **GOTCHA**: [피해야 할 알려진 함정]
- **VALIDATE**: [이 태스크의 정확성 검증 방법]

### Task 2: [이름]
- **ACTION**: ...
- **IMPLEMENT**: ...
- **MIRROR**: ...
- **IMPORTS**: ...
- **GOTCHA**: ...
- **VALIDATE**: ...

[모든 태스크에 반복...]

**(병렬일 때 — Phase로 묶고 Track으로 분할)**

### Phase 1: [동기화 경계 이름]

- **Track A** (agent: tdd-guide, isolation: worktree)
  - Task 1: [이름]
    - ACTION / IMPLEMENT / MIRROR / IMPORTS / GOTCHA / VALIDATE
- **Track B** (agent: tdd-guide, isolation: worktree)
  - Task 2: [이름]
    - ACTION / IMPLEMENT / MIRROR / IMPORTS / GOTCHA / VALIDATE
- **Convergence**: 메인이 Track A·B 브랜치 머지, 통합 검증

### Phase 2: [...]
...

---

## Testing Strategy

### Unit Tests

| 테스트 | 입력 | 기대 출력 | 경계 케이스? |
|-------|-----|----------|-------------|
| ... | ... | ... | ... |

### Edge Cases Checklist
- [ ] 빈 입력
- [ ] 최대 크기 입력
- [ ] 잘못된 타입
- [ ] 동시 접근
- [ ] 네트워크 실패 (해당 시)
- [ ] 권한 거부

---

## Validation Commands

### Static Analysis
```bash
# 타입 체커 실행
[프로젝트별 type-check 명령]
```
EXPECT: 타입 에러 0건

### Unit Tests
```bash
# 영향 영역 테스트 실행
[프로젝트별 test 명령]
```
EXPECT: 모든 테스트 통과

### Full Test Suite
```bash
# 전체 테스트 스위트 실행
[프로젝트별 full test 명령]
```
EXPECT: 회귀 없음

### Database Validation (해당 시)
```bash
# 스키마·마이그레이션 검증
[프로젝트별 db 명령]
```
EXPECT: 스키마 최신

### Browser Validation (해당 시)
```bash
# dev server 시작·검증
[프로젝트별 dev server 명령]
```
EXPECT: 기능이 설계대로 작동

### Manual Validation
- [ ] [단계별 수동 검증 체크리스트]

---

## Acceptance Criteria
- [ ] 모든 태스크 완료
- [ ] 모든 validation 명령 통과
- [ ] 테스트 작성·통과
- [ ] 타입 에러 0건
- [ ] lint 에러 0건
- [ ] UX 설계와 일치 (해당 시)

## Completion Checklist
- [ ] 코드가 발견된 패턴을 따름
- [ ] 에러 핸들링이 코드베이스 스타일과 일치
- [ ] 로깅이 코드베이스 컨벤션 따름
- [ ] 테스트가 테스트 패턴 따름
- [ ] 하드코딩된 값 없음
- [ ] 문서 갱신 (필요 시)
- [ ] 불필요한 범위 추가 없음
- [ ] 자기완결적 — 구현 중 질문 불필요

## Risks
| 리스크 | 가능성 | 영향 | 완화 |
|--------|--------|------|------|
| ... | ... | ... | ... |

## Notes
[추가 컨텍스트·결정·관찰]
```

---

## Output

### 계획 저장

생성된 계획을 다음에 작성한다:
```
.claude/PRPs/plans/{kebab-case-feature-name}.plan.md
```

### PRD 갱신 (입력이 PRD였을 때)

이 계획이 PRD 단계로부터 생성됐으면:
1. 단계 status를 `pending`에서 `in-progress`로 갱신
2. 단계에 계획 파일 경로를 참조로 추가

### 사용자 보고

```
## Plan Created

- **File**: .claude/PRPs/plans/{kebab-case-feature-name}.plan.md
- **Source PRD**: [경로 또는 "N/A"]
- **Phase**: [단계명 또는 "standalone"]
- **Complexity**: [레벨]
- **Scope**: [N개 파일, M개 태스크]
- **Key Patterns**: [발견된 상위 3개 패턴]
- **External Research**: [조사 주제 또는 "none needed"]
- **Risks**: [상위 리스크 또는 "none identified"]
- **Confidence Score**: [1-10] — 단일 패스 구현 가능성

> 다음: `/prp-implement .claude/PRPs/plans/{name}.plan.md`을 실행하여 이 계획을 실행하라.
```

---

## 병렬 구현 실행 메모

병렬 트랙이 포함된 계획은 `/prp-implement` 실행 시 다음 절차를 따른다:

1. Phase 내 모든 Track을 1회 응답에 묶어 병렬 스폰 (Agent 툴, `subagent_type: "tdd-guide"`, `isolation: "worktree"`)
2. 각 Agent 호출 프롬프트에 **계획 파일 경로**·**담당 Track 식별자**(예: "Phase 1 · Track A")·**검증 명령**(Validation Commands Level 1·2) 명시
3. 각 서브에이전트는 격리된 워크트리에서 계획을 Read하여 자체 구현·검증·**커밋**한 뒤, 종료 시 다음 중 하나로 반환:
   - **success**: 워크트리 경로 + 브랜치명 (변경 커밋됨)
   - **no-op**: 변경 없음
   - **failed**: 실패 사유 (미커밋)
4. 메인이 success 트랙 브랜치를 모두 머지, 충돌 해소 (Convergence). 머지 충돌 자동 해소 불가 또는 failed 트랙 ≥1이면 사용자에게 보고하고 중단
5. Convergence 후 다음 Phase로 진행

트랙 간 의존성이 발견되면 즉시 분할 취소하고 직렬화한다.

---

## Verification

확정 전 다음 체크리스트로 계획을 검증한다:

### Context Completeness
- [ ] 모든 관련 파일 발견·문서화
- [ ] 네이밍 컨벤션이 예시와 함께 포착됨
- [ ] 에러 핸들링 패턴 문서화
- [ ] 테스트 패턴 식별
- [ ] 의존성 나열

### Implementation Readiness
- [ ] 모든 태스크에 ACTION·IMPLEMENT·MIRROR·VALIDATE 있음
- [ ] 추가 코드베이스 검색이 필요한 태스크 없음
- [ ] Import 경로 명시
- [ ] 해당 시 GOTCHA 문서화

### Pattern Faithfulness
- [ ] 코드 스니펫이 실제 코드베이스 예시 (지어내지 않음)
- [ ] SOURCE 참조가 실제 파일·줄 번호를 가리킴
- [ ] 패턴이 네이밍·에러·로깅·데이터 접근·테스트를 다룸
- [ ] 새 코드가 기존 코드와 구분 안 될 정도

### Validation Coverage
- [ ] 정적 분석 명령 명시
- [ ] 테스트 명령 명시
- [ ] 빌드 검증 포함

### UX Clarity
- [ ] before/after 상태 문서화 (또는 N/A 표시)
- [ ] 상호작용 변경 나열
- [ ] UX 경계 케이스 식별

### No Prior Knowledge Test
이 코드베이스에 익숙하지 않은 개발자가 코드베이스 검색·질문 없이 오직 이 계획만으로 기능을 구현할 수 있어야 한다. 그렇지 않으면 누락된 컨텍스트를 추가하라.

---

## 다음 단계

- `/prp-implement <plan-path>` 실행하여 이 계획 실행
- `/plan` 실행하여 산출물 없이 빠른 대화형 계획
- 범위가 불분명하면 `/prp-prd` 먼저 실행하여 PRD 생성
````
