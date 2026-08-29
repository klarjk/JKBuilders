# JKBuilders

> Claude Code용 개발 워크플로우 모음 — 멀티세션 개발 지휘부터 요구사항 정의·구현·리뷰까지, 명령 한 줄로 여러 전문 에이전트가 협업합니다.

**한국어** | [English](README.en.md)

---

## 이게 뭔가요?

Claude Code에서 소프트웨어를 만들 때 쓰는 **워크플로우 도구 모음**입니다. 개발 계획을 세우고, 설계를 결정하고, 코드를 구현·테스트·리뷰하는 과정을 여러 전문 에이전트와 스킬이 나눠 맡습니다. 명령 한 줄(`/dev-loop`, `/impl`, `/prp-plan` 등)이면 뒤에서 관련 에이전트들이 자동으로 협업합니다.

멀티세션 개발은 할 일을 한 줄로 늘어놓지 않고 **작업 흐름도(플로우차트)**로 배치합니다. 작업 하나하나가 흐름도의 칸이 되고 "무엇이 끝나야 시작할 수 있는가"로 이어지므로, 동시에 할 수 있는 일은 동시에 굴리고 결과에 따라 길이 갈리는 지점은 분기로 처리합니다.

`/dev-loop`는 여기서 한 걸음 더 갑니다. **흐름도의 칸 하나를 통째로 별도 Claude 세션에 넘겨** 격리된 작업 공간에서 처리하게 하고, 계획이 끝날 때까지 이 위임을 자동으로 반복합니다. 되돌릴 수 없는 조작과 사람이 시안을 골라야 하는 디자인만 사용자 화면에 남습니다.

세션은 세 층으로 나뉩니다. 사용자가 마주 앉는 **창구**, 계획을 읽어 칸을 배분하는 **지휘**, 칸 하나씩을 맡는 **작업** 세션입니다. 창구는 지휘가 쓰는 대화 용량을 수치로 지켜보다가 가득 차기 전에 새 지휘로 갈아 끼우므로, 계획이 아무리 길어도 대화 한도에 걸려 멈추지 않습니다. 프로젝트마다 창구가 따로 서기 때문에 **한 대의 기계에서 여러 저장소를 동시에** 돌릴 수 있습니다.

돌아가는 중에도 언제든 `Esc`로 끼어들어 지시를 바꿀 수 있고, 감시가 한 바퀴 돌 때마다 그 안내가 화면에 나옵니다.

## 무엇이 들어있나요?

네 갈래로 나뉩니다.

| 갈래 | 하는 일 | 진입 명령 |
|------|---------|-----------|
| **/dev-loop 계열** | 멀티세션 개발 지휘 — 할 일을 작업 흐름도로 배치해 조사·설계·구현·리뷰를 완료까지 자동 반복. 노드마다 별도 세션에 위임 | `/dev` · `/dev-loop` · `/impl` · `/adr` |
| **/prp 계열** | 요구사항→계획→구현→PR로 이어지는 단발 개발 파이프라인 | `/prp-prd` · `/prp-plan` · `/prp-implement` · `/prp-pr` · `/prp-commit` |
| **메모리 계열** | 스킬·에이전트가 스스로 배운 것을 다음 실행에서 기억하게 하는 자동 메모리 | `/add-memory` |
| **기타** | 조건부 규칙 트리거 예시 등 | `triggers_CLAUDE.md` |

자세한 사용 흐름과 에이전트 협업 구조는 [**상세 설명서**](#상세-설명서)를 참고하세요.

## 설치 방법

이 저장소는 **Claude Code 자체를 위한 것**이라, 설치도 클로드에게 맡기면 됩니다. 저장소를 내려받은 뒤, 본인의 Claude에게 아래처럼 부탁하세요.

**전체 이식**

```
이 JKBuilders 저장소의 워크플로우를 내 Claude Code 시스템에 이식해줘.
agents/ · commands/ · skills/ · rules/ · rules-detail/ · scripts/ 를 내 ~/.claude/
아래 대응 위치에 복사하고, triggers_CLAUDE.md 의 트리거 정의를 내 전역
~/.claude/CLAUDE.md 에 병합해줘. 겹치는 항목이 있으면 먼저 알려줘.
```

**계열만 골라 이식** (예: `/dev-loop` 계열만)

```
JKBuilders의 /dev-loop 계열만 내 시스템에 이식해줘.
skills/dev · dev-loop · impl · adr · tdd-workflow 와 이들이 스폰하는
agents/* , 그리고 rules/ · rules-detail/ · scripts/ 를 ~/.claude/ 아래에 설치하고,
triggers_CLAUDE.md 의 트리거를 내 전역 CLAUDE.md 에 병합해줘.
설치 후 README 의 '설치 후 필수 설정' 항목을 순서대로 안내해줘.
```

## 설치 후 필수 설정

`/dev-loop` 계열은 아래 둘이 모두 갖춰져야 돕니다. 나머지 계열(`/prp`·메모리)은 1번만 있으면 됩니다.

### 1. settings.json

```jsonc
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "worktree": { "baseRef": "head" },
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/scripts/status-writer.py"
  }
}
```

- **`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`** — 서브에이전트가 다시 서브에이전트를 부르는 중첩 스폰을 켭니다. 없으면 `/impl`의 체인과 `synthesizer`의 수렴이 멈춥니다.
- **`worktree.baseRef`** — 병렬 작업이 격리 작업 공간을 만들 때 기준으로 삼을 커밋입니다.
- **`statusLine`** — 단순한 화면 장식이 아니라 **`/dev`의 계측 배선**입니다. 세션이 자기 대화 용량을 재는 재료가 여기서 나오고, 이 값이 없으면 정지·인수인계 시점을 놓칩니다. 이미 쓰는 상태줄 스크립트가 있다면 `scripts/status-writer.py` 머리말의 **②번 방식**으로 네 줄만 얹으세요.

### 2. tmux · jq

`/dev-loop`는 지휘·작업 세션을 모두 tmux로 띄웁니다. `tmux`가 없으면 세션이 서지 않습니다. `jq`는 무인 운전 중 쌓인 결함 기록을 세는 데 쓰며(`scripts/dl-incident.sh`), 없으면 그 집계만 빈손이 되고 루프 자체는 돕니다. `/dev`·`/impl` 단독 사용에는 둘 다 필요 없습니다.

### 3. 프로젝트 신뢰 수락

무인 세션은 Claude Code가 처음 띄우는 "이 폴더를 신뢰하느냐" 확인 창을 넘지 못합니다. `/dev-loop`는 스폰 전에 이 수락 여부를 확인하고, 없으면 띄우지 않고 사용자에게 넘깁니다. **대상 프로젝트에서 `claude`를 한 번 직접 실행해 수락해 두세요.**

## 주의할 점

- **계열 단위로 설치하세요.** 항목들이 서로를 호출합니다 (예: `/impl`이 planner·tdd-guide·code-reviewer를 자동 스폰). 에이전트 하나만 떼오면 그것이 부르는 다른 에이전트가 없어 멈춥니다.
- **경로는 `~/.claude/` 관례를 전제**합니다. 다른 위치에 설치하면 파일 안의 참조 경로도 함께 바꿔야 합니다.
- **모델 지정에 주의.** 각 에이전트 앞머리에 `model: opus / sonnet / fable` 같은 지정이 있습니다. 본인 요금제에서 쓸 수 없는 모델이면 조정이 필요합니다.
- **자동 메모리는 블록이 심어진 항목에서만** 동작합니다. `/add-memory`로 원하는 스킬·에이전트에 장착하세요.
- **`/prp` 계열은 `.claude/PRPs/` 폴더**에 요구사항·계획·보고서를 쌓습니다.
- **`/dev-loop`는 이 배포본에서 화면 모드로만 돕니다.** 원본에는 진행 상황을 텔레그램으로 주고받는 통로가 있지만, 그 부분은 공식 플러그인에서 갈라져 나온 외부 코드라 여기 싣지 않았습니다. 그래서 개시할 때마다 "채널 준비가 안 되어 화면 모드로 간다"는 경고가 한 줄 뜨는데, **정상 동작이며 루프는 화면에서 그대로 돕니다.**

## 출처 / 크레딧

자체 제작 항목과 외부 오픈소스에서 가져온 항목이 섞여 있습니다.

- **[Wirasm / PRPs-agentic-eng](https://github.com/Wirasm/PRPs-agentic-eng)** — `/prp` 계열 커맨드 전부 (prp-prd · prp-plan · prp-implement · prp-pr · prp-commit)
- **[everything-claude-code](https://github.com/affaan-m/everything-claude-code)** — 에이전트 architect · planner · tdd-guide · code-reviewer · security-reviewer · e2e-runner, 스킬 tdd-workflow, 룰 testing
- 그 외 모든 항목은 자체 제작입니다.

## 상세 설명서

각 명령의 사용 흐름·에이전트 협업 구조·계열별 상세는 아래 문서를 참고하세요.

- [한국어 상세 설명서](docs/manual.ko.html)
- [English manual](docs/manual.en.html)
