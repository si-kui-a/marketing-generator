---
name: ad-copy-google_pmax_sales
description: >
  依「Google PMax-銷售型」規格產生行銷文案的格式指引。適用場景見下方「適用平台」。
  觸發時機:需要撰寫此廣告類型的文案時。
---
# Google PMax-銷售型
## 適用平台
Google Performance Max
## 特性說明
系統自動跨版位（搜尋/多媒體/YouTube/Discover/Gmail/地圖）組合素材，目標為線上銷售/轉換，需完整素材組供AI測試組合。
## 長度規範
標題3-15則，每則30字元內（建議至少1則15字元內）；長標題1-5則，每則90字元內；描述2-5則，每則90字元內；商家名稱1個25字元內
## CTA風格
急迫/導購型，直接對應購買行動，需涵蓋不同角度（優惠/急迫感/品牌信任/社群證明）避免15則標題語意重複
## 建議結構
- 多角度標題組（優惠/賣點/急迫/信任各準備數則）
- 長標題完整價值陳述
- 描述補充細節與CTA
## 標籤
platform:Google、campaign_type:PMax、objective:銷售型
## 使用方式
此Skill可離線於本地資料運作,不強制依賴server啟動。若已有結構化品牌資料
(見`data/brands/{brand_id}.json`格式),可直接依上述規範產出文案,
無需啟動`server.py`或呼叫AI供應商。
## 版本
本Skill依`data/ad_types/google_pmax_sales.json`的version=1欄位產生,
若該筆廣告類型資料異動,需重新呼叫`regenerate_skill('google_pmax_sales')`同步更新本檔。
最後更新:2026-07-21
