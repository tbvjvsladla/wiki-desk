# 질의·증분 유지보수·제거와 실패 처리

## 작업에 맞는 최소 범위

| 작업 | 읽기/검사 범위 | 자동으로 추가하지 않을 작업 |
|---|---|---|
| 지식 질의 | 관련 index/후보와 실제 원문 계보 | 전체 corpus 재검토·sync·format·제품 재실행 |
| 원문/검토 기록 변경 | 현재 계약과 변경된 원문·관련 연결 | 불필요한 전체 의미 검토·역사 승인 재작성 |
| `sync` | 합의된 source inventory와 기존 registry 대조 | 원문 본문 복사·미합의 source root 확장 |
| `format`/`check` | 합의 wiki bundle의 전체 Markdown | source universe 전체 수정·권위 재정의 |
| 배포 변경 | 패키지 dependency closure·관련 회귀·설치 복사본 | 전역/profile 적용·외부 발행·host 모델 자동 호출 |

증분 소비는 필요한 후보만 읽고 변경 metadata만 적용하는 것을 뜻한다. 현재 `sync`는 계약 source 범위를 조사하여 delta를 계획하므로 모든 호출이 파일 이벤트 기반 O(delta) scan이라고 주장하지 않는다. daemon/watch/hook은 없다. 전체 검토가 명시된 요청이면 작은 subset만 확인하고 전체 PASS로 부르지 않는다.

## 원문 변경과 registry 정합성

현재 원문과 ID/path·input scope·내용 관측값을 대조한다. missing 등록·ID 충돌·stale·이동은 원문 root, checkout, relocation 근거를 확인하여 정식 조정한다. 마지막 관측과 역사 이력을 보존하며 source를 지우거나 예외를 끄는 것으로 PASS를 만들지 않는다.

unknown JSON/YAML extension은 보존하되 known field를 덮어쓰는 뜻으로 읽지 않는다. authority/taxonomy·source scope의 중요한 변경은 합의 계약과 변경 계획에 반영하고 기존 결정을 재사용한다. `source_suffixes`는 runtime에서 실제 소비하는 선택 필드다. 그 밖의 extension 값 저장만으로 기능 지원을 광고하지 않는다.

## 상태 위치와 소유권 대조

운영 상태는 `<skill>/project/contract.json`과 `receipt.json`이다. schema_version=1의 receipt는 실제 host/skill/wiki layout과 계약 bytes에 결합된다. 패키지 자체는 최상위 `project/`를 배포 인벤토리에서 제외하고 기존 상태를 다른 대상에 복사하지 않는다. 일반 remove는 패키지 파일만 제거하고 위키·운영 상태를 보존한다.

소유 파일의 지속적 identity는 내용 hash·size·실행 여부로 비교한다. 0644→0664 같은 checkout/umask 차이는 DRIFT나 사용자 편집 보호가 아니다. 실행 여부 또는 내용 변경은 여전히 DRIFT이며 sync/format 후에도 sticky 보호가 남는다. 실행 중 트랜잭션의 snapshot·readback·rollback은 정확한 mode 대조를 유지한다. 이 규칙은 전체 filesystem permission 안전성의 인증이 아니다.

## 원문 삭제·이동의 명시 조정

기본 `sync`는 missing source나 합의 scope 밖 등록 원문을 계속 거부한다. 실제 삭제 수용 또는 이동 계보를 검토한 뒤 지정 경로만 조정한다. 아래 명령은 `wiki-desk/`와 `example-project/`의 공통 부모에서 실행하는 예이며 OLD/NEW는 대상 root 상대 리터럴이다.

```sh
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --accept-removed docs/retired.md
python3 -B wiki-desk/scripts/wiki_desk.py sync --root example-project --relocate docs/old.md=docs/new.md
```

계획 확인 후 같은 범위에 `--apply`를 붙인다. 두 옵션은 반복 지정할 수 있다. 원문 파일을 삭제·이동하는 명령이 아니라 registry의 명시 전환이다. active sources와 `archived_sources`를 분리하고 삭제/이동 전 source 전체 metadata를 reason·시각·이동 목적지와 함께 append-only로 보존한다. 이동한 active 원문은 같은 source ID와 unknown extension을 유지하며 내용 관측과 분류만 현재 원문에 맞춘다. 예전 verified/status는 현재 내용의 재확인으로 승계하지 않는다.

중복·경로 escape·destination 충돌·필터/제외 밖 목적지·아직 inventory에 있는 OLD·남은 다른 missing 경로는 쓰기 전에 거부한다. 옵션은 승인된 경로만 조정하며 나머지 missing guard를 끄지 않는다. source scope 변경은 먼저 합의 계약에 반영한다. history가 실제 승인·실행 권한을 만들어내지는 않는다.

## 1.0.0 루트 상태의 보존형 이관

1.0.0은 계약·receipt를 프로젝트 루트 `.wiki-desk/`에 두었다. 1.1.0의 기본 동작은 그 폴더가 남아 있으면 거부하는 것이다. 별도 위치의 현재 전체 source package에서 `migrate-state --root example-project --host hermes`로 먼저 계획한다. 검증된 VERSION 1.0.0 패키지, manifest와 receipt ownership 일치, 정확한 legacy contract/receipt 두 파일, 새 state 경로 부재가 필요하다.

계획을 수용한 뒤 `--apply`를 사용하면 패키지 파일을 교체하고 상태를 스킬 안으로 옮긴다. 계약 원본 bytes·위키 전체 bytes/mode·source ID/metadata·최초 preimage·기존 사용자 보호는 보존한다. 위키를 제거한 후 재생성하지 않는다. legacy `.wiki-desk/`의 추가 파일, 수정/보호된 패키지, state 충돌은 무검토 삭제하지 않고 거부한다. 사용자 편집된 위키를 이관해도 그 편집은 sticky 보호로 남는다. 이관 후 설치본 `verify-package`, `status`와 필요한 `check`를 확인한다.

`1.1.0-vela.1/.2`의 `<skill>/project/` 배치·schema_version=1은 읽기 호환 대상으로 사용한다. 이 명령은 해당 vela 패키지 또는 임의 1.0.x를 자동 업그레이드하지 않는다. local seed 수정이나 다른 VERSION이면 현재 계약·패키지·소유권을 먼저 대조하고 별도 보존형 채택을 설계한다.

## 버전관리된 설치본 재생성

새 checkout에 manifest와 일치하는 설치 스킬·`project/contract.json`만 있고 위키와 receipt가 없다면 `rebuild --root example-project --host hermes`를 계획한 뒤 `--apply`로 재생성한다. 스킬이나 계약을 지우거나 다시 쓰지 않는다. 기존 package/contract의 preimage를 기록하므로 rebuild 성공이 그 추적 파일을 삭제할 권한을 만들지 않는다. 동일 source/계약의 registry bytes는 재현된다. 계약 외 state 추가물, 기존 위키/receipt, manifest drift면 거부한다.

## receipt 없는 기존 위키 채택

`adopt --root example-project --host hermes --contract example-project/wiki-desk.contract.json`은 기존 위키를 bytes/mode 그대로 소유권 기록에 등록한다. 기본 계획은 쓰기0이며 적용도 위키 자체를 교정하지 않는다. 모든 기존 위키 파일은 최초 preimage와 사용자 보호로 시작한다. 스킬은 없는 목적지에 설치하거나 현재 패키지와 manifest가 일치하는 기존 복사본만 사용한다. source-package가 skill 목적지의 proper ancestor/descendant이면 원본 오염을 막기 위해 plan/apply 전에 거부하며 검증된 기존 설치본인 exact equality는 허용한다. 계약/state 충돌은 거부한다.

채택 직후 `status` PRESENT는 등록 파일의 identity 확인이지 OKF conformance나 의미상 검토 PASS가 아니다. 기존 위키가 부적합하면 `check`에 실패할 수 있다. 후속 format/sync는 별도 계획으로 선택한다. full remove는 사용자 보호 위키를 지우지 않고 거부하며 일반 remove는 위키를 그대로 둔다.

## 읽기 전용 조사와 빈 질의

기존 위키에서도 `scan --contract ...`은 source inventory를 반환하고 `wiki_exists: true`, `scaffold_paths: []`로 scaffold를 생략한다. 원문 scope의 안전 검사는 그대로 유지한다.

`query --fail-on-empty`는 matched_count=0일 때만 exit3을 반환한다. 기본 빈 결과와 일치 결과는 exit0, BLOCKED는 exit2다. 빈 결과·coverage·snapshot/원문 읽기 오류·의미상 근거 충분성은 별도이며 자동 승인 또는 업무 정답 gate로 합치지 않는다.

## metadata와 형식의 변경 루프

1. 관련 원문/검토 기록을 먼저 마무리하고 계약을 읽는다. 동시에 원문을 쓰는 작업과 그것을 읽는 sync를 겹치지 않는다.
2. `sync` 또는 `format`의 기본 읽기 전용 plan을 검토한다. 예상 delta·보존·missing·denominator·충돌 진단을 확인한다.
3. 명시 적용 승인이 있는 동일 범위에서만 `--apply`를 사용한다. source/target drift면 최신 입력으로 plan을 다시 검토한다.
4. 실제 대상 read-back, 영향 범위 check·원문 연결을 확인한다. bundle 전면 교정이면 모든 Markdown과 새 index까지 분모를 일치시킨다.
5. 실제 metadata 변화가 계속되면 fixed point를 확인한다. 이미 통과한 동일 입력의 검사를 보고 단계마다 반복하지 않는다.
6. 결과를 metadata 무결성·형식 적합성·원문 읽기·권위/수용·host 인식으로 나누어 보고한다. source 존재/hash는 의미 검토나 승인과 별개다.

런타임의 변경 전 snapshot/receipt는 안전한 쓰기·ownership 검사 자료다. 원문 전체 snapshot 배포·복사·외부 전송 기능이 아니다. plan은 외부 serialized 실행 계약이 아니며 JSON을 편집해 직접 실행하지 않는다.

## 제거는 보존 우선

`remove`는 기본 plan이다. `remove --apply`도 원문과 wiki를 기본 보존한다. receipt의 생성 경로·현재 변경 여부를 검토하고 사용자 작성 내용·수정된 설치 파일·소유권 불명 경로를 무검토 삭제하지 않는다. 제거 뒤 `status`와 실제 남은 경로를 확인한다.

`--remove-unchanged-wiki`는 별도 명시 opt-in이다. 현재 tree가 receipt의 관리 파일/디렉터리·내용·preimage 조건과 일치할 때만 관리 wiki를 제거한다. `sync`/`format` 뒤 receipt도 갱신될 수 있으므로 최초 설치와 byte가 동일하다는 뜻으로 읽지 않는다. receipt 밖 사용자 추가물이나 사용자가 변경한 파일까지 정리하는 강제삭제 flag가 아니다. 거부되면 차이를 보고하고 파일을 먼저 보존한다. source 원문은 어떤 제거 모드에서도 제거 대상이 아니다.

## 실패와 복구 한계

실패 command·exit code·진단·partial 상태·실제 rollback 범위를 보존한다. 근거 있는 수정만 하고 같은 입력의 실패를 무근거 재시도하지 않는다. 충돌·missing·symlink·root escape·credential·dependency 차단은 권한 완화나 자동 설치로 우회하지 않는다.

파일 단위 교체와 Python 예외 rollback을 전체 트랜잭션의 OS/process-crash atomicity로 광고하지 않는다. 강제 종료·동시 hostile writer·OS별 미시험 행위는 별도 한계다. 필요하면 읽기 전용 상태 조사 후 사용자와 보존형 복구를 합의한다. 지식 원문이나 과거 수용 기록을 rollback 대상으로 확대하지 않는다.

## local seed의 개정과 README-last

수신 후 로컬 소유 패키지에는 자동 upstream updater가 없다. upstream 개선은 명시적 새 채택/비교와 현재 계약·로컬 수정의 검토를 거친다. 기존 이름/경로 충돌을 updater로 덮어쓰지 않는다.

릴리스 관리자는 구현·관련 전체 `pytest`(`unittest` 사례 포함)·격리된 전체 폴더 설치 복사본 검증을 마친 뒤 README를 실제 CLI/파일/한계에 맞춰 마지막으로 확정한다. 그 후 최종 manifest를 생성하고 `verify-package`로 완전성을 확인한다. manifest 부재·부분 suite·source-tree 테스트만으로 installed-copy 또는 host load PASS를 만들지 않는다. README/manifest/host recognition은 이 지원 문서의 주장만으로 완료되지 않는다.
