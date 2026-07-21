---
name: ad-copy-google_pmax_leads
description: >
  依「Google PMax-名單開發型」規格產生行銷文案的格式指引。適用場景見下方「適用平台」。
  觸發時機:需要撰寫此廣告類型的文案時。
---
# Google PMax-名單開發型
## 適用平台
Google Performance Max
## 特性說明
目標為蒐集諮詢名單（表單提交/來電），文案需降低填表門檻感，強調免費諮詢/專業信任。
## 長度規範
同PMax標準規格：標題3-15則30字元內，長標題1-5則90字元內，描述2-5則90字元內
## CTA風格
諮詢導向，如「免費諮詢」「立即預約諮詢」，降低承諾感門檻
## 建議結構
- 痛點/疑問角度標題群
- 專業信任長標題
- 降低門檻話術描述
## 標籤
platform:Google、campaign_type:PMax、objective:名單開發型
## 使用方式
此Skill可離線於本地資料運作,不強制依賴server啟動。若已有結構化品牌資料
(見`data/brands/{brand_id}.json`格式),可直接依上述規範產出文案,
無需啟動`server.py`或呼叫AI供應商。
## 版本
本Skill依`data/ad_types/google_pmax_leads.json`的version=1欄位產生,
若該筆廣告類型資料異動,需重新呼叫`regenerate_skill('google_pmax_leads')`同步更新本檔。
最後更新:2026-07-21
