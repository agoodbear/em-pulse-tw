#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EM Pulse 資料產生器（繁中版）
----------------------------------
每天執行一次：查 PubMed 近 N 天、急診/重症/外傷期刊清單內的文獻 →
依〔期刊分級 + 文獻類型 + 發表新近度〕計分 → 輸出 data/pulse.json。

schema 與原站 derinsoluk.com/pulse 對齊，前端 index.html 可直接吃。
純標準函式庫，無第三方相依。期刊清單與分級放在 journals.json，改表即可調整範圍。

逆向自 İbrahim Sarbay, MD 的 EM Pulse / EM Popular；繁中版 by 曹建雄。
"""

import http.client
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date
from urllib.error import HTTPError, URLError

# ── 設定 ──────────────────────────────────────────────
HERE        = os.path.dirname(os.path.abspath(__file__))
JOURNALS_FP = os.path.join(HERE, "journals.json")
OUT_FP      = os.path.join(HERE, "data", "pulse.json")
DAYS_BACK   = 7
RETMAX      = 600
EUTILS      = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# NCBI 禮貌參數（無 API key 時上限約 3 req/s）。可選：設環境變數 NCBI_API_KEY 提高到 10 req/s。
TOOL        = "em-pulse-tw"
EMAIL       = "agoodbear@gmail.com"
API_KEY     = os.environ.get("NCBI_API_KEY", "")

# 文獻類型優先序（一篇可能掛多個 PublicationType，取序位最前者）
TYPE_ORDER = ["guideline", "meta-analysis", "systematic-review", "rct",
              "clinical-trial", "review", "case-report", "editorial",
              "letter", "comment", "original"]

# MEDLINE PublicationType → 我們的 articleType
PT_MAP = {
    "Practice Guideline": "guideline",
    "Guideline": "guideline",
    "Meta-Analysis": "meta-analysis",
    "Systematic Review": "systematic-review",
    "Randomized Controlled Trial": "rct",
    "Controlled Clinical Trial": "clinical-trial",
    "Clinical Trial": "clinical-trial",
    "Clinical Trial, Phase I": "clinical-trial",
    "Clinical Trial, Phase II": "clinical-trial",
    "Clinical Trial, Phase III": "clinical-trial",
    "Clinical Trial, Phase IV": "clinical-trial",
    "Review": "review",
    "Case Reports": "case-report",
    "Editorial": "editorial",
    "Letter": "letter",
    "Comment": "comment",
}

# NCBI eutils 重試設定：尖峰常見 429/5xx、連線重置、timeout，甚至回 HTML 錯誤頁。
RETRY_MAX     = 4          # 總嘗試次數
RETRY_BACKOFF = 2          # 遞增退避基數（秒）：2, 4, 6 …
RETRY_STATUS  = {429, 500, 502, 503, 504}

# 對不到分級的期刊縮寫 → 全名，跑完在 stderr 列出，供維護者補進 journals.json。
UNMATCHED_JOURNALS = {}

# 計分權重（可自由調整）
TIER_BASE = {1: 40, 2: 26, 3: 16}
TYPE_BONUS = {
    "guideline": 30, "meta-analysis": 26, "systematic-review": 23, "rct": 21,
    "clinical-trial": 13, "review": 9, "case-report": 2, "editorial": 1,
    "letter": 0, "comment": 0, "original": 0,
}


def http_get(url, parse=None):
    """
    抓 url 回傳 bytes；給 parse（如 json.loads / ET.fromstring）時回傳解析後物件。
    對暫時性失敗重試 + 遞增退避：可重試 HTTP 狀態(429/5xx)、連線重置、timeout，
    以及 parse 失敗（NCBI 尖峰偶爾回 HTML 錯誤頁而非 JSON/XML）。非可重試的
    HTTP 錯誤直接拋出；重試耗盡則拋最後一次的例外。
    """
    last_err = None
    for attempt in range(RETRY_MAX):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{TOOL} ({EMAIL})"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            return parse(raw) if parse else raw
        except HTTPError as e:
            last_err = e
            if e.code not in RETRY_STATUS:
                raise
        except (URLError, socket.timeout, ConnectionError,
                http.client.IncompleteRead, ET.ParseError, json.JSONDecodeError) as e:
            last_err = e
        if attempt < RETRY_MAX - 1:
            wait = RETRY_BACKOFF * (attempt + 1)
            print(f"      eutils 連線/解析失敗（{type(last_err).__name__}），"
                  f"{wait}s 後重試（{attempt + 2}/{RETRY_MAX}）…", file=sys.stderr)
            time.sleep(wait)
    raise last_err


def eutils_params(extra):
    p = {"tool": TOOL, "email": EMAIL}
    if API_KEY:
        p["api_key"] = API_KEY
    p.update(extra)
    return urllib.parse.urlencode(p)


def load_journals():
    with open(JOURNALS_FP, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def esearch(journals):
    """用期刊清單 OR 查詢，限近 DAYS_BACK 天（發表日）。回傳 PMID list。"""
    jour_or = " OR ".join(f'"{j}"[jour]' for j in journals)
    term = f"({jour_or})"
    q = eutils_params({
        "db": "pubmed", "retmode": "json", "retmax": RETMAX,
        "datetype": "pdat", "reldate": DAYS_BACK, "term": term, "sort": "pub_date",
    })
    data = http_get(f"{EUTILS}/esearch.fcgi?{q}", parse=json.loads)
    return data.get("esearchresult", {}).get("idlist", [])


def efetch(pmids):
    """分批 efetch 取 XML，回傳所有 PubmedArticle element。"""
    arts = []
    for i in range(0, len(pmids), 200):
        chunk = pmids[i:i + 200]
        q = eutils_params({"db": "pubmed", "retmode": "xml", "id": ",".join(chunk)})
        root = http_get(f"{EUTILS}/efetch.fcgi?{q}", parse=ET.fromstring)
        arts.extend(root.findall(".//PubmedArticle"))
        time.sleep(0.4 if not API_KEY else 0.12)
    return arts


def text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_pubdate(art):
    """回傳 ISO 'YYYY-MM-DD'（盡量），抓不到月日就補 01。"""
    pd = art.find(".//Article/Journal/JournalIssue/PubDate")
    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05",
              "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10",
              "Nov": "11", "Dec": "12"}
    if pd is not None:
        y = text(pd.find("Year"))
        m = text(pd.find("Month"))
        d = text(pd.find("Day"))
        medline = text(pd.find("MedlineDate"))
        if y:
            mm = months.get(m, m if m.isdigit() else "01").zfill(2)
            dd = d.zfill(2) if d else "01"
            return f"{y}-{mm}-{dd}"
        if medline:
            parts = medline.split()
            if parts and parts[0].isdigit():
                yy = parts[0]
                mm = months.get(parts[1][:3], "01") if len(parts) > 1 else "01"
                return f"{yy}-{mm}-01"
    # 退而求其次：用 entrez 收錄日
    art_date = art.find(".//PubMedPubDate[@PubStatus='pubmed']")
    if art_date is not None:
        y = text(art_date.find("Year")); m = text(art_date.find("Month")); d = text(art_date.find("Day"))
        if y:
            return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return ""


def parse_authors(art):
    out = []
    for a in art.findall(".//AuthorList/Author"):
        last = text(a.find("LastName"))
        init = text(a.find("Initials"))
        coll = text(a.find("CollectiveName"))
        if last:
            out.append(f"{last} {init}".strip())
        elif coll:
            out.append(coll)
    return out


def parse_article_type(pub_types):
    mapped = [PT_MAP[p] for p in pub_types if p in PT_MAP]
    for t in TYPE_ORDER:
        if t in mapped:
            return t
    return "original"


def parse_one(art, journals):
    pmid = text(art.find(".//PMID"))
    title = text(art.find(".//Article/ArticleTitle")).rstrip()
    journal_abbr = text(art.find(".//Article/Journal/ISOAbbreviation")) or \
                   text(art.find(".//MedlineJournalInfo/MedlineTA"))
    journal_full = text(art.find(".//Article/Journal/Title"))
    tier = journals.get(journal_abbr)
    if tier is None:
        # 比對 MedlineTA（有時 ISOAbbreviation 與表內 key 大小寫/標點略異）
        ta = text(art.find(".//MedlineJournalInfo/MedlineTA"))
        tier = journals.get(ta)
        if ta:
            journal_abbr = ta
        if tier is None:
            # ISOAbbreviation 與 MedlineTA 都對不到 → 暫記 tier 3，並收錄縮寫供補表
            UNMATCHED_JOURNALS.setdefault(journal_abbr or "?", journal_full)
            tier = 3
    abstract = " ".join(text(t) for t in art.findall(".//Abstract/AbstractText")).strip()
    doi = ""
    for idn in art.findall(".//ArticleIdList/ArticleId"):
        if idn.get("IdType") == "doi":
            doi = text(idn)
    pub_types = [text(p) for p in art.findall(".//PublicationTypeList/PublicationType")]
    keywords = [text(k) for k in art.findall(".//KeywordList/Keyword") if text(k)]
    mesh = [text(m.find("DescriptorName")) for m in art.findall(".//MeshHeadingList/MeshHeading")
            if m.find("DescriptorName") is not None]
    article_type = parse_article_type(pub_types)
    pub_date = parse_pubdate(art)
    return {
        "pmid": pmid,
        "title": title,
        "authors": parse_authors(art),
        "journal": journal_full or journal_abbr,
        "journalTier": tier,
        "journalSJR": None,
        "articleType": article_type,
        "pubDate": pub_date,
        "abstract": abstract,
        "doi": doi,
        "keywords": keywords,
        "meshTerms": mesh,
        "pubTypes": pub_types,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


def impact_score(a, today):
    base = TIER_BASE.get(a["journalTier"], 16)
    bonus = TYPE_BONUS.get(a["articleType"], 0)
    days_old = 0
    if a["pubDate"]:
        try:
            d = date.fromisoformat(a["pubDate"])
            days_old = max(0, (today - d).days)
        except ValueError:
            days_old = DAYS_BACK
    recency = max(0, 10 - days_old)
    return round(base + bonus + recency)


def main():
    journals = load_journals()
    print(f"[1/4] esearch：{len(journals)} 本期刊、近 {DAYS_BACK} 天 …", file=sys.stderr)
    pmids = esearch(journals)
    print(f"      命中 {len(pmids)} 筆 PMID", file=sys.stderr)
    if not pmids:
        print("      無資料，中止（不覆寫舊檔）", file=sys.stderr)
        sys.exit(1)

    print(f"[2/4] efetch：抓取 {len(pmids)} 筆完整紀錄 …", file=sys.stderr)
    raw = efetch(pmids)

    print(f"[3/4] 解析 + 計分 …", file=sys.stderr)
    today = datetime.now(timezone.utc).date()
    arts = []
    for el in raw:
        a = parse_one(el, journals)
        if not a["pmid"] or not a["title"]:
            continue
        a["impactScore"] = impact_score(a, today)
        arts.append(a)

    if UNMATCHED_JOURNALS:
        print(f"      ⚠ {len(UNMATCHED_JOURNALS)} 本期刊對不到分級，暫記 tier 3"
              f"（建議補進 journals.json）：", file=sys.stderr)
        for abbr, full in sorted(UNMATCHED_JOURNALS.items()):
            print(f"        - {abbr}" + (f"  （{full}）" if full else ""), file=sys.stderr)

    # impactScore 由高到低；同分則發表日期由新到舊（pubDate 為 ISO 'YYYY-MM-DD' 字串，可直接比較）
    arts.sort(key=lambda x: (x["impactScore"], x["pubDate"]), reverse=True)

    by_type, by_tier = {}, {}
    for a in arts:
        by_type[a["articleType"]] = by_type.get(a["articleType"], 0) + 1
        t = str(a["journalTier"])
        by_tier[t] = by_tier.get(t, 0) + 1
    scores = [a["impactScore"] for a in arts]

    out = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "daysBack": DAYS_BACK,
        "journalCount": len(journals),
        "stats": {
            "total": len(arts),
            "byType": by_type,
            "byTier": by_tier,
            "topScore": max(scores) if scores else 0,
            "avgScore": round(sum(scores) / len(scores)) if scores else 0,
        },
        "articleOfWeek": arts[0] if arts else None,
        "articles": arts,
    }

    os.makedirs(os.path.dirname(OUT_FP), exist_ok=True)
    with open(OUT_FP, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"[4/4] 完成：{len(arts)} 篇 → {OUT_FP}", file=sys.stderr)
    print(f"      Tier {by_tier} | topScore {out['stats']['topScore']} | "
          f"avg {out['stats']['avgScore']}", file=sys.stderr)


if __name__ == "__main__":
    main()
