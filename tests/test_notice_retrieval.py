import hashlib
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from planning_agent import retrieval

ROOT = Path(__file__).resolve().parents[1]


class NoticeCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notices = retrieval.load_notices()
        cls.by_id = {n.id: n for n in cls.notices}

    def test_corpus_has_24_distinct_excerpts_in_19_event_groups(self):
        self.assertEqual(len(self.notices), 24)
        self.assertEqual(len(self.by_id), 24)
        self.assertEqual(len({n.text_sha256 for n in self.notices}), 24)
        self.assertEqual(len({n.group for n in self.notices}), 19)
        facts = json.loads((ROOT / retrieval.FACTS_DATASET).read_text(encoding="utf-8"))
        development = {item["text_sha256"] for item in facts["splits"]["development"]}
        real = {n.text_sha256 for n in self.notices if n.id.startswith("R")}
        self.assertEqual(development, real)  # the development split only repeats real_notices_v1

    def test_manifest_matches_the_datasets_and_holds_no_notice_text(self):
        self.assertTrue(retrieval.manifest_matches(notices=self.notices))
        text = retrieval.MANIFEST.read_text(encoding="utf-8")
        for notice in self.notices:
            self.assertNotIn(notice.text[:30], text, notice.id)
        documents = json.loads(text)["documents"]
        self.assertEqual([d["excerpt_sha256"] for d in documents], [n.text_sha256 for n in self.notices])
        self.assertTrue(all(d["url"].startswith("https://") for d in documents))

    def test_tokens_split_english_words_and_chinese_bigrams(self):
        self.assertEqual(retrieval.tokenize("Blank voyages and delays at the ports"),
                         ["blank", "voyage", "delay", "port"])
        self.assertEqual(retrieval.tokenize("码头罢工"), ["码头", "头罢", "罢工"])
        tokens, used = retrieval.expand("鹿特丹罢工", retrieval.load_glossary())
        self.assertIn("rotterdam", tokens)
        self.assertIn("strike", tokens)
        self.assertEqual(sorted(used), ["罢工", "鹿特丹"])

    def test_search_finds_the_event_and_the_glossary_carries_chinese_questions(self):
        index = retrieval.Index(self.notices)
        self.assertEqual(index.search("Red Sea diversion via the Cape of Good Hope")[0].notice.id, "R014")
        self.assertEqual(index.search("红海绕行好望角")[0].notice.id, "R014")
        self.assertEqual(index.search("红海绕行好望角", use_glossary=False), [])
        hits = index.search("鹿特丹码头罢工", k=3)
        self.assertEqual(hits[0].notice.id, "R006")
        self.assertEqual([h.rank for h in hits], [1, 2, 3])
        self.assertIn("strike", hits[0].matched)

    def test_random_expectation_matches_enumeration(self):
        n, relevant = 5, 2
        orders = list(itertools.permutations(range(n)))
        for k in (1, 3, 5):
            expected = retrieval.random_expectation(n, relevant, k)
            hits = sum(any(i < relevant for i in order[:k]) for order in orders) / len(orders)
            recall = sum(sum(i < relevant for i in order[:k]) / relevant for order in orders) / len(orders)
            self.assertAlmostEqual(expected["hit"], hits)
            self.assertAlmostEqual(expected["recall"], recall)
        mrr = sum(1 / (1 + min(order.index(i) for i in range(relevant))) for order in orders) / len(orders)
        self.assertAlmostEqual(retrieval.random_expectation(n, relevant, 1)["mrr"], mrr)

    def test_saved_evaluation_is_reproduced_and_names_its_inputs(self):
        result = retrieval.evaluate(self.notices)
        self.assertTrue(retrieval.results_match(result))
        summary = result["summary"]
        self.assertEqual(summary["queries"], {"en": 19, "zh": 19})
        self.assertEqual(summary["independent_cases"], 19)
        self.assertEqual(summary["inputs"]["queries_sha256"], retrieval._sha256(retrieval.QUERIES))
        self.assertIn("development check", summary["status"])


class NoticeFetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name)
        notices = {n.id: n for n in retrieval.load_notices()}
        self.picked = [notices["R014"], notices["R006"]]

    def test_fetch_refuses_without_consent_and_contacts_nothing(self):
        calls = []
        with self.assertRaises(PermissionError):
            retrieval.fetch(self.picked, self.raw, consent=False, get=lambda url: calls.append(url) or (200, "", b""))
        self.assertEqual(calls, [])
        self.assertFalse(any(self.raw.iterdir()))

    def test_fetch_saves_pages_and_logs_hashes_with_a_fake_network(self):
        page = (f"<html><head><title>x</title><script>var a = 1;</script></head><body><p>Intro</p>"
                f"<p>{self.picked[0].text}</p></body></html>").encode()

        def fake(url):
            if url == self.picked[0].url:
                return 200, "text/html", page
            raise OSError("connection refused")

        records = retrieval.fetch(self.picked, self.raw, consent=True, get=fake, pause=0)
        first, second = records
        self.assertEqual(first["status"], 200)
        self.assertEqual(first["bytes"], len(page))
        self.assertTrue(first["excerpt_found"])
        self.assertEqual((self.raw / "R014.html").read_bytes(), page)
        self.assertEqual(first["sha256"], hashlib.sha256(page).hexdigest())
        self.assertIsNone(second["status"])
        self.assertIn("connection refused", second["error"])
        log = json.loads((self.raw / "fetch_log.json").read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in log], ["R014", "R006"])

    def test_downloaded_pages_become_searchable_passages(self):
        body = ("<p>Short</p><style>p {}</style><p>Lashing crews will hold an extended action affecting zebrafish "
                "terminals for several days, according to the carrier.</p>")
        self.assertNotIn("p {}", retrieval.page_text(body))
        (self.raw / "R006.html").write_text(body, encoding="utf-8")
        extra = retrieval.local_passages(self.picked, self.raw)
        self.assertEqual(len(extra), 1)  # the short paragraph is dropped
        index = retrieval.Index(self.picked, extra=extra)
        hit = index.search("zebrafish")[0]
        self.assertEqual((hit.notice.id, hit.local), ("R006", True))


if __name__ == "__main__":
    unittest.main()
