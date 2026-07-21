---
name: ad-copy-google_pmax_store
description: >
  依「Google PMax-來店型」規格產生行銷文案的格式指引。適用場景見下方「適用平台」。
  觸發時機:需要撰寫此廣告類型的文案時。
---
# Google PMax-來店型
## 適用平台
Google Performance Max
## 特性說明
目標為導引實體門市到訪，需綁定Google商家檔案，文案強調地點便利性/到店誘因。
## 長度規範
同PMax標準規格
## CTA風格
到店導向，如「立即導航前往」「到店享優惠」
## 建議結構
- 地點/便利性角度標題群
- 到店誘因描述
- 導航型CTA
## 標籤
platform:Google、campaign_type:PMax、objective:來店型
## 使用方式
此Skill可離線於本地資料運作,不強制依賴server啟動。若已有結構化品牌資料
(見`data/brands/{brand_id}.json`格式),可直接依上述規範產出文案,
無需啟動`server.py`或呼叫AI供應商。
## 版本
本Skill依`data/ad_types/google_pmax_store.json`的version=1欄位產生,
若該筆廣告類型資料異動,需重新呼叫`regenerate_skill('google_pmax_store')`同步更新本檔。
最後更新:2026-07-21
