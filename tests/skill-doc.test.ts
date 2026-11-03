// 안내 문서 회귀 핀: 호스트 중립 명령·안내 연결·버전 일치·선택형 권고·설치 가드·수신자 고지
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { SEARCH_V32_KEYS } from "../src/contract.ts";

const read = (rel: string): string => fs.readFileSync(path.join(import.meta.dirname, "..", rel), "utf8");
const HOST_PATHS = [".claude/skills/wiki-desk", ".agents/skills/wiki-desk"];
const GUIDES = ["references/hosts.md", "references/upgrade.md", "references/recommendations.md"];

/** 마크다운의 ```bash 블록 본문들 */
const bashBlocks = (md: string): string[] => [...md.matchAll(/```bash\n([\s\S]*?)```/g)].map((m) => m[1]);

test("SKILL.md 명령 블록은 호스트 경로 대신 <skill-dir>를 쓰고, 호스트 표에 두 경로가 모두 있다", () => {
  const skill = read("SKILL.md");
  const blocks = bashBlocks(skill);
  assert.ok(blocks.length > 0);
  for (const b of blocks) {
    for (const p of HOST_PATHS) assert.ok(!b.includes(p), `명령 블록에 호스트 경로 ${p}`);
    assert.match(b, /node <skill-dir>\/src\/cli\.ts /);
  }
  for (const p of HOST_PATHS) assert.ok(skill.includes(p), `호스트 표에 ${p} 없음`);
});

test("SKILL.md는 호스트·업그레이드·선택 권고 안내로 연결되고 그 파일들이 있다", () => {
  const skill = read("SKILL.md");
  for (const g of GUIDES) {
    assert.ok(skill.includes(`(${g})`), `SKILL.md 링크 없음: ${g}`);
    assert.ok(fs.existsSync(path.join(import.meta.dirname, "..", g)), `파일 없음: ${g}`);
  }
});

test("SKILL.md metadata.version = package.json version", () => {
  const pkg = JSON.parse(read("package.json")) as { version: string };
  assert.match(read("SKILL.md"), new RegExp(`\\n  version: "${pkg.version.replaceAll(".", "\\.")}"\\n`));
});

test("업그레이드 안내의 누락 키 예시 값 = 계약 검증기의 안내 예시 값", () => {
  assert.match(read("references/upgrade.md"), new RegExp(`"match_lines_max": ${SEARCH_V32_KEYS.match_lines_max.example} `));
});

test("REC-01~03은 각 절에서 선택형으로 표기된다", () => {
  const sections = read("references/recommendations.md").split(/\n## /).slice(1);
  for (const id of ["REC-01", "REC-02", "REC-03"]) {
    const sec = sections.find((s) => s.startsWith(id));
    assert.ok(sec !== undefined, `${id} 절 없음`);
    assert.match(sec, /선택/, `${id}에 선택형 표기 없음`);
  }
});

test("hosts.md의 호스트별 설치 블록은 기존 스킬 폴더가 있으면 중단한다", () => {
  const blocks = bashBlocks(read("references/hosts.md")).filter((b) => b.includes("git -C \"$SOURCE\" archive"));
  for (const p of HOST_PATHS) {
    const b = blocks.find((x) => x.includes(`DEST="$PROJECT/${p}"`));
    assert.ok(b !== undefined, `설치 블록 없음: ${p}`);
    assert.match(b, /if \[ -e "\$DEST" \] \|\| \[ -L "\$DEST" \]; then[\s\S]*?exit 1/);
  }
});

test("README는 헌장 개정·폴더 신설 제안 문서의 위험을 배포 수신자에게 고지한다", () => {
  const readme = read("README.md");
  const m = readme.match(/\n## 배포 수신자 고지[^\n]*\n([\s\S]*?)\n## /);
  assert.ok(m !== null, "README 고지 절 없음");
  const notice = m[1];
  for (const s of ["references/recommendations.md", "references/charter.md", "건드리지 않", "승인", "git diff"]) {
    assert.ok(notice.includes(s), `고지 절에 '${s}' 없음`);
  }
  // 고지는 버전 줄 바로 다음 절이어야 한다(가장 먼저 읽히도록)
  assert.ok(readme.indexOf("## 배포 수신자 고지") < readme.indexOf("## 브랜치 안내"), "고지 절이 브랜치 안내보다 뒤에 있음");
});

test("업그레이드 백업은 스킬 탐색 경로 밖에 둔다(같은 이름 스킬 중복 발견 방지)", () => {
  for (const rel of ["references/upgrade.md", "README.md"]) {
    const doc = read(rel);
    assert.ok(!/<skill-dir>\.bak|…bak-/.test(doc), `${rel}: 백업을 스킬 폴더 옆(탐색 경로 안)에 두라는 안내`);
  }
  assert.match(read("references/upgrade.md"), /탐색 경로 밖/);
});
