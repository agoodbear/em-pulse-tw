#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""靜態站的 build 檢查：Python 語法正確、JSON 合法、pulse.json schema 正確、HTML 內嵌 JS 語法正確。
任何一項失敗即 exit 1。只用標準函式庫 + 系統 node。"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PAGES = ["index.html", "empopular/index.html"]
ARTICLE_KEYS = {"pmid", "title", "authors", "journal", "journalTier", "articleType",
                "pubDate", "abstract", "doi", "keywords", "meshTerms", "pubTypes", "url", "impactScore"}
errors = []


def ok(msg):
    print(f"  ✓ {msg}")


def fail(msg):
    print(f"  ✗ {msg}")
    errors.append(msg)


def check_python():
    for f in ["generate_pulse.py", "scripts/build_check.py"]:
        try:
            with open(os.path.join(ROOT, f), encoding="utf-8") as src:
                compile(src.read(), f, "exec")
            ok(f"Python 語法 {f}")
        except SyntaxError as e:
            fail(f"Python 語法 {f}: {e}")


def check_journals():
    with open(os.path.join(ROOT, "journals.json"), encoding="utf-8") as f:
        j = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    bad = {k: v for k, v in j.items() if v not in (1, 2, 3)}
    (fail(f"journals.json tier 非 1/2/3：{bad}") if bad else ok(f"journals.json {len(j)} 本期刊"))


def check_pulse():
    fp = os.path.join(ROOT, "data", "pulse.json")
    with open(fp, encoding="utf-8") as f:
        d = json.load(f)
    for k in ("generatedAt", "daysBack", "journalCount", "stats", "articles"):
        if k not in d:
            fail(f"pulse.json 缺頂層欄位 {k}")
    arts = d.get("articles", [])
    for i, a in enumerate(arts):
        missing = ARTICLE_KEYS - a.keys()
        if missing:
            fail(f"pulse.json articles[{i}] 缺欄位 {sorted(missing)}")
            break
        if a["journalTier"] not in (1, 2, 3) or not str(a["url"]).startswith("https://"):
            fail(f"pulse.json articles[{i}] tier/url 不合法")
            break
    if d.get("stats", {}).get("total") != len(arts):
        fail("pulse.json stats.total 與 articles 數不符")
    if not errors:
        ok(f"pulse.json schema（{len(arts)} 篇）")


def check_inline_js():
    with tempfile.TemporaryDirectory() as tmp:
        for page in HTML_PAGES:
            with open(os.path.join(ROOT, page), encoding="utf-8") as f:
                scripts = re.findall(r"<script>(.*?)</script>", f.read(), re.S)
            for n, s in enumerate(scripts):
                js = os.path.join(tmp, f"s{n}.js")
                with open(js, "w", encoding="utf-8") as f:
                    f.write(s)
                r = subprocess.run(["node", "--check", js], capture_output=True, text=True)
                if r.returncode:
                    fail(f"{page} <script #{n}> 語法錯誤：{r.stderr.strip()}")
            ok(f"{page} 內嵌 JS 語法（{len(scripts)} 段）")


if __name__ == "__main__":
    print("build check")
    check_python()
    check_journals()
    check_pulse()
    check_inline_js()
    if errors:
        print(f"FAILED：{len(errors)} 項")
        sys.exit(1)
    print("OK")
