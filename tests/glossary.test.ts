import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_GLOSSARY, expandTerms, extractPairs, filterCommon, filterUnambiguous, parseGlossary } from "../src/glossary.ts";

const lines = (text: string): string[] => text.split("\n");

test("parseGlossary: 스키마 v1을 읽는다", () => {
  const g = parseGlossary(JSON.stringify({ schema_version: 1, auto_extract: true, manual: [["토크나이저", "tokenizer"]] }));
  assert.deepEqual(g, { auto_extract: true, manual: [["토크나이저", "tokenizer"]] });
});

test("parseGlossary: 형식 오류는 한국어 메시지로 거부", () => {
  const bad = [
    "not json",
    JSON.stringify([]),
    JSON.stringify({ auto_extract: true, manual: [] }),
    JSON.stringify({ schema_version: 2, auto_extract: true, manual: [] }),
    JSON.stringify({ schema_version: 1, auto_extract: "yes", manual: [] }),
    JSON.stringify({ schema_version: 1, auto_extract: true, manual: [["하나만"]] }),
    JSON.stringify({ schema_version: 1, auto_extract: true, manual: [["가나", " "]] }),
    JSON.stringify({ schema_version: 1, auto_extract: true, manual: [["가나", 3]] }),
    JSON.stringify({ schema_version: 1, auto_extract: true, manual: [], extra: 1 }),
  ];
  for (const text of bad) assert.throws(() => parseGlossary(text), /glossary/, text);
});

test("extractPairs: 한글 표기(English) 쌍", () => {
  assert.deepEqual(extractPairs(lines("토크나이저(tokenizer)는 bigram을 쓴다."), 1), [["토크나이저", "tokenizer"]]);
  assert.deepEqual(extractPairs(lines("저장 매체는 체크포인터(checkpointer)다"), 1), [["체크포인터", "checkpointer"]]);
});

test("extractPairs: English(한글 표기) 쌍", () => {
  assert.deepEqual(extractPairs(lines("reranker(재순위기)를 붙인다"), 1), [["reranker", "재순위기"]]);
  assert.deepEqual(extractPairs(lines("query_mode_surface(질의 표면)"), 1), [["query_mode_surface", "질의 표면"]]);
});

test("extractPairs: 짧거나 섞인 괄호·펜스 코드·frontmatter는 무시", () => {
  assert.deepEqual(extractPairs(lines("함수(f)와 표(참고)와 값(3)"), 1), []);
  assert.deepEqual(extractPairs(lines("설명(see docs, v2)"), 1), []);
  assert.deepEqual(extractPairs(lines("```\n토크나이저(tokenizer)\n```"), 1), []);
  assert.deepEqual(extractPairs(lines("---\ntitle: 토크나이저(tokenizer)\n---\n본문"), 4), []);
});

test("extractPairs: 괄호 안이 예시·버전·경로(숫자·'/'·'.' 포함)면 번역어가 아니므로 무시", () => {
  assert.deepEqual(extractPairs(lines("모델(Qwen3-4B)과 서빙(Phase 4)과 응답(gpt-5.6-terra)과 문서(ai.google.dev/docs)"), 1), []);
  assert.deepEqual(extractPairs(lines("Phase4(서빙)"), 1), []);
});

test("filterUnambiguous: 한 표기가 여러 상대와 짝지어진 쌍은 버리고, 같은 쌍은 합친다", () => {
  const pairs = [["모델", "model"], ["모델", "LLM"], ["토크나이저", "tokenizer"], ["토크나이저", "Tokenizer"], ["reranker", "재순위기"]];
  assert.deepEqual(filterUnambiguous(pairs), [["토크나이저", "tokenizer"], ["reranker", "재순위기"]]);
});

test("extractPairs: 같은 쌍은 한 번만", () => {
  assert.deepEqual(extractPairs(lines("토크나이저(tokenizer)\n다시 토크나이저(Tokenizer)"), 1), [["토크나이저", "tokenizer"]]);
});

test("expandTerms: 묶음의 한 표기가 질의에 있으면 다른 표기를 추가 그룹으로", () => {
  const r = expandTerms(["tokenizer 설정"], [["토크나이저", "tokenizer"]]);
  assert.deepEqual(r, { groups: ["tokenizer 설정", "토크나이저"], added: ["토크나이저"] });
});

test("expandTerms: 일치하지 않으면 그대로, 이미 있는 표기는 중복 추가하지 않는다", () => {
  assert.deepEqual(expandTerms(["멀티턴"], [["토크나이저", "tokenizer"]]), { groups: ["멀티턴"], added: [] });
  assert.deepEqual(expandTerms(["토크나이저", "tokenizer"], [["토크나이저", "tokenizer"]]), { groups: ["토크나이저", "tokenizer"], added: [] });
});

test("expandTerms: 토큰 단위 일치(부분 문자열 우연 일치는 확장하지 않음)", () => {
  assert.deepEqual(expandTerms(["rapid 처리"], [["에이피아이", "api"]]).added, []);
  assert.deepEqual(expandTerms(["API 키"], [["에이피아이", "api"]]).added, ["에이피아이"]);
});

// P4d: 예시 괄호(일반어(식별자)) 걸러내기 — 한글 쪽이 너무 짧거나 말뭉치 대부분에 나오는 일반어면 번역 쌍이 아니다
test("filterCommon: 한글 쪽이 최소 음절 수보다 짧은 쌍은 버린다", () => {
  const df = (): number => 0;
  assert.deepEqual(filterCommon([["없음", "Unlimited"], ["토크나이저", "tokenizer"]], df, 100, { minKoSyllables: 3, dfRatioMax: 0.1, dfFloor: 5 }),
    [["토크나이저", "tokenizer"]]);
});

test("filterCommon: 한글 쪽이 문서 빈도 상한(비율·하한 모두 초과)을 넘는 일반어면 버린다", () => {
  const df = (t: string): number => ({ 스키마: 40, 토크나이저: 4 } as Record<string, number>)[t] ?? 0;
  const opt = { minKoSyllables: 2, dfRatioMax: 0.1, dfFloor: 5 };
  assert.deepEqual(filterCommon([["스키마", "docling"], ["토크나이저", "tokenizer"]], df, 100, opt), [["토크나이저", "tokenizer"]]);
  // 영어가 앞에 온 쌍도 한글 쪽으로 판정
  assert.deepEqual(filterCommon([["docling", "스키마"]], df, 100, opt), []);
});

test("filterCommon: 작은 말뭉치에서는 문서 수 하한 아래면 비율이 높아도 남긴다", () => {
  const df = (): number => 2;
  assert.deepEqual(filterCommon([["토크나이저", "tokenizer"]], df, 3, { minKoSyllables: 2, dfRatioMax: 0.1, dfFloor: 5 }), [["토크나이저", "tokenizer"]]);
});

test("DEFAULT_GLOSSARY: init이 쓰는 기본 용어집은 스키마 v1이고 자동 추출을 켠다", () => {
  assert.deepEqual(parseGlossary(DEFAULT_GLOSSARY), { auto_extract: true, manual: [] });
});

test("assets/glossary.example.json은 init 기본 용어집과 바이트가 같다(측정 = 출하)", async () => {
  const fs = await import("node:fs");
  const path = await import("node:path");
  assert.equal(fs.readFileSync(path.join(import.meta.dirname, "..", "assets", "glossary.example.json"), "utf8"), DEFAULT_GLOSSARY);
});
