---
name: tdd-workflow
description: 새 기능 작성·버그 수정·코드 리팩토링 시 사용한다. 단위·통합·E2E 테스트로 80% 이상 커버리지를 강제하는 테스트 주도 개발(TDD)을 보장한다.
origin: ECC
---

# 테스트 주도 개발(TDD) 워크플로우

이 스킬은 모든 코드 개발이 포괄적인 테스트 커버리지와 함께 TDD 원칙을 따르도록 보장한다.

## 활성화 시점

- 새 기능 또는 기능적 요소 작성
- 버그 또는 이슈 수정
- 기존 코드 리팩토링
- API 엔드포인트 추가
- 새 컴포넌트 생성

## 핵심 원칙

### 1. 코드보다 테스트가 먼저
ALWAYS 테스트를 먼저 작성한 뒤, 테스트를 통과시키는 코드를 구현한다.

### 2. 커버리지 요구 사항
- 최소 80% 커버리지 (단위 + 통합 + E2E)
- 모든 경계 케이스 커버
- 에러 시나리오 테스트
- 경계 조건 검증

### 3. 테스트 종류

#### 단위 테스트(Unit Tests)
- 개별 함수와 유틸리티
- 컴포넌트 로직
- 순수 함수
- 헬퍼와 유틸리티

#### 통합 테스트(Integration Tests)
- API 엔드포인트
- 데이터베이스 작업
- 서비스 상호작용
- 외부 API 호출

#### E2E 테스트(Playwright)
- 크리티컬 사용자 흐름
- 전체 워크플로우
- 브라우저 자동화
- UI 상호작용

### 4. Git 체크포인트
- 저장소가 Git이라면 각 TDD 단계 직후 체크포인트 커밋을 생성한다
- 워크플로우가 완료될 때까지 이 체크포인트 커밋들을 squash하거나 재작성하지 않는다
- 각 체크포인트 커밋 메시지는 단계와 캡처된 정확한 증거를 묘사해야 한다
- 현재 태스크를 위한 현재 활성 브랜치에서 생성된 커밋만 집계한다
- 다른 브랜치의 커밋, 이전의 관련 없는 작업, 먼 브랜치 이력을 유효한 체크포인트 증거로 취급하지 않는다
- 체크포인트가 충족된 것으로 취급하기 전, 그 커밋이 활성 브랜치의 현재 `HEAD`에서 도달 가능하며 현재 태스크 시퀀스에 속하는지 검증한다
- 권장되는 컴팩트 워크플로우는 다음과 같다:
  - 실패하는 테스트를 추가하고 RED를 검증한 커밋 1개
  - 최소 수정을 적용하고 GREEN을 검증한 커밋 1개
  - 리팩토링 완료 커밋 1개(선택)
- 테스트 커밋이 명확히 RED에 대응하고 수정 커밋이 명확히 GREEN에 대응한다면, 별도 증거 전용 커밋은 필요하지 않다

## TDD 워크플로우 단계

### 1단계: 사용자 여정 작성
```
As a [역할], I want to [작업], so that [이익]

예시:
As a user, I want to search for markets semantically,
so that I can find relevant markets even without exact keywords.
```

### 2단계: 테스트 케이스 생성
각 사용자 여정에 대해 포괄적인 테스트 케이스를 작성한다:

```typescript
describe('Semantic Search', () => {
  it('returns relevant markets for query', async () => {
    // Test implementation
  })

  it('handles empty query gracefully', async () => {
    // Test edge case
  })

  it('falls back to substring search when Redis unavailable', async () => {
    // Test fallback behavior
  })

  it('sorts results by similarity score', async () => {
    // Test sorting logic
  })
})
```

### 3단계: 테스트 실행 (실패해야 함)
```bash
npm test
# 아직 구현하지 않았으므로 테스트가 실패해야 한다
```

이 단계는 필수이며, 모든 프로덕션 변경에 대한 RED 게이트다.

비즈니스 로직 또는 다른 프로덕션 코드를 수정하기 전에, 다음 중 하나의 경로로 유효한 RED 상태를 검증해야 한다:
- 런타임 RED:
  - 관련 테스트 타겟이 성공적으로 컴파일됨
  - 새로 추가하거나 변경한 테스트가 실제로 실행됨
  - 결과가 RED임
- 컴파일 타임 RED:
  - 새 테스트가 버그 있는 코드 경로를 새로 인스턴스화·참조·실행함
  - 컴파일 실패 자체가 의도된 RED 신호임
- 두 경우 모두, 실패는 의도된 비즈니스 로직 버그·정의되지 않은 동작·누락된 구현에 의해 발생해야 한다
- 실패가 무관한 구문 에러·깨진 테스트 셋업·누락된 의존·무관한 회귀에만 의해 발생해서는 안 된다

작성만 되고 컴파일·실행되지 않은 테스트는 RED로 인정되지 않는다.

이 RED 상태가 확정되기 전에는 프로덕션 코드를 편집하지 않는다.

저장소가 Git이라면, 이 단계가 검증된 직후 체크포인트 커밋을 생성한다.
권장 커밋 메시지 형식:
- `test: add reproducer for <기능 또는 버그>`
- 재현 테스트가 컴파일·실행되었고 의도된 이유로 실패했다면 이 커밋은 RED 검증 체크포인트의 역할도 겸한다
- 계속 진행하기 전에 이 체크포인트 커밋이 현재 활성 브랜치에 있는지 검증한다

### 4단계: 코드 구현
테스트를 통과시키기 위한 최소한의 코드를 작성한다:

```typescript
// Implementation guided by tests
export async function searchMarkets(query: string) {
  // Implementation here
}
```

저장소가 Git이라면, 최소 수정을 지금 stage하되 체크포인트 커밋은 5단계에서 GREEN이 검증될 때까지 보류한다.

### 5단계: 테스트 재실행
```bash
npm test
# 이제 테스트가 통과해야 한다
```

수정 후 동일한 관련 테스트 타겟을 다시 실행하여, 이전에 실패했던 테스트가 이제 GREEN임을 확인한다.

유효한 GREEN 결과를 얻은 후에만 리팩토링으로 진행한다.

저장소가 Git이라면, GREEN이 검증된 직후 체크포인트 커밋을 생성한다.
권장 커밋 메시지 형식:
- `fix: <기능 또는 버그>`
- 동일한 관련 테스트 타겟이 재실행되어 통과했다면 수정 커밋이 GREEN 검증 체크포인트의 역할도 겸한다
- 계속 진행하기 전에 이 체크포인트 커밋이 현재 활성 브랜치에 있는지 검증한다

### 6단계: 리팩토링
테스트를 green으로 유지하면서 코드 품질을 개선한다:
- 중복 제거
- 명명 개선
- 성능 최적화
- 가독성 향상

저장소가 Git이라면, 리팩토링이 완료되고 테스트가 green으로 유지되는 직후 체크포인트 커밋을 생성한다.
권장 커밋 메시지 형식:
- `refactor: clean up after <기능 또는 버그> implementation`
- TDD 사이클을 완료된 것으로 간주하기 전에 이 체크포인트 커밋이 현재 활성 브랜치에 있는지 검증한다

### 7단계: 커버리지 검증
```bash
npm run test:coverage
# 80% 이상 커버리지가 달성되었는지 검증
```

## 테스트 패턴

### 단위 테스트 패턴 (Jest/Vitest)
```typescript
import { render, screen, fireEvent } from '@testing-library/react'
import { Button } from './Button'

describe('Button Component', () => {
  it('renders with correct text', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByText('Click me')).toBeInTheDocument()
  })

  it('calls onClick when clicked', () => {
    const handleClick = jest.fn()
    render(<Button onClick={handleClick}>Click</Button>)

    fireEvent.click(screen.getByRole('button'))

    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Click</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })
})
```

### API 통합 테스트 패턴
```typescript
import { NextRequest } from 'next/server'
import { GET } from './route'

describe('GET /api/markets', () => {
  it('returns markets successfully', async () => {
    const request = new NextRequest('http://localhost/api/markets')
    const response = await GET(request)
    const data = await response.json()

    expect(response.status).toBe(200)
    expect(data.success).toBe(true)
    expect(Array.isArray(data.data)).toBe(true)
  })

  it('validates query parameters', async () => {
    const request = new NextRequest('http://localhost/api/markets?limit=invalid')
    const response = await GET(request)

    expect(response.status).toBe(400)
  })

  it('handles database errors gracefully', async () => {
    // Mock database failure
    const request = new NextRequest('http://localhost/api/markets')
    // Test error handling
  })
})
```

### E2E 테스트 패턴 (Playwright)
```typescript
import { test, expect } from '@playwright/test'

test('user can search and filter markets', async ({ page }) => {
  // Navigate to markets page
  await page.goto('/')
  await page.click('a[href="/markets"]')

  // Verify page loaded
  await expect(page.locator('h1')).toContainText('Markets')

  // Search for markets
  await page.fill('input[placeholder="Search markets"]', 'election')

  // Wait for debounce and results
  await page.waitForTimeout(600)

  // Verify search results displayed
  const results = page.locator('[data-testid="market-card"]')
  await expect(results).toHaveCount(5, { timeout: 5000 })

  // Verify results contain search term
  const firstResult = results.first()
  await expect(firstResult).toContainText('election', { ignoreCase: true })

  // Filter by status
  await page.click('button:has-text("Active")')

  // Verify filtered results
  await expect(results).toHaveCount(3)
})

test('user can create a new market', async ({ page }) => {
  // Login first
  await page.goto('/creator-dashboard')

  // Fill market creation form
  await page.fill('input[name="name"]', 'Test Market')
  await page.fill('textarea[name="description"]', 'Test description')
  await page.fill('input[name="endDate"]', '2025-12-31')

  // Submit form
  await page.click('button[type="submit"]')

  // Verify success message
  await expect(page.locator('text=Market created successfully')).toBeVisible()

  // Verify redirect to market page
  await expect(page).toHaveURL(/\/markets\/test-market/)
})
```

## 테스트 파일 구성

```
src/
├── components/
│   ├── Button/
│   │   ├── Button.tsx
│   │   ├── Button.test.tsx          # 단위 테스트
│   │   └── Button.stories.tsx       # Storybook
│   └── MarketCard/
│       ├── MarketCard.tsx
│       └── MarketCard.test.tsx
├── app/
│   └── api/
│       └── markets/
│           ├── route.ts
│           └── route.test.ts         # 통합 테스트
└── e2e/
    ├── markets.spec.ts               # E2E 테스트
    ├── trading.spec.ts
    └── auth.spec.ts
```

## 외부 서비스 모킹

### Supabase 모킹
```typescript
jest.mock('@/lib/supabase', () => ({
  supabase: {
    from: jest.fn(() => ({
      select: jest.fn(() => ({
        eq: jest.fn(() => Promise.resolve({
          data: [{ id: 1, name: 'Test Market' }],
          error: null
        }))
      }))
    }))
  }
}))
```

### Redis 모킹
```typescript
jest.mock('@/lib/redis', () => ({
  searchMarketsByVector: jest.fn(() => Promise.resolve([
    { slug: 'test-market', similarity_score: 0.95 }
  ])),
  checkRedisHealth: jest.fn(() => Promise.resolve({ connected: true }))
}))
```

### OpenAI 모킹
```typescript
jest.mock('@/lib/openai', () => ({
  generateEmbedding: jest.fn(() => Promise.resolve(
    new Array(1536).fill(0.1) // Mock 1536-dim embedding
  ))
}))
```

## 테스트 커버리지 검증

### 커버리지 리포트 실행
```bash
npm run test:coverage
```

### 커버리지 임계값
```json
{
  "jest": {
    "coverageThresholds": {
      "global": {
        "branches": 80,
        "functions": 80,
        "lines": 80,
        "statements": 80
      }
    }
  }
}
```

## 피해야 할 흔한 테스트 실수

### FAIL: WRONG — 구현 세부사항을 테스트
```typescript
// 내부 상태를 테스트하지 말 것
expect(component.state.count).toBe(5)
```

### PASS: CORRECT — 사용자에게 보이는 동작을 테스트
```typescript
// 사용자가 보는 것을 테스트
expect(screen.getByText('Count: 5')).toBeInTheDocument()
```

### FAIL: WRONG — 깨지기 쉬운 셀렉터
```typescript
// 쉽게 깨진다
await page.click('.css-class-xyz')
```

### PASS: CORRECT — 의미 기반 셀렉터
```typescript
// 변경에 강건하다
await page.click('button:has-text("Submit")')
await page.click('[data-testid="submit-button"]')
```

### FAIL: WRONG — 테스트 격리 없음
```typescript
// 테스트가 서로 의존
test('creates user', () => { /* ... */ })
test('updates same user', () => { /* depends on previous test */ })
```

### PASS: CORRECT — 독립 테스트
```typescript
// 각 테스트가 자체 데이터를 셋업
test('creates user', () => {
  const user = createTestUser()
  // Test logic
})

test('updates user', () => {
  const user = createTestUser()
  // Update logic
})
```

## 지속적 테스트

### 개발 중 Watch 모드
```bash
npm test -- --watch
# 파일 변경 시 테스트가 자동 실행
```

### Pre-Commit 훅
```bash
# 모든 커밋 전에 실행됨
npm test && npm run lint
```

### CI/CD 통합
```yaml
# GitHub Actions
- name: Run Tests
  run: npm test -- --coverage
- name: Upload Coverage
  uses: codecov/codecov-action@v3
```

## 모범 사례

1. **테스트 먼저** — ALWAYS TDD
2. **테스트당 단일 assert** — 단일 동작에 집중
3. **서술적 테스트 이름** — 무엇을 테스트하는지 설명
4. **Arrange-Act-Assert** — 명확한 테스트 구조
5. **외부 의존을 모킹** — 단위 테스트를 격리
6. **경계 케이스를 테스트** — null, undefined, empty, large
7. **에러 경로를 테스트** — happy path만이 아니라
8. **테스트를 빠르게 유지** — 단위 테스트는 각 50ms 미만
9. **테스트 후 정리** — 사이드 이펙트 없음
10. **커버리지 리포트를 리뷰** — 갭을 식별

## 성공 지표

- 80% 이상 코드 커버리지 달성
- 모든 테스트가 통과(green)
- skip 또는 disabled된 테스트 없음
- 빠른 테스트 실행 (단위 테스트 30초 미만)
- E2E 테스트가 크리티컬 사용자 흐름을 커버
- 테스트가 프로덕션 전에 버그를 잡음

---

**기억하라**: 테스트는 선택 사항이 아니다. 자신 있는 리팩토링·신속한 개발·프로덕션 신뢰성을 가능하게 하는 안전망이다.
