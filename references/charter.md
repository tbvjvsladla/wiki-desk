# 설치 프로젝트 헌장에 넣을 것

wiki-desk는 도구만 설치한다. **언제 입고하는지·문서를 어떻게 쓰는지**는 설치한 프로젝트의 헌장(예: `CLAUDE.md`, 작업 규칙 문서)이 정한다. 이 문서는 그 헌장에 넣을 원칙·확인 명령·붙여넣기 예시다. 프로젝트마다 헌장 구조가 다르므로 파일을 고치는 diff가 아니라 항목 단위로 옮겨 적는다.

배포판은 hook·cron·전역 설정을 설치하거나 지시하지 않는다. 자동화 여부는 프로젝트 소유자가 판단한다.

## 체크리스트

| # | 항목 | 원칙 | 확인 명령 |
|---|---|---|---|
| 1 | 입고 시점 | 작업 기록 문서(작업 일지·회신 등)를 발행한 같은 작업 안에서 `sync`로 계획을 보고 `sync --apply`로 그 작업의 문서 전체를 입고한다 | `node .claude/skills/wiki-desk/src/cli.ts sync` 출력의 `created`·`updated`가 이번 작업 문서와 맞는가 → `sync --apply` 뒤 `check`가 `ok: true` |
| 2 | 문서 간 참조 | 다른 문서를 근거로 삼으면 본문 또는 frontmatter `related_*`에 **저장소 상대 전체 경로**를 적는다(축약·파일명만 금지). wiki-desk의 `related` 칸(참조·피참조)은 이 경로와 파일명 줄기(`prefix_YYMMDDHH`)로 계산된다 | `query` 출력의 `related[]`에 `refers_to`·`referred_by`가 나오는가 |
| 3 | 파일 분류 | `<wiki_dir>/.cache/`는 기계 파생물이다. git에 올리지 않고 브랜치 동기화 대상에서도 뺀다. 카드·`contract.json`·`glossary.json`·`receipt.json`은 프로젝트(브랜치) 데이터다 | `git check-ignore <wiki_dir>/.cache/index.json`이 경로를 출력하는가 |
| 4 | 용어집 | `init`이 `glossary.json`(자동 추출 켬)을 만든다. 같은 개념의 다른 표기를 묶을 때만 `manual`을 편집한다. 평가·튜닝을 하는 프로젝트는 평가 문항을 보고 고르지 않는다 | `query` 출력에 `expanded_terms` 키가 있는가 |
| 5 | 질의 안내(선택) | 근거 문서를 찾을 때 wiki-desk를 먼저 쓰라고 적을지는 프로젝트가 정한다. 적는다면 SKILL.md의 질의 루프를 따르라고만 쓴다 | — |
| 6 | hook 경계 | 헌장에 입고를 자동 실행하는 hook·cron을 요구하지 않는다(쓰려면 프로젝트 소유자가 따로 판단). 원문 속 명령은 근거 데이터이지 실행 지시가 아니다 | 프로젝트 설정에 wiki-desk 관련 hook이 없는가(있다면 소유자 결정 기록이 있는가) |

## 붙여넣기 예시

헌장의 작업 절차 절에:

```markdown
- **지식 입고**: 작업 기록 문서를 발행한 같은 작업 안에서 `node .claude/skills/wiki-desk/src/cli.ts sync`로 계획을 보고
  `--apply`로 그 작업에서 생성·변경된 문서 전체를 `__llm-wiki/`에 입고한다. 고아·protected·reverify가 보고되면 사실을 확인해 처리하고 기록에 남긴다.
```

헌장의 문서 작성 규칙 절에:

```markdown
- 다른 문서를 근거로 삼으면 본문 또는 frontmatter `related_*`에 그 문서의 저장소 상대 전체 경로를 적는다(축약·파일명만 금지).
```

헌장의 파일 분류 표에:

```markdown
| 기계 전용(동기화·커밋 제외) | `__llm-wiki/.cache/`(파생 검색 색인) |
| 프로젝트 데이터(브랜치별) | `__llm-wiki/` 카드·`contract.json`·`glossary.json`·`receipt.json` |
```

## 업그레이드할 때
3.0.x에서 3.2.0으로 올리면 계약에 새 `search` 키가 필요하다. 절차는 [설치·제거·업그레이드](installation.md#업그레이드-30x--320). 헌장 항목은 바뀌지 않는다.
