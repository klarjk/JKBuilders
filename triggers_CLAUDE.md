# triggers_CLAUDE.md — 조건부 상세 규칙 트리거 (예시)

> 이 파일은 **예시 템플릿**입니다. JKBuilders에 포함된 `rules-detail/` 규칙들은 자동으로 로드되지 않습니다. Claude가 특정 작업을 시작하기 **전**에 해당 규칙 파일을 읽고 적용하게 하려면, 아래 "조건부 상세 규칙" 섹션을 본인의 전역 설정 파일(`~/.claude/CLAUDE.md`)에 복사해 넣으세요.
>
> 경로 기준은 규칙 파일을 설치한 위치(`~/.claude/rules-detail/`)에 맞춰 조정합니다.

---

## 조건부 상세 규칙 (필요 시 read)

아래 규칙은 자동 로드되지 않는다. 트리거 조건에 해당하는 작업을 시작하기 **전**에 반드시 해당 파일을 Read 한 뒤 적용한다. 경로 기준: `~/.claude/rules-detail/`

### claude-doc-writing-rules.md — Claude 대상 문서 작성

**트리거:** Claude 자신이 읽고 따르는 문서(CLAUDE.md, skills/**/SKILL.md, agents/*.md, rules/*.md, .claude/** 하위 마크다운) 작성·수정 시.
**제외:** 일반 마크다운 노트, 세션 기록, 사용자용 문서.

→ `rules-detail/claude-doc-writing-rules.md` Read 후 적용.

### learnings-memory-rules.md — Learnings 메모리

**트리거:** 세션 중에 다음 중 하나로 **외부 사실**(학습 데이터에 없거나 컷오프 이후 변경됨)을 검증했을 때.
- 공식 문서·릴리스 노트 1차 출처 URL을 본 세션에서 열람
- 세션 내 직접 실험·실행으로 재현 가능한 결과 관찰
- 2차 출처에서 동일 사실 2건 이상 일치 확인

**제외:** 학습 데이터 컷오프 이전 일반 지식, 프로젝트 코드/구조에서 derive 가능한 정보, 사용자 의견·선호(→ `feedback`), 프로젝트 코드 재발성 quirk(→ `project_known_issue_*`), 1회성 관찰, 시크릿·개인정보.

→ `rules-detail/learnings-memory-rules.md` Read 후 적용.

### review-disposition-rules.md — 리뷰 처분

**트리거:** 리뷰어 서브에이전트(`code-reviewer`·`security-reviewer`·`prompt-reviewer`·`plan-reviewer` 등)의 결과를 받은 직후, 그 지적을 처리하기 전.
**제외:** 리뷰 결과가 단일 ✅(이슈 0건), 리뷰어가 아닌 일반 서브에이전트(`Explore`·`Plan` 등) 결과, 사용자가 표 생략을 명시한 경우.

→ `rules-detail/review-disposition-rules.md` Read 후 적용.
