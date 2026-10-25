// 결정론 문서 연결(P2a 식별자 등장 색인 + P2b 명시 참조 그래프). 순수 함수. LLM·입고 변경 없음.
//
// query 결과마다 "같은 식별자를 다룬 이후 문서·참조하는/받는 문서·같은 사이클 문서"를 별도 칸(related)으로 알려 준다.
// 순위는 바꾸지 않는다 — 에이전트가 '당시 값 → 이후 값'이나 두 번째 근거 문서를 스스로 찾지 않아도 되게 하는 안내다.
// 연결은 원문에서 매 질의 다시 계산한다(카드 형식 불변, 원문 외 저장 없음).

/** 연결 계산 입력 1건. date = 파일명 YYMMDDHH(없으면 null) */
export type LinkDoc = { path: string; date: string | null; title: string; lines: string[] };
export type RelatedReason = "later_same_identifier" | "refers_to" | "referred_by" | "same_cycle";
export type Related = { path: string; date: string | null; title: string; reason: RelatedReason; via: string; shared?: string[] };
export type LinkIndex = {
  docs: Map<string, LinkDoc>;
  ids: Map<string, Set<string>>;
  /** 연결에 쓰는 식별자(문서 빈도가 2 이상이고 흔하지 않은 것) → 등장 문서 */
  idDocs: Map<string, Set<string>>;
  refsOut: Map<string, Set<string>>;
  refsIn: Map<string, Set<string>>;
  cycleDocs: Map<string, Set<string>>;
  docCycles: Map<string, Set<string>>;
};

// 식별자 길이 범위: 2글자 이하는 우연 일치, 60자 초과는 문장·해시 조각
const ID_MIN_LEN = 3;
const ID_MAX_LEN = 60;
// 흔한 식별자 제외: 문서 수가 하한을 넘고 말뭉치의 이 비율보다 많이 나오면 연결 신호가 아니다(frontmatter 키·공통 명령 등)
const ID_DF_RATIO_MAX = 0.2;
const ID_DF_FLOOR = 5;
/** 이후 문서 항목에 보여 줄 공유 식별자 최대 수(출력 길이 억제) */
const SHARED_SHOWN = 3;
const REASON_ORDER: RelatedReason[] = ["later_same_identifier", "refers_to", "referred_by", "same_cycle"];

const BACKTICK = /`([^`\s]+)`/g;
// 구분자(. _ -)가 하나 이상 든 영문 시작 식별자. 앞뒤가 경로(/)·단어 문자면 제외(경로·URL 조각)
const BARE_ID = /(?<![A-Za-z0-9_./\-])([A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)+)(?![A-Za-z0-9_/])/g;
const CYCLE_ID = /(?<![A-Za-z0-9_])(seed_[0-9a-f]{12}|interview_\d{8}_\d{6})(?![A-Za-z0-9])/g;
// 문서 파일명 줄기: prefix_YYMMDDHH (예: plan_26072715)
const DOC_STEM = /(?<![A-Za-z0-9])([a-z][a-z_]*_\d{8})(?![0-9])/g;
const LETTER = /[A-Za-z]/;

/** 문서 줄기·사이클 ID는 식별자가 아니라 따로 다루는 참조다 */
const isReferenceToken = (t: string): boolean => /^[a-z][a-z_]*_\d{8}$/.test(t) || /^(seed_[0-9a-f]{12}|interview_\d{8}_\d{6})$/.test(t);

function keepId(raw: string): string | null {
  const t = raw.replace(/[.,:;]+$/, "").toLowerCase();
  if (t.length < ID_MIN_LEN || t.length > ID_MAX_LEN || !LETTER.test(t)) return null;
  if (t.includes("/") || t.includes("://") || isReferenceToken(t)) return null;
  return t;
}

export function extractIdentifiers(lines: string[]): Set<string> {
  const out = new Set<string>();
  for (const line of lines) {
    for (const m of line.matchAll(BACKTICK)) {
      const t = keepId(m[1]);
      if (t !== null) out.add(t);
    }
    for (const m of line.matchAll(BARE_ID)) {
      const t = keepId(m[1]);
      if (t !== null) out.add(t);
    }
  }
  return out;
}

export function extractCycleIds(lines: string[]): Set<string> {
  const out = new Set<string>();
  for (const line of lines) for (const m of line.matchAll(CYCLE_ID)) out.add(m[1]);
  return out;
}

const basename = (p: string): string => p.slice(p.lastIndexOf("/") + 1);

function stemMap(paths: string[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const p of paths) {
    const m = /^([a-z][a-z_]*_\d{8})(?:_|\.md$)/.exec(basename(p));
    if (m === null) continue;
    const list = out.get(m[1]);
    if (list === undefined) out.set(m[1], [p]);
    else list.push(p);
  }
  return out;
}

function docRefs(lines: string[], paths: string[], stems: Map<string, string[]>, self: string): Set<string> {
  const text = lines.join("\n");
  const out = new Set<string>();
  for (const p of paths) if (p !== self && text.includes(p)) out.add(p);
  for (const m of text.matchAll(DOC_STEM)) for (const p of stems.get(m[1]) ?? []) if (p !== self) out.add(p);
  return out;
}

/** 본문이 가리키는 다른 문서: 저장소 상대 경로 그대로, 또는 파일명 줄기(prefix_YYMMDDHH) */
export function extractDocRefs(lines: string[], paths: string[], self: string): Set<string> {
  return docRefs(lines, paths, stemMap(paths), self);
}

const push = (m: Map<string, Set<string>>, k: string, v: string): void => {
  const s = m.get(k);
  if (s === undefined) m.set(k, new Set([v]));
  else s.add(v);
};

export function buildLinkIndex(docs: LinkDoc[]): LinkIndex {
  const paths = docs.map((d) => d.path);
  const stems = stemMap(paths);
  const ids = new Map<string, Set<string>>();
  const allIdDocs = new Map<string, Set<string>>();
  const refsOut = new Map<string, Set<string>>();
  const refsIn = new Map<string, Set<string>>();
  const cycleDocs = new Map<string, Set<string>>();
  const docCycles = new Map<string, Set<string>>();
  for (const d of docs) {
    const own = extractIdentifiers(d.lines);
    ids.set(d.path, own);
    for (const t of own) push(allIdDocs, t, d.path);
    const refs = docRefs(d.lines, paths, stems, d.path);
    refsOut.set(d.path, refs);
    for (const r of refs) push(refsIn, r, d.path);
    const cycles = extractCycleIds(d.lines);
    docCycles.set(d.path, cycles);
    for (const c of cycles) push(cycleDocs, c, d.path);
  }
  const idDocs = new Map<string, Set<string>>();
  for (const [t, set] of allIdDocs) {
    const common = set.size > ID_DF_FLOOR && set.size / docs.length > ID_DF_RATIO_MAX;
    if (set.size >= 2 && !common) idDocs.set(t, set);
  }
  return { docs: new Map(docs.map((d) => [d.path, d])), ids, idDocs, refsOut, refsIn, cycleDocs, docCycles };
}

/**
 * 결과 문서들의 관련 문서(최대 max개). 이유 우선순위: 이후 같은 식별자 → 참조 → 피참조 → 같은 사이클.
 * 이후 문서는 결과의 근거 구간(spanLines)에 나온 식별자를 공유하고 날짜가 더 늦은 문서만, 공유 식별자 수·최신순.
 * 구간 식별자 중 질의 토큰과 같은 것이 있으면 그것만 쓴다(질의 대상과 무관한 공통 설정 키로 엮이지 않게).
 * 결과에 이미 있는 문서는 넣지 않는다.
 */
export function relatedFor(idx: LinkIndex, hits: { path: string; spanLines: string[] }[], max: number, queryTokens: string[] = []): Related[] {
  const asked = new Set(queryTokens);
  if (max === 0) return [];
  const inResults = new Set(hits.map((h) => h.path));
  const byReason = new Map<RelatedReason, Related[]>(REASON_ORDER.map((r) => [r, []]));
  const item = (path: string, reason: RelatedReason, via: string, shared?: string[]): Related => {
    const d = idx.docs.get(path)!;
    return { path, date: d.date, title: d.title, reason, via, ...(shared === undefined ? {} : { shared }) };
  };
  for (const h of hits) {
    const self = idx.docs.get(h.path);
    if (self === undefined) continue;
    if (self.date !== null) {
      const own = idx.ids.get(h.path)!;
      const usable = [...extractIdentifiers(h.spanLines)].filter((t) => own.has(t) && idx.idDocs.has(t));
      const askedIds = usable.filter((t) => asked.has(t));
      const spanIds = askedIds.length > 0 ? askedIds : usable;
      const later = new Map<string, string[]>();
      for (const t of spanIds) {
        for (const p of idx.idDocs.get(t)!) {
          const d = idx.docs.get(p)!;
          if (p === h.path || d.date === null || d.date <= self.date) continue;
          later.set(p, [...(later.get(p) ?? []), t]);
        }
      }
      const ordered = [...later].sort(([pa, sa], [pb, sb]) => sb.length - sa.length || (idx.docs.get(pb)!.date! < idx.docs.get(pa)!.date! ? -1 : 1));
      for (const [p, shared] of ordered) byReason.get("later_same_identifier")!.push(item(p, "later_same_identifier", h.path, shared.sort().slice(0, SHARED_SHOWN)));
    }
    for (const p of [...(idx.refsOut.get(h.path) ?? [])].sort()) byReason.get("refers_to")!.push(item(p, "refers_to", h.path));
    for (const p of [...(idx.refsIn.get(h.path) ?? [])].sort()) byReason.get("referred_by")!.push(item(p, "referred_by", h.path));
    const cycle = new Set<string>();
    for (const c of idx.docCycles.get(h.path) ?? []) for (const p of idx.cycleDocs.get(c) ?? []) if (p !== h.path) cycle.add(p);
    for (const p of [...cycle].sort()) byReason.get("same_cycle")!.push(item(p, "same_cycle", h.path));
  }
  const seen = new Set<string>();
  const out: Related[] = [];
  for (const r of REASON_ORDER) {
    for (const it of byReason.get(r)!) {
      if (inResults.has(it.path) || seen.has(it.path)) continue;
      seen.add(it.path);
      out.push(it);
      if (out.length === max) return out;
    }
  }
  return out;
}
