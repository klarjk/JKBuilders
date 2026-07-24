# Testing Requirements

## 기본 원칙 (신규 구현)

테스트는 버그를 실제로 잡는 곳에만 작성한다. 모든 코드에 테스트를 강제하지 않는다.

- **테스트 필수 대상** — 다음 중 하나라도 해당하면 반드시 테스트로 커버한다:
  - 핵심 사용자 여정에 닿는 코드 (회귀 시 사용자가 바로 타격)
  - 위험 로직 — 상태 누적(잔액·재고·포인트·세션), 경계 계산(반올림·날짜·할인 중첩)
- **테스트 생략 가능** — 위 둘 다 아닌 단순 코드 (화면 마크업·스타일, 설정·배선, 단순 위임·변환 래퍼)
- **작성 시점** — 구현 먼저(GREEN) → 사후 테스트. 커버리지 숫자는 강제하지 않는다.
- **결제·정산·금액·인증·권한** — 예외적으로 선행(behavior 시나리오 먼저, RED-GREEN).

테스트 필수 대상은 정상 경로 1개 + 틀리기 쉬운 경계 1~2개를 함께 덮는다.

## 디버깅 (TDD 강제)

메인이 직접 수행한다 — tdd-guide 스폰 금지. 버그 수정은 TDD를 따른다. 원인 확정 없이 코드부터 고치지 않는다.

MANDATORY 워크플로우:
1. 원인을 코드·로그로 확정한다 (추측 금지)
2. 그 원인을 직접 단언하는 재현 테스트를 1개 이상 먼저 작성 (RED)
3. 테스트 실행 - 기존 코드에서 FAIL이어야 한다 (재현 확인)
4. 최소 수정으로 통과시킨다 (GREEN)
5. 테스트 실행 - PASS + 인접 테스트 회귀 검증

재현 테스트의 단언은 원인이 되는 잘못된 값을 직접 검증한다. 통과만을 위해 단언을 느슨하게 풀지 않으며, 테스트 없이 코드만 고치고 끝내지 않는다.

재현 테스트를 작성할 수 없으면(외부 상태·실계좌 의존 등) 사유를 보고하고 수동 검증 절차를 남긴다.

### Troubleshooting Test Failures

1. 테스트 격리 점검
2. mock이 올바른지 검증
3. 테스트가 아니라 구현을 수정한다 (테스트가 잘못된 경우 제외)

## Agent Support

- **tdd-guide** - 테스트 작성 전담(신규 구현 위임). 선행/사후 모드는 호출자가 지정한다 (신규 구현=사후, 결제류=선행). 디버그는 메인이 직접 TDD(재현 테스트 먼저 작성)로 수행한다 — tdd-guide 스폰 안 함.

## Test Structure (AAA Pattern)

테스트에는 Arrange-Act-Assert 구조를 선호한다:

```typescript
test('calculates similarity correctly', () => {
  // Arrange
  const vector1 = [1, 0, 0]
  const vector2 = [0, 1, 0]

  // Act
  const similarity = calculateCosineSimilarity(vector1, vector2)

  // Assert
  expect(similarity).toBe(0)
})
```

### Test Naming

테스트되는 동작을 설명하는 descriptive한 이름을 사용한다:

```typescript
test('returns empty array when no markets match query', () => {})
test('throws error when API key is missing', () => {})
test('falls back to substring search when Redis is unavailable', () => {})
```
