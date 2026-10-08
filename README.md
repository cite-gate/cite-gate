# cite-gate

A small checker for scripts written with AI help. It makes every factual item in a script carry
a quote that appears **word for word** in a source file, and it flags prose that copies the
source instead of retelling it.

It doesn't decide whether a claim is true. It decides whether you can point at the sentence
your claim came from, and whether that sentence actually exists.

```
$ python -m cite_gate check examples/gettysburg/claims.json
5 items · 91 words · 2 failures · 1 warnings
  FAIL [number-not-in-quote] number(s) ['1776', '87'] not in the quotes
  FAIL [quote-not-in-source] quote not found in 'gettysburg': 'this nation shall endure forever and ever'
  warn [copied-not-retold] 26 consecutive words shared with the quotes; retell, don't copy
```

The example fails on purpose: its last three items are mistakes that a language model makes
all the time (a number it worked out itself, a quote it half remembered, a paragraph lifted
from the source).

## Why

Language models write fluent prose with confident details. The details that go wrong are
the small ones: a year that's off by one, a name added "for context", a quote paraphrased into
something the source never said. Reading the whole script against the sources by hand doesn't
scale. This tool turns that reading into a gate you can run on every change.

## What it checks

| Check | Result |
|---|---|
| Each quote exists in its source file (curly quotes, dashes and spacing normalised) | failure |
| Each quote is at least 20 characters | failure |
| Every number in the prose appears in that item's quotes (`1,000` = `1000`) | failure |
| Source ids are plain names (no paths) | failure |
| "hundred / thousand / million" in the prose but not in the quotes | warning |
| A capitalised word mid-sentence that isn't in the quotes (possible unsourced name) | warning |
| 11 or more consecutive words shared with the quotes (copying, not retelling) | warning |
| Optional era rule: the prose names an era but the quotes don't tie the item to it; month names or "X era" phrases not in the quotes; special letters in the prose | warning / failure |

Exit code is 1 when there are failures. `--strict` also fails on warnings.

## Input format

A claims file (JSON) and a folder of plain-text sources, one file per source id.

```json
{
 "config": {"allow": ["Lincoln"], "copy_run": 11},
 "sections": [
  {"title": "The occasion",
   "items": [
    {"id": "opening",
     "text": "He began by looking back four score and seven years ...",
     "claims": [{"src": "gettysburg",
                 "quote": "Four score and seven years ago our fathers brought forth on this continent, a new nation"}]}
   ]}
 ]
}
```

`sources/gettysburg.txt` holds the source text. Keep your own copy of each source (with its
URL and revision noted at the top), so a later run checks against the same text.

### Config

| Key | Default | Meaning |
|---|---|---|
| `allow` | `[]` | names accepted without a quote (the subject of the script, for example) |
| `copy_run` | `11` | shared-word run that counts as copying |
| `min_quote_chars` | `20` | shortest accepted quote |
| `fold_accents` | `false` | compare `Tokaido` in prose with `Tōkaidō` in the source |
| `era` | `null` | `{"name": "Victorian", "tie": "\\b18[3-9]\\d\\b", "months": true, "letters": ""}` |

## Use

Command line (Python 3.10+, no dependencies):

```
pip install .            # from a checkout; adds the `cite-gate` command
cite-gate check path/to/claims.json [--sources DIR] [--json] [--strict]

# or without installing
python -m cite_gate check path/to/claims.json
```

GitHub Actions:

```yaml
- uses: actions/checkout@v4
- uses: cite-gate/cite-gate@v0
  with:
    claims: script/claims.json
    strict: "false"
```

## Limits

* The heuristics are tuned for English prose.
* A quote that exists is not a claim that is correct. Sources can be wrong, and an item can
  cite a real sentence that says something else. The gate makes the review smaller; it
  doesn't replace it.
* Proper-noun and quantity checks are warnings because they have false positives. Fix them or
  add the name to `allow`; don't learn to ignore them.

## Example text

`examples/gettysburg/sources/gettysburg.txt` is the Gettysburg Address (1863), in the public
domain, transcribed here from the Bliss copy. Small wording differences between Lincoln's
manuscript copies exist; the checker compares against this file only.

## License

AGPL-3.0-or-later. Copyright (C) 2026 MLPC Inc. (see `LICENSE`).
