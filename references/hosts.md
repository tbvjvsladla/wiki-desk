# 호스트별 안내 — Claude Code · Codex

wiki-desk의 CLI·계약·위키 형식은 호스트와 무관하게 같다. 호스트마다 다른 것은 **스킬 폴더 위치·발견·호출·권한** 네 가지뿐이다. 이 문서는 그 차이만 다룬다. 공통 동작은 [SKILL.md](../SKILL.md)·[installation.md](installation.md)가 정본이다.

## 한눈에 보기
| 항목 | Claude Code | Codex |
|---|---|---|
| 스킬 폴더(`<skill-dir>`) | `<프로젝트>/.claude/skills/wiki-desk/` | `<프로젝트>/.agents/skills/wiki-desk/` |
| 발견 | 프로젝트 스킬 목록에 `wiki-desk` | 저장소의 `.agents/skills`에서 `SKILL.md`의 `name`·`description`으로 발견 |
| 명시 호출 | 스킬 이름 `wiki-desk`(예: `/wiki-desk`) | `$wiki-desk` |
| 자동 선택 | `description`과 호스트 정책에 따름 — 매 요청 선택을 보장하지 않음 | 같음 |
| 명령 실행 위치 | 프로젝트 루트 | 프로젝트 루트(Codex를 프로젝트 루트에서 시작) |
| 권한 | 프로젝트가 정한 명령 허용 규칙 | 세션의 sandbox·승인 정책 |

한 프로젝트에 두 호스트를 함께 쓸 수 있다. 그때 스킬 폴더는 호스트마다 하나씩 두고(같은 배포 버전), 위키(`__llm-wiki/`)는 프로젝트 루트에 **하나만** 둔다. 한 호스트를 지원하려고 다른 호스트의 설정 파일을 만들거나 고치지 않는다.

## 설치 — 스킬 폴더만 만든다
- 설치는 `<skill-dir>` 폴더 하나를 만들고 배포 태그를 풀어 넣는 일이다. `docs/`·`AGENTS.md`·`CLAUDE.md`·작업 규칙·위키·hook·cron·전역/profile 설정은 **만들지도 고치지도 않는다**.
- 아래 블록은 대상 스킬 폴더가 이미 있으면 아무것도 쓰지 않고 멈춘다(exit 1). 이 검사는 **스킬 폴더 한 곳만** 본다. 이미 설치돼 있다면 [업그레이드](upgrade.md) 절차를 따른다.
- 준비물: Node.js 24 이상, 이 저장소의 git clone(`SOURCE`). Node가 없으면 차단 사유를 보고하고 자동 설치하지 않는다.

### Claude Code
```bash
(
  set -euo pipefail
  SOURCE="/absolute/path/to/wiki-desk"     # 이 저장소를 받은 폴더(git clone)
  VERSION="v3.3.0"
  PROJECT="/absolute/path/to/project"      # 설치할 프로젝트 루트
  DEST="$PROJECT/.claude/skills/wiki-desk"
  if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    printf '중단: 기존 스킬을 보존합니다: %s (업그레이드는 references/upgrade.md)\n' "$DEST" >&2
    exit 1
  fi
  mkdir -p "$DEST"
  git -C "$SOURCE" archive "$VERSION" | tar -x -C "$DEST"
  cd "$DEST"
  node scripts/package-manifest.ts --check   # 파일 집합·sha256 대조
  node --test
)
```

### Codex
```bash
(
  set -euo pipefail
  SOURCE="/absolute/path/to/wiki-desk"     # 이 저장소를 받은 폴더(git clone)
  VERSION="v3.3.0"
  PROJECT="/absolute/path/to/project"      # 설치할 프로젝트 루트
  DEST="$PROJECT/.agents/skills/wiki-desk"
  if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    printf '중단: 기존 스킬을 보존합니다: %s (업그레이드는 references/upgrade.md)\n' "$DEST" >&2
    exit 1
  fi
  mkdir -p "$DEST"
  git -C "$SOURCE" archive "$VERSION" | tar -x -C "$DEST"
  cd "$DEST"
  node scripts/package-manifest.ts --check   # 파일 집합·sha256 대조
  node --test
)
```

기존 동명 폴더가 있어 멈췄다면, 그 폴더 `SKILL.md`의 `metadata.version`을 보고하고 사용자에게 업그레이드·중단 중 무엇을 할지 묻는다. 묻지 않고 지우거나 덮어쓰지 않는다.

## 권한
- **Claude Code**: 서브에이전트가 CLI를 쓰게 하려면 프로젝트가 명령 허용 규칙을 둘 수 있다(예: `Bash(node .claude/skills/wiki-desk/src/cli.ts:*)`). 이 규칙은 명령 문자열 앞부분으로 맞춰지므로 SKILL.md의 명령을 한 줄씩 그대로 실행한다. 규칙 추가는 프로젝트 소유자의 결정이며 설치가 대신 넣지 않는다.
- **Codex**: 세션의 sandbox·승인 정책을 그대로 따른다. 막히면 차단 사실을 보고하고 정책을 임의로 완화하지 않는다.

명령별 쓰기 범위(호스트 공통):

| 명령 | 쓰기 |
|---|---|
| `read`·`tree`·`status`·`check`·`sync`(계획)·`init`(계획)·`remove`(계획) | 없음 — 쓰기 금지 환경에서도 동작 |
| `query` | 색인 캐시(`<wiki_dir>/<cache_dir>/`)가 없거나 원문보다 오래되면 캐시를 다시 쓴다. 쓰기 금지 환경에서는 캐시가 최신일 때만 동작하고, 아니면 접근 오류로 멈춘다. 캐시는 파생물이며 원문·카드는 쓰지 않는다 |
| `init --apply`·`sync --apply`·`remove --apply` | 위키 파일(계약·receipt·카드·index·log). 프로젝트 쓰기가 허용된 세션에서만 실행한다 |

## 다른 디렉터리에서 실행할 때
CLI는 `--root`가 없으면 **현재 디렉터리**를 프로젝트 루트로 본다. 프로젝트 루트가 아닌 곳(스킬 폴더 안 포함)에서 실행하면 그 위치를 프로젝트로 오인한다. 그러므로 다른 위치에서는 세 가지를 모두 절대경로로 준다.

```bash
node /abs/project/.agents/skills/wiki-desk/src/cli.ts status --root /abs/project
node /abs/project/.agents/skills/wiki-desk/src/cli.ts init --contract /abs/path/contract.json --root /abs/project
node /abs/project/.agents/skills/wiki-desk/src/cli.ts query --terms "질의할 개념" --with-text --limit 5 --root /abs/project
```

- `init --contract <파일>`의 상대경로는 **명령을 실행한 디렉터리** 기준으로 풀린다(`--root` 기준이 아니다). 헷갈리면 절대경로를 쓴다.
- `read`·`tree`의 원문 경로는 `--root` 기준 상대경로다.

## 인식 확인 — CLI 성공과 따로 본다
파일 존재·`node --test`·`status` 성공은 호스트가 스킬을 **읽었다는 증거가 아니다**. 새 세션에서 따로 확인한다.
- Claude Code: 새 세션의 스킬 목록에 `wiki-desk`가 보이는가, 명시 호출 시 SKILL.md 지침(질의 루프)을 따르는가.
- Codex: 프로젝트 루트에서 시작한 새 세션에서 `$wiki-desk`로 호출했을 때 SKILL.md 지침을 읽고 `<skill-dir>` 명령을 실행하는가. 예: `codex exec "\$wiki-desk 로 status 를 실행하고 SKILL.md 의 질의 루프 첫 단계를 그대로 인용해줘"`.

## 보고할 네 상태
설치 결과는 아래 네 상태를 **따로** 보고한다. 확인하지 않은 상태를 성공으로 합치지 않는다.

| 상태 | 확인 방법 | 예 |
|---|---|---|
| 1. 패키지 설치 | 설치 블록 exit 0(manifest·테스트 통과) | 성공 / 기존 폴더 보존으로 중단 |
| 2. 호스트 발견·로드 | 위 인식 확인 | 확인 / 미확인(NOT_RUN) |
| 3. 계약 준비 | `<wiki_dir>/contract.json` 존재·`check` 실행 가능 | 계약 없음은 **설치 실패가 아니다** — 문서 범위를 합의하기 전 정상 상태 |
| 4. 입고·질의 | `sync --apply` 뒤 `check` ok, `query`→`read` 회수 | 성공 / 미실행 |

계약이 없으면 `status`·`check`·`query` 등 데이터 명령은 `계약 파일은 정확히 하나여야 한다(__llm-wiki, __llm_wiki): 발견 0개` 오류로 멈춘다. 이는 상태 3이 아직 아니라는 신호이며 설치 실패가 아니다. 상태 1·2와 구분해 보고한다.
