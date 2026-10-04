# wiki-desk

프로젝트 원문을 복사하지 않고, 문서의 위치·근거·권위·현재 상태를 찾아 읽는 지식 사서와 OKF 교정 도구입니다.

배포 버전 1.0.0 · Hermes / Codex / Claude Code용 전체 폴더 seed

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
2. `.wiki-desk/contract.json`은 수신 프로젝트의 범위·분류·권위 운영 계약입니다.
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

Claude에서는 경로의 `.agents`를 `.claude`로 바꿉니다. query는 원문을 로컬에서 읽고 일치 후보·경로·읽기 coverage를 보고합니다. 결과 문서가 의미상 수용됐다고 판정하거나 전체 원문을 위키에 복사하지 않습니다. agent는 관련 후보 원문·계보·후속 수용을 직접 읽어 최종 답변합니다.

## 원문 변경과 기존 위키의 OKF 교정

색인 변경은 계획부터 확인합니다:

```sh
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project
python3 -B example-project/.agents/skills/wiki-desk/scripts/wiki_desk.py sync --root example-project --apply
```

기존 관리 위키 교정은 프로젝트의 합의 계약 `.wiki-desk/contract.json`과 설치/소유권 receipt `.wiki-desk/receipt.json`이 있고 위키가 존재해야 합니다. fresh install로 기존 위키를 덮어쓰지 않습니다. receipt 없는 임의의 기존 위키를 자동으로 관리 대상으로 채택하는 CLI는 제공하지 않습니다. 그런 위키는 먼저 사용자와 별도 보존형 이관을 설계해야 합니다. 아래는 이 패키지로 생성·관리하는 위키의 교정이며 받은 source 폴더에서 실행해도 됩니다:

```sh
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --check
python3 -B wiki-desk/scripts/wiki_desk.py format --root example-project --apply
python3 -B wiki-desk/scripts/wiki_desk.py check --root example-project
```

기본은 write-zero입니다. `format --check`는 변경 필요 시 exit1이고 --apply와 동시에 쓰지 않습니다. unsafe/duplicate YAML·경로 escape·symlink·missing registered source·drift·collision은 적용 전에 차단합니다. unknown type/key·source ID/resource·generated/verified·역사·workflow status·코드 예시·directory listing 앞뒤 원본문은 보존합니다. YAML 주석/표현 스타일은 보존 대상이 아닙니다. 전체 Markdown 분모는 README/SCHEMA·새 index도 포함합니다.

OKF conformance와 project profile completeness, broken-link/unsafe-resource 경고, source 무결성·semantic 승인은 별도 판정입니다. 오류·분모/보존 실패가 있으면 전체 apply/check를 BLOCKED로 멈추고 일부 정상 파일도 적용하지 않습니다. 기본 description은 본문 발췌 대신 경로 stub이며 기존 명시 description은 보존합니다. 형식 PASS로 사용자 승인·제품 완료를 만들어내지 않습니다.

## 제거는 위키 보존이 기본입니다

```sh
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project
python3 -B wiki-desk/scripts/wiki_desk.py remove --root example-project --apply
```

managed 스킬을 제거하고 위키·원문·운영 계약은 보존합니다. 수정된 managed 파일은 자동 삭제하지 않습니다. 변하지 않은 관리 위키까지 되돌리는 명시 opt-in은 `--apply --remove-unchanged-wiki`입니다. 사용자가 편집한 내용은 이후 sync/format이 성공해도 receipt의 sticky 보호로 남으며 full remove는 거부합니다. 최신 hash가 맞는다는 이유로 사용자 내용의 삭제 권한을 재생성하지 않습니다. 사용자 추가 파일/디렉터리를 broad-delete하지 않습니다. [유지보수](references/maintenance.md)를 먼저 확인하세요.

## 검증 범위와 한계

- 공통 runtime/OKF·lifecycle 회귀는 합성 fixture에서 실제 기존 Python으로 실행했습니다. 원문 복사·사용자 승인 조작·동결 benchmark 재실행을 하지 않습니다.
- 세 호스트의 설치 목적지와 두 위키 이름은 helper surface입니다. host model을 실호출하거나 모든 버전의 selector 인식을 인증한 것이 아닙니다.
- 확인한 실행 환경은 Linux/WSL입니다. Windows 네이티브/macOS·동시 hostile writer·OS/process 강제종료 복구는 별도 미검증입니다.
- file atomic replace와 Python exception rollback을 제공하지만 전체 OS/process-crash atomicity나 source 인증·semantic authority의 자동 proof는 아닙니다.
- daemon/cron/inline-shell/hook·자동 upstream·전역/profile/context 편집·자동 install은 없습니다.

릴리스 개발자는 최종 README/지원파일/시험까지 마무리한 뒤 manifest를 다시 생성합니다. 로컬 소유 seed를 편집하면 이전 manifest도 stale입니다:

```sh
python3 -B -m pytest tests -q -o addopts='' -p no:cacheprovider
python3 -B scripts/package_manifest.py generate
python3 -B scripts/wiki_desk.py verify-package
```

공식 설계 근거는 [외부 출처](references/external-sources.md), 보존 계약은 [OKF](references/okf.md), 실제 판단 경계는 [권위](references/authority.md)에 있습니다.
