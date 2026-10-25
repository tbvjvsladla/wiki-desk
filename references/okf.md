# OKF 0.2 카드 형식과 보존 규칙 (TS판)

## 세 층의 구분
| 층 | 위치 | 계층 |
|---|---|---|
| 스킬(코드·지침) | `.claude/skills/wiki-desk/` | Common — 모든 sync 브랜치에서 동일 |
| 지식 bundle(포인터 카드) | `<wiki_dir>/` (`__llm-wiki/` 등) — `index.md`·`log.md`·`<cards_dir>/**` | Workflow-local — 브랜치별 |
| 운영 상태 | `<wiki_dir>/contract.json`(합의 계약) · `<wiki_dir>/receipt.json`(생성물 소유 기록 — sync 보호·remove 판단 근거) · `<wiki_dir>/<cache_dir>/`(파생 색인) | 계약·receipt=Workflow-local(추적), 캐시=Machine-local(추적 제외) |

`contract.json`·`receipt.json`과 캐시는 Markdown이 아니므로 OKF concept 분모에 들어가지 않는다. bundle 안의 그 밖의 `.md`는 모두 concept이며(`index.md`·`log.md`는 예약 파일) 임의 예외를 두지 않는다.

## 카드(concept) 형식
원문 1건당 카드 1건을 `<cards_dir>/<원문 상대경로>.card.md`에 둔다(원문 이름이 `index.md`·`log.md`이거나 `.md`가 아니어도 카드는 OKF concept 이름이 된다). 카드는 원문 본문을 복사하지 않는다(`copy_policy: path_reference`).

| 필드 | 값 | 출처 |
|---|---|---|
| `type` | 원문 `document_type` → 파일명 접두사 → 계약 authority의 `document_type` | 결정론 도출(OKF 필수) |
| `title` | 원문 `title` 또는 파일명 한글제목 | 원문 값/경로 |
| `description` | 원문 frontmatter의 `description` 값, 없으면 `null` | **원문 값 복사만** — 생성·요약 금지 |
| `resource` | 프로젝트 루트 상대 원문 경로 | 관측 |
| `tags` | 문서 종류 + 원문 frontmatter `tags`의 문자열 원소 | 관측/원문 값 |
| `authority` | 계약 `authority_rules` 첫 일치 또는 fallback의 `{document_type, authority_rank, role}` | 계약 도출(탐색 순서용, 승인 판정 아님) |
| `generated` | `{by: process:wiki-desk-ts, at: <UTC ISO>}` | 카드 작성 이력(확인 이력 아님) |
| `source_meta` | 계약 `frontmatter_aliases`의 정본 키로 흡수한 원문 키 | 원문 값 |
| `source_meta_unknown` | 매핑되지 않은 원문 키, 원형 보존 | 원문 값 |
| `needs_review` / `review_reasons` | 파일명 규칙 위반·frontmatter 파싱 불가·닫힘 누락·UTF-8 아님·빈 title 등. `needs_review`는 사유가 있을 때만 true | 판정 불가 표면화 |
| (그 밖의 키) | 사람이 카드에 추가한 OKF 키(`verified` 등) | 원형 보존 |
| `source_sha256` | 원문 내용 해시 | stale 판정용 관측값 |

`verified`는 만들지 않는다. 실제 확인 actor·시점이 없는 확인 이력을 만들지 않는다.

## OKF 0.2 MUST 준수
- `type`만 항상 필수. 알 수 없는 type·key·선택 필드 부재·깨진 링크·`index.md` 부재로 문서를 거부하지 않는다.
- unknown key는 round-trip에서 보존한다.
- `verified`의 단일 mapping은 원소 1개 리스트로 읽는다(§5.2). `generated`는 단일 mapping이며 `by` 필수.
- trust 메타가 없는 문서도 소비한다.
- `log.md` 날짜 헤딩은 `YYYY-MM-DD`.
- 예약 파일명(`index.md`, `log.md`)을 concept 용도로 쓰지 않는다.

## 경로 해석
- 카드의 `resource`는 **프로젝트 루트 상대** 경로다. OKF bundle 상대 링크(`/topics/…`)와 혼동하지 않는다. 원문을 bundle 안으로 복사해 링크를 통과시키지 않는다.
- 카드 본문의 원문 표기는 `resource`와 같은 프로젝트 루트 상대 경로(인라인 코드)이며 링크가 아니다.

## 형식 적합성과 품질 gate
`check`의 OKF PASS는 형식 적합성일 뿐이다. 카드 누락·고아·stale, `needs_review` 건수, 권위 충돌, 원문 실재는 별도 항목으로 보고하며 서로 대체하지 않는다.

## 용어집 `glossary.json`
- 위치: `<wiki_dir>/glossary.json`. 프로젝트 데이터이므로 브랜치·프로젝트마다 따로 둔다. `init --apply`가 `{"schema_version": 1, "auto_extract": true, "manual": []}`으로 만든다(receipt 소유 — 사람이 고치면 `remove`가 보존한다). **파일을 지우면 질의 확장을 하지 않는다.**
- 형식(스키마 v1, 모르는 키·형식 오류는 질의를 거부):
  ```json
  {"schema_version": 1, "auto_extract": true, "manual": [["토크나이저", "tokenizer"]]}
  ```
  - `manual`: 같은 개념의 표기 묶음 목록(묶음마다 비어 있지 않은 문자열 2개 이상).
  - `auto_extract: true`: 질의 때 원문 본문(펜스 코드·frontmatter 제외)의 괄호 병기 쌍 `한글 표기(English term)`·`English term(한글 표기)`을 결정론으로 뽑아 묶음에 더한다. LLM은 쓰지 않는다. 번역이 아니라 예시를 단 괄호(예: `서버(vLLM)`)를 거르기 위해, 한 표기가 여러 상대와 짝지어진 쌍, 한글 쪽이 짧은 쌍, 한글 쪽이 말뭉치 대부분 문서에 나오는 일반어인 쌍은 버린다(기준은 `src/glossary.ts` 상수).
- 확장 규칙: `--terms` 그룹의 토큰이 묶음의 한 표기의 토큰을 모두 포함하면, 같은 묶음의 다른 표기를 추가 그룹(OR)으로 붙이고 `expanded_terms`로 보고한다.
- 평가·튜닝을 하는 프로젝트라면 수동 항목은 튜닝용 문항만 보고 추가한다(평가 문항을 보고 고르면 평가가 오염된다).

## 외부·벤더 문서 제외
- 다른 저장소에서 통째로 반입한 외부·벤더 문서(플러그인 사본 등)는 계약 `excluded_roots`에 넣는다. 영문 위주 외부 문서가 섞이면 영어 질의를 흡수해 프로젝트 문서의 순위를 밀어낸다.
