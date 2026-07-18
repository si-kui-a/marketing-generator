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
