# 婚紗行銷文案生成系統 — 交接規格書 (spec.md)
version: 1.0

> 本檔案為唯一真相來源。任何未來的 Claude session 接手此專案時,先讀此檔,再讀 `rules_changelog.md`,再動工。

---

## 0. 交接須知(給接手的 Claude 讀)

- 這不是新專案,是已收斂七版以上架構討論後的**定案版本**,不要重新評估「要不要用網頁」「要不要用 Python」這類已決議問題。
- 若使用者要求新增功能,先對照本文件「已排除模組」章節,判斷是否重蹈已否決的複雜度。
- 系統核心誠實原則:**不得將規則比對/頻率計數包裝成「AI 學習」或「自主分析」**。這是使用者明確要求的用詞紅線,違反會造成長期預期落差。
- 修改任何規則、模板、關鍵字庫,必須同步寫一行到 `rules_changelog.md`,否則視為未完成。

---

## 1. 核心理念

| 原則 | 說明 |
|---|---|
| 本地優先 | 全程 localhost 運作,不架設對外伺服器,不依賴雲端資料庫 |
| 供應商中立 | 生成層透過 adapter 隔離,不綁定單一 AI 供應商,只需替換金鑰 + 選供應商類型 |
| 誠實機制命名 | 規則比對稱「關鍵字比對輔助標記」,計數稱「頻率統計」,禁用「自主學習」「AI 分析」等會誤導預期的詞 |
| 人工在迴圈中 | 任何機器產出的建議(標籤、預標記)必須經人工確認才落地,機器不自動決策 |
| 零高風險自動化 | 排除自動爬蟲、CI/CD、自動語意抽取,只保留寫死不變、無需持續除錯的固定腳本 |
| 可回溯可替換 | 資料層(md/YAML)與生成層(API 呼叫)分離,未來換模型或供應商,資料不需重建 |

---

## 2. 需求與範圍(重申)

1. 婚紗行銷文案生成,依廣告類型(IG/FB/SEO)產出多版本。
2. 品牌知識庫可依名稱查詢調用,不必重新輸入。
3. 商業機密僅存本機與私有 GitHub repo,不外流。
4. 成效紀錄以人工標記保留,供回溯與強化參考。
5. 演算法規則隨社群平台變化即時更新,更新需可追溯原因與時間。
6. 支援批次貼入多篇參考文案,快速預標記後人工確認、自動備份。
7. 架構可複製、長期可維護,不綁定任何單一模型或供應商。

---

## 3. 系統架構

```
marketing-generator/
├── index.html                 # 前端 UI,不含金鑰、不含供應商邏輯
├── server.py                   # 唯一對外溝通節點,零第三方套件依賴
├── start.command / start.bat   # 雙擊啟動,自動起 server + 開瀏覽器
├── .env                         # PROVIDER / API_KEY / MODEL,不進 Git
├── .gitignore                   # 排除 .env、暫存檔
├── providers/
│   ├── anthropic.py             # MVP 唯一實作
│   └── (預留位置,未來供應商依此格式擴充)
├── config/
│   └── keywords.yaml            # 關鍵字比對規則庫,人工維護
├── prompts/
│   ├── system_base.md
│   ├── wedding_ig.md            # 含 version / last_algo_update 欄位
│   ├── wedding_fb.md
│   └── wedding_seo.md
├── data/
│   ├── brand/brand-XXX.md
│   ├── sample/sample-XXX.md
│   ├── archive/YYYY/日期-品牌-類型.md
│   ├── tag_frequency.json       # 純計數,非語意
│   └── _local_backup/           # git 不可用時的降級備份
├── rules_changelog.md           # 規則異動紀錄,含觸發原因
├── README.md
└── spec.md                      # 本檔案
```

---

## 4. 供應商轉接層

| 項目 | Anthropic | OpenAI 相容端點(第二輪) |
|---|---|---|
| Endpoint | `api.anthropic.com/v1/messages` | `<base_url>/chat/completions` |
| 驗證標頭 | `x-api-key` | `Authorization: Bearer` |
| 回應取值 | `content[0].text` | `choices[0].message.content` |
| 特殊標頭 | `anthropic-version` | 無 |

`server.py` 依 `.env` 的 `PROVIDER` 欄位載入對應 `providers/*.py`,統一回傳 `{text: string}` 給前端。新增供應商 = 新寫一支 15–20 行 adapter,前端與資料層零異動。

---

## 5. API 端點清單

| 方法 | 路徑 | 功能 |
|---|---|---|
| GET | `/brands` | 掃描 `data/brand/` 檔名,回傳品牌清單 |
| GET | `/brand/<name>` | 回傳單一品牌 md 內容 |
| POST | `/generate` | 組合 brand + sample + prompt 模板,呼叫 provider,回傳 N 版文案 |
| POST | `/archive` | 寫入 `data/archive/YYYY/日期-品牌-類型.md`,含 YAML frontmatter |
| POST | `/tag` | 標記 archive 的 `performance_tag`,同步累加 `tag_frequency.json` |
| POST | `/samples/batch` | 批次貼入多篇文案,關鍵字比對後回傳預標記(未落地) |
| POST | `/samples/confirm` | 人工確認後正式寫入 `data/sample/`,觸發自動備份 |

技術要點:server.py 用 Python 內建 `http.server`,零 pip 安裝;明確回傳 `Access-Control-Allow-Origin: *` 解決 `file://` 呼叫 `localhost` 的 CORS 問題;無快取層,檔案即時讀取,改模板立即生效。

---

## 6. 資料結構規範

**archive frontmatter(僅 5 個核心欄位,不可增加)**

```yaml
brand_id: 唯美婚紗
prompt_version: v1.2
performance_tag: high | low | 未標記
structure_tags: [急迫CTA, 故事型]
notes: ""
```

**sample frontmatter**

```yaml
source: 貼入 / 手動輸入
suggested_tags: [關鍵字比對結果]
confirmed_tags: [人工確認結果]
confidence: 系統不判斷,固定留空由人工填
```

---

## 7. 關鍵字比對機制(誠實聲明)

`config/keywords.yaml` 為人工維護的字串比對規則庫,命中即掛建議標籤。**準確率不保證,不做語意理解**,任何 UI 文案與內部文件一律稱「關鍵字比對輔助標記」,禁稱「AI 分析」「自主學習」。使用者需持續手動擴充關鍵字庫以提升命中率。

---

## 8. 自動備份機制

| 情境 | 處理 |
|---|---|
| 本機已是 git repo 且已設定 user.name/email | `/samples/confirm` 成功後自動 `git add -A && git commit` |
| git 未設定或未安裝 | 降級為時間戳複製至 `data/_local_backup/YYYYMMDD_HHMM/`,純檔案操作零依賴 |
| 無網路 | commit 仍在本機完成,之後手動 `git push` 一次性同步 |

---

## 9. 日常執行 SOP

**首次設定(一次性,約 10 分鐘)**

1. 取得專案資料夾,填入 `.env` 的 `ANTHROPIC_API_KEY`。
2. 確認本機已裝 Python(無需額外套件)。
3. 雙擊 `start.command` / `start.bat` 測試能否正常開啟瀏覽器。

**日常生成(約 2 分鐘)**

雙擊啟動 → 選品牌 → 選廣告類型與版本數 → 按生成 → 檢視 → 按存檔(強制填 performance_tag)。

**批次匯入參考文案(約 3–5 分鐘)**

多篇文案以 `---` 分隔貼入 → 按解析 → 逐篇核對建議標籤 → 全部確認並存檔 → 自動觸發備份。

**演算法規則更新(不定期,約 5 分鐘)**

編輯 `prompts/*.md` → 於 `rules_changelog.md` 新增一行(日期/平台/異動摘要/觸發原因)→ 立即生效,無需重啟。

**每週備份**

GitHub Desktop 或指令列對整個資料夾 commit(`.env` 已排除,金鑰不上雲)。

---

## 10. 已排除模組(不重新評估,除非使用者明確聲明具備相關技能)

| 模組 | 排除原因 |
|---|---|
| 自動網頁爬蟲抓取來源 | 結構易變、易崩潰,維護成本高 |
| 語意抽取樣本結構 | 現有能力僅為關鍵字比對,非語意理解,不可包裝為「自動演進」 |
| 自動索引/自動觸發更新 | 一旦腳本壞掉,查詢流程全停,單人維護風險過高 |
| GitHub Actions CI/CD | 除錯成本高於效益,非工程背景維護者不宜 |
| 多供應商 Day1-3 同時做 | 對照 7 版反覆教訓,範圍蔓延風險,MVP 僅做 Anthropic 一家 |
| Flask 等第三方套件 | 增加安裝依賴,改用標準函式庫維持零依賴、長期可維護 |

---

## 11. 風險與應對總表(P > 60%)

| 風險 | 機率 | 應對 |
|---|---|---|
| 純前端方案金鑰外洩 | 75% | 一律經 server.py 端轉發,金鑰不落瀏覽器 |
| File System Access API 跨瀏覽器/裝置失敗 | 90% | 改由 server.py 直接讀寫檔案,不依賴此 API |
| 3 天內範圍蔓延 | 70–75% | Day1 鎖定 spec.md 後當日禁止修改範圍 |
| 關鍵字比對誤判 | 80% | 強制人工確認,不可批次跳過 |
| 使用者誤解比對=AI理解 | 65% | UI 與文件統一用詞紅線 |
| git commit 因未設定使用者資訊靜默失敗 | 65% | 首次設定加入 git 設定檢查,失敗需明確告警 |
| 忘記啟動 server 導致連線失敗 | 60% | index.html 加連線狀態偵測與提示 |

---

## 12. 三天排程(MVP)

| 天 | 內容 |
|---|---|
| Day1 | `data/` 結構、spec.md、2–3 家品牌 md、server.py 基本框架(`/brands` `/brand`) |
| Day2 | Anthropic adapter、`/generate` 接通、index.html 生成流程測試 |
| Day3 | `/archive` `/tag` 完成、`start.command/.bat`、GitHub 首次 commit(確認 `.env` 排除) |

批次匯入、自動備份、第二供應商屬第二輪擴充,不列入首版 3 天範圍。

---

## 13. 版本異動守則

`rules_changelog.md` 每行格式:

```
2026-07-17 | IG | wedding_ig.md v1.2 | 降低純文字貼文權重,加強首句提問結構 | 觸發原因:IG降觸及公告
```

不建立額外評分系統,commit message 僅標註 `[perf:high]` / `[perf:low]` 即足夠追溯。
