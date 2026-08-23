"""발신 — 직렬 큐·상한·분할·마스킹 (ADR-002 D2, ADR-001 D6·D9 승계).

- 채팅당 **초당 1건**을 넘지 않게 직렬로 내보낸다(세션 여럿의 우편함이 한 채팅으로 몰린다).
- 429의 `parameters.retry_after`(초)를 그대로 기다렸다가 재시도한다.
- 4096자를 넘는 본문은 분할한다.
- `parse_mode`를 쓰지 않는다 — 이스케이프 취약면 자체를 없앤다.
- **모든 본문과 버튼 라벨이 마스킹 관문(`masking.mask`)을 지난다.** 관문을 통과하지 않는
  발신 경로를 새로 만들지 않는다 (D2).
- 발신 상한 2단(`limits.SendLimiter`)이 여기 걸린다 — 억제는 실패와 구별해 보고한다.
- **모든 발신문이 출처 표시(`[<프로젝트>/<세션>]`)를 달고 나간다** (후속 59). 규칙은
  `paths.display_label` 한 곳에 있다 — 붙이는 자리를 여기로 모았으므로 배달·명령 응답이
  각자 접두를 조립하지 않는다. 같은 채팅에 여러 세션이 몰리는데 질문에는 출처가 아예
  없었고, 창구 우편함은 이름이 `counter` 고정이라 프로젝트가 둘이면 구별되지 않았다.

**분할된 본문의 일부만 나갔는데 성공으로 처리하지 않는다.** 호출자가 원본을 지우거나
완료 표식을 붙이면 잘린 메시지가 그대로 유실된다. 전체 실패로 다뤄 다음 순회에
재시도하게 한다 — 중복 발신과 유실 중 **중복 쪽으로 기운다**(유실이 더 나쁘다).

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import logging
import time

from postman import eventlog
from postman import masking
from postman import paths
from postman.transport import TelegramError

log = logging.getLogger("postman.sender")

MAX_TEXT = 4096

# 한 발신문의 본문 상한. 직렬 큐가 **초당 1건**이라 4096자 조각이 200개면 큐가 200초 동안
# 막히고, 그 사이 질문·경보가 뒤에 줄을 선다. **마스킹을 지난 뒤에** 자른다 — 넘치면
# 잘라 내되 **잘랐다고 적는다** —
# 조용히 자르면 사람은 그 뒤에 무엇이 있었는지 영영 모른다. 화면 캡처를 40줄로 줄이는 것은
# 만드는 쪽(`masking.truncate_capture`)의 몫이고, 이것은 그것과 무관한 마지막 방벽이다.
MAX_BODY = 20000
TRUNCATED = "\n…(본문이 길어 %d자에서 잘랐습니다)"

SENT = "sent"
SUPPRESSED = "suppressed"
FAILED = "failed"
EMPTY = "empty"


class SendResult(object):
    """`sent` · `suppressed` · `failed` · `empty`. 억제와 실패를 섞지 않는다.

    섞으면 호출자가 상한에 걸린 알림을 전송 실패로 보고 영원히 재시도한다.
    """

    def __init__(self, status, message_ids=()):
        self.status = status
        self.message_ids = list(message_ids)

    def __bool__(self):
        return self.status == SENT

    __nonzero__ = __bool__      # 3.9 호환 관용 표기

    def __repr__(self):
        return "SendResult(%r, %r)" % (self.status, self.message_ids)


def split_text(text, limit=MAX_TEXT):
    """4096자 상한으로 자른다. 가능하면 줄바꿈 경계에서 자른다."""
    if not isinstance(text, str) or not text:
        return []
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut <= 0:
            chunks.append(text[:limit])
            text = text[limit:]
        else:
            chunks.append(text[:cut])
            text = text[cut + 1:]  # 경계가 된 줄바꿈 하나만 버린다
    if text:
        chunks.append(text)
    return chunks


class Sender(object):
    def __init__(self, transport, chat_id, never_send=(), limiter=None, min_interval=1.0,
                 max_chars=MAX_TEXT, sleep=time.sleep, clock=time.monotonic, max_retries=3,
                 now=time.time, max_body=MAX_BODY, project=None):
        self.transport = transport
        self.chat_id = chat_id
        # None이면 발신 시점에 `POSTMAN_PROJECT`를 읽는다 — 기동 순서에 매이지 않는다.
        self.project = project
        self.never_send = tuple(never_send or ())
        self.limiter = limiter
        self.min_interval = float(min_interval)
        self.max_chars = int(max_chars)
        self.max_body = int(max_body)
        self.sleep = sleep
        self.clock = clock
        self.now = now
        self.max_retries = int(max_retries)
        self._last_send = None

    # ------------------------------------------------------------------ 발신

    def mask(self, text):
        """관문. 발신도 기록도 이 함수를 지난다 — 우회로를 만들지 않는다."""
        return masking.mask(text, self.never_send)

    def label(self, session=None):
        """이 발신문 앞에 설 출처 표시. 규칙은 `paths.display_label`이 단일 출처다."""
        return paths.display_label(session, self.project)

    def send_text(self, text, kind="system", buttons=None, reply_to=None, session=None):
        masked = self.mask(text)
        if not isinstance(masked, str) or not masked:
            return SendResult(EMPTY)       # 출처 표시만 남은 빈 발신을 만들지 않는다
        body = self._cap(self._labeled(masked, session))
        chunks = split_text(body, self.max_chars)
        if not chunks:
            return SendResult(EMPTY)

        if self.limiter is not None and not self.limiter.consume(kind, now=self.now()):
            eventlog.record("send_suppressed", kind=kind, session=session, text=body,
                            now=self.now())
            log.info("발신 억제 — 상한 (kind=%s)", kind)
            return SendResult(SUPPRESSED)

        markup = self._masked_buttons(buttons)
        message_ids = []
        for index, chunk in enumerate(chunks):
            params = {"chat_id": self.chat_id, "text": chunk}
            if reply_to is not None and index == 0:
                params["reply_parameters"] = {"message_id": reply_to}
            if markup and index == len(chunks) - 1:
                params["reply_markup"] = {"inline_keyboard": markup}
            result = self._call("sendMessage", params)
            if not (isinstance(result, dict) and "message_id" in result):
                log.warning("분할 발신 중단 — %d/%d 조각에서 실패", index + 1, len(chunks))
                eventlog.record("send_failed", kind=kind, session=session,
                                chunk=index + 1, chunks=len(chunks), now=self.now())
                return SendResult(FAILED, message_ids)
            message_ids.append(result["message_id"])
        eventlog.record("send", kind=kind, session=session, chunks=len(chunks),
                        text=body, buttons=bool(markup), now=self.now())
        return SendResult(SENT, message_ids)

    def answer_callback(self, callback_query_id, text=None):
        """버튼 처리 시 **반드시** 호출한다 — 미호출이면 클라이언트가 로딩 상태로 남는다."""
        params = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = self.mask(text)[:200]
        try:
            self.transport.call("answerCallbackQuery", params)
        except TelegramError as exc:
            log.warning("answerCallbackQuery 실패: status=%s", exc.status)

    # ------------------------------------------------------------------ 내부

    def _labeled(self, text, session):
        """출처 표시를 앞에 붙인다. **마스킹 뒤·자르기 앞**이 자리다.

        마스킹 뒤인 이유: 표시는 세션명·슬러그라 관문에 걸릴 외부 데이터가 아니고, 앞에
        먼저 붙이면 관문이 표시까지 훑는다. 자르기 앞인 이유: 표시가 상한 밖으로 밀려나면
        **누가 말했는지 모르는 잘린 본문**이 남는다.
        """
        label = self.label(session)
        return ("[%s] %s" % (label, text)) if label else text

    def _cap(self, text):
        """본문 상한. 마스킹보다 **나중에** 건다.

        순서가 중요하다. 자르기가 먼저면 값 형태 마스킹의 최소 길이(16진 32자 따위) 바로
        아래로 잘린 조각이 **패턴에 안 맞아 평문으로 남는다**(재검에서 실측). 관문을 먼저
        통과시키면 잘린 자리에 남는 것은 이미 마스크뿐이다. 이름 계층이 선형이 된 뒤로는
        먼저 자를 이유도 없어졌다.
        """
        if not isinstance(text, str) or len(text) <= self.max_body:
            return text
        return text[:self.max_body] + (TRUNCATED % self.max_body)

    def _masked_buttons(self, buttons):
        """버튼 라벨도 관문을 지난다. `callback_data`는 `v1|<id>`뿐이라 손대지 않는다."""
        if not buttons:
            return None
        rows = []
        for row in buttons:
            masked_row = []
            for button in row or ():
                if not isinstance(button, dict):
                    continue
                masked = dict(button)
                if isinstance(masked.get("text"), str):
                    masked["text"] = self.mask(masked["text"])
                masked_row.append(masked)
            if masked_row:
                rows.append(masked_row)
        return rows or None

    def _throttle(self):
        now = self.clock()
        if self._last_send is not None:
            wait = self.min_interval - (now - self._last_send)
            if wait > 0:
                self.sleep(wait)
        self._last_send = self.clock()

    def _call(self, method, params):
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return self.transport.call(method, params)
            except TelegramError as exc:
                if exc.retry_after and attempt < self.max_retries - 1:
                    self.sleep(float(exc.retry_after))
                    continue
                # 본문은 로그에 남기지 않는다 — 외부 데이터가 섞여 있다.
                log.warning("%s 실패: status=%s", method, exc.status)
                return None
        return None
