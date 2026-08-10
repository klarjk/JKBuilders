# JKBuilders

> Claude Code용 개발 워크플로우 모음 — 멀티세션 개발 지휘부터 요구사항 정의·구현·리뷰까지, 명령 한 줄로 여러 전문 에이전트가 협업합니다.

**한국어** | [English](README.en.md)

---

## 이게 뭔가요?

Claude Code에서 소프트웨어를 만들 때 쓰는 **워크플로우 도구 모음**입니다. 개발 계획을 세우고, 설계를 결정하고, 코드를 구현·테스트·리뷰하는 과정을 여러 전문 에이전트와 스킬이 나눠 맡습니다. 명령 한 줄(`/dev-loop`, `/impl`, `/prp-plan` 등)이면 뒤에서 관련 에이전트들이 자동으로 협업합니다.

멀티세션 개발은 할 일을 한 줄로 늘어놓지 않고 **작업 흐름도(플로우차트)**로 배치합니다. 작업 하나하나가 흐름도의 칸이 되고 "무엇이 끝나야 시작할 수 있는가"로 이어지므로, 동시에 할 수 있는 일은 동시에 굴리고 결과에 따라 길이 갈리는 지점은 분기로 처리합니다.

## 무엇이 들어있나요?

네 갈래로 나뉩니다.

| 갈래 | 하는 일 | 진입 명령 |
|------|---------|-----------|
| **/dev-loop 계열** | 멀티세션 개발 지휘 — 할 일을 작업 흐름도로 배치해 조사·설계·구현·리뷰를 완료까지 자동 반복 | `/dev` · `/dev-loop` · `/impl` · `/adr` |
| **/prp 계열** | 요구사항→계획→구현→PR로 이어지는 단발 개발 파이프라인 | `/prp-prd` · `/prp-plan` · `/prp-implement` · `/prp-pr` · `/prp-commit` |
| **메모리 계열** | 스킬·에이전트가 스스로 배운 것을 다음 실행에서 기억하게 하는 자동 메모리 | `/add-memory` |
| **기타** | 조건부 규칙 트리거 예시 등 | `triggers_CLAUDE.md` |

자세한 사용 흐름과 에이전트 협업 구조는 [**상세 설명서**](#상세-설명서)를 참고하세요.

## 설치 방법

이 저장소는 **Claude Code 자체를 위한 것**이라, 설치도 클로드에게 맡기면 됩니다. 저장소를 내려받은 뒤, 본인의 Claude에게 아래처럼 부탁하세요.

**전체 이식**

```
이 JKBuilders 저장소의 워크플로우를 내 Claude Code 시스템에 이식해줘.
agents/ · commands/ · skills/ · rules/ · rules-detail/ 를 내 ~/.claude/ 아래
대응 위치에 복사하고, triggers_CLAUDE.md 의 트리거 정의를 내 전역
~/.claude/CLAUDE.md 에 병합해줘. 겹치는 항목이 있으면 먼저 알려줘.
```

**계열만 골라 이식** (예: `/dev-loop` 계열만)

```
JKBuilders의 /dev-loop 계열만 내 시스템에 이식해줘.
skills/dev · dev-loop · impl · adr · tdd-workflow 와 이들이 스폰하는
agents/* , 그리고 rules/ · rules-detail/ 를 ~/.claude/ 아래에 설치하고,
triggers_CLAUDE.md 의 트리거를 내 전역 CLAUDE.md 에 병합해줘.
```

## 주의할 점

- **계열 단위로 설치하세요.** 항목들이 서로를 호출합니다 (예: `/impl`이 planner·tdd-guide·code-reviewer를 자동 스폰). 에이전트 하나만 떼오면 그것이 부르는 다른 에이전트가 없어 멈춥니다.
- **경로는 `~/.claude/` 관례를 전제**합니다. 다른 위치에 설치하면 파일 안의 참조 경로도 함께 바꿔야 합니다.
- **모델 지정에 주의.** 각 에이전트 앞머리에 `model: opus / sonnet / fable` 같은 지정이 있습니다. 본인 요금제에서 쓸 수 없는 모델이면 조정이 필요합니다.
- **자동 메모리는 블록이 심어진 항목에서만** 동작합니다. `/add-memory`로 원하는 스킬·에이전트에 장착하세요.
- **`/prp` 계열은 `.claude/PRPs/` 폴더**에 요구사항·계획·보고서를 쌓습니다.
- **settings.json 필수 설정** — 이 워크플로우는 서브에이전트 스폰·병렬 트랙·중첩 수렴을 전제합니다. `~/.claude/settings.json`에 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`·`worktree.baseRef`를 설정하세요 (상세 설명서 참고).

## 출처 / 크레딧

자체 제작 항목과 외부 오픈소스에서 가져온 항목이 섞여 있습니다.

- **[Wirasm / PRPs-agentic-eng](https://github.com/Wirasm/PRPs-agentic-eng)** — `/prp` 계열 커맨드 전부 (prp-prd · prp-plan · prp-implement · prp-pr · prp-commit)
- **[everything-claude-code](https://github.com/affaan-m/everything-claude-code)** — 에이전트 architect · planner · tdd-guide · code-reviewer · security-reviewer · e2e-runner, 스킬 tdd-workflow, 룰 testing
- 그 외 모든 항목은 자체 제작입니다.

## 상세 설명서

각 명령의 사용 흐름·에이전트 협업 구조·계열별 상세는 아래 문서를 참고하세요.

- [한국어 상세 설명서](docs/manual.ko.html)
- [English manual](docs/manual.en.html)
