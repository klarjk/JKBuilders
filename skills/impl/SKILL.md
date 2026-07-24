---
name: impl
description: 신규 기능·리팩토링을 architect/synthesizer/planner/tdd-guide/code-reviewer/evaluator/e2e-runner 체인으로 자동 스폰하는 오케스트레이션 스킬. 사용자가 /impl, "구현해줘", "만들어줘", "리팩토링", "수정해줘", "추가해줘", "기능" 등 코드 작성·수정·리팩토링 의도를 표현하면 이 스킬을 사용한다. (디버그·버그 수정은 본 스킬 적용 대상이 아니다)
---

# /impl

메인 에이전트는 **워크플로우 진행자**만 한다. 직접 코드를 짜거나 산출물 본문을 Read 하지 않는다.

> **상태 머신(state.json·워크스페이스·instructions·핸드오프 파일)을 만드는 경로는 ① 크기=중 + 검증 단계 있음 ② 크기=대뿐이다.** 크기=소, 그리고 크기=중 + 검증 단계 없음은 상태 머신을 일절 만들지 않고 메인이 직접 진행한다 — 아래 "소 빠른 경로"·"중 경량 경로" 참조. 본 문서의 나머지(메인 임무·state.json·워크스페이스·1~7단계·사이클 제어)는 전부 **중(검증 있음)·대 전용**이다.

## 메인의 임무 (중(검증 있음)·대 전용, 이 두 가지뿐)

1. state.json 단독 갱신·조회
2. 위임 프롬프트 작성·서브에이전트 스폰

## 핵심 불변식 — state.json 단독 writer

state.json은 **메인만** 쓴다. 서브에이전트는 5문장 이내 보고 끝에 `state_delta` JSON 블록만 첨부하고, 메인이 회수 후 머지한다 — 서브가 state.json을 직접 Write·Edit하지 않는다(워크트리 격리 시 메인 워킹트리 접근 불가). (스키마는 아래 state.json 절, 예시는 위임 프롬프트 템플릿 참조)

## 재진입 (`--resume <워크스페이스 절대경로>`, 메인 직접)

`--resume`은 **중(검증 있음)·대 전용**이다 — 소·중(검증 없음)은 state.json·워크스페이스가 없어 재진입 대상이 되지 않는다. `--resume <경로>`로 호출됐는데 그 경로에 state.json이 없으면 "상태 머신 없는 경로(소·중 검증 없음)는 재진입 불가. 신규로 실행합니다" 1줄 보고 후 신규 진입 절차를 따른다. state.json이 있으면 신규 진입 대신 재개한다 — 해당 경로의 state.json을 읽어 `phase`부터 이어간다 — `prd_pending`이고 `00_prd.md`가 있으면 PRD 게이트를 건너뛰고 설계 단계(대: state.json `design_agent`가 가리키는 architect 또는 synthesizer)·planner(중)부터 스폰한다. `prd_pending`인데 `00_prd.md`가 없으면(작성 중 중단) 사용자에 "PRD 미완성. 다시 작성할까요?" 1줄 질문 후 답 대기 → 동의 시 0.5단계 2번(prp-prd 실행)부터 재개. 0단계 크기 판단·워크스페이스 생성은 어느 경우든 다시 하지 않는다.

## 사전 점검 (0단계 직후, 중(검증 있음)·대만, 메인 직접)

> **분기 순서:** 0단계 크기·검증 판단을 **먼저** 수행한다. **소 또는 중(검증 없음)으로 판정되면 본 사전 점검·PRD 게이트·이후 모든 단계를 건너뛰고 각각 "소 빠른 경로"·"중 경량 경로"만 실행한다.** 본 사전 점검은 중(검증 있음)·대로 판정됐을 때만 0단계 직후에 실행한다. 본 사전 점검의 `.worktreeinclude` 패턴 보장은 `_workspace/` 산출물을 워크트리에 공유하기 위한 것이라, 산출물을 만들지 않는 두 경량 경로에는 불필요하다(중 경량 경로가 worktree를 쓸 때도 핸드오프 파일이 없어 패턴이 필요 없다). 아래 사전 점검은 중(검증 있음)·대에만 적용한다.

1. **git 저장소 판정** — `git rev-parse --show-toplevel` 실패 시 비-git. 워크트리 격리 불가하므로 사용자에 "비-git 프로젝트 감지. 트랙 직렬 진행할까요?" 1줄 질문 후 **답을 받을 때까지 대기**. 동의 시 `isolation=serial`로 state.json 기록 후 계속. 거부 시 abort.
2. **.worktreeinclude 패턴 보장** — git 저장소면 프로젝트 루트의 `.worktreeinclude`에 `_workspace/` 패턴이 있는지 grep. 미포함이면 메인이 1줄 append (사용자 질문 없이 자동). 워크트리는 git 추적 파일만 복사하므로 untracked `_workspace/` 산출물(state.json 등)을 서브가 읽으려면 이 패턴이 필수.

## 워크스페이스

```
<프로젝트 루트>/_workspace/impl_<YYYYMMDDHHMMSS>/
├── state.json
├── 00_prd.md
├── 01_intent.md
├── 02_architect.md
├── 03_plan.md
├── instructions/<track_id>.md
├── 04_impl_handoff.md
├── 06_review_<track_id>.md
├── 07_security_<track_id>.md
├── 08_integration_handoff.md
├── 09_e2e_strategy.md
└── 05_e2e_report.md
```

프로젝트 루트는 `git rev-parse --show-toplevel`. 비-git이면 cwd.

## state.json 스키마

```json
{
  "run_id": "20260526_153012",
  "size": "small|medium|large",
  "design_agent": "architect|synthesizer",
  "phase": "intake|prd_pending|architect|plan|tdd|review|merge|integration|e2e_strategy|e2e|done|aborted",
  "cycle_total": 1,
  "cycle_max": 3,
  "isolation": "worktree|serial",
  "tracks": [
    {
      "id": "A",
      "agent": "tdd-guide",
      "model": "sonnet|opus",
      "instruction": "instructions/A.md",
      "needs_security_review": false,
      "test_tier": "bdd|tested|none",
      "status": "pending|running|done|failed"
    }
  ],
  "artifacts": {
    "prd": "00_prd.md",
    "intent": "01_intent.md",
    "architect": "02_architect.md",
    "plan": "03_plan.md",
    "impl": "04_impl_handoff.md",
    "integration": "08_integration_handoff.md",
    "e2e_strategy": "09_e2e_strategy.md",
    "e2e": "05_e2e_report.md"
  },
  "last_result": "pass|fail|partial",
  "next_action": "spawn:tdd-guide|spawn:code-reviewer|spawn:security-reviewer|spawn:tdd-guide-integration|spawn:evaluator|spawn:e2e|respawn:planner|respawn:tdd-guide|respawn:tdd-guide-integration|abort|complete",
  "notes": "한 줄"
}
```

`cycle_max`는 크기별 결정. `cycle_total`은 모든 respawn 누적. `design_agent`는 대 크기에만 설정(0단계 변경 범위 분기 결과) — 중·소는 미설정.

## 워크플로우

### 0단계 — 크기·검증 판단 (메인 직접)

1. Glob·LS로 파일 목록만 확인. 개별 Read는 판단에 필수일 때만 3개 이하.
2. 아래 표로 크기·체인·`cycle_max` 분류.
3. **크기=중이면 아래 "검증 단계 유무 판정"을 수행한다.** 검증 없음으로 판정되면 곧장 "중 경량 경로"로 분기한다(4·5번 미실행).
4. **크기=소면 곧장 아래 "소 빠른 경로"로 분기한다 — 5·6번(워크스페이스·state.json 생성)을 실행하지 않는다.**
5. (중-검증·대) 사용자에 한 줄 보고 ("크기 중. planner → tdd-guide → code-reviewer → e2e, cycle_max=5, isolation=worktree"). 워크스페이스 생성, `01_intent.md` Write (요청 원문 + 크기 + 근거 3줄). **사용자(또는 상위 `/dev`)가 성공 조건을 제시했으면 `01_intent.md`에 `## 사용자 성공 조건` 섹션으로 각 항목을 원문 그대로 기록한다(제시 안 했으면 섹션 생략).** 이 섹션이 있으면 아래 1단계 planner·7단계 evaluator·e2e 위임 프롬프트에 반드시 실려 여정 커버리지로 이어진다 — 성공 조건 관통은 planner·evaluator·e2e가 존재하는 중-검증·대 경로에만 적용된다.
6. (중-검증·대) state.json 초기화.

| 크기 | 기준 | 체인 | cycle_max |
|------|------|------|------|
| 소 | 파일 1~2개, 함수 1~3개 수정, 신규 추상화 없음 | **메인 직접 구현 → code-reviewer** (워크스페이스·state.json 없음) | — |
| 중 (검증 있음) | 파일 3~10개, 신규 기능 1개, 기존 모듈 내 재사용 | planner → tdd-guide(단위) → code-reviewer → 머지 → tdd-guide(통합) → code-reviewer → evaluator → e2e | 5 |
| 중 (검증 없음) | 위와 같되 e2e 검증을 생략 (아래 판정) | **메인 직접 계획 → tdd-guide(단위) → code-reviewer → 머지 → tdd-guide(통합) → code-reviewer** (워크스페이스·state.json 없음) | — |
| 대 | 파일 10개+, 신규 모듈·패키지·외부 의존 추가 | architect/synthesizer → planner(ultra) → tdd-guide(단위) → code-reviewer → 머지 → tdd-guide(통합) → code-reviewer → evaluator → e2e | 10 |

소·중(검증 없음)은 상태 머신 없이 메인이 직접 처리하고, 중(검증 있음)·대만 워크스페이스·state.json 기반 체인을 거친다.

#### 검증 단계 유무 판정 (크기=중에서만, 메인 직접)

"검증 단계"란 체인 끝의 e2e 검증(evaluator + e2e 실행)을 가리킨다. 아래 ① 또는 ② 중 하나라도 해당하면 **검증 없음**으로 판정해 중 경량 경로로 보낸다. 둘 다 아니면 **검증 있음**(기존 정식 경로).

① 사용자가 e2e 검증을 원치 않는다는 의도를 표현 — "검증 없이", "테스트는 됐고", "e2e 빼고", "빠르게 구현만" 등 e2e·검증·테스트 생략을 직접 지칭한 발화. 속도·간결함만 언급한 발화("빨리 해줘", "간단하게")는 ①에 해당하지 않는다.
② e2e 검증이 구조적으로 불가능 — 실행 가능한 사용자 플로우·UI가 없는 순수 라이브러리·내부 모듈·CLI 유틸이거나, e2e 인프라(Playwright 등)와 전용 e2e 에이전트(7단계의 `.claude/agents/e2e-*.md` glob 대상)가 **둘 다** 없는 경우.

판정 근거를 사용자에 1줄 보고한다 ("크기 중, e2e 인프라 없음 → 검증 없음 경량 경로").

**Do:** ②는 단위·통합 테스트로 검증 가능해도 *e2e*가 불가능하면 검증 없음으로 본다(tdd-guide 단위·통합 테스트는 두 경로 모두 수행).
**Don't:** 사용자 발화·코드베이스 근거 없이 임의로 검증을 생략한다 — 근거가 없으면 검증 있음(정식 경로)이 기본이다.

**대의 설계 단계는 변경 범위로 갈린다** — 신규 첫 구현이거나 모듈 경계·데이터 모델·외부 인터페이스가 두루 바뀌면 synthesizer를, 기존 모듈 내부 구조만 바뀌면 architect를 스폰하고, 그 분기 결과를 state.json `design_agent`에 기록한다. **요청에 확정 ADR/설계 문서 경로가 명시돼 있으면 설계 단계(architect/synthesizer)를 스폰하지 않고 그 문서를 `02_architect.md`로 채택(복사 또는 경로 참조)한 뒤 planner부터 시작한다.** synthesizer는 ADR을 본문 반환이 기본이므로, 위임 프롬프트에 최종 ADR을 `02_architect.md`에 Write하도록 명시한다. **대의 planner는 항상 ultra 모드**(위임 프롬프트에 `ultra` 포함)로 스폰해 plan-reviewer 3 분담 자가 비평을 활성화한다(중은 미적용).

크기가 모호하면 큰 쪽으로 분류.

### 소 빠른 경로 (메인 직접, 상태 머신 없음)

크기=소면 impl의 상태 머신(state.json·워크스페이스·instructions·핸드오프 파일)과 서브에이전트 핸드오프 계약을 **일절 만들지 않는다.** 스킬을 거치지 않고 작업할 때와 동일하게 메인이 직접 처리한다.

1. **사용자에 한 줄 보고** ("크기 소. 메인 직접 구현 후 code-reviewer.").
2. **메인이 직접 테스트 tier를 판정한다** (3-tier, "테스트 tier 판정" 절 참조). 결제·정산·금액·인증·권한이면 `bdd`(behavior 단위·선행), 핵심 여정에 닿거나 위험 로직(상태 누적·경계 계산)이면 `tested`(구현 후 사후 테스트), 단순 전달·표시뿐이면 `none`(테스트 생략). 근거 없으면 `tested`가 기본.
3. **메인이 직접 구현한다.** `bdd`면 `rules/testing.md`에 따라 선행(테스트 먼저 RED → 구현 GREEN → 리팩토링), `tested`면 사후(구현 먼저 → 정상 경로 + 위험·경계를 테스트로 커버)로 메인이 직접 수행한다 — 별도 tdd-guide 스폰·핸드오프 파일·state_delta는 없다. `none`이면 테스트 없이 구현만 한다(소는 끝단 e2e가 없으므로, 다음 단계 code-reviewer 육안 점검으로 갈음 — 단순 코드라 e2e 없이도 리스크 낮음).
4. **구현·수정 직후 code-reviewer를 1회 스폰한다** (immediate agent usage와 동일). 위임 프롬프트에는 변경 파일 경로·작업 범위만 전달한다 — `_workspace`·state_delta·`06_review_*.md` 계약을 주입하지 않는다. 사용자 입력 처리·인증/인가·API 엔드포인트·시크릿/외부 통신 중 하나라도 닿으면 security-reviewer도 같은 응답에 묶어 병렬 스폰한다.
5. 리뷰에 차단성 결함이 있으면 메인이 직접 수정하고 필요 시 재리뷰한다. 0건이면 종료한다.

소에는 사전 점검·PRD 게이트·머지·통합·evaluator·e2e·사이클 제어를 적용하지 않는다.

### 중 경량 경로 (검증 없음, 상태 머신 없음)

크기=중 + 검증 없음이면 상태 머신(state.json·워크스페이스·instructions·핸드오프 파일)을 **일절 만들지 않고**, 메인이 planner 역할을 직접 맡아 tdd-guide·code-reviewer에 위임 프롬프트로 직접 지시한다. e2e만 빠질 뿐 단위·통합 구현과 머지는 그대로 거친다.

1. **사용자에 한 줄 보고** ("크기 중(검증 없음). 메인 직접 계획 → tdd-guide → code-reviewer → 머지 → 통합.").
2. **메인이 직접 계획·트랙 분할한다** (planner 스폰 없음). 트랙이 독립 ≥ 2개면 병렬, 아니면 단일 트랙. 트랙별 테스트 tier 판정(3-tier, "테스트 tier 판정" 절)은 메인이 직접 적용한다 — `bdd`(결제·정산·금액·인증·권한 → behavior 단위·선행 + opus 고정)·`tested`(핵심 여정·위험 로직 → 구현 후 사후 테스트)·`none`(단순 전달·표시).
3. **tdd-guide 스폰 (트랙별).** 위임 프롬프트에 트랙 작업 범위를 **직접 적고, 모드를 명시한다 — `bdd`는 선행(시나리오 먼저 RED-GREEN), `tested`는 사후(구현 먼저 → 정상 경로 + 위험·경계 커버)** — `instructions/<id>.md`·state_delta·`_workspace` 계약을 주입하지 않는다. 독립 트랙 ≥ 2개 + git 저장소면 `isolation: worktree`로 병렬 스폰, 아니면 직렬. **`test_tier="none"` 트랙은 tdd-guide를 스폰하지 않는다** — 병렬이면 범용 서브에이전트(general-purpose)에 위임 프롬프트로 직접 지시("테스트 미작성, 구현만"), 단일 트랙이면 메인이 직접 구현한다. 중(검증 없음) 경로는 끝단 e2e가 없으므로 `none` 트랙은 다음 단계 code-reviewer 육안 점검으로 갈음한다(단순 코드라 리스크 낮음).
4. **트랙 완료마다 code-reviewer 스폰** (immediate agent usage와 동일). 보안 민감 트랙(사용자 입력·인증/인가·API·시크릿/외부 통신)은 security-reviewer를 같은 응답에 병렬 스폰. 차단성 결함이 있는 트랙은 tdd-guide(`none` 트랙은 general-purpose)로 재위임, 0건이면 다음 단계.
5. **머지** (worktree 병렬이었으면). 충돌 시 통합 tdd-guide 위임 프롬프트에 해소를 포함한다.
6. **통합 tdd-guide → 통합 code-reviewer** 스폰 (머지된 단일 트리). 통합 테스트·결합부 구현·최종 회귀까지 마치면 종료한다.

중 경량 경로는 PRD 게이트·evaluator·e2e·state.json 기반 사이클 제어를 적용하지 않는다. 위임 프롬프트는 `_workspace` 산출물·state_delta 항목을 뺀 단순형으로 작성한다.

### 0.5단계 — PRD 게이트 (대 + 신규 제품/기능, 메인 직접)

크기=대이고 ① 요청에 사용자 대상·성공 기준이 명시 안 됐거나 ② 코드베이스에 해당 기능 관련 파일이 없으면(신규 제품·기능) 구현 전에 PRD를 먼저 만든다. 둘 다 아니면(기존 모듈 확장·리팩토링) 건너뛴다.

1. 사용자에 "신규 기능이라 PRD부터 만들까요? (작성 후 세션 종료, 새 세션 `--resume`으로 구현 재개)" 1줄 질문 후 답 대기.
2. 동의 시: (0단계에서 이미 생성된) state.json을 `phase=prd_pending`으로 갱신 → `/prp-prd`를 Skill로 실행하되 args에 "산출물을 `<워크스페이스 절대경로>/00_prd.md`에 저장"을 명시 → 완료 후 "PRD 작성 완료. 새 세션에서 `/impl --resume <워크스페이스 절대경로>`로 구현을 시작합니다" 안내 후 **종료**한다.

PRD 완료 안내 후 세션을 종료한다. 같은 세션에서 설계(architect/synthesizer) 이후 단계로 진행하지 않는다(PRD 작성 컨텍스트 격리 목적).

3. 거부 시: PRD 없이 대 체인 계속 — 설계 단계부터(변경 범위로 architect/synthesizer 분기).

### 테스트 tier 판정 (중·대, planner)

중·대 크기에서는 planner가 트랙별로 아래 3-tier 중 하나를 판정해 `state_delta`의 `tracks[].test_tier`에 기록한다. 테스트가 버그를 실제로 잡는 영역에만 비용을 쓰고, 단순 코드에는 테스트를 생략한다.

| tier | 대상 | 작성 방식 | 모델 |
|------|------|----------|------|
| `bdd` | 결제·정산·금액 계산·인증·권한 | behavior(Given-When-Then) 시나리오마다 독립 선행 RED-GREEN 사이클 | **opus 고정** |
| `tested` | 핵심 사용자 여정에 닿는 코드(사용자가 직접 호출·체감하는 기능 경로. 단순 위임·변환 래퍼는 `none`) **또는** 위험 로직(상태 누적: 잔액·재고·포인트·세션 / 경계 계산: 반올림·날짜·할인 중첩) | 구현 먼저 → 정상 경로 + 위험·경계를 사후 테스트로 필수 커버 | 컨텍스트 기준 |
| `none` | 위 둘 다 아닌 단순 코드 — 화면 마크업·스타일, 설정/상수/배선, 단순 위임·변환 래퍼(로직 0), 일회성 스크립트 | 테스트 미작성, 구현만 | 컨텍스트 기준 |

**판정 순서:** ① 결제·정산·금액·인증·권한 도메인인가 → `bdd`. ② 아니면 핵심 사용자 여정에 닿거나 위험 로직(상태 누적·경계 계산)인가 → `tested`. ③ 둘 다 아니면 → `none`.

**핵심 여정 판정은 끝단 e2e 유무와 무관하다.** e2e가 회귀를 잡는 시점은 체인 끝단이라, 거기서 실패하면 앞 단계로 되돌아가 재구현·재머지·재통합하는 비용이 크다. 핵심 여정은 e2e가 있어도 단위 레벨에서 사후 테스트로 먼저 덮어 싸게 회귀를 차단한다(단위=1차 방어선, e2e=최종 통합 확인).

**근거 없으면 `tested`가 기본**(`none`은 단순 코드 명시 근거가 있을 때만). "귀찮으면 무테스트"로 흐르는 것을 차단한다. `bdd` 트랙은 모델 **opus 고정**(behavior 단위·선행), 전면 적용은 비용이 가치를 초과하므로 위 도메인에만 적용한다. `tested` 트랙은 정상 경로 1개 + 틀리기 쉬운 경계 1~2개를 함께 덮는다. `none` 트랙은 자기 테스트 없이 끝단 e2e 검증(중-검증·대)에만 기댄다.

### 1단계 — planner (중·대만)

크기=대면 위임 프롬프트에 `ultra`를 포함한다(중은 미적용). 설계 단계(architect/synthesizer) 선행 스폰은 0단계 참조.

1. planner 스폰, `03_plan.md` Write + 트랙 분할 결정 요청. `track_id`(A·B…)는 planner가 정하고, planner가 직접 `instructions/<track_id>.md`를 Write한다. 메인은 경로를 미리 만들지 않는다. 위임 프롬프트에 ① `00_prd.md`가 있으면 Read 지시 ② 위 "테스트 tier 판정" 3-tier 기준을 주입하고, `test_tier="bdd"` 트랙의 `instructions/<id>.md`는 behavior(Given-When-Then) 시나리오마다 독립 선행 RED-GREEN 단계로 쪼개 작성하도록, `test_tier="tested"` 트랙은 구현 단계 뒤에 사후 테스트 단계(정상 경로 + 위험·경계)를 두도록, `test_tier="none"` 트랙은 테스트 단계 없이 구현 단계만 쓰도록 지시한다(planner 정의는 수정하지 않고 프롬프트로만 주입). **③ `01_intent.md`에 `## 사용자 성공 조건`이 있으면 각 항목을 `03_plan.md`의 Success Criteria 섹션(없으면 신설)에 원문 그대로 포함하고, 각 조건에 대응하는 사용자 여정을 Testing Strategy의 E2E 골격에 최소 1개씩 배치하도록 지시한다.**
2. planner 보고 `state_delta`에 `tracks[]`(트랙별 `id`·모델·지시문 경로·`needs_security_review`·`test_tier`) 포함.
3. 회수 후 메인이 state.json에 머지. 메인은 planner의 `state_delta.tracks[].id`를 그대로 사용한다.

### 2단계 — tdd-guide / 무테스트 트랙 구현 (트랙별)

1. state.json `tracks[]` 읽어 각 트랙을 모델 명시로 스폰. **`test_tier`로 스폰 에이전트가 갈린다 — `bdd`·`tested`는 tdd-guide, `none`은 범용 서브에이전트(general-purpose)에 위임한다**(전용 무테스트 에이전트는 신규 작성하지 않는다 — 강제할 방법론이 없어 범용으로 충분). **tdd-guide 위임 프롬프트에 모드를 명시한다 — `bdd`는 선행(시나리오 먼저 RED-GREEN), `tested`는 사후(구현 먼저 → 정상 경로 + 위험·경계 커버).** `none` 트랙의 위임 프롬프트는 "테스트 미작성, 구현만"을 명시하고, 산출은 `04_impl_handoff.md`에 RED-GREEN 로그 대신 "구현 로그(테스트 없음)"로 기록하도록 지시한다. 모델은 컨텍스트·난이도 기준 sonnet/opus 분기를 그대로 적용(`none`엔 bdd의 opus 고정 정책 해당 없음).
2. 독립 트랙 ≥ 2개 + `isolation=worktree`면 한 응답에 묶어 **병렬 스폰**, `isolation: worktree` 지정.
3. `isolation=serial`이면 트랙을 순차 스폰.
4. 위임 프롬프트에 트랙 지시 박지 말고 `instructions/<id>.md` Read 지시만 — `none` 트랙도 동일(planner가 구현 단계만 적은 지시문 Read). 범용 서브에이전트도 impl 위임 계약(state_delta·`_workspace`·200줄 보고 상한)을 모르므로 기존 위임 프롬프트 템플릿을 그대로 주입한다.
5. 회수 후 `state_delta`로 `tracks[].status` 머지. `test_tier="none"` 트랙이어도 중(검증 있음)·대 경로면 끝단 e2e(7단계)는 그대로 거친다(구멍 메우기).

### 3단계 — code-reviewer + security-reviewer (트랙별 병렬)

tdd-guide 완료 트랙마다 code-reviewer 스폰. `needs_security_review: true` 트랙은 security-reviewer를 같은 응답에 묶어 병렬 스폰. 리뷰어는 자기 정의의 차단성 판정에 따라 차단 비트와 비차단성 결함의 처분 권고를 산출물 파일에 기록하고, `state_delta`에 자기 트랙의 비트를 `tracks[].status`로 환원해 담는다 — `BLOCK`→`"failed"`·`PASS`→`"done"`(`next_action`은 채우지 않음). 메인은 트랙 `status`만 보고 라우팅하며 리뷰 본문·처분 권고를 읽지 않는다 — `failed` 트랙만 `respawn:tdd-guide` 스폰(나머지 `done` 트랙은 대기), 전 트랙이 `done`이면 4단계 머지로 진행한다. 비차단성 지적은 리뷰어 산출물에 처분 권고로 남고 메인이 표로 판정하지 않는다.

**security-reviewer 스폰 조건** (planner가 판정해 `needs_security_review`에 기록):
- 사용자 입력 처리
- 인증·인가
- API 엔드포인트
- 시크릿·민감 데이터·외부 통신

### 4단계 — 머지 (중·대, `isolation=worktree`일 때, 메인 직접)

1. 트랙별 워크트리 브랜치를 메인 워킹트리로 머지.
2. 충돌 발생 시 **메인은 충돌 코드 본문을 읽지 않는다.** 충돌 파일 수·헝크 수(`git diff --check` 등)만 확인해 5단계 모델 결정에 쓰고, 충돌 해소는 5단계 통합 tdd-guide 위임 프롬프트에 포함한다.
3. `isolation=serial`이면 머지 단계 생략(이미 단일 트리). state.json `phase=merge`.

### 5단계 — tdd-guide 통합 (중·대)

1. 머지된 단일 트리에서 **새 tdd-guide 인스턴스** 스폰. 단위 단계 인스턴스를 재사용하지 않는다(fresh 컨텍스트로 폭증 방지).
2. **모델**: 충돌 발생 시 opus, 충돌 0이고 머지 코드 200K 초과도 opus, 그 외 sonnet.
3. 위임 프롬프트에 `03_plan.md`의 Testing Strategy(통합 설계도) Read 지시. 작업: 통합 테스트 + 결합부 구현 + 최종 회귀 + (충돌 시) 충돌 해소.
4. 산출 `08_integration_handoff.md`. 회수 후 `state_delta`로 `phase=integration`·`last_result` 머지.

### 6단계 — 통합 code-reviewer (중·대)

머지·통합 코드 대상으로 code-reviewer 스폰. 통합은 단일 트리이므로 리뷰어는 차단 비트를 `tracks[].status`가 아닌 `last_result`로 보고한다(`BLOCK`→`"fail"`·`PASS`→`"pass"`). `"fail"`이면 `respawn:tdd-guide-integration`, `"pass"`이면 다음 단계.

### 7단계 — evaluator + e2e 실행 (중·대만)

**evaluator 스폰 (메인 직접)**: 머지·통합이 끝난 코드에서 evaluator(sonnet) 스폰. 위임 프롬프트에 머지 코드 범위 + `03_plan.md`의 E2E 골격 Read 지시. **`01_intent.md`에 `## 사용자 성공 조건`이 있으면 그 파일 Read 지시를 함께 넣고, 각 사용자 성공 조건을 검증하는 e2e 시나리오를 `09_e2e_strategy.md`에 반드시 하나 이상 포함하며 각 시나리오에 대응 성공 조건을 명시하도록 지시한다(어느 조건도 누락 금지).** evaluator는 e2e 세부 전략과 실행 에이전트용 스폰 지시문을 `09_e2e_strategy.md`에 Write한다. **메인은 이 파일 본문을 읽지 않고 경로째 e2e 에이전트에 전달한다.**

**e2e 에이전트 결정 (스폰 전, 메인 직접)**: 프로젝트 루트 기준 `.claude/agents/`를 Glob(`e2e-*.md`)한다.
- 1개 → 그 프로젝트 전용 e2e 에이전트를 스폰.
- 0개 또는 `.claude/agents/` 디렉터리 자체가 없음 → 기본 `e2e-runner` 스폰.
- 2개 이상 → 어느 것을 쓸지 사용자에 1줄 질문 후 답을 받을 때까지 대기.

e2e 에이전트(전용·기본 `e2e-runner` 모두)는 impl 계약(state.json·state_delta·`05_e2e_report.md`·실패 분류)을 정의에 모를 수 있다. tdd-guide·code-reviewer와 동일하게 **어느 에이전트를 스폰하든 메인이 위임 프롬프트 템플릿으로 계약을 주입**한다 — 특히 아래 실패 분류 기준과 `state_delta` 첨부 지시, 그리고 `09_e2e_strategy.md`(evaluator가 작성한 전략·스폰 지시문) Read 지시를 프롬프트에 명시한다. **`01_intent.md`에 `## 사용자 성공 조건`이 있으면 그 각 조건을 반드시 검증 대상 시나리오로 포함하고 `05_e2e_report.md`에 성공 조건별 pass/fail을 개별 기록하도록 명시한다 — 조건이 fail하면 아래 실패 분류 기준(구현·계획·환경·복합)을 그대로 적용하며, 여러 조건이 서로 다른 원인으로 동시에 fail하면 '상위 원인 우선'(계획 > 구현)으로 `next_action` 하나에 수렴시키고 나머지 원인은 `notes`에 남기되, 환경 결함이 하나라도 섞이면 `abort`를 우선한다.**

선택된 e2e 에이전트는 실패 원인을 아래 기준으로 분류해 `state_delta.next_action`에 기록한다.
- 구현 결함(어서션 실패·로직 오류) → `respawn:tdd-guide`(단위 결함) 또는 `respawn:tdd-guide-integration`(통합·결합부 결함)
- 계획 결함(누락 시나리오·설계 오류) → `respawn:planner`
- 환경 결함(포트·인증·외부 서비스 연결 실패) → `abort`
- 복합·분류 불가 → `abort`, notes에 "분류 불가: <증상>"

기준이 겹치면 상위 원인(계획 > 구현) 우선.

### 사이클 제어

- respawn 1회마다 `cycle_total` +1.
- `cycle_total > cycle_max` 시 자동 중단, 사용자 확인 후 재설계.

## 모델 결정 (중·대, planner)

- 컨텍스트 추정 = 트랙이 읽을 코드·테스트 토큰 합 × **1.5**
- ≤ 200K → sonnet
- 200K~400K → opus
- 400K 초과 → 트랙 분할
- 신규 도메인·복잡 알고리즘은 한 단계 위로
- `test_tier="bdd"` 트랙은 opus 고정 (sonnet이어도 opus로 승격, 이미 opus면 유지)

## 위임 프롬프트 템플릿

메인은 서브에이전트 스폰 시 아래 템플릿 구조를 반드시 따른다. 섹션 순서·항목을 변경하지 않는다.

```
[역할] <서브에이전트 이름>으로서 <단계명>을 수행한다.

[입력 — Read 지시]
- 코드 수정은 현재 작업 위치(cwd, 워크트리 루트)에서 수행한다. 아래 _workspace 경로는 오케스트레이션 산출물 전용이며 코드 작업장이 아니다.
- 산출물 경로(입력·산출물 read/write 전용): <절대경로>/_workspace/impl_<run_id>/
- state.json
- 00_prd.md (있으면 — architect·planner 스폰 시)
- 01_intent.md
- <이전 단계 산출물> (있으면)
- <트랙 지시문 instructions/<id>.md> (단위 tdd-guide 스폰 시)
- 03_plan.md Testing Strategy (통합 tdd-guide는 통합 설계도, evaluator는 E2E 골격 Read)

[작업 범위]
- <한 줄>
- 범위 밖 결함은 산출물 "발견 사항" 섹션에만 기록, 직접 수정 금지

[산출]
- <단계 산출 파일> Write
- state.json 직접 수정 금지. 보고 말미에 `state_delta` JSON 블록 첨부 (planner 예: `{"phase":"plan","tracks":[{"id":"A","agent":"tdd-guide","model":"sonnet","instruction":"instructions/A.md","needs_security_review":false,"test_tier":"tested","status":"pending"}],"next_action":"spawn:tdd-guide"}`. 단위 tdd-guide 예: `{"phase":"tdd","tracks":[{"id":"A","status":"done"}],"last_result":"pass","next_action":"spawn:code-reviewer"}` — `test_tier="none"` 트랙(범용 서브에이전트)도 동일 형식 사용. 통합 tdd-guide 예: `{"phase":"integration","last_result":"pass","next_action":"spawn:code-reviewer"}`. evaluator 예: `{"phase":"e2e_strategy","next_action":"spawn:e2e"}` — `09_e2e_strategy.md` Write 후. 리뷰어 예: `{"tracks":[{"id":"A","status":"failed"}]}` — 트랙 차단 비트를 `status`로 환원(`BLOCK`→`"failed"`·`PASS`→`"done"`), `next_action`은 메인이 머지 후 결정하므로 리뷰어는 채우지 않음. 복수 트랙 병렬 시 각 리뷰어는 자기 트랙만 담아 보고).
- 메인 회신은 5문장 이내 + state_delta. 산출물 본문 포함 금지.

[공통 룰]
- 보고 분량 ≤ 200줄·표 ≤ 2개. 초과 시 _workspace/에 파일 저장 후 절대경로만 회신.
- 위임 cwd 외부에 파일 쓰기·커밋 금지. 외부 경로 읽기는 절대경로 Read 또는 `git -C <path>` 읽기 전용만.
- 룰북·docs 등 큰 지시문 파일은 `Read offset/limit`로 좁힘.
```

프로젝트 CLAUDE.md는 서브에이전트 cwd 기준으로 자동 주입된다. `isolation=worktree` 스폰 시 cwd가 워크트리 루트로 설정되므로 위임 프롬프트에 `<프로젝트 루트>/CLAUDE.md` 절대경로 Read 지시를 포함한다.

## 단계별 산출 contract

| 단계 | 산출 파일 | 핵심 섹션 |
|------|----------|----------|
| prp-prd (대+신규, 게이트) | 00_prd.md | Problem, Hypothesis, Out of Scope, Success Metrics, Phases |
| architect / synthesizer (대, 변경 범위 분기) | 02_architect.md | ADR, 데이터 모델, 인터페이스 계약 |
| planner | 03_plan.md + instructions/*.md | Mandatory Reading, Patterns to Mirror, Step-by-Step, Confidence Score, (사용자 성공 조건 있으면) Success Criteria / 트랙별 모델·지시문 / Testing Strategy(통합 설계도·E2E 골격 — 성공 조건별 여정 포함) |
| tdd-guide (단위) | 04_impl_handoff.md | RED-GREEN 로그, 커밋 SHA, 테스트한 경로(핵심 여정·경계), 발견 사항 |
| tdd-guide (통합) | 08_integration_handoff.md | 통합 테스트, 결합부 구현, 최종 회귀, (충돌 시) 해소 로그 |
| code-reviewer | 06_review_<track_id>.md | 결함 목록, 처분 권고 |
| security-reviewer | 07_security_<track_id>.md | 취약점 목록, 심각도, 처분 권고 |
| evaluator | 09_e2e_strategy.md | E2E 세부 전략, 시나리오·우선순위, 실행 스폰 지시문, (사용자 성공 조건 있으면) 조건별 검증 시나리오 |
| e2e (e2e-runner 또는 프로젝트 전용) | 05_e2e_report.md | 시나리오 결과, 실패 원인 분류, (사용자 성공 조건 있으면) 조건별 pass/fail |

산출 파일 본문 분량은 자유. 200줄·표 2개 상한은 메인 회신 텍스트에만 적용.

## 실패·중단

- `next_action: abort` → 메인이 사용자에 원인 보고, 재시도/중단 선택 요청.
- `cycle_total > cycle_max` → 자동 중단.

## 사용자 보고

각 단계 전환은 1문장(단계가 많으므로 압축).

**Do:** "planner 완료 (03_plan.md, 트랙 2개). tdd-guide A·B 병렬 스폰."
**Don't:** 산출물 본문 인용.

최종 보고는 5문장 이내 + 워크스페이스 절대경로.
