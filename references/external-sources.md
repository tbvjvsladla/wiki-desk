# 공식 외부 근거와 채택 한계

## 조회 기준

조회일: **2026-10-04**. 공식 페이지 본문·공식 Markdown·공식 repository SPEC을 회수한 조사에서 필요한 짧은 문단만 발췌했다. 이는 문서 근거이며 설치·host 실호출·runtime load·제품 승인 검증 결과가 아니다. 이 문서는 공식 URL과 공개 규격 내용만 담고 비공개 감사 경로·원문 자료·실험/benchmark를 배포하지 않는다.

OKF 근거는 canonical `GoogleCloudPlatform/open-knowledge-format`의 **Version 0.2** 조회본이다. `main` URL은 변경될 수 있으며 commit SHA를 pin했다고 주장하지 않는다. 이 패키지는 자동으로 upstream을 따라가지 않는다. 인용은 해당 조회본의 설명 범위이며 수신 host의 버전·정책·실제 상태를 확인해야 한다.

## Agent Skills 형식

- 공식 URL: https://agentskills.io/specification
- 조회일: 2026-10-04

> * A map from string keys to string values

> 1. **Metadata** (~100 tokens): The `name` and `description` fields are loaded at startup for all skills
> 2. **Instructions** (< 5000 tokens recommended): The full `SKILL.md` body is loaded when the skill is activated
> 3. **Resources** (as needed): Files (e.g. those in `scripts/`, `references/`, or `assets/`) are loaded only when required

> When referencing other files in your skill, use relative paths from the skill root:

채택과 한계: 필수 name/description과 string-valued metadata를 사용하고 지원 자료는 필요한 때만 읽는다. 이 패키지의 version은 표준 metadata 안의 문자열로 둔다.

## Agent Skills와 발견 위치의 분리

- 공식 URL: https://agentskills.io/client-implementation/adding-skills-support
- 조회일: 2026-10-04

> While the Agent Skills specification does not mandate where skill directories live (it only defines what goes inside them)

채택과 한계: 형식과 발견 위치는 별도다. 하나의 디렉터리를 세 host에 공통 등록 경로로 광고하지 않는다. 구현 가이드의 universal precedence 일반화보다 각 host의 문서를 따른다.

## Hermes 스킬과 trust

- 공식 URL: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- 조회일: 2026-10-04

> The agent only loads the full skill content when it actually needs it.

> Trusted roots are stored in `skills.trusted_project_dirs` in `~/.hermes/config.yaml`. Set `skills.project_discovery: false` to turn the feature off entirely (no scanning, no notices).

> Project skills are the **highest-precedence tier**: `project → local (~/.hermes/skills/) → external_dirs`.

채택과 한계: 이 배포의 Hermes project adapter는 .agents/skills다. 지원 버전·trusted project·scan·동명이름·플랫폼 설정을 별도로 확인하며 trust/profile을 자동 변경하지 않는다.

## Hermes token과 실행 경계

- 공식 URL: https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills
- 조회일: 2026-10-04

> | `${HERMES_SKILL_DIR}` | Absolute path to the skill's directory |

> This is **off by default** — any snippet in a SKILL.md runs on the host without approval, so only enable it for skill sources you trust:

채택과 한계: HERMES_SKILL_DIR는 Hermes 전용 token이다. portable core는 inline shell을 사용하지 않는다. script 실행은 정상 tool/permission 경로에서 수행한다.

## Codex 스킬

- 공식 URL: https://developers.openai.com/codex/skills
- 조회일: 2026-10-04

> Codex reads skills from repository, user, admin, and system locations. For repositories, Codex scans `.agents/skills` in every directory from your current working directory up to the repository root. If two skills share the same `name`, Codex doesn’t merge them; both can appear in skill selectors.

> Direct skill folders are best for local authoring and repo-scoped workflows.

채택과 한계: Codex의 repo-local .agents/skills를 사용하되 동명이름을 자동 merge로 읽지 않는다. local seed adoption과 vendor plugin 배포는 구별한다.

## Codex context 선택

- 공식 URL: https://developers.openai.com/codex/guides/agents-md
- 조회일: 2026-10-04

> In each directory along the path, it checks for `AGENTS.override.md`, then `AGENTS.md`, then any fallback names in `project_doc_fallback_filenames`. Codex includes at most one file per directory.

채택과 한계: startup context chain은 lazy skill loading과 별개다. HERMES.md/CLAUDE.md를 Codex 기본 context라고 가정하지 않는다.

## Claude Code 스킬과 도구 권한

- 공식 URL: https://code.claude.com/docs/en/skills.md
- 조회일: 2026-10-04

> Skills can include multiple files in their directory. This keeps `SKILL.md` focused on the essentials while letting Claude access detailed reference material only when needed.

> Enterprise over personal, and personal over project.

> It does not restrict which tools are available: every tool remains callable

채택과 한계: Claude adapter는 .claude/skills다. 개인/enterprise 동명이름과 permission을 확인한다. allowed-tools를 restrictive allowlist나 모든 도구의 일괄 사전승인으로 채택하지 않는다.

## Claude Code context 조건

- 공식 URL: https://code.claude.com/docs/en/memory.md
- 조회일: 2026-10-04

> Reading `AGENTS.md` directly requires Claude Code v2.1.277 or later.

> you can still keep it as the one file every tool shares by putting an `@AGENTS.md` import in a `CLAUDE.md` next to it.

채택과 한계: AGENTS 직접지원은 대상 버전·내장 기능/설정과 실제 CLAUDE context 존재에 따라 확인한다. 선택적 import/routing은 수동 opt-in이며 설치기가 기존 context를 수정하지 않는다.

## OKF 0.2 정본

- 공식 URL: https://raw.githubusercontent.com/GoogleCloudPlatform/open-knowledge-format/main/SPEC.md
- 조회일: 2026-10-04

> `type` is the only always-required key; a concept carrying just `type` is
> fully conformant (§11).

> **Extensions:** Producers MAY include any additional keys. Consumers
> SHOULD preserve unknown keys when round-tripping and MUST NOT reject
> documents with unrecognized fields.

> a bundle-relative path beginning with `/`, or

> Index files contain no frontmatter, with one exception: a bundle-root
> `index.md` MAY carry an `okf_version` key (§12).

> - Missing optional frontmatter fields.
> - Unknown `type` values.
> - Unknown additional frontmatter keys.
> - Broken cross-links.
> - Missing `index.md` files.

> All other `.md` files are concept documents.

채택과 한계: Version 0.2의 concept/type·unknown 보존·예약 index/log·bundle-root 경로·별도 품질 gate 원칙을 채택한다. sources의 descriptor를 실제 원문으로 위장하지 않으며 generated/verified/status는 제품 승인과 다르다.

## Hermes 전용 context 문서

- 공식 URL: https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files
- 조회일: 2026-10-04

> Only **one** project context type is loaded per session (first match wins): `.hermes.md` → `AGENTS.override.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`.

> Hermes loads a **merged chain** of `AGENTS.md` files at session start: the git-root `AGENTS.md` first, then the `AGENTS.md` in every intermediate directory down to your working directory.

채택과 한계: 수신 host의 native HERMES/.hermes context와 실제 선택 타입/로드 경로를 확인한다. 공식 문서만으로 실제 host load PASS를 주장하지 않는다.

## Hermes 문서 불일치

- 공식 URL: https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly
- 조회일: 2026-10-04

> | 2 | `AGENTS.md` | CWD only | Common agent instruction file |

채택과 한계: Prompt Assembly의 CWD-only 표와 전용 Context Files의 merged-chain 설명이 불일치한다. 버전/실제 loaded context 검증이 필요한 한계로 보존한다.

## Hermes configuration 교차 확인

- 공식 URL: https://hermes-agent.nousresearch.com/docs/user-guide/configuration
- 조회일: 2026-10-04

> *   **AGENTS.md** is hierarchical: if subdirectories also have AGENTS.md, all are combined.

채택과 한계: 이 요약도 hierarchy를 설명한다. 공식 페이지들 사이의 context 선택/범위 및 cap 설명 차이를 하나의 확정 runtime 동작으로 합치지 않는다.

## Codex sandbox와 승인

- 공식 URL: https://developers.openai.com/codex/sandboxing
- 조회일: 2026-10-04

> The sandbox applies to spawned commands, not just to built-in file operations.

> Approvals determine when Codex pauses before an action, while the sandbox determines which files and network resources commands can access.

채택과 한계: helper도 host sandbox/approval 경계 안에서 실행한다. full-access나 승인 우회를 배포 기본으로 넣지 않는다.

## 공통 비채택·검증 경계

전체 폴더 seed를 local adoption으로 제공한다. 단일 SKILL URL의 일부 support-file 복사와 전체 패키지 closure를 같다고 하지 않는다. host별 precedence·context·inline shell 의미를 universal 계약으로 합치지 않는다. daemon·hook·provider 설치·전역/profile 편집·자동 upstream 갱신·원문 자동 복사·일괄 도구 사전승인·제품 재실행은 기본 동작이 아니다.

실제 recipient 검증에서는 패키지 완전성 → 대상 helper 실행 → host 발견/정확한 경로 → 실제 skill load → 원문 회수를 나누어 확인한다. 이번 문서 근거 조회를 그 시험의 PASS로 재사용하지 않는다.
