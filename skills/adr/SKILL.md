---
name: adr
description: 아키텍처 결정을 ADR 문서로 작성하는 스킬. 설계 난이도를 판정해 쉬우면 메인이 직접, 어려우면 synthesizer(architect+critic 수렴)로 분기한다. 사용자가 /adr, "ADR 써줘", "아키텍처 결정 기록", "설계 결정 문서화", "이 결정 ADR로 남겨줘" 등을 표현하면 이 스킬을 사용한다. (구현 계획은 impl/planner, 범용 계획은 deep-plan)
---

# /adr 스킬

아키텍처 결정을 ADR(Architecture Decision Record) 문서로 작성해 프로젝트 `docs/adr/`에 저장한다. 설계 난이도를 판정해, 되돌리기 쉽고 국소적인 결정은 메인이 직접 작성하고, 그렇지 않은 결정은 적대적 검증(architect↔critic 수렴)을 거친다.

## 적용 범위

**Do (이 스킬 사용):**
- 저장소·데이터 모델·API 계약·인증/보안 경계·주요 라이브러리 선택 등 아키텍처 결정 기록
- 이미 내린 결정을 근거·대안·트레이드오프와 함께 문서로 남기기

**Don't (다른 스킬 사용):**
- 단계별 구현 계획 → `impl`·`planner`
- 워크플로우·프로세스·마이그레이션 등 범용 계획 → `deep-plan`
- 코드·설계안 비평만 필요 → `critic` 직접

## 입력 / 출력

- **입력**: 자유 텍스트 — 배경, 후보안, 제약. 아래 두 케이스를 구분한다.
  - **확정 결정 문서화**: 사용자가 이미 내린 결정을 전달 → 그 결정을 그대로 Decision으로 채택하고, 검증 루트에서는 "이 결정을 검증·보강하라"는 취지로 스폰한다.
  - **미확정 문제 해결**: 후보안 비교가 필요 → architect·synthesizer가 도출한 결론을 사용자 확인 없이 Decision으로 확정하지 않는다. 사용자가 준 방향과 다른 결론이 나오면 그 차이를 1줄 보고하고 확정 여부를 확인받는다.
- **출력**: `<프로젝트 루트>/docs/adr/ADR-NNN-<slug>.md` 파일 1개
- **금지**: 본 스킬은 ADR 작성만 한다. 코드 구현·수정·커밋은 하지 않는다

---

## 절차

### Phase 1 — 난이도 판정 (분기)

아래 4축을 훑어 판정한다. **네 축 모두 낮으면 "직접"(Phase 2A), 하나라도 뚜렷하면 "검증"(Phase 2B)** 이다.

| 축 | 뚜렷함 신호 |
|----|------------|
| 되돌리기 어려움 | 데이터 모델·저장소 선택·API 계약·보안 경계처럼 한번 정하면 바꾸기 힘든 결정 |
| 대안 경쟁 | 실질 후보가 2개 이상이라 트레이드오프 비교가 필요 |
| 영향 범위 | 여러 모듈·외부 통합·데이터 흐름을 관통 |
| 실패·보안 민감도 | 실패 모드·롤백·보안 경계가 결과에 크게 작용 |

- **Do:** 판정 결과와 근거(어느 축이 뚜렷한지)를 1줄로 사용자에게 보고한 뒤 해당 Phase로 진행한다.
- **Don't:** 애매하면 "직접"으로 기울지 않는다 — ADR은 태생이 무거운 산출물이므로 경계에서는 "검증"을 택한다.

### Phase 2A — 메인 직접 작성 (난이도 하)

1. 아래 "ADR 표준 구조" 템플릿을 포맷의 단일 출처로 삼아 메인이 직접 ADR 본문을 작성한다.
2. 설계 원칙·체크리스트가 필요할 때만 `agents/architect.md`를 선택적으로 Read하되, 포맷은 이 문서 템플릿을 우선한다.
3. Phase 3으로 진행.

- **Do:** 포맷은 자체 템플릿을 따르고, architect.md는 원칙 보강이 필요할 때만 읽는다.
- **Don't:** architect·synthesizer를 스폰하지 않는다(난이도 하에서는 직접 작성이 목적).

### Phase 2B — synthesizer 검증 (난이도 중·상)

1. `synthesizer` 에이전트를 `subagent_type="synthesizer"`로 스폰한다. 프롬프트에 결정할 문제·배경·후보안·제약을 전달하고, **ADR 본문을 스크래치패드 파일에 Write한 뒤 회신에는 경로와 수렴 요약만 담으라**고 지시한다. 자식(architect·critic)에게도 같은 방식을 쓰라고 함께 지시한다.
2. 회신받은 경로를 Read해 ADR 본문을 회수한다.
3. Phase 3으로 진행 — 회수한 본문을 ADR 파일 내용으로 사용한다.

- **Do:** synthesizer **하나만** 스폰한다. synthesizer가 내부에서 architect·critic을 스폰·수렴한다.
- **Don't:** architect·critic을 메인이 직접 스폰하지 않는다(수렴 오케스트레이션은 synthesizer 담당). 긴 산출을 회신 본문으로 받는다(잘린다).

**손자 산출 오통지.** architect·critic의 산출이 synthesizer를 건너뛰고 메인에 배달될 수 있다 — 발신자가 synthesizer가 아니면 이 상황이고, 같은 내용의 반복 도착이 추가 확증이다. 받은 산출을 스크래치패드에 저장해 경로를 `SendMessage`로 넘기고, 통지 결함이므로 재요청을 멈추라고 명시해 재개시킨다. 응답이 없다고 synthesizer를 버리고 재스폰하거나 메인이 ADR을 직접 쓰지 않는다. 실행 전 `~/.claude/memory/feedback_misrouted_result_relay_to_parent.md`를 Read해 적용한다.

### Phase 3 — 저장

1. **프로젝트 루트 결정**: `git rev-parse --git-common-dir`의 부모 디렉토리(메인 워킹트리). 워크트리에서 호출해도 메인 레포 기준.
2. **번호 결정**: `docs/adr/` 내 `ADR-*.md` 중 최대 번호 +1(3자리 zero-pad). 파일이 하나도 없으면 `001`.
3. **파일 작성**: `<프로젝트 루트>/docs/adr/ADR-NNN-<slug>.md`. `docs/adr/`가 없으면 생성. `<slug>`는 영문 소문자 kebab-case(결정 주제 요약).
4. **보고**: 1줄 요약 — 저장 경로 + 분기(직접/검증) + (검증 시) 수렴 요약 핵심.

---

## ADR 표준 구조

```markdown
---
title: <결정 제목>
status: <Accepted|Proposed|Superseded|Deprecated|Rejected>
created: YYYY-MM-DD
project: <프로젝트명>
tags: [adr]
---

# ADR-NNN: <결정 제목>

## Context
<이 결정이 필요한 배경·문제. 1~2단락>

## Decision
<채택한 결정. 명확한 단언형>

## Consequences

### Positive
- <이득>

### Negative
- <잔존 단점 — "완화"로 전부 봉합하지 말 것>

### Alternatives Considered
- **<대안>**: <기각 사유>

## Status
Accepted

## Date
YYYY-MM-DD
```

---

## 주의사항

- **날짜는 현재 세션 컨텍스트의 날짜**를 쓴다(추측 금지).
- **frontmatter `status`에는 한 낱말만** 적는다(`Accepted`·`Proposed`·`Superseded`·`Deprecated`·`Rejected`). 조건·개정 이력은 본문 `## Status`에 적고, 상태가 바뀌면 둘을 함께 고친다.
- **잔존 단점을 최소 1건 남긴다** — 모든 단점을 "완화"로 봉합한 ADR은 신뢰도가 떨어진다.
