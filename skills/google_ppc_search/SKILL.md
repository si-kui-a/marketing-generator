---
name: ad-copy-google_ppc_search
description: >
  依「Google PPC-搜尋廣告」規格產生行銷文案的格式指引。適用場景見下方「適用平台」。
  觸發時機:需要撰寫此廣告類型的文案時。
---
# Google PPC-搜尋廣告
## 適用平台
Google Search Network
## 特性說明
文字為主，出現於使用者主動搜尋結果，需直接對應搜尋意圖關鍵字，相關性要求高。
## 長度規範
標題最多15則，每則30字元內；描述最多4則，每則90字元內；網址路徑2組，每組15字元內
## CTA風格
直接對應搜尋意圖，如「立即查詢價格」「線上預約」
## 建議結構
- 關鍵字對應標題
- 賣點/差異化描述
- 明確CTA
## 標籤
platform:Google、campaign_type:PPC、format:search
## 使用方式
此Skill可離線於本地資料運作,不強制依賴server啟動。若已有結構化品牌資料
(見`data/brands/{brand_id}.json`格式),可直接依上述規範產出文案,
無需啟動`server.py`或呼叫AI供應商。
## 版本
本Skill依`data/ad_types/google_ppc_search.json`的version=1欄位產生,
若該筆廣告類型資料異動,需重新呼叫`regenerate_skill('google_ppc_search')`同步更新本檔。
最後更新:2026-07-21
