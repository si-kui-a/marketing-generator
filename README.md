# marketing-generator

婚紗行銷文案生成系統。本地優先、零第三方依賴、供應商中立。

完整規格見 `spec.md`(唯一真相來源),異動紀錄見 `rules_changelog.md`。

## 啟動(Day1 驗證用)

1. 安裝 Python 3.9+(無需任何套件)
2. `python server.py`
3. 瀏覽器開 `http://localhost:8765/brands`

## 現況

Day1 完成:目錄結構、spec、changelog、server 基本框架(/brands、/brand/<name>)、品牌模板×3。
Day2 待辦:Anthropic adapter、/generate、index.html。

## 用詞規範

規則比對功能一律稱「關鍵字比對輔助標記」,禁用「AI 分析」「自主學習」等用語。

## 對外 API(供其他工具整合,Phase5)

1. 於 `your-extensions/config.local.yaml` 填入 `api_key: "自訂隨機字串"`(使用者自行產生,不要使用範例值)
2. 呼叫時 Header 帶 `X-API-Key: <你的api_key>`
3. 開放端點(讀取 + generate,不含建立/刪除類CRUD):
   - `GET /api/brands`
   - `GET /api/brand/<id>`
   - `POST /api/generate`
   - `GET /api/performance/<brand>`
   - `GET /api/health`
4. 本系統為單執行緒 `http.server`,不保證伺服器端逾時中斷,呼叫端請自行設定 client 端 timeout 並優雅降級。
5. 對外 API 呼叫會在 `logs/activity.log` 額外記一行 `[API]` 前綴的紀錄;既有內部(UI)呼叫路徑完全不受影響。
