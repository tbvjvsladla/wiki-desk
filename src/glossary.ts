// 결정론 용어집: `<wiki_dir>/glossary.json`(선택 파일) 검증, 말뭉치 괄호 병기 쌍 추출, 질의 확장. 순수 함수.
//
// 파일이 없으면 호출자가 확장하지 않는다(no-op). 파일이 있으면 형식을 엄격히 검증하고 위반은 throw한다.
// 묶음(bundle) = 같은 개념의 표기 목록. 질의 term group에 한 표기가 토큰 단위로 들어 있으면
// 같은 묶음의 다른 표기를 추가 term group으로 붙인다(그룹 간 OR — queryTokens 규칙 그대로).
import { normalize, tokenize } from "./tokenize.ts";
import { scanLines } from "./tree.ts";

export const GLOSSARY_FILE = "glossary.json";
const SCHEMA_VERSION = 1;
const KEYS = ["schema_version", "auto_extract", "manual"] as const;
/** 한 묶음의 최소 표기 수(자기 자신 + 다른 표기 하나 이상) */
const MIN_BUNDLE = 2;

export type Glossary = { auto_extract: boolean; manual: string[][] };

/** init --apply가 만드는 기본 용어집: 자동 추출을 켜고 수동 묶음은 비운다(프로젝트가 필요하면 manual을 편집). */
export const DEFAULT_GLOSSARY = `${JSON.stringify({ schema_version: SCHEMA_VERSION, auto_extract: true, manual: [] })}\n`;

// 자동 추출 쌍에서 예시 괄호("서버(vLLM)"처럼 일반어 뒤에 예시를 단 괄호)를 걸러내는 기준.
// 값은 개발 분할에서 사전등록 격자로 고른다(plan_26102420 설계 §5.4) — 조정 대상이 아니라 고정 상수다.
/** 한글 쪽 최소 음절 수: 2음절 일반어(없음·서버·채점)는 예시 괄호가 대부분이다 */
export const MIN_KO_SYLLABLES = 3;
/** 한글 쪽이 말뭉치 문서의 이 비율보다 많이 나오면 일반어로 본다 */
export const DF_RATIO_MAX = 0.05;
/** 문서 빈도 판정의 하한: 이 문서 수 미만이면 비율과 무관하게 일반어로 보지 않는다(작은 말뭉치 보호) */
export const DF_FLOOR = 5;
export type CommonFilter = { minKoSyllables: number; dfRatioMax: number; dfFloor: number };
export const COMMON_FILTER: CommonFilter = { minKoSyllables: MIN_KO_SYLLABLES, dfRatioMax: DF_RATIO_MAX, dfFloor: DF_FLOOR };

// 괄호 병기 쌍. 괄호 바로 앞(공백 없이)에 붙은 표기와 괄호 안 표기가 서로 다른 문자 체계일 때만 쌍으로 본다.
// 영문 쪽은 글자·'_'·'-'만 허용한다: 숫자·'.'·'/'가 든 괄호(버전·모델명·경로·단계 번호)는 번역어가 아니라 예시다.
// 한글(English): 한글 2자 이상 + 영문 1~4단어
const KO_EN = /([가-힣]{2,})\(([A-Za-z][A-Za-z_-]+(?: [A-Za-z][A-Za-z_-]*){0,3})\)/g;
// English(한글): 단어 경계에서 시작하는 영문 2자 이상 + 한글 1~3어절
const EN_KO = /(?<![A-Za-z0-9_\-./])([A-Za-z][A-Za-z_-]+)\(([가-힣]{2,}(?: [가-힣]+){0,2})\)/g;

function fail(why: string): never {
  throw new Error(`glossary.json: ${why}`);
}

export function parseGlossary(text: string): Glossary {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    // 외부 입력 오류에 파일명을 붙여 다시 던진다(삼키지 않음).
    throw new Error(`glossary.json: JSON 문법 오류 — ${(err as Error).message}`, { cause: err });
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) fail("JSON 객체여야 한다");
  const obj = raw as Record<string, unknown>;
  for (const key of Object.keys(obj)) if (!(KEYS as readonly string[]).includes(key)) fail(`알 수 없는 키 ${key}`);
  if (obj["schema_version"] !== SCHEMA_VERSION) fail(`schema_version은 ${SCHEMA_VERSION}이어야 한다`);
  if (typeof obj["auto_extract"] !== "boolean") fail("auto_extract는 true/false여야 한다");
  const manual = obj["manual"];
  if (!Array.isArray(manual)) fail("manual은 목록이어야 한다");
  manual.forEach((bundle, i) => {
    if (!Array.isArray(bundle) || bundle.length < MIN_BUNDLE) fail(`manual[${i}]은 표기 ${MIN_BUNDLE}개 이상의 목록이어야 한다`);
    for (const v of bundle) if (typeof v !== "string" || v.trim() === "") fail(`manual[${i}]에 비어 있지 않은 문자열만 둔다`);
  });
  return { auto_extract: obj["auto_extract"] as boolean, manual: manual as string[][] };
}

/** 본문(펜스 코드·frontmatter 제외)의 괄호 병기 쌍. 정규화 기준으로 처음 나온 쌍만, 처음 표기 그대로. */
export function extractPairs(lines: string[], bodyStartLine: number): string[][] {
  const { kinds } = scanLines(lines, bodyStartLine);
  const seen = new Set<string>();
  const out: string[][] = [];
  const keep = (a: string, b: string): void => {
    const key = `${normalize(a)}\u0000${normalize(b)}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push([a, b]);
  };
  for (let i = 0; i < lines.length; i++) {
    const kind = kinds[i];
    if (kind === null || kind === "fence" || kind === "code") continue;
    for (const m of lines[i].matchAll(KO_EN)) keep(m[1], m[2]);
    for (const m of lines[i].matchAll(EN_KO)) keep(m[1], m[2]);
  }
  return out;
}

/**
 * 말뭉치 전체의 쌍에서 모호한 것을 버린다: 한 표기(정규화)가 둘 이상의 상대 표기와 짝지어지면 그 표기가 든 쌍은 모두 제외.
 * 괄호가 번역 대신 예시·설명으로 쓰인 경우("모델(…)"이 여러 이름과 짝)를 걸러낸다. 같은 쌍은 처음 표기로 합친다.
 */
export function filterUnambiguous(pairs: string[][]): string[][] {
  const partners = new Map<string, Set<string>>();
  const link = (a: string, b: string): void => {
    const set = partners.get(a) ?? new Set<string>();
    set.add(b);
    partners.set(a, set);
  };
  for (const [a, b] of pairs) {
    link(normalize(a), normalize(b));
    link(normalize(b), normalize(a));
  }
  const seen = new Set<string>();
  const out: string[][] = [];
  for (const [a, b] of pairs) {
    const na = normalize(a);
    const nb = normalize(b);
    if (partners.get(na)!.size > 1 || partners.get(nb)!.size > 1) continue;
    const key = `${na}\u0000${nb}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push([a, b]);
  }
  return out;
}

const HANGUL = /[가-힣]/;

/**
 * 일반어 쌍 제거(P4d). 쌍의 한글 쪽(한글이 든 표기)이 짧거나(음절 수 < minKoSyllables)
 * 말뭉치 문서 빈도가 하한·비율을 모두 넘으면 번역 쌍이 아니라 예시 괄호로 보고 버린다.
 * df: 한글 표기 → 그 표기가 나오는 문서 수, nDocs: 말뭉치 문서 수.
 */
export function filterCommon(pairs: string[][], df: (term: string) => number, nDocs: number, opt: CommonFilter = COMMON_FILTER): string[][] {
  return pairs.filter((pair) => {
    const ko = pair.find((v) => HANGUL.test(v));
    if (ko === undefined) return true;
    if ([...ko.replace(/\s+/g, "")].length < opt.minKoSyllables) return false;
    const n = df(ko);
    return !(n >= opt.dfFloor && n / nDocs > opt.dfRatioMax);
  });
}

/** term group 집합을 묶음으로 확장. 표기의 모든 토큰이 그룹 토큰에 있으면 일치로 본다(부분 문자열 우연 일치 배제). */
export function expandTerms(groups: string[], bundles: string[][]): { groups: string[]; added: string[] } {
  const groupTokens = groups.map((g) => new Set(tokenize(g)));
  const present = new Set(groups.map(normalize));
  const added: string[] = [];
  const matches = (variant: string): boolean => {
    const toks = tokenize(variant);
    return toks.length > 0 && groupTokens.some((set) => toks.every((t) => set.has(t)));
  };
  for (const bundle of bundles) {
    if (!bundle.some(matches)) continue;
    for (const v of bundle) {
      const key = normalize(v);
      // 질의가 이미 덮는 표기(일치한 표기 자신 포함)는 다시 붙이지 않는다
      if (present.has(key) || matches(v)) continue;
      present.add(key);
      added.push(v);
    }
  }
  return { groups: [...groups, ...added], added };
}
