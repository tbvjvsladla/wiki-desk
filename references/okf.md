# OKF 0.2 읽기와 보존형 교정

## 스킬·지식·운영 계약의 세 층

`SKILL.md`는 Agent Skills 형식이고 이 문서는 그 지원 자료다. 대상의 `wiki_dir` 내부는 OKF bundle이며 `.wiki-desk/contract.json`/receipt는 bundle 밖 운영 계약이다. 이 지원 폴더나 패키지 전체를 OKF concept corpus라고 보지 않는다.

일반 OKF concept은 UTF-8 Markdown과 파일 시작의 `---` YAML frontmatter를 사용하며, `type`이 항상 필수인 유일한 key다. `title`, `description`, `tags`, `resource`, provenance/trust/lifecycle은 선택이다. 알 수 없는 `type`은 generic concept으로 읽고 unknown key·producer extension을 round-trip에서 보존한다. 스킬의 string-valued `metadata` 제약을 OKF 전체 YAML에 적용하지 않는다.

## 예약 파일과 전체 분모

- `index.md`는 directory listing 예약 파일이다. 일반 frontmatter를 넣지 않으며 bundle-root `index.md`에만 `okf_version`을 넣을 수 있다. `index.md`의 부재 자체는 OKF 부적합 사유가 아니다.
- `log.md`는 변경 이력 예약 파일이다. 최신순 날짜 그룹의 설명을 사용하며 날짜 heading은 `YYYY-MM-DD`다. 일반 concept용 `type`을 강제로 넣지 않는다.
- 그 밖의 모든 bundle 내부 `.md`는 concept이다. `README.md`, `SCHEMA.md`를 임의 예외로 두지 않는다. 실행 안내·계약·패키지 지원 문서는 bundle 밖에 둔다.
- `format`/`check`는 계약 bundle의 전체 Markdown inventory를 사용한다. 예약 파일도 수집 분모에 포함하되 적절한 규칙을 적용한다. 새 directory index 생성 뒤 최종 `expected`/`collected`/`unique`를 다시 맞춘다.

## 출처·작성·확인의 분리

| 필드 | 의미와 읽기 원칙 |
|---|---|
| `sources[].resource` | entry 안에서 필수. 실제 URL·bundle 경로 또는 population/scope descriptor. descriptor는 회수 가능한 파일이 아닐 수 있음 |
| `sources[].id` | 선택적 안정 attribution key. claim footnote label과 연결하며 재정렬·경로 이동 때문에 함부로 바꾸지 않음 |
| `generated` | 현재 지식 내용 생산 이력. mapping 내부 `by`는 필수이며 `at`는 의미 있는 변경 시점을 나타냄 |
| `verified` | 실제 확인 이력. `{by, at}` mapping 하나도 한 개 event 목록으로 읽음. 없는 확인 actor·시점을 만들지 않음 |
| `status` | 지식 lifecycle `draft`/`stable`/`deprecated`; 부재는 OKF 읽기상 `stable`이나 사용자 승인을 뜻하지 않음 |
| `stale_after` | 이 시점 이후 지식이 stale임을 나타냄. source의 현재 존재·검토·제품 결과와 별도 |

OKF timestamp는 명시 UTC offset을 가진 ISO 8601 datetime이다. 확인 없는 문서는 미확인으로 읽을 수 있으며 형식에서 거절하지 않는다. `verified`의 trust tier는 advisory signal이지 access control·작업 실행 허가·제품 승인/완료가 아니다. 지식이 변경됐다고 과거 검증을 현재 검증으로 승계하지 않는다.

원문 input scope·수용 제외 범위·마지막 관측 상태를 보존한다. registry의 `source_path`, `sha256`, authority 등 프로젝트 extension은 관측/라우팅 정보이지 OKF가 보증한 정본·승인 판정이 아니다.

## 경로 해석을 혼동하지 않기

| 위치 | 기준 |
|---|---|
| OKF link/path의 `/topics/example.md` | OS `/`가 아니라 해당 knowledge bundle root |
| OKF `../topics/example.md` | 지식문서 위치에 대한 상대 링크. bundle boundary와 실제 target을 확인 |
| OKF 절대 URL | 외부 artifact. 접근·검토 여부와 URL 존재를 구별 |
| `sources[].resource`의 scope 설명 | path로 강제 변환하지 않음 |
| 스킬 지원 파일 | skill root에서 찾는 resource; Markdown link는 해당 문서 위치 기준으로 resolve |
| 계약 source root·runtime output | 대상 project root 상대경로; OS 절대경로 및 traversal과 별도 |

bundle 밖 원문을 OKF의 `/docs/...`로 표시해 bundle 안의 파일인 것처럼 만들지 않는다. runtime registry의 project-relative `source_path`와 `resource`/URI를 구별하고 실제 project root에서 원문을 읽는다. 경로 해석이 불명확하면 unresolved로 보고한다. 원문을 자동 복사해 링크를 통과시키지 않는다.

## 형식 적합성과 품질 gate

unknown type/key, 선택 필드 부재, broken cross-link, missing `index.md`만으로 OKF conformance를 거절하지 않는다. broken link는 미작성 지식일 수 있다. package dependency closure·missing 원문·중복 ID·권위 충돌·수용 근거는 별도 이름의 안전/품질 gate로 보고한다. OKF PASS를 이 gate들의 PASS로 바꾸지 않는다.

불안전/중복 YAML, 부적절한 known field shape, 경로 escape 등은 구체적 진단을 보존한다. extension을 삭제하거나 metadata를 축약해 통과시키지 않는다. 코드 fence·blockquote·inline code의 wikilink 예시를 실제 지식 edge로 자동 해석하지 않는다.

## 교정의 적용 경계

기본 교정은 본문 문장을 description이나 directory preview로 복제하지 않는다. 기존 명시 description은 보존하며, 부재 시 본문 excerpt 대신 bundle-relative 경로 stub을 만든다. 별도 excerpt 옵션은 제공하지 않는다. 지식 작성자가 설명을 추가하려면 내용과 노출 범위를 검토해 metadata에 직접 작성한다. 이전 교정본에 이미 있는 description을 무검토 삭제하지 않는다.

`format`의 기본 plan과 보존 보고를 읽고 `--check` 또는 `check`로 실제 읽기 전용 결과를 확인한다. 본문·unknown metadata·source/verification/history·예약 index의 사용자 작성 부분·기존 log 이력을 보존하는 변경인지 검토한다. 기존 wiki의 정본 의미·승인 상태를 형식 변환으로 변경하지 않는다.

동의한 변경에만 `format --apply`를 사용한다. 변경 전 snapshot/drift guard는 쓰기 안전성 근거이지 원문 snapshot 배포 허가가 아니다. 실패 시 원인·부분 산출물·rollback 범위를 보고하고 전체 process-crash atomicity를 주장하지 않는다. 공식 정본과 한정 인용은 [외부 근거](external-sources.md)에 있다.
