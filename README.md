# EM Pulse（繁體中文版）

急診醫學與重症照護**文獻雷達**：每天清晨自動掃描 PubMed 近 7 天、急診/重症/外傷期刊清單內的新文獻，依〔期刊分級 + 文獻類型 + 發表新近度〕計分排序，做成可篩選的網頁。

> 逆向自 İbrahim Sarbay, MD 的 [EM Pulse](https://derinsoluk.com/pulse/)。介面繁中化、資料產生器自建（方案 C：每日自動更新）。by 曹建雄。

## 架構

```
generate_pulse.py  ──每天跑──▶  data/pulse.json  ──fetch──▶  index.html（純靜態前端）
（查 PubMed + 計分）            （排好序的清單）             （原生 JS 渲染，零框架）
        ▲
   journals.json（期刊→分級表，改這張就能改掃描範圍與計分）
```

- **前端**：單一 `index.html`，內嵌 CSS + 原生 JS，無框架、無打包。`fetch('data/pulse.json')` 讀檔後渲染統計列、本週精選、類型/分級篩選、分頁清單、側欄（類型分布 + 熱門關鍵字 + 運作說明）。
- **資料**：`data/pulse.json`，schema 與原站對齊。
- **產生器**：`generate_pulse.py`，純標準函式庫（無第三方相依）。走 NCBI eutils 的 esearch + efetch。
- **排程**：`.github/workflows/update-pulse.yml`，每天 22:00 UTC（＝台灣 06:00）自動重生並 commit。

## 計分公式（可調，在 `generate_pulse.py`）

```
impactScore = 期刊分級基底 + 文獻類型加分 + 新近度加分
  期刊分級基底  Tier1=40  Tier2=26  Tier3=16
  文獻類型加分  指引+30 統合分析+26 系統性回顧+23 RCT+21 臨床試驗+13 綜論+9 …
  新近度加分    max(0, 10 − 發表至今天數)   # 越新越高、上限 10
```

## 客製化

- **改掃描範圍/分級**：編輯 `journals.json`。key 用 PubMed 的 `[jour]` 縮寫（在 PubMed 進階搜尋的 Journal 欄查得到），value 填 `1`/`2`/`3`。
- **做「心臟版」雷達**：把 `journals.json` 收斂成心臟相關期刊，或在 `generate_pulse.py` 的 `esearch()` term 加 MeSH 條件，即可當 EM Cardio Weekly 的上游選題雷達。
- **加抓量**：調 `RETMAX`、`DAYS_BACK`。
- **提高 NCBI 速率上限**：申請免費 [NCBI API key](https://www.ncbi.nlm.nih.gov/account/)，在 repo Settings → Secrets and variables → Actions 新增 `NCBI_API_KEY`。

## 本機預覽

```bash
cd pulse-zhtw
python3 generate_pulse.py          # （可選）先抓最新資料
python3 -m http.server 8800        # 因為前端用 fetch()，必須用 http 開、不能 file://
# 瀏覽器開 http://127.0.0.1:8800/
```

## 部署到 GitHub Pages

```bash
cd pulse-zhtw
git init && git add -A && git commit -m "init EM Pulse 繁中版"
gh repo create em-pulse-tw --public --source=. --push     # 或手動到 github.com 開 repo 再 push
```

接著到 GitHub repo → **Settings → Pages** → Source 選 `Deploy from a branch`、Branch 選 `main` / `/ (root)`。
幾分鐘後網址為 `https://<帳號>.github.io/em-pulse-tw/`。之後每天清晨 Action 會自動更新 `data/pulse.json`，網站資料隨之更新。

> 首次部署後，建議到 Actions 頁手動按一次 **Run workflow** 確認排程正常。
