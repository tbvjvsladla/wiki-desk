# 전체 폴더 채택·설치·host 인식

## 배포 방식과 선행 확인

이 배포는 전체 `wiki-desk/` 폴더를 수신 프로젝트에 채택하는 seed다. bare `SKILL.md`나 단일 다운로드 URL은 전체 dependency closure를 보장하지 않는다. 수신 후 로컬 코드·합의 계약이 정본이며 자동 upstream 업데이트·hub 등록·구독·watcher는 없다.

Python 3.10+와 `PyYAML>=6,<7`가 helper의 runtime prerequisite다. `requirements.txt`에는 runtime dependency만 있다. 전체 개발시험은 `unittest` 사례를 포함한 `pytest`이며 선택적 `requirements-dev.txt`로 분리한다. 누락되면 차단 사유를 보고하고 자동 `pip`/provider/도구 설치를 하지 않는다. Python helper는 host의 일반 명령 실행 도구·permission/sandbox 안에서 호출한다.

source package root, 대상 project root, 설치 후 skill root, knowledge bundle root를 구별한다. remote/container backend이면 해당 실행 환경에서 실제 전체 폴더와 원문이 보이는지 확인한다. 경로 token을 모든 host의 공통 변수라고 가정하지 않는다. `.wiki-desk/contract.json`은 knowledge bundle 밖 target-local 운영 계약이다.

## host별 project adapter

| host | 이 패키지의 설치 목적지 | 발견·동명이름·인식 조건 |
|---|---|---|
| Hermes | `.agents/skills/wiki-desk` | 지원 버전의 trusted project discovery 필요. project → local → external 우선순위와 quarantine/플랫폼 enablement를 확인 |
| Codex | `.agents/skills/wiki-desk` | CWD부터 repository root까지 발견 경로 확인. 같은 이름이 merge되지 않고 selector에 함께 나타날 수 있어 실제 경로를 선택 |
| Claude Code | `.claude/skills/wiki-desk` | `.agents`만으로 발견을 보장하지 않음. enterprise → personal → project 우선순위·safe/managed policy·session 가시성 확인 |

이 표는 공식 문서 기반 경로 계약이며 host 실행 시험 보고가 아니다. 세 host에서 동일한 precedence나 등록 절차를 가정하지 않는다. 기존 동명 skill, 기존 wiki, contract/control path, 사용자 파일과 충돌하면 먼저 plan/소유권을 검토하고 덮어쓰지 않는다. symlink·root escape·special file 거부를 우회하지 않는다.

## 고정 CLI 표면

entrypoint는 전체 패키지의 `scripts/wiki_desk.py`다. 다음은 `wiki-desk/` source package와 `example-project/`의 공통 부모 디렉터리에서 실행하는 합성 예시다. 대상 `example-project`와 그 실제 합의 계약 `example-project/wiki-desk.contract.json`이 이미 존재해야 한다. 아래 경로를 개인 프로젝트의 현재 경로라고 주장하지 않는다. 실제 대상에서는 확인한 경로를 사용한다.

| action | 명령 예시 | 쓰기 여부 |
|---|---|---|
| 패키지 확인 | `python3 wiki-desk/scripts/wiki_desk.py verify-package` | 읽기 전용, 최종 manifest가 있어야 함 |
| source 조사 | `python3 wiki-desk/scripts/wiki_desk.py scan --root example-project --contract example-project/wiki-desk.contract.json` | 읽기 전용 |
| 설치 계획 | `python3 wiki-desk/scripts/wiki_desk.py install --root example-project --host hermes --contract example-project/wiki-desk.contract.json` | 기본 plan, 대상 쓰기 없음 |
| 설치 적용 | 위 명령에 `--apply` 추가 | 명시 승인 범위의 대상 쓰기 |
| 상태 | `python3 wiki-desk/scripts/wiki_desk.py status --root example-project` | 읽기 전용 |
| 색인 계획 | `python3 wiki-desk/scripts/wiki_desk.py sync --root example-project` | 읽기 전용 plan |
| 색인 적용 | 위 명령에 `--apply` 추가 | 명시 승인 범위의 metadata 쓰기 |
| 후보 검색 | `python3 wiki-desk/scripts/wiki_desk.py query --root example-project --terms decision --limit 10` | 읽기 전용, 실제 원문 검토와 별도 |
| 형식 계획 | `python3 wiki-desk/scripts/wiki_desk.py format --root example-project` | 읽기 전용 plan |
| 형식 확인 | `python3 wiki-desk/scripts/wiki_desk.py format --root example-project --check` | 읽기 전용 check |
| bundle 확인 | `python3 wiki-desk/scripts/wiki_desk.py check --root example-project` | 읽기 전용 |
| 형식 적용 | 기본 `format` 명령에 `--apply` 추가 | 명시 승인 범위의 wiki 쓰기 |
| 제거 계획 | `python3 wiki-desk/scripts/wiki_desk.py remove --root example-project` | 기본 plan |
| 제거 적용 | 위 명령에 `--apply` 추가 | 소유권·변경 여부 검사 후 제거, wiki는 기본 보존 |
| 관리 wiki까지 제거 | 기본 `remove` 명령에 `--apply --remove-unchanged-wiki` 추가 | 명시 승인 및 unchanged/receipt 조건을 만족하는 관리 wiki만 |

`--host`는 `hermes`, `codex`, `claude` 중 명시한다. stdout은 JSON이고 진단·exit code도 함께 확인한다. `sync`/`query`/`format`/`check`는 대상의 `.wiki-desk/contract.json`을 읽는다. JSON plan을 외부에서 고쳐 적용하는 interface는 없다. 최신 입력으로 trusted plan을 생성하는 정상 CLI만 사용한다.

## source 확인 → 대상 적용 → read-back

1. 전체 패키지 파일을 확인하고 `verify-package`를 실행한다. manifest 부재는 미완성/차단이지 PASS가 아니다. 패키지 무결성은 출판자 신뢰 또는 host 인식을 인증하지 않는다.
2. [초기화](bootstrap.md)로 현재 결정·원문 scope·계약·변경 계획을 확정한다. 예제 rank를 자동 적용하지 않는다.
3. 기본 `install`로 충돌·안전성·created paths를 검토한다. `--apply` 전 정확한 대상·계약·범위의 명시 승인을 확인한다.
4. 적용 뒤 `status`와 실제 대상 파일/receipt를 읽고 필요한 `check`를 실행한다. fresh install은 기존 wiki 교정 수단이 아니다. 설치를 updater로 쓰지 않는다.
5. helper smoke, host 발견, 실제 SKILL 로드, 원문 회수의 결과를 따로 기록한다. 파일이 있다는 사실 또는 `status`의 존재 확인을 host load PASS라고 하지 않는다.

## context 선택과 선택적 routing

- Hermes는 native `HERMES.md`/`.hermes.md`와 context-type 선택을 버전별로 확인한다. 공식 문서의 AGENTS CWD-only 설명과 hierarchy 설명이 일치하지 않으므로 대상에서 실제 로드된 경로를 확인한다.
- Codex는 directory별 `AGENTS.override.md` → `AGENTS.md` → 설정 fallback 및 startup chain을 확인한다. `HERMES.md`/`CLAUDE.md`의 기본 자동 주입을 가정하지 않는다.
- Claude는 `CLAUDE.md` 계열을 확인한다. 공식 문서상 `AGENTS.md` 직접 읽기는 v2.1.277+와 내장 기능/설정 조건에 의존하며 CLAUDE 계열 존재가 기본 선택을 바꿀 수 있다. 모든 context가 함께 로드되는 것은 아니다.

아래는 사용자에게 제안할 수 있는 **수동 opt-in 문구**다. 설치기는 기존 `HERMES.md`, `AGENTS.md`, `CLAUDE.md`를 편집하지 않는다. 기존 내용과 충돌하지 않는지 검토하고 사용자가 선택한 context에만 별도로 반영한다. 반영했다고 실제 로딩을 검증한 것은 아니다.

```text
프로젝트 지식·문서 권위·색인 작업에는 설치된 wiki-desk 스킬을 필요할 때 읽는다.
대상 .wiki-desk/contract.json의 원문 scope와 wiki_dir를 먼저 확인한다.
index로 후보를 좁힌 뒤 실제 원문·검토·수용 범위를 대조한다.
예제 권위는 강제하지 않으며 쓰기 변경은 계획 검토와 명시적 적용 승인을 따른다.
```

이 문구는 전체 헌법/문서 계층을 복사하거나 상위 host 지침을 대체하지 않는다. 전역·profile·trust 설정을 자동 수정하거나 개발 작업공간 root에 `.claude`를 만드는 절차가 아니다. 수신 프로젝트가 `.claude`를 금지하면 `--host claude` 적용도 하지 않고 그 제약을 먼저 해결한다.

## refresh와 인식의 한계

설치 후 현재 버전에서 제공하는 목록/selector를 새로 확인하고 필요하면 새 host 세션을 연다. Hermes에서 해당 명령이 제공되는 버전은 `/reload-skills` 후 `/skill wiki-desk` 또는 새 세션으로 확인할 수 있지만, trust/quarantine/플랫폼 설정은 여전히 별개다. Codex·Claude도 selector의 실제 경로와 새 세션 로드를 확인한다. 모든 host에 통하는 refresh 명령을 만들지 않는다.

인식 실패는 실제 loaded path·동명이름·backend 가시성·trust·quarantine·context 선택·Python dependency를 분리하여 진단한다. agent가 실호출하지 않았으면 그 host는 미검증이라고 보고한다. 전역/profile 변경·권한 완화를 기본 복구로 제안하지 않는다.
