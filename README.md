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
