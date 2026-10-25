import { test } from "node:test";
import assert from "node:assert/strict";
import { buildLinkIndex, extractCycleIds, extractDocRefs, extractIdentifiers, relatedFor, type LinkDoc } from "../src/links.ts";

test("extractIdentifiers: 백틱 토큰과 구분자(. _ -)가 든 영문 식별자, 일반 단어는 제외", () => {
  const ids = extractIdentifiers(["`persist_dir` 값은 vectorstore.faiss 블록에 있다.", "임베딩 모델 gemini-embedding-2 와 plain word"]);
  assert.deepEqual([...ids].sort(), ["gemini-embedding-2", "persist_dir", "vectorstore.faiss"]);
});

test("extractIdentifiers: 경로·URL·너무 짧거나 긴 백틱은 식별자가 아니다", () => {
  const ids = extractIdentifiers(["`a` `docs/plan/x.md` https://x.io/a_b `" + "x".repeat(80) + "`"]);
  assert.deepEqual([...ids], []);
});

test("extractCycleIds: seed·interview ID", () => {
  assert.deepEqual([...extractCycleIds(["ouroboros_seed_id: seed_563b79554c12", "interview_20261023_170810 참고"])].sort(),
    ["interview_20261023_170810", "seed_563b79554c12"]);
});

test("extractDocRefs: 저장소 상대 경로와 파일명 줄기(prefix_YYMMDDHH)로 다른 문서를 가리킨다", () => {
  const paths = ["docs/plan/plan_26072715_파서_설계.md", "docs/plan/plan_26072715_파서_구현.md", "docs/devlog/devlog_26072800_마감.md"];
  const refs = extractDocRefs(["근거: docs/devlog/devlog_26072800_마감.md 와 plan_26072715 참조"], paths, "docs/x/self.md");
  assert.deepEqual([...refs].sort(), [...paths].sort());
});

const doc = (path: string, date: string | null, title: string, lines: string[]): LinkDoc => ({ path, date, title, lines });
const DOCS: LinkDoc[] = [
  doc("docs/plan/plan_26052418_설계.md", "26052418", "설계", ["`persist_dir`: data/vectorstore/faiss", "ouroboros_seed_id: seed_aaaaaaaaaaaa"]),
  doc("docs/devlog/devlog_26060100_교체.md", "26060100", "교체", ["persist_dir 는 inert 키로 판명, index_cache 로 대체"]),
  doc("docs/devlog/devlog_26040100_이전.md", "26040100", "이전", ["persist_dir 첫 도입"]),
  doc("docs/request/request_26052420_요청.md", "26052420", "요청", ["plan_26052418 검토 요청"]),
  doc("docs/interview/interview_26052417_인터뷰.md", "26052417", "인터뷰", ["seed: seed_aaaaaaaaaaaa"]),
  doc("docs/misc/무관.md", null, "무관", ["다른 이야기"]),
];

test("relatedFor: 같은 식별자를 다룬 이후 문서, 참조·피참조, 같은 사이클을 이유와 함께", () => {
  const idx = buildLinkIndex(DOCS);
  const rel = relatedFor(idx, [{ path: "docs/plan/plan_26052418_설계.md", spanLines: ["`persist_dir`: data/vectorstore/faiss"] }], 10);
  const by = new Map(rel.map((r) => [r.path, r.reason]));
  assert.equal(by.get("docs/devlog/devlog_26060100_교체.md"), "later_same_identifier");
  assert.equal(by.has("docs/devlog/devlog_26040100_이전.md"), false, "이전 날짜 문서는 '이후'가 아니다");
  assert.equal(by.get("docs/request/request_26052420_요청.md"), "referred_by");
  assert.equal(by.get("docs/interview/interview_26052417_인터뷰.md"), "same_cycle");
  assert.equal(by.has("docs/misc/무관.md"), false);
  const later = rel.find((r) => r.reason === "later_same_identifier")!;
  assert.deepEqual(later.shared, ["persist_dir"]);
  assert.equal(later.via, "docs/plan/plan_26052418_설계.md");
});

test("relatedFor: 결과에 이미 있는 문서는 빼고, max로 자르며, 0이면 빈 목록", () => {
  const idx = buildLinkIndex(DOCS);
  const hits = [{ path: "docs/plan/plan_26052418_설계.md", spanLines: ["`persist_dir`"] }, { path: "docs/devlog/devlog_26060100_교체.md", spanLines: [] }];
  const rel = relatedFor(idx, hits, 10);
  assert.equal(rel.some((r) => r.path === "docs/devlog/devlog_26060100_교체.md"), false);
  assert.equal(relatedFor(idx, hits, 1).length, 1);
  assert.deepEqual(relatedFor(idx, hits, 0), []);
});

test("buildLinkIndex: 말뭉치 대부분에 나오는 흔한 식별자는 연결에 쓰지 않는다", () => {
  const many: LinkDoc[] = Array.from({ length: 20 }, (_, i) => doc(`docs/d/devlog_260601${String(i).padStart(2, "0")}_x.md`, `260601${String(i).padStart(2, "0")}`, "x", ["`app.serve` 기동"]));
  const idx = buildLinkIndex(many);
  assert.deepEqual(relatedFor(idx, [{ path: many[0].path, spanLines: ["`app.serve`"] }], 10).filter((r) => r.reason === "later_same_identifier"), []);
});

test("relatedFor: 질의 토큰과 같은 식별자가 구간에 있으면 그 식별자로만 이후 문서를 고른다(흔한 공통 식별자 잡음 억제)", () => {
  const docs: LinkDoc[] = [
    doc("docs/plan/plan_26050100_a.md", "26050100", "a", ["`persist_dir` 와 `api_key` 설정"]),
    doc("docs/devlog/devlog_26050200_b.md", "26050200", "b", ["persist_dir 교체"]),
    doc("docs/devlog/devlog_26050300_c.md", "26050300", "c", ["api_key 갱신"]),
  ];
  const idx = buildLinkIndex(docs);
  const hit = [{ path: docs[0].path, spanLines: docs[0].lines }];
  const scoped = relatedFor(idx, hit, 10, ["persist_dir"]).filter((r) => r.reason === "later_same_identifier").map((r) => r.path);
  assert.deepEqual(scoped, ["docs/devlog/devlog_26050200_b.md"]);
  const all = relatedFor(idx, hit, 10, ["설정"]).filter((r) => r.reason === "later_same_identifier").map((r) => r.path).sort();
  assert.deepEqual(all, ["docs/devlog/devlog_26050200_b.md", "docs/devlog/devlog_26050300_c.md"]);
});
