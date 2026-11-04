# -*- coding: utf-8 -*-
"""generate_pulse.py 單元測試（純標準函式庫，不連網）。執行：python3 -m unittest discover -s tests -t ."""
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr
from datetime import date
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generate_pulse as gp  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "efetch_sample.xml")
JOURNALS = {"Ann Emerg Med": 1, "Injury": 2, "Emergencias": 3}


def art(xml):
    return ET.fromstring(f"<PubmedArticle>{xml}</PubmedArticle>")


def pubdate_xml(inner):
    return art(f"<MedlineCitation><Article><Journal><JournalIssue><PubDate>{inner}"
               f"</PubDate></JournalIssue></Journal></Article></MedlineCitation>")


class FakeResp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestParsePubdate(unittest.TestCase):
    def test_full_date_named_month(self):
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<Year>2026</Year><Month>Nov</Month><Day>3</Day>")),
                         "2026-11-03")

    def test_numeric_month(self):
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<Year>2026</Year><Month>7</Month>")), "2026-07-01")

    def test_year_only(self):
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<Year>2026</Year>")), "2026-01-01")

    def test_month_range_and_season(self):
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<Year>2026</Year><Month>Nov-Dec</Month>")), "2026-11-01")
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<Year>2026</Year><Month>Winter</Month>")), "2026-01-01")

    def test_medline_date(self):
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<MedlineDate>2026 Oct-Dec</MedlineDate>")), "2026-10-01")
        self.assertEqual(gp.parse_pubdate(pubdate_xml("<MedlineDate>2026</MedlineDate>")), "2026-01-01")

    def test_fallback_to_pubmed_history_date(self):
        a = art("<PubmedData><History><PubMedPubDate PubStatus='pubmed'><Year>2026</Year>"
                "<Month>11</Month><Day>2</Day></PubMedPubDate></History></PubmedData>")
        self.assertEqual(gp.parse_pubdate(a), "2026-11-02")

    def test_fallback_incomplete_returns_empty(self):
        a = art("<PubmedData><History><PubMedPubDate PubStatus='pubmed'><Year>2026</Year>"
                "</PubMedPubDate></History></PubmedData>")
        self.assertEqual(gp.parse_pubdate(a), "")

    def test_no_date(self):
        self.assertEqual(gp.parse_pubdate(art("")), "")


class TestParseAuthorsAndType(unittest.TestCase):
    def test_authors_person_and_collective(self):
        a = art("<AuthorList><Author><LastName>Chen</LastName><Initials>YH</Initials></Author>"
                "<Author><CollectiveName>ILCOR</CollectiveName></Author>"
                "<Author><LastName>Lin</LastName></Author><Author/></AuthorList>")
        self.assertEqual(gp.parse_authors(a), ["Chen YH", "ILCOR", "Lin"])

    def test_article_type_priority(self):
        self.assertEqual(gp.parse_article_type(["Journal Article", "Review", "Meta-Analysis"]), "meta-analysis")
        self.assertEqual(gp.parse_article_type(["Randomized Controlled Trial", "Clinical Trial"]), "rct")
        self.assertEqual(gp.parse_article_type(["Practice Guideline", "Systematic Review"]), "guideline")
        self.assertEqual(gp.parse_article_type(["Clinical Trial, Phase III"]), "clinical-trial")

    def test_article_type_default_original(self):
        self.assertEqual(gp.parse_article_type(["Journal Article"]), "original")
        self.assertEqual(gp.parse_article_type([]), "original")

    def test_type_tables_consistent(self):
        # 每個 PT_MAP 輸出都要在 TYPE_ORDER 與 TYPE_BONUS 裡，否則排序/計分會靜默失效
        for t in set(gp.PT_MAP.values()) | {"original"}:
            self.assertIn(t, gp.TYPE_ORDER)
            self.assertIn(t, gp.TYPE_BONUS)


class TestParseOne(unittest.TestCase):
    def setUp(self):
        gp.UNMATCHED_JOURNALS.clear()
        self.arts = {gp.text(a.find(".//PMID")): a for a in ET.parse(FIXTURE).getroot().findall(".//PubmedArticle")}

    def test_full_record(self):
        a = gp.parse_one(self.arts["1001"], JOURNALS)
        self.assertEqual(a["pmid"], "1001")
        self.assertEqual(a["title"], "Early epinephrine in OHCA: a randomized trial.")
        self.assertEqual(a["journalTier"], 1)
        self.assertEqual(a["journal"], "Annals of emergency medicine")
        self.assertEqual(a["articleType"], "rct")
        self.assertEqual(a["pubDate"], "2026-11-02")
        self.assertEqual(a["doi"], "10.1016/j.annemergmed.2026.001")
        self.assertEqual(a["authors"], ["Wang CH", "Tsai MS"])
        self.assertIn("Background text.", a["abstract"])
        self.assertIn("Results text.", a["abstract"])
        self.assertEqual(a["keywords"], ["cardiac arrest", "epinephrine"])
        self.assertEqual(a["meshTerms"], ["Out-of-Hospital Cardiac Arrest"])
        self.assertEqual(a["url"], "https://pubmed.ncbi.nlm.nih.gov/1001/")
        self.assertEqual(gp.UNMATCHED_JOURNALS, {})

    def test_inline_markup_flattened(self):
        # PubMed 標題常含 <i>/<sub>；itertext 應攤平成純文字
        a = gp.parse_one(self.arts["1002"], JOURNALS)
        self.assertEqual(a["title"], "CO2 levels in <5 y children & H&E staining")

    def test_medline_ta_fallback(self):
        a = gp.parse_one(self.arts["1002"], JOURNALS)
        self.assertEqual(a["journalTier"], 2)  # ISOAbbreviation 對不到，MedlineTA=Injury 對到

    def test_unmatched_journal_defaults_tier3_and_recorded(self):
        a = gp.parse_one(self.arts["1003"], JOURNALS)
        self.assertEqual(a["journalTier"], 3)
        self.assertIn("Unknown J", gp.UNMATCHED_JOURNALS)
        self.assertEqual(a["articleType"], "original")


class TestImpactScore(unittest.TestCase):
    T = date(2026, 11, 4)

    def score(self, tier, typ, pub):
        return gp.impact_score({"journalTier": tier, "articleType": typ, "pubDate": pub}, self.T)

    def test_formula(self):
        self.assertEqual(self.score(1, "guideline", "2026-11-04"), 40 + 30 + 10)
        self.assertEqual(self.score(2, "rct", "2026-11-01"), 26 + 21 + 7)
        self.assertEqual(self.score(3, "original", "2026-10-01"), 16 + 0 + 0)

    def test_unknown_values_fallback(self):
        self.assertEqual(self.score(9, "weird", "2026-11-04"), 16 + 0 + 10)

    def test_bad_or_missing_date(self):
        self.assertEqual(self.score(1, "original", ""), 40 + 10)  # 現行行為：無日期視為今天
        self.assertEqual(self.score(1, "original", "2026-13-40"), 40 + max(0, 10 - gp.DAYS_BACK))

    def test_future_date_gets_full_recency(self):
        # 現行行為（見 docs/review）：期刊預排的未來日期拿滿新近度分
        self.assertEqual(self.score(1, "original", "2026-12-01"), 50)


class TestHttpGet(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(gp.time, "sleep")
        self.sleep = p.start()
        self.addCleanup(p.stop)

    def run_get(self, effects, parse=None):
        with mock.patch.object(gp.urllib.request, "urlopen", side_effect=effects) as m, \
                redirect_stderr(io.StringIO()):
            return gp.http_get("https://x/", parse=parse), m

    def test_success_with_parse(self):
        r, m = self.run_get([FakeResp(b'{"a":1}')], parse=json.loads)
        self.assertEqual(r, {"a": 1})
        self.assertEqual(m.call_count, 1)

    def test_sends_user_agent(self):
        _, m = self.run_get([FakeResp(b"x")])
        self.assertIn(gp.TOOL, m.call_args[0][0].get_header("User-agent"))

    def test_retry_on_transient_then_success(self):
        err = HTTPError("u", 503, "busy", {}, None)
        r, m = self.run_get([err, URLError("reset"), socket.timeout(), FakeResp(b"ok")])
        self.assertEqual(r, b"ok")
        self.assertEqual(m.call_count, 4)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4, 6])

    def test_retry_on_html_error_page(self):
        r, _ = self.run_get([FakeResp(b"<html>oops"), FakeResp(b"[1]")], parse=json.loads)
        self.assertEqual(r, [1])

    def test_non_retryable_http_error_raises_immediately(self):
        with self.assertRaises(HTTPError):
            self.run_get([HTTPError("u", 400, "bad", {}, None), FakeResp(b"never")])
        self.sleep.assert_not_called()

    def test_retries_exhausted_raises_last(self):
        errs = [HTTPError("u", 429, "slow", {}, None)] * gp.RETRY_MAX
        with self.assertRaises(HTTPError) as cm:
            self.run_get(errs)
        self.assertEqual(cm.exception.code, 429)
        self.assertEqual(self.sleep.call_count, gp.RETRY_MAX - 1)


class TestEutils(unittest.TestCase):
    def test_params_include_api_key_only_when_set(self):
        with mock.patch.object(gp, "API_KEY", ""):
            self.assertNotIn("api_key", gp.eutils_params({"db": "pubmed"}))
        with mock.patch.object(gp, "API_KEY", "k123"):
            self.assertIn("api_key=k123", gp.eutils_params({"db": "pubmed"}))

    def test_esearch_builds_journal_query(self):
        captured = {}

        def fake(url, parse=None):
            captured["url"] = url
            return {"esearchresult": {"idlist": ["1", "2"]}}
        with mock.patch.object(gp, "http_get", side_effect=fake):
            self.assertEqual(gp.esearch(["Ann Emerg Med", "Injury"]), ["1", "2"])
        q = gp.urllib.parse.parse_qs(gp.urllib.parse.urlsplit(captured["url"]).query)
        self.assertEqual(q["term"], ['("Ann Emerg Med"[jour] OR "Injury"[jour])'])
        self.assertEqual(q["reldate"], [str(gp.DAYS_BACK)])

    def test_esearch_warns_when_truncated(self):
        buf = io.StringIO()
        with mock.patch.object(gp, "http_get", return_value={"esearchresult": {"count": "900", "idlist": ["1"]}}), \
                redirect_stderr(buf):
            self.assertEqual(gp.esearch(["X"]), ["1"])
        self.assertIn("RETMAX", buf.getvalue())

    def test_esearch_no_warning_when_complete(self):
        buf = io.StringIO()
        with mock.patch.object(gp, "http_get", return_value={"esearchresult": {"count": "1", "idlist": ["1"]}}), \
                redirect_stderr(buf):
            gp.esearch(["X"])
        self.assertEqual(buf.getvalue(), "")

    def test_esearch_missing_result(self):
        with mock.patch.object(gp, "http_get", return_value={}):
            self.assertEqual(gp.esearch(["X"]), [])

    def test_efetch_chunks_by_200(self):
        calls = []

        def fake(url, parse=None):
            ids = gp.urllib.parse.parse_qs(gp.urllib.parse.urlsplit(url).query)["id"][0].split(",")
            calls.append(len(ids))
            return ET.fromstring("<PubmedArticleSet>" + "<PubmedArticle/>" * len(ids) + "</PubmedArticleSet>")
        with mock.patch.object(gp, "http_get", side_effect=fake), mock.patch.object(gp.time, "sleep"):
            out = gp.efetch([str(i) for i in range(450)])
        self.assertEqual(calls, [200, 200, 50])
        self.assertEqual(len(out), 450)


class TestLoadJournals(unittest.TestCase):
    def test_real_table_valid(self):
        j = gp.load_journals()
        self.assertTrue(j)
        self.assertFalse(any(k.startswith("_") for k in j))
        self.assertTrue(all(v in (1, 2, 3) for v in j.values()), "tier 必須是 1/2/3")


class TestMain(unittest.TestCase):
    def setUp(self):
        gp.UNMATCHED_JOURNALS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "data", "pulse.json")
        for p in (mock.patch.object(gp, "OUT_FP", self.out),
                  mock.patch.object(gp, "load_journals", return_value=JOURNALS)):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self):
        with redirect_stderr(io.StringIO()):
            gp.main()
        with open(self.out, encoding="utf-8") as f:
            return json.load(f)

    def test_end_to_end_output_schema_and_sorting(self):
        arts = ET.parse(FIXTURE).getroot().findall(".//PubmedArticle")
        with mock.patch.object(gp, "esearch", return_value=["1001", "1002", "1003", "1004"]), \
                mock.patch.object(gp, "efetch", return_value=arts):
            out = self.run_main()
        self.assertEqual(out["daysBack"], gp.DAYS_BACK)
        self.assertEqual(out["journalCount"], 3)
        self.assertEqual(out["stats"]["total"], 3)  # 1004 無標題被略過
        scores = [a["impactScore"] for a in out["articles"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(out["articleOfWeek"]["pmid"], out["articles"][0]["pmid"])
        self.assertEqual(out["stats"]["topScore"], max(scores))
        self.assertEqual(sum(out["stats"]["byTier"].values()), 3)
        self.assertEqual(set(out["stats"]["byTier"]), {"1", "2", "3"})
        self.assertRegex(out["generatedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.000Z$")
        self.assertEqual(os.listdir(os.path.dirname(self.out)), ["pulse.json"])  # 無殘留暫存檔

    def test_no_pmids_does_not_overwrite(self):
        os.makedirs(os.path.dirname(self.out))
        with open(self.out, "w") as f:
            f.write('{"old": true}')
        with mock.patch.object(gp, "esearch", return_value=[]), self.assertRaises(SystemExit):
            self.run_main()
        with open(self.out) as f:
            self.assertEqual(json.load(f), {"old": True})

    def test_no_parsable_articles_does_not_overwrite(self):
        os.makedirs(os.path.dirname(self.out))
        with open(self.out, "w") as f:
            f.write('{"old": true}')
        with mock.patch.object(gp, "esearch", return_value=["1"]), \
                mock.patch.object(gp, "efetch", return_value=[]), self.assertRaises(SystemExit):
            self.run_main()
        with open(self.out) as f:
            self.assertEqual(json.load(f), {"old": True})


class TestWriteJsonAtomic(unittest.TestCase):
    def test_failure_keeps_old_file_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "pulse.json")
            with open(fp, "w") as f:
                f.write('{"old": 1}')
            with self.assertRaises(TypeError):
                gp.write_json_atomic(fp, {"bad": object()})
            with open(fp) as f:
                self.assertEqual(json.load(f), {"old": 1})
            self.assertEqual(os.listdir(d), ["pulse.json"])


if __name__ == "__main__":
    unittest.main()
