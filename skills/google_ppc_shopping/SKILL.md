---
name: ad-copy-google_ppc_shopping
description: >
  依「Google PPC-購物廣告」規格產生行銷文案的格式指引。適用場景見下方「適用平台」。
  觸發時機:需要撰寫此廣告類型的文案時。
---
# Google PPC-購物廣告
## 適用平台
Google Shopping
## 特性說明
廣告內容（標題/描述/價格/圖片）主要來自商品Feed資料，非手寫文案主導，優化重點在Feed欄位品質而非傳統文案技巧。
## 長度規範
依Feed規格（商品標題建議150字元內，需含品牌/型號/關鍵屬性）
## CTA風格
N/A（系統制式呈現價格與商品資訊，無自訂CTA文字欄位）
## 建議結構
- Feed標題：品牌+商品名+關鍵屬性
- Feed描述：規格/賣點條列
## 標籤
platform:Google、campaign_type:PPC、format:shopping
## 使用方式
此Skill可離線於本地資料運作,不強制依賴server啟動。若已有結構化品牌資料
(見`data/brands/{brand_id}.json`格式),可直接依上述規範產出文案,
無需啟動`server.py`或呼叫AI供應商。
## 版本
本Skill依`data/ad_types/google_ppc_shopping.json`的version=1欄位產生,
若該筆廣告類型資料異動,需重新呼叫`regenerate_skill('google_ppc_shopping')`同步更新本檔。
最後更新:2026-07-21
