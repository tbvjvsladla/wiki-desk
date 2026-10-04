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

unknown JSON/YAML extension은 보존하되 known field를 덮어쓰는 뜻으로 읽지 않는다. authority/taxonomy·source scope의 중요한 변경은 합의 계약과 변경 계획에 반영하고 기존 결정을 재사용한다. extension 값의 저장을 runtime 기능 지원이라고 광고하지 않는다.

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
