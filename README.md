# wiki-desk (TypeScript, 2.0.0)

프로젝트 원문을 복사하거나 요약하지 않고, **원문의 위치·근거 줄범위·권위**를 찾아 주는 지식 사서입니다. 브랜치마다 OKF 0.2 포인터 카드 도서관(`__llm-wiki/`)을 두고, 결정론 검색으로 `경로:시작-끝` 근거를 돌려줍니다.

이 브랜치(`wiki-desk_TS`)는 `main`의 Python 1.1.0을 TypeScript로 **재설계**한 판입니다. `main`은 바뀌지 않습니다. 01_RAG_Agent에 설치해 쓰는 판에서 출발했습니다(계보: `SKILL.md` metadata).

## 1.1.0(Python)과 달라진 점
| 항목 | 1.1.0 | 2.0.0 (TS) |
|---|---|---|
| 실행 | Python 3.10+ · PyYAML | Node.js 24+ · `.ts` 직접 실행 · **런타임 의존성 0** |
| 카드 | 위키 문서 | 원문 1건당 포인터 카드 `<원문 경로>.card.md`(frontmatter 메타는 원문 값 그대로, LLM 요약 없음) |
| 검색 | 경로 색인 조회 | BM25(제목·헤딩·메타·본문 가중) + 헤딩 트리 → 문단 단위 근거 span |
| 소유권 | 스킬 안 `project/receipt.json`(추적 제외) | 위키 안 `receipt.json`(추적) — 사람이 고친 카드 `protected`, `verified` 카드 `reverify` |
| 색인 | — | `<wiki>/.cache/index.json` 파생 캐시(추적 제외, 바뀐 원문만 재색인) |
| 테스트 | pytest | `node --test` 238건 |

## 준비물
- Node.js 24 이상. npm 설치가 필요 없습니다. Node가 없으면 차단 사유를 보고하고 자동 설치하지 않습니다.

## 설치
폴더 전체가 한 단위입니다.
1. 이 저장소 내용을 프로젝트의 `.claude/skills/wiki-desk/`로 복사합니다(기존 동명 스킬이 있으면 차이를 먼저 검토).
2. `cd .claude/skills/wiki-desk && node --test` 로 회귀를 확인합니다.
3. 프로젝트와 합의한 계약 파일을 만듭니다(예: `assets/project-contract.example.json` — 01_RAG_Agent의 실제 계약).
4. 프로젝트 루트에서:
```bash
node .claude/skills/wiki-desk/src/cli.ts init --contract <계약 파일>            # 계획만
node .claude/skills/wiki-desk/src/cli.ts init --contract <계약 파일> --apply    # 위키 골격 생성
node .claude/skills/wiki-desk/src/cli.ts sync --apply                            # 카드 생성
node .claude/skills/wiki-desk/src/cli.ts check                                   # OKF 0.2 MUST·누락/고아/stale
```

## 사용
```bash
node .claude/skills/wiki-desk/src/cli.ts query --terms "멀티턴 기본값" --terms "multi-turn default"
node .claude/skills/wiki-desk/src/cli.ts read docs/devlog/<file>.md:41-58
node .claude/skills/wiki-desk/src/cli.ts tree docs/devlog/<file>.md
```
명령은 한 줄에 하나씩 실행합니다(셸 변수·`cd … &&` 묶음은 서브에이전트 권한 규칙에 막힐 수 있음). 상세는 `SKILL.md`, `references/`.

## 검증 기록 (01_RAG_Agent, 2026-10-14)
- 자동 테스트 238 통과, OKF 공식 예제 81건 round-trip 무손실, TypeScript strict 타입 점검 1회 통과.
- 코드 리뷰 6종 5라운드 — 치명·주요 결함 0.
- 설치 전후 벤치(Claude Sonnet 5.5, 60문항×3회×3조건=540회): 정확도 저하 없음(모든 조건 만점). 문서 150~240건 규모에서는 서브에이전트가 스스로 도구를 쓰지 않았고(0/180), 사용을 지시하면 턴이 늘어 4~17% 느려졌습니다. 이 규모에서 응답 시간은 색인(질의 0.3초)이 아니라 대화 턴 수에 좌우됩니다.

## 한계
- Python 1.1.0과의 속도 비교는 하지 않았습니다(재설계 범위·사용자 결정).
- 상시 타입 검사 단계가 없습니다(의존성 0 유지). 리뷰 minor 8건 미수정.
- 1.0.x 마이그레이션 경로는 범위 밖입니다.

## 라이선스
MIT — `LICENSE`.
