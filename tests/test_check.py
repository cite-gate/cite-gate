import json
import tempfile
import unittest
from pathlib import Path

from cite_gate.check import check, fold, longest_shared_run, normalise, numbers
from cite_gate.__main__ import main

SOURCE = ("The harbour held 1,200 ships in 1850. A lighthouse stood on the eastern pier, and "
          "fishermen sold their catch at the market each morning before sunrise.")


def run(items, config=None, source=SOURCE):
    d = Path(tempfile.mkdtemp())
    (d / "town.txt").write_text(source, encoding="utf-8")
    claims = {"config": config or {}, "sections": [{"title": "t", "items": items}]}
    return check(claims, d)


def item(text, *quotes, src="town"):
    return {"id": "x", "text": text, "claims": [{"src": src, "quote": q} for q in quotes]}


class Helpers(unittest.TestCase):
    def test_normalise_quotes_and_dashes(self):
        self.assertEqual(normalise("it’s  a — test"), "it's a - test")

    def test_fold(self):
        self.assertEqual(fold("Tōkaidō"), "Tokaido")
        self.assertEqual(fold("Kadıköy"), "Kadikoy")

    def test_numbers_ignore_separators(self):
        self.assertEqual(numbers("1,200 and 1200"), {"1200"})

    def test_shared_run(self):
        self.assertEqual(longest_shared_run("a b c d", "x b c d y"), 3)


class Gates(unittest.TestCase):
    def test_clean_item_passes(self):
        r = run([item("The harbour had room for 1,200 ships by 1850.", "The harbour held 1,200 ships in 1850.")])
        self.assertEqual(r.failures, [])
        self.assertEqual(r.warnings, [])

    def test_quote_must_exist(self):
        r = run([item("There were many ships.", "The harbour held 2,000 ships in 1850.")])
        self.assertTrue(any("not found" in f["message"] for f in r.failures))

    def test_quote_too_short(self):
        r = run([item("Ships.", "1,200 ships")])
        self.assertTrue(any("too short" in f["message"] for f in r.failures))

    def test_number_must_be_quoted(self):
        r = run([item("The harbour held 1,500 ships.", "The harbour held 1,200 ships in 1850.")])
        self.assertTrue(any("1500" in f["message"] for f in r.failures))

    def test_missing_source_file(self):
        r = run([item("Ships came in.", "The harbour held 1,200 ships in 1850.", src="nope")])
        self.assertTrue(any("no source file" in f["message"] for f in r.failures))

    def test_src_cannot_escape_directory(self):
        r = run([item("Ships came in.", "The harbour held 1,200 ships in 1850.", src="../secret")])
        self.assertTrue(any("invalid source id" in f["message"] for f in r.failures))

    def test_no_claims(self):
        r = run([{"id": "x", "text": "Something."}])
        self.assertTrue(any("no claims" in f["message"] for f in r.failures))


class Warnings(unittest.TestCase):
    def test_quantity_word(self):
        r = run([item("Over a thousand ships came in.", "The harbour held 1,200 ships in 1850.")])
        self.assertTrue(any("quantity word" in w["message"] for w in r.warnings))

    def test_proper_noun(self):
        r = run([item("The harbour near Dover held 1,200 ships in 1850.", "The harbour held 1,200 ships in 1850.")])
        self.assertTrue(any("Dover" in w["message"] for w in r.warnings))

    def test_allow_list(self):
        r = run([item("The harbour near Dover held 1,200 ships in 1850.", "The harbour held 1,200 ships in 1850.")],
                {"allow": ["Dover"]})
        self.assertFalse(any("Dover" in w["message"] for w in r.warnings))

    def test_accented_allow_entry_matches_folded_prose(self):
        r = run([item("Travellers walked the Tōkaidō in 1850.", "The harbour held 1,200 ships in 1850.")],
                {"fold_accents": True, "allow": ["Tōkaidō"]})
        self.assertFalse(any("Tokaido" in w["message"] for w in r.warnings))

    def test_copy_run(self):
        q = "fishermen sold their catch at the market each morning before sunrise."
        r = run([item("Here fishermen sold their catch at the market each morning before sunrise.", q)])
        self.assertTrue(any("consecutive words" in w["message"] for w in r.warnings))

    def test_copy_run_threshold_configurable(self):
        q = "fishermen sold their catch at the market each morning before sunrise."
        r = run([item("Here fishermen sold their catch at the market each morning before sunrise.", q)],
                {"copy_run": 50})
        self.assertFalse(any("consecutive words" in w["message"] for w in r.warnings))


class Era(unittest.TestCase):
    ERA = {"name": "Harbour Age", "tie": r"\b18\d\d\b", "months": False}

    def test_tie_missing(self):
        src = "In the Harbour Age the lighthouse stood on the eastern pier."
        r = run([item("In the Harbour Age the eastern pier had a light.",
                      "the lighthouse stood on the eastern pier.")], {"era": self.ERA, "allow": ["Harbour", "Age"]}, src)
        self.assertTrue(any("ties this item" in w["message"] for w in r.warnings))

    def test_month_not_quoted(self):
        r = run([item("In March the harbour held 1,200 ships in 1850.", "The harbour held 1,200 ships in 1850.")],
                {"era": self.ERA})
        self.assertTrue(any("month name" in w["message"] for w in r.warnings))

    def test_era_must_be_object(self):
        with self.assertRaises(ValueError):
            run([item("x", "The harbour held 1,200 ships in 1850.")], {"era": True})


class Cli(unittest.TestCase):
    def test_exit_codes(self):
        d = Path(tempfile.mkdtemp())
        (d / "sources").mkdir()
        (d / "sources" / "town.txt").write_text(SOURCE, encoding="utf-8")
        good = {"sections": [{"items": [item("The harbour had room for 1,200 ships by 1850.",
                                                 "The harbour held 1,200 ships in 1850.")]}]}
        (d / "good.json").write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(main(["check", str(d / "good.json")]), 0)
        warn = {"sections": [{"items": [item("Over a thousand ships came in.",
                                                 "The harbour held 1,200 ships in 1850.")]}]}
        (d / "warn.json").write_text(json.dumps(warn), encoding="utf-8")
        self.assertEqual(main(["check", str(d / "warn.json")]), 0)
        self.assertEqual(main(["check", str(d / "warn.json"), "--strict"]), 1)

    def test_example_fails_on_purpose(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(main(["check", str(root / "examples" / "gettysburg" / "claims.json")]), 1)


if __name__ == "__main__":
    unittest.main()
