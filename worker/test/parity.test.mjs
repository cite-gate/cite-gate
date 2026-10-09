// The JS checker must report exactly what the Python checker reports.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { checkTexts } from "../src/check.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const python = process.env.PYTHON || "python";
const fixtures = readdirSync(join(here, "fixtures")).filter((f) => f.endsWith(".json"));

function pythonReport(path) {
  const code =
    "import json,sys; sys.path.insert(0, sys.argv[1]); from cite_gate.check import check_texts; " +
    "d=json.load(open(sys.argv[2],encoding='utf-8')); " +
    "sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(check_texts(d['claims'], d['sources']).as_dict(), ensure_ascii=False))";
  return JSON.parse(execFileSync(python, ["-c", code, root, path], { encoding: "utf-8" }));
}

for (const name of fixtures) {
  test(`parity: ${name}`, () => {
    const path = join(here, "fixtures", name);
    const { claims, sources } = JSON.parse(readFileSync(path, "utf-8"));
    assert.deepEqual(checkTexts(claims, sources), pythonReport(path));
  });
}
