# wiki-desk

프로젝트 원문을 복사하지 않고, 문서의 위치·근거·권위·현재 상태를 찾아 읽는 지식 사서와 OKF 교정 도구입니다.

배포 버전 1.1.0 · Hermes / Codex / Claude Code용 전체 폴더 seed

## 무엇을 배포하나요?

기존 프로젝트의 지식 모음이 아니라 **새 프로젝트에 지식층을 만드는 운영 방식과 도구**를 배포합니다.

- `SKILL.md`: 필요한 원문을 읽고 권위·검토·승인 경계를 구분하는 사서 계약.
- `references/`: 적응형 초기화·OKF0.2·권위·호스트 설치·유지보수·공식 외부 근거.
- `assets/`: 명시적인 프로젝트 계약 예제와 JSON schema.
- `scripts/`: 원문 경로 색인·조회·위키 생성·OKF 보존형 교정과 안전한 설치/제거.
- `tests/`: 합성 자료를 이용하는 개발 회귀시험. 실제 업무 자료·비밀값·벤치마크 말뭉치는 없습니다.

수신 에이전트가 사용자와 문서 범위·제외·분류·권위를 확정한 뒤 새로운 위키를 만듭니다. 예제 권위서열을 실제 승인으로 사용하지 않습니다. 채택 후 로컬 코드·계약이 정본이고 자동 upstream update는 없습니다.

## 세 층을 구분합니다

1. Agent Skills 폴더는 스킬 형식과 지원 파일을 담습니다.
2. 설치된 스킬 안의 `project/contract.json`은 수신 프로젝트의 합의 계약이고 `project/receipt.json`은 기계별 설치·소유권 기록입니다. 계약은 수신 프로젝트가 추적하고 receipt는 스킬 `.gitignore`로 제외합니다. 최상위 `project/`는 패키지 인벤토리에서 빠지므로 설치본도 상태를 품은 채로 패키지 검증이 가능합니다. 새 설치는 프로젝트 루트에 `.wiki-desk/`를 만들지 않습니다.
3. 계약 `wiki_dir`의 지식층은 OKF0.2 Markdown, index/log, 원문 경로 registry입니다.

원문은 기존 위치에 남습니다. source ID/hash/경로가 맞는다는 사실은 원문 내용에 대한 인간 검토·승인·업무 정답을 뜻하지 않습니다. `generated`·`verified`·지식 lifecycle과 문서 workflow 판정도 별개입니다.

## 준비물

Python 3.10+와 PyYAML6(`requirements.txt`)가 필요합니다. 실행기는 의존성을 자동 설치하거나 host 인증·provider·권한·profile·전역 설정을 바꾸지 않습니다. 누락 시 BLOCKED로 보고합니다.

전체 개발시험은 pytest(`requirements-dev.txt`)이고 unittest 사례를 포함합니다. 실행 dependency와 개발시험 dependency를 구분합니다. 기존 환경을 사용하거나 수신 사용자가 자신의 승인 절차로 준비하세요.

## 사용자에게 받은 폴더로 시작하기

`wiki-desk/` **전체 폴더**가 전달 단위입니다. SKILL.md 하나나 단일 URL을 설치하면 도구·schema·참조가 빠집니다. 이 패키지는 원격 repository/hub/plugin에 발행됐다고 주장하지 않습니다.

받은 폴더에서 먼저 검사합니다:

```sh
python3 -B scripts/wiki_desk.py verify-package
```

manifest는 파일 집합/내용/entrypoint를 확인할 뿐 출판자 신뢰를 인증하는 서명은 아닙니다. 신뢰할 수 있는 출처에서 받고 처음 보는 코드는 실행 전에 읽으세요.

## 수신 에이전트에 전달할 첫 요청

```text
받은 wiki-desk 폴더 전체를 읽고 이 프로젝트에 맞게 채택해 줘.
SKILL.md와 references/bootstrap.md부터 읽고 현재 문서 관리 결정을 확인해.
문서 roots·제외·분류·권위·위키 이름이 미정인 부분만 나와 합의해.
기존 스킬·위키·context를 덮어쓰거나 원문을 복사하지 마.
처음에는 scan과 install 계획만 보여 주고 합의한 scope에서만 --apply를 사용해.
생성된 위키에서 실제 원문 경로를 회수하고 check 결과와 인식 한계를 구분해 보고해.
```

자세한 적응형 대화는 [bootstrap](references/bootstrap.md)에 있습니다. 이 패키지의 install은 새 위키 설치입니다. 이미 존재하는 위키에 적용하는 방식은 아래의 형식 교정 절차를 따릅니다.

## 프로젝트 계약

[예제](assets/project-contract.example.json)는 합성 예시입니다. 실제 계약으로 그대로 승인됐다고 해석하지 마세요.

필수 key는 `schema_version`, `project_name`, `wiki_dir`, `source_roots`, `excluded_roots`, `authority_rules`, `fallback`, `copy_policy`입니다. authority rule은 `pattern/document_type/authority_rank/role`을 명시하고 첫 matching rule을 적용합니다. 검색에서는 높은 숫자 rank를 먼저 검토합니다. rank는 탐색 우선순위이지 자동 수용 판정이 아닙니다.

`wiki_dir`는 프로젝트 상대경로이며 `__llm-wiki` 또는 `__llm_wiki`를 정확히 선택할 수 있습니다. 두 폴더를 자동으로 이름 변경·병합하지 않습니다. copy_policy는 `path_reference`만 지원합니다. source roots·제외가 합의되지 않으면 적용하지 않습니다.

선택 key `source_suffixes`(예: `[".md"]`)를 넣으면 디렉터리 원천에서 해당 확장자의 파일만 수집합니다(대소문자 무시). 생략하면 기존처럼 모든 일반 파일을 수집합니다. 필터 밖 파일은 본문을 열거나 source snapshot/registry에 넣지 않고 내용 변경도 sync delta가 아닙니다. 빈 목록·점 없는 값·다중 점·공백·casefold 중복·문자열 단일값은 거부합니다. 명시한 파일 root가 목록 밖이면 조용히 제외하지 않고 계약을 거부하며 visible symlink 검사는 필터보다 먼저입니다.

## 설치 → 조회 → 교정 → 제거

다음은 받은 `wiki-desk/`와 대상 `example-project/`가 같은 부모 폴더에 있는 명령입니다. 대상 프로젝트와 문서 roots가 실제로 존재하고, 합의한 계약을 `example-project/wiki-desk.contract.json`에 저장했다고 가정합니다. 예제 계약을 자동 생성·승인하는 명령이 아닙니다.

```sh
# 읽기 전용 조사와 설치 계획
python3 -B wiki-desk/scripts/wiki_desk.py scan --root example-project --contract example-project/wiki-desk.contract.json
python3 -B wiki-desk/scripts/wiki_desk.py install --root example-project --host codex --contract example-project/wiki-desk.contract.json

# 계획/범위가 합의된 뒤 명시 적용
python3 -B wiki-desk/scripts/wiki_desk.py install --root example-project --host codex --contract example-project/wiki-desk.contract.json --apply
```

호스트별 목적지:

| host | 프로젝트 스킬 경로 |
|---|---|
| hermes | `.agents/skills/wiki-desk` |
| codex | `.agents/skills/wiki-desk` |
| claude | `.claude/skills/wiki-desk` |

같은 이름의 기존 스킬·위키·관리 경로는 덮어쓰지 않습니다. 같은 receipt와 실제 bytes가 일치하는 재설치만 no-op입니다. host 경로가 맞는 것, 파일을 생성한 것, host가 실제 스킬을 발견·로드한 것은 다른 확인입니다. [설치 문서](references/installation.md)에 버전·trust·동명이름·refresh·backend·context 선택 조건을 구분했습니다.

설치된 복사본에서 실행합니다(Codex/Hermes 예):

```sh
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py status --root example-project
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py query --root example-project --terms decision --limit 10
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py check --root example-project
```

Claude에서는 경로의 `.agents`를 `.claude`로 바꿉니다. 상태 명령은 설치본에서 실행하면 자기 `project/`를 읽고, 받은 source package에서 실행하면 계약이 있는 host 목적지를 정확히 하나 찾습니다. 0개 또는 여러 개면 BLOCKED이며 두 상태를 조용히 병합하지 않습니다.

query는 원문을 로컬에서 읽고 일치 후보·경로·읽기 coverage를 보고합니다. 결과 문서가 의미상 수용됐다고 판정하거나 전체 원문을 위키에 복사하지 않습니다. agent는 관련 후보 원문·계보·후속 수용을 직접 읽어 최종 답변합니다. 선택 flag `--fail-on-empty`는 빈 결과 exit3, 일치 결과 exit0을 반환하며 기본 빈 결과는 기존 exit0입니다. BLOCKED exit2와 구분하세요. 기존 위키가 있어도 읽기 전용 scan은 `wiki_exists: true`, `scaffold_paths: []`와 source inventory를 반환합니다.

## 새 checkout·기존 위키·1.0.0 설치본

각 명령은 기본 쓰기0 계획입니다. 선행조건과 계획을 검토한 뒤 같은 범위에 `--apply`를 붙입니다. 자세한 보존·거부 조건은 [유지보수](references/maintenance.md)에 있습니다.

```sh
# 추적 스킬·계약만 있고 위키·receipt는 없는 새 checkout
python3 -B wiki-desk/scripts/wiki_desk.py rebuild --root example-project --host codex

# receipt 없는 기존 위키를 bytes/mode 그대로 보호 등록
python3 -B wiki-desk/scripts/wiki_desk.py adopt --root example-project --host codex --contract example-project/wiki-desk.contract.json

# 별도 위치의 현재 패키지에서 검증된 1.0.0 상태/패키지를 보존형 이관
python3 -B wiki-desk/scripts/wiki_desk.py migrate-state --root example-project --host codex
```

rebuild는 manifest가 일치하는 스킬·계약을 다시 쓰지 않으며 registry를 재현합니다. 기존 위키/receipt 또는 package drift면 거부합니다. adopt는 위키를 교정하지 않고 기존 파일의 최초 preimage·사용자 보호부터 기록하므로 `status` PRESENT가 OKF PASS라는 뜻은 아닙니다. source-package가 skill 목적지의 proper ancestor/descendant이면 plan/apply 전에 거부하고 검증된 기존 설치본인 exact equality만 허용합니다.

migrate-state는 VERSION 1.0.0 패키지·legacy receipt·manifest·소유권이 일치할 때만 실행합니다. 계약 원본 bytes·위키 전체·ID/metadata·최초 preimage·sticky 보호를 유지하고 패키지 교체와 상태 이동을 함께 수행합니다. 먼저 위키를 지우고 재설치하지 않습니다. legacy `.wiki-desk/`에 추가물이 있거나 패키지가 수정/보호됐거나 새 state가 충돌하면 거부합니다. 일반 명령은 legacy 상태가 남아 있으면 이관을 요구합니다. vela의 `1.1.0-vela.1/.2` 상태 배치는 읽기 호환 대상이지만 이 명령으로 임의 local seed/vela 코드까지 자동 업그레이드하지 않습니다.

## 원문 변경과 기존 위키의 OKF 교정

색인 변경은 계획부터 확인합니다:

```sh
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project --apply
```

기존 관리 위키 교정은 설치된 스킬의 합의 계약 `project/contract.json`과 소유권 receipt `project/receipt.json`이 있고 위키가 존재해야 합니다. fresh install로 기존 위키를 덮어쓰지 않습니다. receipt 없는 위키는 위의 보존형 adopt로 먼저 등록하며 그 뒤에도 형식 교정은 별도 계획입니다. 아래는 관리 위키의 교정이며 받은 source 폴더에서 실행해도 됩니다:

```sh
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --check
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --apply
python3 -B wiki-desk/scripts/wiki_desk.py check --root example-project
```

기본은 write-zero입니다. `format --check`는 변경 필요 시 exit1이고 --apply와 동시에 쓰지 않습니다. unsafe/duplicate YAML·경로 escape·symlink·missing registered source·drift·collision은 적용 전에 차단합니다. unknown type/key·source ID/resource·generated/verified·역사·workflow status·코드 예시·directory listing 앞뒤 원본문은 보존합니다. YAML 주석/표현 스타일은 보존 대상이 아닙니다. 전체 Markdown 분모는 README/SCHEMA·새 index도 포함합니다.

OKF conformance와 project profile completeness, broken-link/unsafe-resource 경고, source 무결성·semantic 승인은 별도 판정입니다. 오류·분모/보존 실패가 있으면 전체 apply/check를 BLOCKED로 멈추고 일부 정상 파일도 적용하지 않습니다. 기본 description은 본문 발췌 대신 경로 stub이며 기존 명시 description은 보존합니다. 형식 PASS로 사용자 승인·제품 완료를 만들어내지 않습니다.

등록 원문 삭제·이동은 기본적으로 계속 차단합니다. 원문 이동이나 삭제를 직접 수행하는 명령이 아니라 이미 검토한 변화의 registry 조정입니다:

```sh
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --accept-removed docs/retired.md
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --relocate docs/old.md=docs/new.md
```

계획 확인 후 `--apply`를 붙이며 반복 지정도 가능합니다. 지정 경로만 조정하고 과거 source 전체 metadata를 append-only `archived_sources`에 보존합니다. 이동 원문의 ID·unknown extension은 유지합니다. 경로 escape·중복·destination 충돌·필터/제외 밖 목적지·미해결 다른 missing 경로는 거부합니다. archive/history는 승인이나 내용 재확인을 만들지 않습니다.

## 제거는 위키 보존이 기본입니다

```sh
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project --apply
```

managed 패키지 파일을 제거하고 위키·원문·`<skill>/project/`의 계약·receipt는 보존합니다. 소유 파일 대조는 내용·size·실행 여부를 사용하므로 0644→0664 같은 checkout 차이는 DRIFT나 사용자 보호를 만들지 않습니다. 실행 여부/내용 변경은 여전히 DRIFT이며 실행 중 snapshot·rollback은 정확한 mode를 보존합니다.

수정된 managed 파일은 자동 삭제하지 않습니다. 변하지 않은 관리 위키까지 되돌리는 명시 opt-in은 `--apply --remove-unchanged-wiki`입니다. 사용자가 편집한 내용은 이후 sync/format이 성공해도 receipt의 sticky 보호로 남으며 full remove는 거부합니다. 최신 hash가 맞는다는 이유로 사용자 내용의 삭제 권한을 재생성하지 않습니다. rebuild의 기존 추적 파일은 최초 preimage로, adopt의 기존 위키는 사용자 보호로 남습니다. 사용자 추가 파일/디렉터리를 broad-delete하지 않습니다. [유지보수](references/maintenance.md)를 먼저 확인하세요.

## 검증 범위와 한계

- 공통 runtime/OKF·lifecycle 회귀는 합성 fixture에서 실제 기존 Python으로 실행했습니다. 원문 복사·사용자 승인 조작·동결 benchmark 재실행을 하지 않습니다.
- 세 호스트의 설치 목적지와 두 위키 이름은 helper surface입니다. 한국어 trigger는 합성 프로젝트의 새 Claude Code 2.1.287 세션에서 스킬명 없는 요청에 `Skill(wiki-desk)` 선택을 실제 확인했습니다. 모든 호스트·버전의 자동 선택이나 private 수신 프로젝트의 동작을 인증한 것은 아닙니다.
- 확인한 실행 환경은 Linux/WSL입니다. Windows 네이티브/macOS·동시 hostile writer·OS/process 강제종료 복구는 별도 미검증입니다.
- file atomic replace와 Python exception rollback을 제공하지만 전체 OS/process-crash atomicity나 source 인증·semantic authority의 자동 proof는 아닙니다.
- daemon/cron/inline-shell/hook·자동 upstream·전역/profile/context 편집·자동 install은 없습니다.

릴리스 개발자는 최종 README/지원파일/시험까지 마무리한 뒤 manifest를 다시 생성합니다. 로컬 소유 seed를 편집하면 이전 manifest도 stale입니다:

```sh
python3 -B -m pytest tests -q -o addopts='' -p no:cacheprovider
python3 -B scripts/package_manifest.py generate
python3 -B scripts/wiki_desk.py verify-package
```

시험 모듈 import는 패키지 상대경로를 지원합니다. 임시 위치는 `tempfile`의 기본값(`TMPDIR` 포함)을 사용하고 `WIKI_DESK_TEST_TMPDIR`로 명시 override할 수 있습니다. 다른 호스트의 HOME 아래에 Hermes 전용 경로를 만들지 않습니다. unittest 단일 모듈 smoke는 전체 pytest를 대체하지 않습니다:

```sh
python3 -B -m unittest tests.test_release_safety.ReleaseSafetyTests.test_receipt_protection_flag_must_be_boolean_and_status_guarded
```

공식 설계 근거는 [외부 출처](references/external-sources.md), 보존 계약은 [OKF](references/okf.md), 실제 판단 경계는 [권위](references/authority.md)에 있습니다.

1.1.0 변경 판단과 검증 범위는 [R1~R10 항목별 회신](docs/response/response_26100514_위키데스크_개선요청_항목별회신.md)에 기록합니다. 기능 검증·최종 패키지 identity·실제 운영 적용·원격 발행을 구분하세요.
