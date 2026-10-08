# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 MLPC Inc.
"""Core checks.

Input is a claims file (JSON) plus a directory of plain-text sources:

    {"config": {...optional...},
     "sections": [
       {"title": "Opening",
        "items": [
          {"id": "1",
           "text": "The prose a reader or narrator will see.",
           "claims": [{"src": "speech", "quote": "words copied exactly from sources/speech.txt"}]}
        ]}
     ]}

Failures (exit code 1):
  * a quote that is not found in its source file (after normalising quotes, dashes and spaces)
  * a quote shorter than `min_quote_chars`
  * a `src` id that has no file, or that is not a plain name
  * a number in the prose that does not appear in that item's quotes

Warnings (exit code 0 unless --strict):
  * quantity words (hundred, thousand, ...) in the prose but not in the quotes
  * a capitalised word mid-sentence that is not in the quotes (possible unsourced proper noun)
  * a run of `copy_run` or more consecutive words shared with the quotes (copying, not retelling)
  * optional era rule: the prose names the era but the quotes carry no tie to it, month names
    the quotes do not use, "X era/period" phrases not in the quotes, special letters in the prose
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Words that are capitalised at sentence starts or are too common to signal a proper noun.
COMMON = set("""I A An The And But Or So Then Now Here There This That These Those It Its In On At By For
From With Without Of To Into Onto Over Under After Before When While If As Even Some Most Many Much Few
Each Every All Both Either Neither No Not Nothing One Two Three Four Five Six Seven Eight Nine Ten You Your
We Our They Their He His She Her Him Them Let Imagine Picture Perhaps Maybe Somewhere Outside Inside
Today Yes Just Only Still Also Yet Above Below Down Up Out""".split())
NUMWORD = re.compile(r"\b(hundred|thousand|million|billion)s?\b", re.I)
MONTHS = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November"
                    r"|December)\b")
ERA_PHRASE = re.compile(r"\b([A-Z][a-z]+) (?:era|period)\b")
SAFE_SRC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

DEFAULTS = {
    "copy_run": 11,          # 9-10 shared words occur legitimately in lists; 11+ reads as copying
    "min_quote_chars": 20,
    "allow": [],             # proper nouns always accepted (e.g. the place the script is about)
    "fold_accents": False,   # compare prose "Tokaido" with source "Tōkaidō"
    "era": None,             # {"name": "...", "tie": "<regex>", "months": true, "letters": "..."}
}


@dataclass
class Report:
    items: int = 0
    words: int = 0
    failures: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def fail(self, item: str, msg: str) -> None:
        self.failures.append({"item": item, "message": msg})

    def warn(self, item: str, msg: str) -> None:
        self.warnings.append({"item": item, "message": msg})

    def as_dict(self) -> dict:
        return {"items": self.items, "words": self.words,
                "failures": self.failures, "warnings": self.warnings}


def normalise(s: str) -> str:
    """Curly quotes to straight, any dash to '-', drop zero-width spaces, collapse whitespace."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub("[–—−]", "-", s)
    s = s.replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def fold(s: str) -> str:
    """Strip accents and macrons. The Turkish dotless i is a separate letter, not a combining
    mark, so it is mapped by hand."""
    s = s.replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def numbers(s: str) -> set[str]:
    """Digit groups, with thousands separators removed so 1,000 equals 1000."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def longest_shared_run(text: str, quotes: str) -> int:
    """Longest run of consecutive identical words (lower-cased, punctuation ignored)."""
    a = re.findall(r"[a-z0-9']+", normalise(text).lower())
    b = re.findall(r"[a-z0-9']+", quotes.lower())
    best, prev = 0, [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _era_issues(text: str, qtext: str, allow: set[str], era: dict) -> tuple[list[str], list[str]]:
    fails, warns = [], []
    letters = era.get("letters")
    if letters and re.search(letters if letters.startswith("[") else f"[{re.escape(letters)}]", text):
        warns.append("special letters in the prose; use the plain spelling")
    low = qtext.lower()
    for name in ERA_PHRASE.findall(fold(text)):
        if name.lower() not in low and name not in allow:
            fails.append(f"'{name} era/period' is not in the quotes")
    if not era.get("months", True):
        for m in sorted(set(MONTHS.findall(text))):
            if m.lower() not in low:
                warns.append(f"month name '{m}' is not in the quotes")
    name, tie = era.get("name"), era.get("tie")
    if name and tie and name in text and not re.search(tie, qtext):
        warns.append(f"the prose says '{name}' but no quote ties this item to that era")
    return fails, warns


def check(claims: dict, sources_dir: Path) -> Report:
    """Check a claims document against `<sources_dir>/<src>.txt` files."""
    def load(src: str) -> str | None:
        p = sources_dir / f"{src}.txt"
        return p.read_text(encoding="utf-8") if p.is_file() else None
    return _check(claims, load)


def check_texts(claims: dict, sources: dict[str, str]) -> Report:
    """Same checks, with the source texts passed in directly (used by the MCP server)."""
    return _check(claims, sources.get)


def _check(claims: dict, load_source) -> Report:
    cfg = {**DEFAULTS, **claims.get("config", {})}
    era = cfg["era"]
    if era is not None and not isinstance(era, dict):
        raise ValueError("config.era must be an object like {\"name\": ..., \"tie\": ...}")
    folding = bool(cfg["fold_accents"] or era)
    # Prose is folded before the name check, so fold the allow list too ("Tōkaidō" -> "Tokaido").
    allow = set(cfg["allow"]) | ({fold(a) for a in cfg["allow"]} if folding else set())
    rep = Report()
    cache: dict[str, str | None] = {}

    for sec in claims.get("sections", []):
        for it in sec.get("items", []):
            rep.items += 1
            tag = str(it.get("id", rep.items))
            text = it.get("text", "")
            rep.words += len(text.split())
            if not it.get("claims"):
                rep.fail(tag, "no claims")
                continue
            quotes = []
            for c in it["claims"]:
                src = str(c.get("src", ""))
                if not SAFE_SRC.match(src):
                    rep.fail(tag, f"invalid source id {src!r} (letters, digits, '.', '_', '-' only)")
                    continue
                if src not in cache:
                    raw = load_source(src)
                    cache[src] = normalise(raw) if raw is not None else None
                if cache[src] is None:
                    rep.fail(tag, f"no source file for '{src}'")
                    continue
                q = normalise(c.get("quote", ""))
                if len(q) < cfg["min_quote_chars"]:
                    rep.fail(tag, f"quote too short: {q!r}")
                elif q not in cache[src]:
                    rep.fail(tag, f"quote not found in '{src}': {q[:70]!r}")
                quotes.append(q)

            qtext, body = " ".join(quotes), text
            if folding:
                qtext, body = fold(qtext), fold(body)
            if era:
                ef, ew = _era_issues(text, qtext, allow, era)
                for x in ef:
                    rep.fail(tag, x)
                for x in ew:
                    rep.warn(tag, x)

            missing = numbers(body) - numbers(qtext)
            if missing:
                rep.fail(tag, f"number(s) {sorted(missing)} not in the quotes")
            if NUMWORD.search(body) and not NUMWORD.search(qtext):
                rep.warn(tag, "quantity word (hundred/thousand/...) not in the quotes")
            run = longest_shared_run(body, qtext)
            if run >= cfg["copy_run"]:
                rep.warn(tag, f"{run} consecutive words shared with the quotes; retell, don't copy")
            low = qtext.lower()
            for sent in re.split(r"(?<=[.!?])\s+", body):
                for w in re.findall(r"(?<=\s)[A-Z][a-zA-Z']+", " " + sent)[1:]:
                    w = w.removesuffix("'s")
                    if (w in COMMON or w in allow or w.lower() in low
                            or w.lower().rstrip("s") in low):
                        continue
                    rep.warn(tag, f"possible unsourced proper noun: {w}")
    return rep


def check_file(claims_path: Path, sources_dir: Path | None = None) -> Report:
    claims = json.loads(Path(claims_path).read_text(encoding="utf-8"))
    return check(claims, sources_dir or Path(claims_path).parent / "sources")
