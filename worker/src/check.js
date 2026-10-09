// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 MLPC Inc.
//
// JavaScript port of cite_gate/check.py for the hosted MCP endpoint (Cloudflare Workers).
// It must give the same failures and warnings as the Python checker; test/parity.test.mjs
// compares the two on the same inputs.

const COMMON = new Set(`I A An The And But Or So Then Now Here There This That These Those It Its In On At By For
From With Without Of To Into Onto Over Under After Before When While If As Even Some Most Many Much Few
Each Every All Both Either Neither No Not Nothing One Two Three Four Five Six Seven Eight Nine Ten You Your
We Our They Their He His She Her Him Them Let Imagine Picture Perhaps Maybe Somewhere Outside Inside
Today Yes Just Only Still Also Yet Above Below Down Up Out`.split(/\s+/));
const NUMWORD = /\b(hundred|thousand|million|billion)s?\b/i;
const MONTHS = /\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/g;
const ERA_PHRASE = /\b([A-Z][a-z]+) (?:era|period)\b/g;
const SAFE_SRC = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export const DEFAULTS = { copy_run: 11, min_quote_chars: 20, allow: [], fold_accents: false, era: null };

export function normalise(s) {
  s = s.replace(/’/g, "'").replace(/‘/g, "'").replace(/“/g, '"').replace(/”/g, '"');
  s = s.replace(/[–—−]/g, "-").replace(/​/g, "");
  return s.replace(/\s+/g, " ").trim();
}

export function fold(s) {
  return s.replace(/ı/g, "i").normalize("NFKD").replace(/\p{M}/gu, "");
}

export function numbers(s) {
  return new Set((s.match(/\d[\d,]*(?:\.\d+)?/g) || []).map((n) => n.replace(/,/g, "")));
}

export function longestSharedRun(text, quotes) {
  const a = normalise(text).toLowerCase().match(/[a-z0-9']+/g) || [];
  const b = quotes.toLowerCase().match(/[a-z0-9']+/g) || [];
  let best = 0;
  let prev = new Uint32Array(b.length + 1);
  for (const x of a) {
    const cur = new Uint32Array(b.length + 1);
    for (let j = 1; j <= b.length; j++) {
      if (x === b[j - 1]) {
        cur[j] = prev[j - 1] + 1;
        if (cur[j] > best) best = cur[j];
      }
    }
    prev = cur;
  }
  return best;
}

// Python repr() of a str, enough to keep messages identical to the Python checker.
export function pyRepr(s) {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = "";
  for (const ch of s) {
    if (ch === "\\") out += "\\\\";
    else if (ch === q) out += "\\" + q;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\r") out += "\\r";
    else out += ch;
  }
  return q + out + q;
}

function pyList(items) {
  return "[" + items.map(pyRepr).join(", ") + "]";
}

function pySorted(set) {
  return [...set].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));
}

// Python patterns may start with (?i); JS takes flags separately.
function pyRegex(pattern) {
  let flags = "";
  if (pattern.startsWith("(?i)")) {
    flags = "i";
    pattern = pattern.slice(4);
  }
  return new RegExp(pattern, flags);
}

function escapeClass(s) {
  return s.replace(/[\\\]\[^-]/g, "\\$&");
}

function eraIssues(text, qtext, allow, era) {
  const fails = [], warns = [];
  const letters = era.letters;
  if (letters) {
    const re = letters.startsWith("[") ? new RegExp(letters) : new RegExp(`[${escapeClass(letters)}]`);
    if (re.test(text)) warns.push("special letters in the prose; use the plain spelling");
  }
  const low = qtext.toLowerCase();
  for (const m of fold(text).matchAll(ERA_PHRASE)) {
    const name = m[1];
    if (!low.includes(name.toLowerCase()) && !allow.has(name)) fails.push(`'${name} era/period' is not in the quotes`);
  }
  if (!(era.months ?? true)) {
    for (const m of pySorted(new Set([...text.matchAll(MONTHS)].map((x) => x[1])))) {
      if (!low.includes(m.toLowerCase())) warns.push(`month name '${m}' is not in the quotes`);
    }
  }
  const name = era.name, tie = era.tie;
  if (name && tie && text.includes(name) && !pyRegex(tie).test(qtext)) {
    warns.push(`the prose says '${name}' but no quote ties this item to that era`);
  }
  return [fails, warns];
}

export function checkTexts(claims, sources) {
  const cfg = { ...DEFAULTS, ...(claims.config || {}) };
  const era = cfg.era;
  if (era !== null && era !== undefined && (typeof era !== "object" || Array.isArray(era))) {
    throw new Error('config.era must be an object like {"name": ..., "tie": ...}');
  }
  const folding = Boolean(cfg.fold_accents || era);
  const allow = new Set(cfg.allow);
  if (folding) for (const a of cfg.allow) allow.add(fold(a));
  const rep = { items: 0, words: 0, failures: [], warnings: [] };
  const fail = (item, message) => rep.failures.push({ item, message });
  const warn = (item, message) => rep.warnings.push({ item, message });
  const cache = new Map();

  for (const sec of claims.sections || []) {
    for (const it of sec.items || []) {
      rep.items += 1;
      const tag = String(it.id ?? rep.items);
      const text = it.text || "";
      rep.words += text.split(/\s+/).filter(Boolean).length;
      if (!it.claims || !it.claims.length) {
        fail(tag, "no claims");
        continue;
      }
      const quotes = [];
      for (const c of it.claims) {
        const src = String(c.src ?? "");
        if (!SAFE_SRC.test(src)) {
          fail(tag, `invalid source id ${pyRepr(src)} (letters, digits, '.', '_', '-' only)`);
          continue;
        }
        if (!cache.has(src)) {
          const raw = Object.prototype.hasOwnProperty.call(sources, src) ? sources[src] : null;
          cache.set(src, raw === null || raw === undefined ? null : normalise(String(raw)));
        }
        if (cache.get(src) === null) {
          fail(tag, `no source file for '${src}'`);
          continue;
        }
        const q = normalise(String(c.quote ?? ""));
        if ([...q].length < cfg.min_quote_chars) fail(tag, `quote too short: ${pyRepr(q)}`);
        else if (!cache.get(src).includes(q)) fail(tag, `quote not found in '${src}': ${pyRepr([...q].slice(0, 70).join(""))}`);
        quotes.push(q);
      }

      let qtext = quotes.join(" "), body = text;
      if (folding) {
        qtext = fold(qtext);
        body = fold(body);
      }
      if (era) {
        const [ef, ew] = eraIssues(text, qtext, allow, era);
        ef.forEach((x) => fail(tag, x));
        ew.forEach((x) => warn(tag, x));
      }
      const have = numbers(qtext);
      const missing = pySorted(new Set([...numbers(body)].filter((n) => !have.has(n))));
      if (missing.length) fail(tag, `number(s) ${pyList(missing)} not in the quotes`);
      if (NUMWORD.test(body) && !NUMWORD.test(qtext)) warn(tag, "quantity word (hundred/thousand/...) not in the quotes");
      const run = longestSharedRun(body, qtext);
      if (run >= cfg.copy_run) warn(tag, `${run} consecutive words shared with the quotes; retell, don't copy`);
      const low = qtext.toLowerCase();
      for (const sent of body.split(/(?<=[.!?])\s+/)) {
        const words = [...(" " + sent).matchAll(/(?<=\s)[A-Z][a-zA-Z']+/g)].map((m) => m[0]).slice(1);
        for (let w of words) {
          if (w.endsWith("'s")) w = w.slice(0, -2);
          const lw = w.toLowerCase();
          if (COMMON.has(w) || allow.has(w) || low.includes(lw) || low.includes(lw.replace(/s+$/, ""))) continue;
          warn(tag, `possible unsourced proper noun: ${w}`);
        }
      }
    }
  }
  return rep;
}

export function checkNumbers(text, quotes) {
  const have = numbers(quotes.map(String).join(" "));
  return pySorted(new Set([...numbers(text)].filter((n) => !have.has(n))));
}
