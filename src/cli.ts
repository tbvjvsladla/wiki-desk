// wiki-desk CLI. 사용: node .claude/skills/wiki-desk/src/cli.ts <명령> [옵션]  — 출력은 JSON(stdout)
import { parseArgs } from "node:util";
import { initWiki, syncWiki, queryWiki, readRef, treeOf, checkWiki, statusWiki, removeWiki } from "./commands.ts";

const USAGE = `명령: init --contract <파일> [--apply] | sync [--apply] [--accept-removed P]... [--relocate OLD=NEW]...
      query --terms <질의>... [--limit N] | read <경로:시작-끝> | tree <경로> | check | status | remove [--apply]
공통: --root <프로젝트 루트>(생략 시 현재 디렉터리)`;

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    root: { type: "string" },
    contract: { type: "string" },
    apply: { type: "boolean", default: false },
    terms: { type: "string", multiple: true },
    limit: { type: "string" },
    "accept-removed": { type: "string", multiple: true },
    relocate: { type: "string", multiple: true },
  },
});

const [cmd, arg] = positionals;
const root = values.root ?? process.cwd();
const now = new Date().toISOString();
const need = (v: string | undefined, name: string): string => {
  if (v === undefined || v === "") throw new Error(`${name} 필요\n${USAGE}`);
  return v;
};
const pair = (s: string): [string, string] => {
  const i = s.indexOf("=");
  if (i <= 0 || i === s.length - 1) throw new Error(`--relocate 형식은 OLD=NEW: ${s}`);
  return [s.slice(0, i), s.slice(i + 1)];
};
const limit = values.limit === undefined ? undefined : Number(values.limit);
if (limit !== undefined && !(Number.isInteger(limit) && limit > 0)) throw new Error(`--limit는 양의 정수: ${values.limit}`);

const run: Record<string, () => unknown> = {
  init: () => initWiki(root, need(values.contract, "--contract"), { apply: values.apply, now }),
  sync: () => syncWiki(root, {
    apply: values.apply, now,
    acceptRemoved: values["accept-removed"] ?? [],
    relocate: (values.relocate ?? []).map(pair),
  }),
  query: () => queryWiki(root, values.terms ?? [], limit),
  read: () => readRef(root, need(arg, "<경로:시작-끝>")),
  tree: () => treeOf(root, need(arg, "<경로>")),
  check: () => checkWiki(root),
  status: () => statusWiki(root),
  remove: () => removeWiki(root, { apply: values.apply }),
};
const name = need(cmd, "<명령>");
// 상속 속성(toString·constructor 등)이 명령으로 잡히지 않게 자기 키만 허용
if (!Object.hasOwn(run, name)) throw new Error(`알 수 없는 명령: ${name}\n${USAGE}`);
const action = run[name];
const result = action();
process.stdout.write(JSON.stringify(result, null, 2) + "\n");
// check는 문제가 있으면 exit 1 (기계 판정용)
if (cmd === "check" && !(result as { ok: boolean }).ok) process.exitCode = 1;
