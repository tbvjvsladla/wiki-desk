# 적응형 초기화와 합의 계약

## 기존 결정을 먼저 회수하기

수신 agent는 대상 root·host 버전·실제 context·현재 wiki와 계약·관련 사용자 결정부터 읽기 전용으로 확인한다. 이미 결정된 wiki 이름·문서 roots·권위·검토 절차를 다시 인터뷰하지 않는다. 같은 이름의 배포본과 기존 스킬을 구별하고 기존 파일을 덮어쓰지 않는다. 기존 wiki 형식 교정은 새 `install`과 별도 `format` 작업이다.

문서 root가 아직 미정이면 실제 context와 명시된 경로에서 제한된 파일 목록·대표 원문만 조사한다. source tree 전체 재귀 탐색을 동의 없이 시작하지 않으며 비밀·개인자료·dataset·생성물은 먼저 범위에서 제외한다. 확인할 수 없는 파일을 있다고 쓰지 않는다.

## 미정 사항만 묻기

질문은 기존 기록으로 해결되지 않은 아래 항목을 묶어 제시한다. 응답 없는 시간을 승인으로 해석하지 않는다.

| 결정 | 확인할 내용 |
|---|---|
| 대상과 문서 roots | 프로젝트 식별자, 실제 root, 포함할 원문 디렉터리, 문서가 어떤 업무의 근거인가 |
| 제외영역 | 비밀·개인자료·생성물·cache·대용량 데이터·다른 업무·접근 불가 영역 |
| wiki 경로 | `__llm-wiki` 또는 `__llm_wiki` 중 정확한 이름, 기존 wiki 존재와 소유권 |
| taxonomy | 현재 문서 종류·역할과 미분류 문서의 `fallback`; 예제 taxonomy를 고정하지 않음 |
| 권위 | 어떤 원문이 정본·지시·의도·결과·수용인지, 충돌·동순위·후속 정정 처리 |
| 상태 | 지식 lifecycle과 문서 workflow/제품 승인 상태를 어떻게 구별할지 |
| 검토와 변경 | 실제 원문 검토자·수용 범위·색인 갱신 시점, 적용 전에 확인할 변경 목록 |

상태·동순위 처리·review workflow는 합의 문서에 설명한다. 새 machine field가 꼭 필요할 때만 명시적 producer extension으로 제안한다. 기본 런타임이 그 extension을 자동 집행한다고 주장하지 않는다.

## 읽기 전용 조사 → 계획 → 합의 → 적용

1. 현재 파일·지침·기존 결정을 근거로 포함/제외와 대표 분류를 제안한다. 관측과 제안을 구별한다.
2. [계약 예제](../assets/project-contract.example.json)를 구조 참고로만 사용하여 수신 프로젝트에 맞는 JSON을 작성한다. 예제를 복사한 것만으로 합의가 생기지 않는다.
3. [schema](../assets/project-contract.schema.json)의 필수 필드를 모두 채우고 원문·제외 경로를 실제 root 기준으로 대조한다. source와 wiki는 구분하고 wiki 자체를 원문 inventory에 포함하지 않는다.
4. 사용자에게 계약 JSON·변경 계획·created-path 소유권·쓰기 대상·보존/제거 정책을 제시한다. 합의 기록은 계약과 같은 것으로 취급하지 않는다. 런타임은 실제 인간 승인을 판정하지 않으므로 agent가 명시 승인 근거를 확인해야 한다.
5. 계약 파일 저장이 승인된 범위에서 `scan`과 기본 `install`을 실행하여 실제 읽기 전용 결과를 검토한다. `install`은 기본 plan이며 wiki/skill을 쓰지 않는다. schema 검사만으로 경로·symlink·충돌 안전성을 인증하지 않는다.
6. 사용자가 정확한 대상·계약·변경 범위를 명시적으로 승인한 다음에만 `install --apply`를 실행한다. 대상 또는 입력이 변했으면 최신 plan을 다시 검토한다.
7. `status`와 영향 범위 검사로 실제 생성물·receipt를 확인한다. 실제 host의 발견/로드 확인은 별도이고 설치기의 성공 메시지로 대체하지 않는다.

## 계약 필드

필수 root 필드는 정확히 `schema_version`, `project_name`, `wiki_dir`, `source_roots`, `excluded_roots`, `authority_rules`, `fallback`, `copy_policy`다.

- `schema_version`: 정수 `1`. `project_name`: 비어 있지 않은 수신 프로젝트 식별 문자열.
- `wiki_dir`: `__llm-wiki` 또는 `__llm_wiki`만 선택. 자동 rename 없음.
- `source_roots`: 하나 이상의 프로젝트 상대 파일/디렉터리. 프로젝트 전체를 뜻하는 `.`는 명시적으로 그 범위를 합의한 경우에만 사용한다. `excluded_roots`: 제외할 프로젝트 상대 경로 목록이며 빈 목록도 의도적으로 명시한다.
- `authority_rules`: `pattern`, `document_type`, 정수 `authority_rank`, `role`을 가진 규칙 목록. 빈 목록을 합의하면 모든 문서는 명시 `fallback`을 사용한다.
- `fallback`: `document_type`, 정수 `authority_rank`, `role`을 모두 명시. 모호한 default를 숨기지 않는다.
- `copy_policy`: `path_reference`만 지원. 원문 본문 복사를 승인하는 값은 아니다.

경로는 `/` 구분자, root 상대 표기를 사용한다. 절대경로·drive/URI·backslash·빈 segment·`.`/`..` segment를 쓰지 않는다. 단, 위에서 명시한 `source_roots`의 단일 `.` 값은 예외다. 파일시스템 symlink·실제 존재·root escape는 런타임 검사 대상이다. pattern은 같은 상대경로 체계의 glob이며 literal source root와 별개다.

unknown extension은 JSON으로 보존할 수 있으며 known field의 의미·안전 경계를 덮어쓰지 못한다. schema가 허용하는 구조와 현재 runtime이 실제 지원하는 동작을 구별한다. 알 수 없는 extension의 소비를 약속하지 않는다.

## 합성 예제의 한계

예제의 `Example project`, `docs/decisions`, `docs/reports`, `docs/plans`와 rank는 구조를 설명하는 합성 값이다. 실제 문서·승인자·승인일·검증 이력은 담지 않는다. 실제 자료를 조사하기 전에 이 rank를 적용하거나 샘플을 승인된 사용자 계약으로 기록하지 않는다.
