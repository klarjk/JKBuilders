# 우체부 (postman)

ADR-002의 **텔레그램 중계 프로그램**. 머신 전역 1개 프로세스로 돌며, 나가는 알림을 텔레그램으로
보내고 들어오는 답장·명령을 tmux 세션에 넣는다. 경계 문구는 하나다 (D1).

> **우체부는 프로젝트 상태를 해석하지 않는다 — 무엇을 넣을지는 결정하지 않고, 이미 결정된
> 문자열을 지정된 주소에 넣고 들어갔는지 확인한다.**

`skills/dev-run/`(DEV_PLAN-001, 동결)의 **사본이자 재배선판**이다. 001 트리는 한 줄도 고치지
않으며 임포트도 하지 않는다(D5). 유일한 예외는 **봇 토큰 파일을 읽는 것**뿐이다 — 새 봇을
만들지 않는 것이 승계 규약이다(D2).

## 두 계층

이 트리는 두 노드로 나눠 지었고, 경계는 `postman/bot.py`의 `Handler` 인터페이스다.

| 계층 | 노드 | 범위 |
|---|---|---|
| **코어** | 002-N4A | 폴링·오프셋 영속·허용자 검증·발신 직렬 큐·상한 2단·마스킹 관문·1회 한정 장부·회신 변별자·주소 규약·유휴 종료·중복 기동 차단·SIGTERM 정상 종료·경계 AST 검사 |
| **주입·세대** | 002-N4B | tmux 주입(재캡처 3회 확인)·`pending`과 재주입·인라인 버튼 행동 레코드와 세대·알림 파일 스캔 배달·중계 라우팅·`done` 중계 |

`main()`이 `handler.SessionHandler`를 끼운다. **아무것도 끼우지 않고 띄운 우체부**(코어
단독 시험)는 받은 것을 조용히 버리지 않고 "주입 계층이 연결되지 않았다"고 회신한다.

### 답 하나가 화면에 닿기까지

```
텔레그램 답장 ──▶ bot: 허용자·1:1 검증 ──▶ messages.json 매핑(없으면 현 지휘)
                                              │
                                              ▼
                        handler ──▶ 교체 중인가? ──예──▶ pending 보관
                                              │아니오
                                              ▼
       inject: 장부 intent ─▶ 질문 열림? ─▶ send-keys -l ─▶ Enter
                        (응답 표식 1차 · 화면 재캡처 보조)
                                              │
                                    같은 순서로 반영 확인 (표식 → 재캡처 3회)
                                    ├─ 확인 ──▶ 장부 done + answer-g<세대>-NN.json
                                    ├─ 확인 못 함 ──▶ 중단 + attach 안내 + diag/ 캡처 보존
                                    │                (**전달 실패가 아니다** — 들어갔을 수 있다)
                                    └─ 대상 소멸 ──▶ pending 보관 → running 뒤 재주입
```

## 파일

| 파일 | 무엇을 |
|---|---|
| `protocol/commands.py` | 닫힌 명령 열거형의 **단일 출처** — `status`·`done`·`halt`·`resume` |
| `postman/paths.py` | 우편함 경로·`config.json`(fail-closed)·토큰 읽기·원자적 쓰기. 나머지 전부가 임포트한다 |
| `postman/addressing.py` | **주소 정규식의 단일 출처** — tmux 세션명·노드 ID·클로드 UUID 세 이름공간 |
| `postman/transport.py` | 텔레그램 HTTP(urllib). **네트워크에 닿는 유일한 지점** — 테스트는 여기를 갈아끼운다 |
| `postman/masking.py` | **마스킹 관문** — 값 형태 + 이름 계층 + `never_send` 파일 내용 제거 |
| `postman/sender.py` | 발신 직렬 큐(초당 1건)·429 `retry_after`·4096자 분할·상한 적용. 모든 본문이 관문을 지난다 |
| `postman/limits.py` | 발신 상한 2단(연 30·경 60) — `counters.json` |
| `postman/ledger.py` | 부작용 1회 한정 장부 — `ledger.json`. 주입만 2단(intent → done) |
| `postman/store.py` | `offset.json`과 손상 격리 공용 저장소 |
| `postman/discriminator.py` | 회신 변별자 `[<노드ID> g<세대>#<n>]` — 동일 본문 회신이 삼켜지는 것을 피한다 |
| `postman/commands.py` | 명령 파싱(한글 별칭 포함)·노드 ID 인식기(`002-N4B` 형식 허용) |
| `postman/inject.py` | **주입 절차** — 장부 2단 기록·열림 확인·반영 확인. 두 확인 모두 **응답 표식이 1차, 화면 재캡처 3회가 보조**다. 실패는 대상의 생사로 가른다 |
| `postman/delivery.py` | **우편함 → 텔레그램** — 안정화 확인·손상 격리·질문 선택지의 인라인 버튼 조립 |
| `postman/handler.py` | **라우팅** — 답장·버튼·`done`을 어느 화면에 넣을지. 세대 대조와 보관·재주입 |
| `postman/relay.py` | `relay.json` **읽기 전용** — 쓰는 주체는 창구 하나뿐이다 |
| `postman/mailbox.py` | 우편함 파일 규약(표식 이름 포함)·미발신 판정·청소·권한 점검 대상 열거 |
| `postman/tmuxq.py` | tmux 조회·캡처·리터럴 주입(+`halt`의 `kill-session`). **캡처 실패는 `None`, 빈 화면은 `""`** |
| `postman/eventlog.py` | `log/postman-YYYYMMDD.jsonl` — **이벤트 메타만, 본문 불기록** |
| `postman/diag.py` | **중단 진단 캡처** — 중단 시 화면 `before`/`after`를 `diag/`에 보존. 마스킹 관문을 지나고, 실패해도 예외를 올리지 않는다 |
| `postman/bot.py` | 폴링 루프·명령 처리·잠금·heartbeat·청소·유휴 종료·신호 처리. `python3 postman/bot.py`로 기동 |

## 우편함 (`~/.claude/postman/`)

```
config.json      허용 user id·never_send·타임아웃 (600, fail-closed)
lock             이중 기동 차단 (pid)
heartbeat        폴링 사이클마다 touch — 지휘·창구가 생존을 판정한다
offset.json      getUpdates 오프셋
actions.json     버튼 행동 레코드 — 1회 소진·만료·**발급 세대와 session_uuid**
messages.json    질문 message_id ↔ 세션·세대·seq — 답장 라우팅의 1순위
ledger.json      1회 한정 장부 — 우체부 단독 쓰기
counters.json    발신 상한 계수
relay.json       현 지휘 주소·세대·상태 — **창구 단독 쓰기**
log/             이벤트 메타
sessions/<tmux세션명>/ (700)   notify-*.json · *.sent · question-g<세대>-NN.json
                        question-….json.answered (600 · 세션이 남기는 응답 표식 · 청소 대상 제외)
                        answer-g<세대>-NN.json · pending-*.json (청소 대상 제외)
sessions/counter/       창구 전용 우편함 (고정 이름)
corrupt/         손상 파일 격리
diag/            중단 진단 캡처 — 마스킹 관문을 지난 화면 두 장 (14일 보존)
```

**파일 하나에 쓰는 주체는 정확히 하나. 모든 쓰기는 같은 디렉토리에 `.tmp`로 쓴 뒤 rename한다.**

## 기동

```bash
POSTMAN_PROJECT=<프로젝트슬러그> python3 skills/postman/postman/bot.py --check   # 설정·경로 자가 점검 (네트워크 안 씀)
POSTMAN_PROJECT=<프로젝트슬러그> python3 skills/postman/postman/bot.py           # 창구가 /dev-loop 시작 시 띄운다
```

`POSTMAN_PROJECT`는 발신문 앞에 붙는 출처 표시와, 다른 프로젝트의 지휘가 도는 동안의 기동
거부가 함께 읽는 값이다. **비워 두면 둘 다 잠든다** — 세션명에 쓰는 슬러그(`dev-<슬러그>-<노드>`)를
그대로 넣는다. 세션명 규약을 못 지나는 값은 없는 것으로 친다.

launchd 상시 감독을 두지 않는다 — 우체부는 개발 루프가 돌 때만 필요하고, 지휘가 오래
부재하면 **스스로 물러난다**(001의 봇은 동결 후 25시간을 살아 통로를 막을 뻔했다).

`config.json` 최소 형태:

```json
{"allowed_user_ids": [123456789], "chat_id": 123456789,
 "never_send": ["~/vault/계정.md", "~/vault/비밀번호.md"]}
```

> `never_send`를 비워 두면 화면 캡처에 실린 평문 개인정보가 그대로 제3자 서버로 나간다.
> 볼트 운용이면 루트의 평문 파일을 **실제로 훑어** 전부 등록한다.

### 처음 놓는 경우 — 봇 토큰과 허용 상대

001(`skills/dev-run/`)을 쓰지 않고 이 트리만 떼어 놓는 설치에는 승계할 봇이 없다. 다섯을
차례로 밟는다.

1. **봇을 만들고 토큰을 받는다.** 텔레그램에서 `@BotFather`에게 `/newbot` → 이름·사용자명을
   정하면 토큰 한 줄을 준다.
2. **토큰을 파일에 넣는다.** 기본 자리는 `~/.claude/dev-run/telegram-bot-token`이고(001에서
   그대로 읽는 승계 규약 — D2), 다른 자리에 두려면 `POSTMAN_TOKEN_FILE`로 가리킨다.
   **값은 파일 밖 어디에도 두지 않는다** — 셸 히스토리에 남는 `echo`보다 편집기가 낫다.

   ```bash
   mkdir -p ~/.claude/dev-run && install -m 600 /dev/null ~/.claude/dev-run/telegram-bot-token
   # 편집기로 열어 토큰 한 줄만 붙여 넣는다
   ```

3. **자기 user id를 알아낸다.** 만든 봇에게 아무 말이나 1:1로 보낸 뒤 아래를 돌리면
   `from.id`가 보인다. **이 명령은 토큰을 인자로 받지 않고 파일에서 읽는다.**

   ```bash
   python3 -c "import urllib.request,json,pathlib; \
     t=pathlib.Path.home().joinpath('.claude/dev-run/telegram-bot-token').read_text().strip(); \
     print(json.dumps(json.load(urllib.request.urlopen('https://api.telegram.org/bot'+t+'/getUpdates')),ensure_ascii=False,indent=2))"
   ```

4. **`config.json`을 만들어 적는다.** 토큰 파일과 같이 **600으로 먼저 만들고** 편집기로 채운다 —
   편집기가 기본으로 만들면 644로 남고, `--check`는 그것을 주의로만 찍고 통과시킨다.

   ```bash
   install -m 600 /dev/null ~/.claude/postman/config.json
   # 편집기로 열어 아래를 적는다
   # {"allowed_user_ids": [<3번에서 본 id>], "chat_id": <같은 id>,
   #  "never_send": ["~/개인정보.md"]}
   ```

5. **점검한다.** `bot.py --check`가 fail-closed·권한·`never_send`를 한 번에 훑는다.
   **주의가 1건이라도 찍히면 고치고 다시 돌린다** — 종료코드는 주의가 있어도 0이라, 통과 여부는
   출력 마지막 줄의 건수로 읽는다.

> **Do:** 토큰은 600 파일에만 두고, 허용 목록에 자기 id만 적고, `--check`로 확인한 뒤 띄운다
> **Don't:** 토큰 **값**을 명령줄 인자·환경변수(경로만 담는 `POSTMAN_TOKEN_FILE`은 제외)·리포 안 파일에 싣거나, 허용 목록을 비운 채 띄운다
> (비어 있으면 전부 폐기라 통로가 조용히 죽는다)

## 시험

```bash
cd skills/postman && python3 -m pytest -q
```

`tmux`도 텔레그램도 실호출하지 않는다. 인터프리터는 pytest가 깔린 것을 쓰되(이 기계에서는
`/usr/local/bin/python3`), 코드는 **시스템 파이썬 3.9에서도 임포트되어야 한다** — 전역 상태줄
확장이 남의 프로세스 안에서 임포트되는 조건과 같은 폭을 유지한다.

## 세션이 우체부에게 말하는 법

세션은 텔레그램을 모른다. 자기 우편함에 파일만 쓴다.

**우편함 디렉토리는 700, 그 안에 쓰는 파일은 600으로 만든다.** 질문 본문과 답이 여기 쌓인다.
리다이렉션·편집기로 바로 만들면 755·644로 남으므로 **자리를 먼저 잡고 채운다.**

```bash
install -d -m 700 ~/.claude/postman/sessions/<자기 tmux명>
install -m 600 /dev/null <파일>     # 그 뒤 리다이렉션으로 채운다 — 권한은 그대로 남는다
```

`bot.py --check`가 우편함 디렉토리(700)와 응답 표식(600)의 어긋남을 **검출만 하고 고쳐 쓰지
않는다** — 쓰는 주체가 세션이라, 우체부가 권한까지 손대면 한 파일에 두 주체가 쓰게 된다.

**알림** — `sessions/<자기 tmux명>/notify-<ts_ms>-<rand6>.json`

```json
{"text": "노드 002-N4B 완료 — 커밋 3519d2a", "kind": "notify"}
```

`kind`는 `notify`·`alert`·`done_report` 중 하나(생략하면 `notify`). `alert`와
`done_report`는 연성 발신 상한 면제라 대기 해제성 통보가 막히지 않는다.
**`buttons`를 넣어도 버려진다** — 알림은 텍스트만이다.

지휘가 창구에 내는 제어 통보도 이 두 kind를 쓴다 — 교체 요청·계측 불능·우체부 재기동
요청은 `alert`, 완주 보고는 `done_report`다. 창구는 tmux 세션이 아니라 주입 대상이 되지
못해, **그 통보는 창구가 이 우편함을 직접 훑어 가져간다** — 청소 기한(`.sent` 뒤 7일)이 곧
제어 통보의 보존 기한이다. 통로 정본은 `skills/dev-loop/SKILL.md`의 「사용자에게 닿는 통로」다.

**질문** — `sessions/<자기 tmux명>/question-g<세대>-NN.json`

```json
{"text": "[002-N4B g2#3] 이 노드를 계속 진행할까요?",
 "question": "이 노드를 계속 진행할까요?",
 "choices": ["진행", "중단"], "node": "002-N4B"}
```

- **파일 이름의 `g<세대>`가 세대의 정본이다.** 본문 필드가 아니라 이름을 믿는다 — 이름이
  곧 세대 간 충돌 회피 장치라, 본문을 믿으면 그 장치가 무력해진다. 세대의 단일 출처는
  `relay.json`이고, 작업 세션은 위임 메시지로 받는다.
- `text`가 텔레그램에 나가는 본문, `question`은 **주입 직전 화면에 그 질문이 아직 열려
  있는지 대조하는 재료**다. 생략하면 `text`로 대조한다.
- `choices`가 인라인 버튼이 된다(최대 8개). 버튼을 누르면 그 라벨이 세션 화면에 들어간다.
- 발신 뒤에도 **원본은 그대로 남는다**(`.sent` 표식만 붙는다). 하룻밤 뒤 온 답도 이 파일에서
  대조 재료를 얻는다.
- 첫머리 변별자(`[<노드ID> g<세대>#<n>]`)는 **세션이 붙인다**(D10). 우체부는 붙이지 않는다.

### 답을 받았다고 알리는 법 — 응답 표식

**응답 표식** — `question-g<세대>-NN.json.answered`

```json
{"ts": 1756000000.0}
```

`ts`는 **초 단위 UNIX epoch**다(`time.time()`이 주는 값 그대로).

세션은 그 질문의 답을 화면으로 받아 처리한 **직후** 표식을 남긴다. `.sent`와 같은 자리·같은
형태이고(원본은 건드리지 않는다) 내용은 시각 하나면 된다.

**표식 파일은 600으로 만든다** — 「세션이 우체부에게 말하는 법」의 자리 잡기 명령을 그대로 쓴다.

우체부는 이 표식을 **주입 전 열림 확인과 주입 후 반영 확인 양쪽의 1차 근거로 읽는다.**
표식이 있으면 화면을 보지 않고, **없을 때만 화면 판정(재캡처 3회)으로 내려선다.** 표식을
빠뜨려도 통로는 종전대로 서지만, 남기면 화면 에코가 늦어 생기는 `not_reflected` 오판과
같은 질문에 답이 두 번 들어가는 일이 사라진다.

> **Do:** 답을 처리한 직후 그 질문 파일 이름 뒤에 `.answered`를 붙여 **600으로** 남긴다
> **Don't:** 답을 받기 전에 미리 남기거나, 644로 두고 우체부가 고쳐 줄 것으로 기대한다 —
> 미리 남기면 그 좌표의 답은 **영영 안 들어간다**

**표식이 확실히 듣는 자리는 다음 주입의 열림 확인이다.** 반영 확인은 넣은 직후 몇 초를 보는 자리라
세션이 답을 처리해 표식을 남기기 전에 끝나는 경우가 흔하다 — 그때는 화면 판정이 그대로 서므로
판정이 늦어지지도 깨지지도 않는다. 표식을 기다리려고 재캡처 창을 늘리지 않는다.

### 답이 도착했는지 어떻게 아는가 — **정본은 화면이다**

우체부가 답을 넣으면 같은 좌표로 `answer-g<세대>-NN.json`이 생긴다. 선택지 응답은
`UserPromptSubmit`을 발화시키지 않으므로 이 파일의 시각이 그 대용으로 쓸모가 있다.

> ⚠️ **이 파일은 답 도착의 증거가 아니라 사후 기록이다.** `answer-…`가 없다고 답이 안
> 들어온 것이 아니다 (002-N7 결함 ⑤).

안 써지는 경로가 실재한다.

- **주입은 성공했는데 반영 확인이 실패했다**(`not_reflected`) — 002-N7에서 실물로 났다.
  답은 화면에 들어가 세션이 정상 처리했지만 우체부는 확인하지 못했고, 그래서 이 파일을
  쓰지 않는다. 우체부는 이때 **「전달 실패」로 단정하지 않고** "확인하지 못했다(전달됐을
  수 있다)"로 회신하며, 중단 시점의 화면 두 장을 `diag/`에 남긴다.
- **기록 쓰기 자체가 실패했다** — 주입이 이미 끝난 뒤라 예외를 삼킨다. 여기서 예외를
  올리면 성공한 주입의 회신까지 사라진다.

응답 표식은 그 판정의 **결과를 우체부에게 알리는 것**이지 판정 재료가 아니다 — 표식을
기다리는 쪽은 우체부이고, 쓰는 쪽은 세션이다.

> **Do:** 답 도착은 **자기 화면**으로 판정한다 — 답은 세션의 입력으로 들어오므로 평소대로
> 프롬프트를 받아 처리하면 된다
> **Don't:** `answer-g<세대>-NN.json`이 생기기를 기다리는 대기 루프를 건다 — 위 경로에
> 걸리면 **영영 안 깨어난다**
