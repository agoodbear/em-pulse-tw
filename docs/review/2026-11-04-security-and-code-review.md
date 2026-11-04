# EM Pulse 繁中版：安全稽核與 Code Review（2026-11-04）

> 範圍：`generate_pulse.py`、`index.html`、`empopular/index.html`、`journals.json`、`.github/workflows/`、`data/pulse.json`（只檢查資料，不修改）
> 分支：`claude/keen-bardeen-vrr6n2`（未 push main、未 merge、未部署）

---

## 0. 一句話結論

**這不是 Node 專案，`npm audit` 不適用**（沒有 `package.json`/lockfile，執行結果為 `ENOLOCK`）。專案也沒有任何第三方套件（Python 只用標準函式庫，前端是原生 JS），所以**沒有相依套件漏洞要修，也沒有框架需要大升級**。
真正的安全問題在前端：**PubMed 的第三方文字直接塞進 `innerHTML`**（中度風險，已修）。另外修了 4 個正確性 bug，新增 52 項單元測試，並加上 `make build`／`make test` 和 PR 用的 CI。

---

## 1. 相依套件稽核

| 項目 | 結果 | 說明 |
|---|---|---|
| `npm audit` | **不適用** | 無 `package.json`、無 lockfile → `npm error code ENOLOCK`。前端零框架、無打包。 |
| Python 相依 | **無** | `generate_pulse.py` 只 import 標準函式庫，沒有 `requirements.txt`，pip-audit 沒有東西可以掃。 |
| Python 執行環境 | OK | CI 用 `actions/setup-python@v5` 搭配 `'3.12'`，每次都會拿到 3.12 最新 patch 版（含 stdlib 安全修補）。 |
| GitHub Actions | 低風險，**未改** | `actions/checkout@v4`、`actions/setup-python@v5` 用的是 major tag，不是 commit SHA，見 S4。 |
| 外部 CDN 腳本 | 低風險，**未改** | Google Tag Manager（gtag）與 Google Fonts，無 SRI、無 CSP，見 S3。 |

### 框架大升級清單

**無。** 專案沒有使用任何框架或函式庫，因此沒有需要大版本升級的項目。

---

## 2. 發現清單

嚴重度：🔴 高｜🟠 中｜🟡 低｜⚪ 資訊

### 2.1 安全性

| # | 嚴重度 | 位置 | 問題 | 狀態 |
|---|---|---|---|---|
| S1 | 🟠 | `index.html` `renderAOW`/`renderCard`/`renderKeywords`/篩選標籤/錯誤訊息 | `title`、`abstract`、`journal`、`authors`、`keywords`（含放進 `data-kw="…"` 屬性的值）、`url`、`articleType`/`journalTier`（被當成 class 名稱）全部未跳脫就用 template string 塞進 `innerHTML`。這些都是 PubMed 第三方內容。今天的 532 筆中有 177 筆含 `< > & "` 字元（例如 `<1 year`、`H&E`），只是剛好沒有組成合法 tag 才沒出事；只要哪天出現 `<i…`、`<sup` 或含 `"` 的關鍵字，就會破版或被注入（stored XSS）。 | ✅ 已修：新增 `esc()`、`safeUrl()`（只允許 http/https）、`tierOf()`/`typeOf()` 白名單 |
| S2 | 🟠 | `empopular/index.html` `buildCloud`、錯誤區塊 | 關鍵字 `word` 與 `err.message` 未跳脫就進 `innerHTML`。 | ✅ 已修：同樣加上 `esc()` |
| S3 | 🟡 | 兩個 HTML `<head>` | 沒有 Content-Security-Policy；gtag 屬於動態腳本，無法使用 SRI。S1/S2 修好後殘餘風險低。 | ❌ 未改，建議見 §4 |
| S4 | 🟡 | `.github/workflows/update-pulse.yml` | Actions 用 tag 而非 SHA 固定，且 job 具備 `contents: write`，可以直接 push main（也就是會觸發 Pages 部署）。若上游 action 被入侵，就能改站。 | ❌ 未改（屬於部署管線），建議見 §4 |
| S5 | ⚪ | `generate_pulse.py:36` | `EMAIL` 寫死在公開 repo（NCBI 禮貌參數本來就要求提供），會被爬蟲收集。 | ❌ 未改（要不要改成環境變數由你決定） |
| S6 | ⚪ | `empopular/index.html` | 瀏覽器端直接打 NCBI eutils，沒帶 `tool`/`email`；流量由每位訪客的 IP 各自承擔，NCBI 限制約每秒 3 次。目前可接受。 | 未改 |

### 2.2 正確性 / 穩健性

| # | 嚴重度 | 位置 | 問題 | 狀態 |
|---|---|---|---|---|
| B1 | 🟠 | `index.html` `relDate` | (a) 期刊預排的**未來日期**會顯示成「**-27 天前**」：今天的資料有 16 篇 `pubDate=2026-12-01`，用 Playwright 在實際頁面上重現過。(b) `new Date('YYYY-MM-DD')` 會被當成 **UTC** 午夜；台灣 06:00 更新時，當天的文獻算出來是 -2 小時，結果顯示「-1 天前」。 | ✅ 已修：改用本地日曆日計算，未來日期直接顯示日期 |
| B2 | 🟡 | `index.html` `relDate`/`renderStats` | 不合法的日期會顯示「Invalid Date」；`2026-00-00` 會被 JS 自動滾成 2025/11/30（新測試抓到的）。 | ✅ 已修 |
| B3 | 🟡 | `generate_pulse.py` `main` | (a) `pulse.json` 直接覆寫，排程中途被砍掉會留下半截 JSON，整站就白屏。(b) esearch 有結果但 efetch 解析出 0 篇時，會寫入空清單蓋掉昨天的資料。 | ✅ 已修：`write_json_atomic()`（暫存檔 + `os.replace`）；0 篇時 exit 1、不覆寫 |
| B4 | 🟡 | `generate_pulse.py` `parse_pubdate` | `<Month>Nov-Dec</Month>` 會被解析成 01 月；history fallback 缺月日時會產出 `2026-00-00`。 | ✅ 已修 |
| B5 | 🟠 | `generate_pulse.py` `esearch` | `RETMAX=600`，**今天已有 532 筆，接近上限**。超過時 PubMed 只回前 600 筆，而且**完全不會提示**（依 pub_date 排序，被丟掉的是較舊的文獻）。 | ⚠️ 部分處理：加了 stderr 警告；**沒有改抓取邏輯**（調高 RETMAX 或分頁由你決定） |
| B6 | 🟠 | `generate_pulse.py` `impact_score` | **未來日期直接拿滿新近度 +10**（`max(0, 負數天)` = 0 天），缺日期也會被當成今天。今天這 16 篇 12 月期號的文獻因此排名偏高。 | ❌ 未改：會改變排名，屬於計分設計，建議見 §4 |
| B7 | 🟡 | `empopular/index.html` `getColor` | `colorMap` 用 `{}`，遇到 `constructor` 這類關鍵字會拿到原型鏈上的函式當顏色。 | ✅ 已修：`Object.create(null)` |
| B8 | ⚪ | `index.html` `renderStats` | 「更新時間」只顯示時:分、沒有日期；排程如果連續壞好幾天，使用者也看不出資料已經過期。 | 未改（UI 調整） |
| B9 | ⚪ | `empopular/index.html` | 期刊清單（64 本）寫死，跟 `journals.json`（59 本）是兩套，而且已經不一致；統計卡上的「64」也是寫死的。 | 未改 |
| B10 | ⚪ | `index.html` `loadData` | `?t=Date.now()` 讓約 1 MB 的 `pulse.json` 每次都無法被快取。 | 未改 |
| B11 | ⚪ | `index.html` CSS `@media (max-width:840px)` | 手機版直接隱藏側欄，熱門關鍵字篩選在手機上用不到。 | 未改 |
| B12 | ⚪ | `index.html` `<title>`、nav、footer | 頁面標題與導覽列都標示「Derin Soluk」並連到原作者網站。這是品牌/授權問題，不是技術問題，建議確認原作者是否同意。 | 未改 |

---

## 3. 驗證方式

### 3.1 改動前 baseline
```
npm audit                  → ENOLOCK（無 lockfile，不適用）
python3 -m py_compile      → OK
JSON 驗證（journals/pulse）→ OK
node --check 內嵌 JS        → OK（兩頁）
單元測試                   → 不存在（0 項）
```

### 3.2 改動後
```
make build   → 6/6 檢查通過（Python 語法、journals.json tier、pulse.json schema 532 篇、兩頁內嵌 JS 語法）
make test    → Python 37/37 通過；前端 15/15 通過
```
- `generate_pulse.py` 覆蓋率 **98%**（coverage.py；沒覆蓋到的是 `efetch` 中途 sleep 的分支、`if __name__` 等）。
- 前端腳本在 `node:vm` 沙箱中執行，Node 的覆蓋率工具量不到，所以**不提供前端覆蓋率數字**。
- **Playwright 實機驗證**（本機 `http.server` + 真實 `data/pulse.json`）：
  - 修改前：頁面出現「-27 天前」。
  - 修改後：負天數 0 筆；本週精選、RCT 篩選（13 篇）、關鍵字篩選、分頁（2/18）正常；console 0 個錯誤。

### 3.3 沒有驗證到的部分
- **實際連 PubMed 跑產生器**：此雲端環境的網路政策擋掉 `eutils.ncbi.nlm.nih.gov`（proxy 回 403）。產生器的網路層只用 mock 測過；從 log 可以看到重試邏輯有照設計跑滿 4 次後才失敗。
- EM Popular 頁同樣因為連不到 NCBI 而無法實際渲染文字雲，只驗證了錯誤畫面有正確顯示且有跳脫。

---

## 4. 建議下一步（依優先序）

1. **B5 RETMAX**：今天 532/600，一兩個大期刊出刊日就會超過。建議把 `RETMAX` 調到 2000，或改用 `usehistory=y` + `retstart` 分頁。
2. **B6 新近度計分**：建議改用 PubMed 收錄日（`PubMedPubDate[@PubStatus='pubmed']`，也就是「本週新出現」）算新近度，期號日期只拿來顯示；或者未來日期一律 `days_old = DAYS_BACK`。這會改變排名，所以等你決定。
3. **S4 Actions 安全**：把 `uses:` 改成 commit SHA 固定，並加 `.github/dependabot.yml`（`package-ecosystem: github-actions`）自動提 PR 更新。另外建議在 `update-pulse.yml` 的 commit 前先跑 `make build`，避免壞掉的 `pulse.json` 被推上 main。
4. **S3 CSP**：在兩頁加
   `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; connect-src 'self' https://*.google-analytics.com https://eutils.ncbi.nlm.nih.gov; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https://*.google-analytics.com">`
   上線前要先在瀏覽器確認 GA 仍然能送資料。
5. **B8/B10**：更新時間加上日期；cache-busting 改用 `generatedAt` 或直接拿掉。
6. **B9**：EM Popular 改成讀 `journals.json`，消除兩套清單。

---

## 5. 本次新增 / 修改檔案

| 檔案 | 類型 |
|---|---|
| `index.html` | 修：XSS 跳脫、白名單、`relDate` 日期 bug、`sw` 上下限 |
| `empopular/index.html` | 修：XSS 跳脫、`getColor` 原型鏈 |
| `generate_pulse.py` | 修：原子寫檔、0 篇不覆寫、`parse_pubdate` 邊界、RETMAX 截斷警告 |
| `tests/test_generate_pulse.py`、`tests/fixtures/efetch_sample.xml` | 新：37 項 Python 單元測試 |
| `tests/frontend.test.mjs` | 新：15 項前端單元／整合測試（`node:test` + `vm`，零相依） |
| `scripts/build_check.py`、`Makefile` | 新：`make build`、`make test` |
| `.github/workflows/test.yml` | 新：PR／非 main 分支 push 時跑 build + test（唯讀權限，不 commit、不部署） |
