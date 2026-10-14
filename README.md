# wiki-desk

> **에이전트가 기억에 기대어 답하지 않고, 프로젝트 원문의 위치·근거·권위로 돌아가 읽게 하는 지식 사서 스킬입니다.**
>
> 배포 버전 **1.1.0 (Python)** · 브랜치 `wiki-desk_PY` · Hermes / Codex / Claude Code용 전체 폴더 seed

## 브랜치 안내 — 같은 사서, 두 구현

| 브랜치 | 구현 | 대상 | 상태 |
|---|---|---|---|
| `wiki-desk_PY` (이 브랜치) | Python 3.10+ · PyYAML | Hermes · Codex · Claude Code 공통 seed, 설치기·이관·형식 교정 포함 | 1.1.0 |
| `wiki-desk_TS` | TypeScript (Node.js 24, 런타임 의존성 0) | Claude Code 프로젝트 스킬, 포인터 카드 + 결정론 검색 | 2.0.0 |

두 브랜치는 서로를 대체한다고 주장하지 않습니다. 계약 파일·위키 배치·명령 체계가 달라 **한쪽 설치본을 다른 쪽 명령으로 관리할 수 없습니다.** 이 문서는 Python판만 설명합니다.

## 해결하려는 문제 — "아마 그렇게 결정했을 것"과 "이 문서 이 줄에 그렇게 적혀 있다"는 다릅니다

프로젝트가 길어지면 결정·승인·결과가 여러 문서에 흩어집니다. 에이전트에게 "예전에 이거 어떻게 정했지?"라고 물으면 그럴듯한 답이 나오지만, 그 답이 어느 원문에 근거했는지, 그 문서가 나중에 뒤집혔는지, 사람이 승인한 것인지는 따로 확인해야 합니다.

wiki-desk는 이 확인을 돕는 **사서**입니다. 원문을 복사하거나 요약해 새 정답지를 만들지 않습니다. 원문은 제자리에 두고, 위키에는 "어떤 원문이 어디 있고 어떤 종류·권위인지"를 OKF 0.2 형식으로 기록합니다. 에이전트는 위키로 후보를 좁힌 뒤 **원문을 직접 읽고** 답합니다.

## 큰 그림 — 원문은 제자리, 위키는 목록, 판단은 에이전트와 사람이

```text
사용자 질문 → 에이전트 → wiki-desk(후보 원문 경로·권위·coverage) → 원문 직접 읽기 → 근거 경로와 함께 답변
```

- **스킬 폴더**: `SKILL.md`(사서 계약), `references/`(초기화·OKF·권위·설치·유지보수), `scripts/`(색인·조회·설치·교정), `assets/`(계약 예제·schema), `tests/`(합성 자료 회귀시험).
- **프로젝트 계약(`project/contract.json`)**: 설치된 스킬 안에 두는 수신 프로젝트의 합의 문서입니다. 어떤 폴더를 원문으로 볼지, 무엇을 제외할지, 문서 종류별 권위 순서를 정합니다. 수신 프로젝트가 git으로 추적합니다.
- **소유권 기록(`project/receipt.json`)**: 기계별 설치·소유권 기록입니다. 스킬 `.gitignore`로 추적에서 빠지며, 최상위 `project/`는 패키지 인벤토리에서 제외되므로 설치본도 패키지 검증이 가능합니다.
- **지식층(계약의 `wiki_dir`)**: OKF 0.2 Markdown, index/log, 원문 경로 registry입니다.

경로·hash·ID가 맞는다는 사실은 **원문 내용을 사람이 검토·승인했다는 뜻이 아닙니다.** `generated`·`verified`·지식 lifecycle과 문서 workflow 판정도 서로 별개입니다.

## 사용자와 에이전트의 대화로 보는 사용법

아래는 사용 흐름을 설명하는 **예시 대화이며 실제 실행 기록은 아닙니다.**

> **사용자**: 받은 wiki-desk 폴더를 이 프로젝트에 채택해 줘. 원문은 건드리지 마.
>
> **에이전트**: 먼저 패키지 무결성을 검사하고 `SKILL.md`·`references/bootstrap.md`를 읽겠습니다. 문서 폴더·제외·권위 순서·위키 이름 중 정해지지 않은 것만 여쭙겠습니다.
>
> **사용자**: 원문은 `docs/`만, 권위는 결과 보고 > 계획 순으로.
>
> **에이전트**: 합의한 계약으로 scan과 install **계획**만 먼저 보여 드리겠습니다. 쓰기는 0건입니다. 확인해 주시면 같은 범위에만 `--apply`를 붙이겠습니다. 이후 질의 결과는 후보일 뿐이라, 최종 답은 원문을 직접 읽고 근거 경로와 함께 드리겠습니다.

## 설치 여정 1 — 받은 폴더부터 검사하기

준비물은 Python 3.10+와 PyYAML 6(`requirements.txt`)입니다. 실행기는 의존성을 자동 설치하거나 host 인증·provider·권한·profile·전역 설정을 바꾸지 않습니다. 없으면 `BLOCKED`로 보고합니다. 개발 시험은 pytest(`requirements-dev.txt`)입니다.

**전체 폴더가 전달 단위입니다.** `SKILL.md` 하나나 단일 URL만 설치하면 도구·schema·참조가 빠집니다. 이 README가 원격 repository/hub/plugin 발행을 보증하지는 않습니다.

```sh
python3 -B scripts/wiki_desk.py verify-package
```

`package-manifest.json`은 파일 집합·내용·entrypoint를 대조할 뿐, 출판자를 인증하는 서명이 아닙니다(`publisher_trust_verified: false`). 신뢰할 수 있는 출처에서 받고 처음 보는 코드는 실행 전에 읽으세요.

## 설치 여정 2 — 프로젝트와 합의하고 위키 만들기

### 수신 에이전트에게 전달할 첫 요청

```text
받은 wiki-desk 폴더 전체를 읽고 이 프로젝트에 맞게 채택해 줘.
SKILL.md와 references/bootstrap.md부터 읽고 현재 문서 관리 결정을 확인해.
문서 roots·제외·분류·권위·위키 이름이 미정인 부분만 나와 합의해.
기존 스킬·위키·context를 덮어쓰거나 원문을 복사하지 마.
처음에는 scan과 install 계획만 보여 주고 합의한 scope에서만 --apply를 사용해.
생성된 위키에서 실제 원문 경로를 회수하고 check 결과와 인식 한계를 구분해 보고해.
```

자세한 적응형 대화는 [bootstrap](references/bootstrap.md)에 있습니다.

### 프로젝트 계약

[예제](assets/project-contract.example.json)는 **합성 예시**입니다. 그대로 승인된 계약으로 쓰지 마세요.

| key | 뜻 |
|---|---|
| `schema_version`, `project_name` | 계약 식별 |
| `wiki_dir` | 프로젝트 상대 경로. `__llm-wiki` 또는 `__llm_wiki`를 정확히 고릅니다. 두 폴더를 자동으로 이름 변경·병합하지 않습니다. |
| `source_roots`, `excluded_roots` | 원문 범위와 제외. 합의되지 않으면 적용하지 않습니다. |
| `authority_rules`, `fallback` | `pattern/document_type/authority_rank/role`. 첫 일치 규칙을 적용하고 높은 rank를 먼저 검토합니다. **rank는 탐색 우선순위이지 자동 수용 판정이 아닙니다.** |
| `copy_policy` | `path_reference`만 지원합니다. |
| `source_suffixes`(선택) | 예: `[".md"]`. 디렉터리 원천에서 해당 확장자만 수집합니다(대소문자 무시). 빈 목록·점 없는 값·다중 점·공백·중복·문자열 단일값은 거부합니다. |

### 계획 → 적용

받은 `wiki-desk/`와 대상 `example-project/`가 같은 부모 폴더에 있고, 합의한 계약을 `example-project/wiki-desk.contract.json`에 저장했다고 가정합니다. 계약을 자동 생성·승인하는 명령은 없습니다.

```sh
# 읽기 전용 조사와 설치 계획(쓰기 0)
python3 -B wiki-desk/scripts/wiki_desk.py scan --root example-project --contract example-project/wiki-desk.contract.json
python3 -B wiki-desk/scripts/wiki_desk.py install --root example-project --host codex --contract example-project/wiki-desk.contract.json

# 범위가 합의된 뒤 명시 적용
python3 -B wiki-desk/scripts/wiki_desk.py install --root example-project --host codex --contract example-project/wiki-desk.contract.json --apply
```

| host | 프로젝트 스킬 경로 |
|---|---|
| hermes | `.agents/skills/wiki-desk` |
| codex | `.agents/skills/wiki-desk` |
| claude | `.claude/skills/wiki-desk` |

같은 이름의 기존 스킬·위키·관리 경로는 덮어쓰지 않습니다. receipt와 실제 bytes가 일치하는 재설치만 no-op입니다. **경로가 맞는 것, 파일을 만든 것, host가 스킬을 실제로 발견·로드한 것은 서로 다른 확인입니다.** 버전·trust·동명 스킬·refresh·backend·context 선택 조건은 [설치 문서](references/installation.md)에 있습니다.

## 실제 작업 여정 — 조회 → 원문 변경 반영 → 형식 교정 → 제거

설치본에서 실행합니다(Codex/Hermes 경로 예시, Claude는 `.agents`를 `.claude`로).

### 1. 조회하고 원문을 직접 읽습니다

```sh
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py status --root example-project
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py query --root example-project --terms decision --limit 10
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py check --root example-project
```

query는 원문을 로컬에서 읽고 일치 후보·경로·읽기 coverage를 보고합니다. 결과가 의미상 정답이라고 판정하지 않습니다. 에이전트는 후보 원문·계보·후속 수용을 직접 읽고 답합니다. `--fail-on-empty`는 빈 결과를 exit 3으로 돌려줍니다(기본은 exit 0, `BLOCKED`는 exit 2).

### 2. 원문 변경을 반영합니다

```sh
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project --apply
```

등록 원문의 삭제·이동은 기본적으로 차단합니다. 이미 검토한 변화만 지정해 registry를 조정합니다(원문을 옮기거나 지우는 명령이 아닙니다).

```sh
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --accept-removed docs/retired.md
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --relocate docs/old.md=docs/new.md
```

과거 metadata는 append-only `archived_sources`에 보존하고, 이동 원문의 ID·unknown extension은 유지합니다. archive는 승인이나 재확인을 만들지 않습니다.

### 3. 기존 관리 위키를 OKF 형식으로 교정합니다

```sh
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project           # 계획
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --check   # 변경 필요 시 exit 1
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --apply
python3 -B wiki-desk/scripts/wiki_desk.py check  --root example-project
```

unsafe/duplicate YAML·경로 escape·symlink·누락 원문·drift·충돌은 적용 전에 차단하고, 하나라도 있으면 일부 정상 파일도 적용하지 않습니다. unknown type/key·source ID·`generated`/`verified`·역사·workflow status·코드 예시는 보존합니다. YAML 주석·표현 스타일은 보존 대상이 아닙니다. 기본 description은 본문 발췌가 아니라 경로 stub입니다. **형식 PASS는 사용자 승인이나 제품 완료가 아닙니다.**

### 4. 제거해도 위키는 남습니다

```sh
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project --apply
```

관리 패키지 파일만 지우고 위키·원문·`project/`의 계약·receipt는 보존합니다. 수정된 관리 파일은 자동 삭제하지 않습니다. 변하지 않은 관리 위키까지 지우려면 `--apply --remove-unchanged-wiki`를 명시합니다. 사용자가 편집한 내용은 receipt의 sticky 보호로 남고, 사용자 추가 파일을 일괄 삭제하지 않습니다.

## 새 checkout·기존 위키·1.0.0 설치본

모두 기본은 쓰기 0 계획이며, 검토 후 같은 범위에 `--apply`를 붙입니다. 상세는 [유지보수](references/maintenance.md)입니다.

| 상황 | 명령 | 하는 일 |
|---|---|---|
| 스킬·계약만 추적되고 위키·receipt가 없는 새 checkout | `rebuild --root P --host H` | manifest가 맞는 스킬·계약은 다시 쓰지 않고 registry를 재현합니다. 기존 위키/receipt·package drift면 거부합니다. |
| receipt 없는 기존 위키 | `adopt --root P --host H --contract C` | 위키를 고치지 않고 기존 파일을 bytes·mode 그대로 사용자 보호로 등록합니다. `status` PRESENT는 OKF PASS가 아닙니다. |
| 1.0.0 설치본(프로젝트 루트 `.wiki-desk/`) | `migrate-state --root P --host H` | VERSION·legacy receipt·manifest·소유권이 맞을 때만 계약·위키·ID·보호를 유지한 채 이관합니다. 위키를 지우고 재설치하지 않습니다. |

## 안전 경계와 검증 방법

- 설치·발견·로드·실행은 서로 다른 관문입니다. 한 단계 성공을 전체 성공으로 확대하지 않습니다.
- daemon·cron·hook·자동 upstream 갱신·전역/profile/context 편집·자동 설치는 없습니다. 채택 후에는 로컬 코드·계약이 정본입니다.
- 원자적 파일 교체와 Python 예외 rollback을 제공하지만 OS/프로세스 강제 종료까지의 원자성, 원문 인증, 의미상 권위의 자동 증명은 아닙니다.
- 확인한 실행 환경은 Linux/WSL입니다. Windows 네이티브·macOS·동시 적대적 writer는 미검증입니다.
- 한국어 trigger는 합성 프로젝트의 새 Claude Code 2.1.287 세션에서 스킬명 없는 요청에 `Skill(wiki-desk)` 선택을 확인했습니다. 모든 host·버전의 자동 선택을 인증한 것은 아닙니다.
- 아래 시험은 합성 fixture 기반 **결정론 회귀**입니다. 실제 업무 자료·비밀값·벤치마크 말뭉치는 포함하지 않습니다.

```sh
python3 -B -m pytest tests -q -o addopts='' -p no:cacheprovider
python3 -B scripts/package_manifest.py generate   # README·지원파일·시험을 마무리한 뒤 재생성
python3 -B scripts/wiki_desk.py verify-package
```

임시 위치는 `tempfile` 기본값(`TMPDIR` 포함)을 쓰며 `WIKI_DESK_TEST_TMPDIR`로 바꿀 수 있습니다. 로컬 seed를 편집하면 이전 manifest는 stale이 됩니다.

## 더 읽을 문서

| 파일 | 읽는 이유 |
|---|---|
| [SKILL.md](SKILL.md) | 에이전트가 따르는 사서 계약과 발동 범위 |
| [적응형 초기화](references/bootstrap.md) | 문서 범위·권위·위키 이름을 사용자와 합의하는 대화 |
| [OKF](references/okf.md) | OKF 0.2 보존 계약 |
| [권위](references/authority.md) | 권위 순서와 승인·검토의 경계 |
| [설치와 인식](references/installation.md) | host별 경로·발견·로드 조건 |
| [유지보수](references/maintenance.md) | sync·format·rebuild·adopt·migrate·remove의 보존·거부 조건 |
| [외부 출처](references/external-sources.md) | 공식 설계 근거 |
| [1.1.0 항목별 회신](docs/response/response_26100514_위키데스크_개선요청_항목별회신.md) | 1.1.0 변경 판단과 검증 범위 |

라이선스: [MIT](LICENSE).
