# 規則異動紀錄

格式:`日期 | 平台 | 異動檔案與版本 | 異動摘要 | 觸發原因`
每次修改 `prompts/*.md` 或 `config/keywords.yaml`,新增一行,不刪除舊紀錄。

2026-07-18 | 系統 | spec.md v1.0 | 初始化架構規格書與交接文件 | 觸發原因:專案啟動,Day1 建檔
2026-07-18 | 全平台 | prompts/system_base.md+wedding_ig/fb/seo.md v1.0 | 建立系統基底與三類型模板初版 | 觸發原因:Day2 排程建檔
2026-07-18 | 系統 | server.py v3.0 | 新增 /archive /tag 端點,完成 MVP 三天排程 | 觸發原因:Day3 排程建檔
2026-07-18 | 全平台 | server.py+index.html+config/styles.json | 新增品牌 UI 管理、prompts 編輯器、文風選項(固定+自訂) | 觸發原因:第二輪功能擴充
<!-- 以下為範例格式,非真實紀錄,首次實際異動時刪除本行以下範例 -->
<!-- 2026-07-20 | IG | wedding_ig.md v1.1 | 加強首句提問結構,降低純文字貼文比重 | 觸發原因:IG 降觸及公告 -->
2026-07-18 | prompts | wedding_ig.md | 驗收測試:確認 prompts/save 與 auto git commit 功能正常(內容未變更) | 觸發原因:UI 編輯器存檔
2026-07-18 | prompts | wedding_ig.md | 驗收測試:確認 encoding=utf-8 修正後 auto git commit 回報正確狀態(內容未變更) | 觸發原因:UI 編輯器存檔
2026-07-18 | 系統 | spec.md v2.0 | 架構從本地優先改為 GitHub 優先,data/ 目錄移除,Contents API 為資料層 | 觸發原因:多裝置同步需求
2026-07-18 | prompts | wedding_ig.md | 驗收測試，將還原 | 觸發原因:UI 編輯器存檔
2026-07-18 | prompts | wedding_ig.md | 驗收測試已還原原始內容 | 觸發原因:UI 編輯器存檔
2026-07-18 | prompts | wedding_ig.md | 驗收測試已還原原始內容(修正結尾換行) | 觸發原因:UI 編輯器存檔
2026-07-18 | 系統 | spec.md v2.1 | 修正 GitHub 架構描述:本機 data/ 非獨立資料,為同一 repo 的安全網,§E 移除操作永久停用 | 觸發原因:§E 執行導致 GitHub 真實資料誤刪事故,已 revert
2026-07-21 | 系統 | spec.md v3 + server.py + index.html | 目錄結構重建、品牌/文風格式遷移為JSON、新增廣告類型管理模組(Phase1) | 觸發原因:v3規格書導入,DA Trainer整合準備
2026-07-21 | 系統 | server.py + index.html | 新增修正案例庫(Phase2):diff引擎、保留政策、/generate結果頁儲存功能 | 觸發原因:Master Spec v3.0 Phase2實作
2026-07-21 | 系統 | server.py + index.html | 新增標籤統計(Phase3):增量更新(create+1/delete-1)、手動重算、查詢端點;封存不觸發統計異動 | 觸發原因:Master Spec v3.0 Phase3實作
2026-07-21 | 系統 | server.py + index.html | 新增成效登記(Phase4):/performance/create、/performance/<brand>查詢,含懸空參照軟性檢查 | 觸發原因:Master Spec v3.0 Phase4實作
2026-07-21 | 系統 | server.py | 新增對外API(Phase5):/api/*前綴+X-API-Key驗證,複用既有內部handler邏輯 | 觸發原因:Master Spec v3.0 Phase5實作,為Phase6 DA Trainer整合鋪路
2026-07-21 | 系統 | server.py | 修復log_message對/api/路徑的雙重記錄問題,外部呼叫改為僅記錄一行[API]標記 | 觸發原因:Phase5驗收後發現的日誌縫隙(見governance-lessons v1.4)
2026-07-21 | 系統 | server.py | 新增Skill封裝(Phase8.1):regenerate_skill()函式+端點,五筆廣告類型SKILL.md已產生 | 觸發原因:Master Spec v3.0 Phase8.1實作,start_all.py因依賴DA Trainer暫緩
2026-07-21 | 系統 | server.py | 補齊/api/revisions系列端點白名單(revisions/revision/<id>/revision_stats/recompute),解決DA Trainer整合缺口 | 觸發原因:DA Trainer交接文件§1.2指出的已知缺口
2026-07-22 | 系統 | server.py + index.html | 移除prompts模板系統,/generate改為讀取ad_types作為唯一廣告類型來源,system_base規則內嵌程式碼 | 觸發原因:使用者需求——生成頁廣告類型應對應真實ad_types資料而非寫死IG/FB/SEO
