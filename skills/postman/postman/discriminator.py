"""회신 변별자 — `[<노드ID> g<세대>#<n>]` (ADR-002 D10).

**실측된 사고가 근거다**(002-N2 1-5절). 세션 간 메시지에서 **동일 본문 회신이 조용히
삼켜지고 발신자에게 실패로 보고되지 않았다** — 회신 1건이 실제로 사라졌다. 보내는 쪽은
보냈다고 믿고, 받는 쪽은 오지 않았다고 믿는다. 둘 다 틀린 것을 아무도 모른다.

그래서 **모든 세션 간 메시지의 첫머리에 변별자를 강제한다.**

    [002-N4A g2#3] 완료 — ...
    [cmd g2#1] 교체 요청          ← 노드 귀속이 없는 제어 메시지는 노드 자리에 `cmd`

목적은 둘이다.

1. **본문 상이화** — 같은 문장을 두 번 보내도 문자열이 달라진다. 단 중복 차단의 키(본문
   해시인지 발신자 포함인지)와 시간창은 **미실측 추정**이므로 "차단 회피 보장"이 아니라
   확률을 낮추는 조치다.
2. **유실 탐지** — 수신자는 일련번호 공백을 유실로, 낮은 세대의 변별자를 이전 세대의
   지연분으로 해석한다. 해석 규칙이 있어야 "역행"이 잡음이 아니라 신호가 된다.

**세대(`g`)가 붙는 것이 초안의 결함을 막는다.** 세대 없이 `[cmd #1] 교체 요청`만 쓰면
교체마다 같은 본문이 되어 **교체 요청 자체가 중복 차단에 삼켜질 수 있다.** 세대의 단일
출처는 `relay.json`이고, 작업 세션은 위임 메시지로 세대를 전달받는다.

**변별자 없는 회신은 수신자가 신뢰하지 않고 재발신을 요청한다.**

시스템 파이썬(3.9)에서도 임포트되어야 하므로 3.9 문법만 쓴다.
"""
import re

from postman import addressing

# 노드 ID 폭은 `addressing`이 단일 출처다 — 여기 베껴 적으면 두 정규식이 갈린다 (D9).
PREFIX_RE = re.compile(
    r"\A\[(?P<node>%s) g(?P<generation>\d{1,6})#(?P<seq>\d{1,9})\]" % addressing.NODE_ID_BODY
)


class Discriminator(object):
    def __init__(self, node, generation, seq):
        self.node = node
        self.generation = int(generation)
        self.seq = int(seq)

    def __eq__(self, other):
        return (isinstance(other, Discriminator)
                and (self.node, self.generation, self.seq)
                == (other.node, other.generation, other.seq))

    def __hash__(self):
        return hash((self.node, self.generation, self.seq))

    def __repr__(self):
        return "Discriminator(%r, %d, %d)" % (self.node, self.generation, self.seq)

    def text(self):
        return "[%s g%d#%d]" % (self.node, self.generation, self.seq)


def format_prefix(node, generation, seq):
    """변별자 문자열. 노드 ID가 없는 제어 메시지는 `cmd`를 쓴다."""
    node = addressing.CONTROL_NODE if node in (None, "") else addressing.safe_node_id(node)
    return Discriminator(node, generation, seq).text()


def stamp(text, node, generation, seq):
    """본문 앞에 변별자를 붙인다. **이미 붙어 있으면 덧붙이지 않는다.**"""
    body = text if isinstance(text, str) else ""
    if parse(body) is not None:
        return body
    return "%s %s" % (format_prefix(node, generation, seq), body.lstrip())


def parse(text):
    """첫머리의 변별자를 읽는다. 없으면 None."""
    if not isinstance(text, str):
        return None
    match = PREFIX_RE.match(text.lstrip())
    if not match:
        return None
    return Discriminator(match.group("node"), match.group("generation"), match.group("seq"))


def has_discriminator(text):
    return parse(text) is not None


class SeqCounter(object):
    """발신 세션이 자기 발신마다 1씩 올린다.

    교체 후 카운터가 1로 되감겨도 **세대가 붙으므로 변별자는 세대를 넘어 유일하다.**
    """

    def __init__(self, start=0):
        self._n = int(start)

    def next(self):
        self._n += 1
        return self._n

    @property
    def value(self):
        return self._n


def missing_seqs(seen, generation):
    """받은 변별자 목록에서 그 세대의 일련번호 공백을 돌려준다 — 유실 탐지 (D10 ②).

    1번부터 최고 번호까지 중 오지 않은 번호가 유실 후보다. 낮은 세대의 변별자는 이전
    세대의 지연분이므로 여기서 세지 않는다.
    """
    nums = sorted(d.seq for d in seen
                  if isinstance(d, Discriminator) and d.generation == int(generation))
    if not nums:
        return []
    return [n for n in range(1, nums[-1] + 1) if n not in set(nums)]
