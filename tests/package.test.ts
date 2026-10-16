// 배포 패키지 게이트: 위생 검사 0건 + PACKAGE_MANIFEST가 현재 트리와 일치
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_ROOT, FORBIDDEN_PATTERNS, scan } from "../scripts/sanitize-check.ts";
import { diff } from "../scripts/package-manifest.ts";

test("sanitize: 금지 패턴은 대표 사례를 잡고 중립 표현·문자열 이스케이프는 통과시킨다", () => {
  // 사례 문자열은 이 파일 자신이 트리 검사에 걸리지 않도록 조각으로 잇는다
  const hit = (s: string): string[] => Object.entries(FORBIDDEN_PATTERNS).filter(([, re]) => re.test(s)).map(([k]) => k);
  assert.deepEqual(hit("/ho" + "me/user/ws/x"), ["home_path"]);
  assert.deepEqual(hit("http://192." + "168.0.7:8000"), ["private_ip"]);
  assert.deepEqual(hit("12_" + "Example_Agent"), ["project_identifier"]);
  assert.deepEqual(hit("x" + "07_unknown: {}"), ["project_identifier"]);
  for (const ok of ["source_meta: {}", "\\x07", "plan_26090109_예시_설계.md", "10.5초", "v3.0.0"]) assert.deepEqual(hit(ok), [], ok);
});

test("sanitize: 패키지 트리에 금지 패턴 0건", () => {
  assert.deepEqual(scan(DEFAULT_ROOT), []);
});

test("manifest: PACKAGE_MANIFEST.json이 현재 트리와 일치", () => {
  assert.deepEqual(diff(DEFAULT_ROOT), []);
});
