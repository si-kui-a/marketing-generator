# marketing-generator — Master Spec v3.0(完整合併版)

> 本檔取代所有前版文件(v3原始規格、local_kit_architecture v1.0/v2.0/v2.1、
> functional_spec_operational_logic v1.1、phase2_spec、phase3_spec、phase5-8_spec)。
> 前版文件保留於對話歷史供考古,不再更新,任何衝突以本檔為準。
> 交接對象:Claude Code。這是唯一交付依據。

---

## 0. 專案定位與核心原則(不可違反)

一套本地運行的婚紗品牌行銷文案生成工具,供使用者日常兼職工作使用,同時作為GitHub作品集展示。

1. **零依賴、輕量化**:純Python標準庫,不引入Web framework
2. **誠實原則**:規則式比對/統計一律誠實標示,禁用「AI學習」「自主學習」等誤導用詞;AI輔助推論須明確標示、可見、可覆寫、可在AI不可用時降級
3. **機密保護**:真實品牌資料只存private repo,公開部分(程式邏輯/schema/空白模板)與機密嚴格分離
4. **架構已定案**:localhost + Python標準庫 + GitHub Contents API,不重啟技術棧討論
5. **安全機制的判準**:能否寫成自動化測試覆蓋。「文字規則靠AI記得」一律視為不可靠,必須有技術強制點

---

## 1. 系統總覽

```
使用者(瀏覽器 localhost:8765)
        │
        ▼
server.py(Python標準庫 http.server,手動路由)
        │
        ├── import local_kit.*(config_loader/safe_git/json_collection/logger/migration_tracker)
        ├── 讀寫 → GitHub Contents API(唯一正本,private repo,每次寫入即時commit)
        ├── 讀寫 → 本地 data/ 目錄(與GitHub同一份資料,非獨立備份,此為Phase1事故後的準確認知)
        └── 選配呼叫 → Claude API(AI輔助推論,逾時或無Key時降級為規則式/手動模式)

對外API(Phase5起,供DA Trainer與其他工具整合,通用設計非量身打造)
        │
        └── 全部內部端點 + X-API-Key驗證 + source="API"日誌標記
```

---

## 2. local-kit 共用模組(跨 marketing-generator 與 da-stats-trainer)

### 2.1 目錄結構

```
~/dev/
├── local-kit-source/              ← 唯一正本,獨立git repo
│   ├── config_loader.py
│   ├── safe_git.py
│   ├── json_collection.py
│   ├── logger.py
│   ├── migration_tracker.py
│   ├── VERSION
│   ├── scripts/
│   │   ├── install_hooks.py       ← 跨OS git hook安裝
│   │   └── pre_commit_guard.py
│   └── tests/
│       ├── test_safe_git.py       ← 優先度最高
│       ├── test_pre_commit_guard.py
│       ├── test_migration_tracker.py
│       └── test_config_loader.py  ← 須覆蓋:正常啟動/moved未verified拒絕啟動/降級模式
│
├── marketing-generator/
│   ├── local_kit/                 ← sync_local_kit.sh 複製而來,非symlink
│   ├── server.py
│   ├── config.default.yaml
│   ├── your-extensions/config.local.yaml   ← .gitignore排除
│   ├── data/{brands,styles,ad_types,performance,revisions,revision_stats,sample}/
│   ├── MIGRATION_STATUS.json
│   ├── logs/{activity,error}.log
│   ├── skills/{ad_type_id}/SKILL.md
│   └── scripts/sync_local_kit.sh
│
└── da-stats-trainer/
    ├── local_kit/
    ├── app.py
    ├── core/stats_engine.py       ← 供跨專案import(見§8.2)
    └── ...
```

**同步機制**:`sync_local_kit.sh` 執行 `cp -r ../local-kit-source/*.py ./local_kit/` + 寫入VERSION + 獨立commit(`sync: local_kit v{VERSION}`)。非symlink,避免跨機器相容性問題。

### 2.2 `config_loader.py`(含強制遷移檢查,最終版)

```python
def load_config(project_root: str, allow_degraded_start: bool = False) -> dict:
    """
    1. 讀 config.default.yaml(不存在則 raise FileNotFoundError,拒絕啟動)
    2. 若 your-extensions/config.local.yaml 存在,深度合併覆蓋
    3. 強制檢查:MigrationTracker.list_unverified()
       - 非空 且 allow_degraded_start=False → raise RuntimeError,啟動中止
       - 非空 且 allow_degraded_start=True → config["_degraded_mode"]=True,
         印巨大警告,所有寫入操作將回503
    4. 顯示 local_kit/VERSION(純資訊性,不做比對防呆,不假裝是檢查機制)
    5. 回傳合併後 dict
    """
```

**降級模式啟動**:`ALLOW_DEGRADED_START=1 python server.py`,此模式下所有 `Collection.create()/delete()` 呼叫前統一檢查 `config.get("_degraded_mode")`,是則回 503「系統處於降級模式,寫入操作暫停」。不提供跳過檢查的隱藏參數,緊急情況只能降級唯讀,不能繞過。

**實作補充(Phase1實測校正)**:降級狀態的判定僅在 server.py 啟動時(import/module-level)執行一次,不逐請求重新呼叫 `load_config()`。逐請求重算會讓「同一次連續執行完safe_delete→POST建新資料→mark_verified→purge_deprecated」這個設計目標失效——因為Step2本身就是在對應path仍為`moved`狀態下對 `Collection.create()` 寫入,若逐請求檢查會被自己的降級機制擋下。長時間運行的process也不應在背景其他流程把migration狀態改成moved後,對現有連線悄悄開始擋寫入。

### 2.3 `safe_git.py`(批次遷移專用,5個函式)

```python
def safe_delete(path, project_root):
    """
    前置:git status必須clean,否則中止並列出髒污檔案。
    1. git mv {path} {path}_deprecated
    2. migration_tracker.record(path, "moved", note)
    3. safe_commit("migrate: mv {path} to deprecated [1/3]",
                    allowed_scope=[path, f"{path}_deprecated", "MIGRATION_STATUS.json"])
    """
def mark_verified(path, project_root, note):
    """
    前置:狀態必須為'moved',否則拒絕。note不可為空字串(強制寫明具體驗證方式)。
    人工呼叫,AI不可自行判定「應該沒問題」就呼叫。
    """
def purge_deprecated(path, project_root):
    """
    前置:狀態必須為'verified',否則raise PermissionError(硬性阻擋)。
    互動式 input("確認刪除以上檔案?[yes/N] ") 供最終人工確認。
    1. git rm -r {path}_deprecated
    2. migration_tracker.record(path, "purged", "")
    3. safe_commit("migrate: purge {path}_deprecated [3/3]", ...)
    """
def rollback_migration(path, reason, project_root):
    """
    僅適用狀態='moved'(尚未verified)。reason不可為空。
    git mv {path}_deprecated {path} → record(path, "rolled_back", reason) → safe_commit
    """
    # 若已verified才發現問題:不提供自動化撤銷,走人工re_migrate流程:
    # 1. 檢查data/{x}_deprecated是否還在(未purge則還能rollback)
    # 2. 已purge則 git log --diff-filter=D --oneline -- {path}_deprecated 定位commit,
    #    git show {commit}^:{path}_deprecated/{file} 取回內容,人工逐筆核對修正
def safe_commit(message, allowed_scope, project_root):
    """
    比對邏輯:前綴比對,路徑正規化為'/'分隔(處理Windows'\\')。
    scope統一加'/'結尾比對,避免'data/brand2'誤判屬於'data/brand'範圍。
    任一staged檔案未命中allowed_scope任一項 → raise PermissionError,
    列出「超出宣告範圍」清單,要求拆分commit。
    """
```

**實作補充(Phase1事故修正)**:`_run()` 的 `subprocess.run()` 必須明確指定 `encoding="utf-8"`。Windows 主控台預設編碼(如 zh-TW 的 cp950)無法解碼 git 輸出的中文檔名,`text=True` 若不指定 encoding 會在背景 reader thread 拋出 `UnicodeDecodeError`,導致 `stdout` 靜默變成 `None`,後續 `.strip()` 對 `None` 呼叫拋出 `AttributeError`,讓整個遷移操作在「檔案已 mv、tracker已記錄」但「commit未完成」的中間狀態卡住。

**兩層刪除保護分工表**(消除歷史文件矛盾):

| 保護機制 | 管轄對象 | 對日常CRUD是否生效 |
|---|---|---|
| UI按住3秒 | 前端操作意圖確認 | ✅ 唯一防線 |
| GitHub sha樂觀鎖 | 併發修改衝突 | ✅ 生效 |
| `pre_commit_guard.py`(git hook) | 僅本地git歷史中的檔案刪除 | ❌ 不生效(日常CRUD走GitHub API直接刪除,從未產生本地commit) |
| `safe_git`五函式 | 僅批次格式遷移 | ❌ 不適用 |

**日常單筆刪除(`Collection.delete()`)定案不經過safe_git**:理由——已有UI按住3秒防呆;GitHub commit歷史可回溯;safe_git保護的是「批次結構性遷移」,風險等級不同,套用會拖慢日常操作。

### 2.4 `pre_commit_guard.py`(Git Hook)

```
安裝:python scripts/install_hooks.py(跨OS,見§2.7),兩專案各裝一次
邏輯:
1. git diff --cached --name-status,篩出狀態'D'(deleted)的檔案
2. 對每個刪除檔案,反查migration_tracker中對應path(去除_deprecated後綴)的狀態
3. 狀態不在 {"verified", "purged"} → exit(1),固定格式錯誤訊息:
   "❌ 阻擋commit:偵測到刪除{filename},但migration_tracker中狀態為{status}
   (需為verified或purged)。請先執行mark_verified()並提供具體驗證說明,
   或此操作不應包含在本次commit中。"
4. 找不到MIGRATION_STATUS.json → 視為未啟用批次遷移保護,直接放行
```

`--no-verify` 為CLAUDE.md列為絕對禁止的紅線指令,出現即需人工複核,AI不可自行決定使用。

**實作補充(Phase1事故修正,兩處)**:
1. 與 §2.3 同理,兩處 `subprocess.run()` 皆須指定 `encoding="utf-8"`,否則中文檔名會讓 hook 本身以未捕捉例外崩潰、非零結束碼阻擋commit。
2. 第 3 步驟允許狀態為 `"verified"` **或** `"purged"`,不可只允許 `"verified"`:`purge_deprecated()` 自身在呼叫 `git commit` 之前就已把 tracker 狀態寫成 `"purged"`,若 hook 只放行 `"verified"`,會變成 `purge_deprecated()` 自己產生的合法 commit 被此 hook 反過來擋下(執行到一半時磁碟上的狀態已經是 purged,而非 verified)。

### 2.5 `migration_tracker.py`

```python
class MigrationTracker:
    def record(self, path, status, note=""):
        # status: "moved"|"verified"|"purged"|"rolled_back"
        # 寫入{path: {history: [...]}},非覆寫,保留歷史陣列
    def get_status(self, path) -> str | None: ...
    def list_pending_purge(self) -> list[str]:
        # status='verified'但未purged
    def list_unverified(self) -> list[str]:
        # status='moved'但未verified,代表危險殘留狀態
```

檢查點已從「session開場靠AI記得」改為「寫死在config_loader.load_config()執行序列」,與AI是否記得無關(見§2.2)。

### 2.6 `json_collection.Collection`(通用CRUD引擎)

```python
class Collection:
    def __init__(self, gh_prefix, id_field, default_fields, env_loader): ...
    def list(self) -> list[str]:
        """GitHub連線失敗→502,不快取舊資料掩蓋失敗"""
    def get(self, item_id) -> dict:
        """
        不存在→404
        JSON解析失敗(檔案損毀)→500,訊息明確標註「資料格式錯誤非找不到檔案」
        兩種錯誤不可混用同一訊息,避免除錯誤判方向
        """
    def create(self, item_id, data, extra_fields=None) -> dict:
        """
        1. 先get()檢查是否已存在 → 存在則409 Conflict
        2. default_fields ← data ← extra_fields 合併(後者覆蓋前者)
        3. 自動補version=1/last_updated(若未提供)
        4. json.dumps(ensure_ascii=False, indent=2)
        5. _gh_put,失敗即該筆未建立,重呼叫即可,無需回滾邏輯
           (GitHub為唯一正本、無本地暫存設計,故無中間不一致狀態)
        """
    def delete(self, item_id) -> bool:
        """
        不經過safe_git(見§2.3說明)。
        1. get()取sha,不存在→404
        2. _gh_delete,sha不符(樂觀鎖失敗)→409「該筆資料已被其他操作修改,請重新整理」
        """
```

**不提供`update()`**:修正案例等歷史紀錄類資料一旦寫入不應被竄改,要修正用delete()重建(僅適用未verified的批次遷移情境例外,見§2.3 rollback)。品牌/文風/廣告類型的「更新」操作留待有實際需求時再議,非本階段範圍。

### 2.7 跨OS Git Hook安裝

```python
# scripts/install_hooks.py
def find_python_cmd():
    for cmd in ["python3", "python"]:
        if shutil.which(cmd): return cmd
    raise RuntimeError("找不到python3或python指令")
def install():
    repo_root = subprocess.run(["git","rev-parse","--show-toplevel"], ...).stdout.strip()
    py_cmd = find_python_cmd()
    hook_path = os.path.join(repo_root, ".git", "hooks", "pre-commit")
    content = f'#!/bin/sh\n{py_cmd} "$(git rev-parse --show-toplevel)/scripts/pre_commit_guard.py"\nexit $?\n'
    with open(hook_path, "w", newline="\n") as f: f.write(content)  # 強制LF
    os.chmod(hook_path, os.stat(hook_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
```

README需註明:`pip install -r requirements.txt` 後必須執行 `python scripts/install_hooks.py`,git hooks不隨clone自動生效。

### 2.8 `logger.py`

```python
def log(project_root, filename, line, source="UI"):
    # 寫入 {project_root}/logs/{filename},格式 "[{source}] {line}"
    # source: "UI" | "API" | "SYSTEM"
```

---

## 3. Phase 1:目錄重建 + 品牌/文風JSON化 + 廣告類型管理 【已完成】

### 3.1 品牌 Schema(`data/brands/{brand_id}.json`)

```json
{
  "brand_id": "唯美婚紗",
  "name": "唯美婚紗",
  "positioning": "(待填)",
  "target_audience": "(待填)",
  "selling_points": [],
  "legacy_notes": [
    {"label": "Google 地圖評價", "content": "(待填)"},
    {"label": "活動頁面文案", "content": "(待填)"}
  ],
  "version": 1,
  "last_updated": "2026-07-18"
}
```

`Collection("data/brands/", "brand_id", BRAND_DEFAULTS, _load_env)`

### 3.2 文風 Schema(`data/styles/{style_id}.json`)

```json
{
  "style_id": "warm_story",
  "name": "溫暖敘事",
  "description": "以故事視角帶入新人的情感旅程,語氣溫柔、有畫面感。",
  "sample_copy": "",
  "version": 1
}
```

**slug生成邏輯(實作校正)**:規格原文描述四層(內建對照表 → pypinyin轉拼音 → 碰撞流水號 → timestamp fallback),但 §0 核心原則明訂「零依賴、純Python標準庫」不可違反,`pypinyin` 屬第三方套件,與此牴觸。實作定案:
1. 內建對照表(`STYLE_SLUG_TABLE`,涵蓋三個預設:溫暖敘事→warm_story、急迫促銷→urgent_promo、輕奢質感→luxury_refined)
2. 不在表中 → **直接**進入 timestamp fallback(`style_{int(time.time())}`),不引入pypinyin
3. 碰撞 → 附加流水號(warm_story_2)

犧牲不在表中標籤的slug可讀性以維持零依賴承諾,此為明確取捨,非遺漏。三個預設種子:`warm_story`(溫暖敘事)、`urgent_promo`(急迫促銷)、`luxury_refined`(輕奢質感)。

### 3.3 廣告類型 Schema(`data/ad_types/{type_id}.json`)

```json
{
  "type_id": "fb_feed_ad",
  "name": "(待填)",
  "platform": "(待填)",
  "characteristics": "(待填)",
  "length_guide": "(待填)",
  "cta_style": "(待填)",
  "sample_structure": [],
  "tags": [],
  "version": 1,
  "last_updated": "2026-07-18",
  "status": "active",
  "_raw_paste_pending_review": ""
}
```

**貼上原始文字流程**:使用者輸入type_id+貼上文字 → 全欄位「(待填)」+ 原始文字存`_raw_paste_pending_review`(無規則式解析,暫無規則可依)→ 清單顯示時該筆項目顯示紅點圖示 → 點擊顯示原始文字全文供人工比對 → 逐欄編輯UI留Phase2。

**種子資料**:五筆Google廣告類型(`google_pmax_sales`、`google_pmax_leads`、`google_pmax_store`、`google_ppc_search`、`google_ppc_shopping`),已透過 `POST /ad_types/create` 匯入,內容詳見 GitHub `data/ad_types/*.json`。

### 3.4 品牌/文風格式遷移(四步驟,已完成)

品牌(`data/brand/` → `data/brands/`)與文風(`config/styles.json` → `data/styles/`)皆已依 moved→verified→purged 四步驟完成遷移,`MIGRATION_STATUS.json` 為唯一權威紀錄,`list_unverified()` 回傳空清單。

**實作補充(Phase1事故記錄)**:Step2(用修改後的server建立新格式資料)無法透過全新啟動的HTTP server完成——降級模式(`ALLOW_DEGRADED_START=1`)本身就會擋掉包含新增在內的所有寫入操作,而正常模式在有unverified路徑時直接拒絕啟動。實務作法:直接呼叫 `server.brands.create()` / `server.styles.create()`(Python腳本形式,復用server.py內建立好的Collection物件與GitHub讀寫函式),等同於「用修改後的系統建立資料」,但不透過會被自身降級機制鎖死的HTTP層。

### 3.5 `/generate` 品牌資料組裝邏輯

```python
brand_data = brands.get(brand_id)  # 404 → /generate直接回400,不靜默用空字串繼續
brand_readable = (
    f"品牌名稱:{brand_data['name']}\n定位:{brand_data['positioning']}\n"
    f"目標客群:{brand_data['target_audience']}\n"
    f"賣點:{'、'.join(brand_data['selling_points']) or '(待填)'}\n"
)
for note in brand_data.get("legacy_notes", []):
    brand_readable += f"{note['label']}:{note['content']}\n"
```

### 3.6 UI:按住3秒二次確認刪除(取代前版「點兩次」)

```javascript
function bindHoldToDelete(btn, onConfirm) {
  let timer = null;
  const HOLD_MS = 3000;
  const start = () => {
    btn.textContent = "按住3秒確認刪除"; btn.classList.add("holding");
    timer = setTimeout(() => { onConfirm(); reset(); }, HOLD_MS);
  };
  const cancel = () => { clearTimeout(timer); reset(); };
  const reset = () => { btn.textContent = "刪除"; btn.classList.remove("holding"); };
  btn.addEventListener("mousedown", start);
  btn.addEventListener("touchstart", start);
  ["mouseup","mouseleave","touchend","touchcancel"].forEach(ev => btn.addEventListener(ev, cancel));
}
```

適用範圍:品牌、文風、廣告類型、修正案例的所有刪除操作。

### 3.7 目錄骨架

```
data/{brands,styles,ad_types,performance,revisions,revisions/_archive,revision_stats,sample}/
config.default.yaml
your-extensions/config.local.yaml
logs/{activity,error}.log
skills/.gitkeep
```

`work/`目錄已刪除,內容未遷移(純操作紀錄非機密)。

### 3.8 Phase1 驗收清單(全數通過)

- [x] `local_kit/`已同步,`local-kit-source`測試通過(20 tests passed)
- [x] `install_hooks.py`已執行,`.git/hooks/pre-commit`存在
- [x] 品牌/文風遷移完整走過四步驟,`MIGRATION_STATUS.json`顯示`purged`
- [x] `list_unverified()`回傳空清單
- [x] 廣告類型五筆Google種子資料正確匯入,`GET /ad_types`回傳5筆
- [x] 按住3秒刪除UI在品牌/文風/廣告類型皆正常運作
- [x] `/generate`品牌組裝邏輯正確,品牌不存在時回400非靜默
- [x] `logs/`取代`work/`,`[UI]`前綴正確
- [x] 用詞紅線0命中,無BOM
- [x] 每個子步驟為獨立commit,`git log`可查對照表

---

## 4. Phase 2:修正案例庫

### 4.1 Schema(`data/revisions/{case_id}.json`)

```json
{
  "case_id": "rev_20260720_143022",
  "brand_id": "唯美婚紗",
  "style_id": "warm_story",
  "ad_type_id": "fb_convert_single",
  "original_text": "AI生成的原始文案全文",
  "revised_text": "使用者修改後的全文",
  "category_tags": ["語氣過重", "CTA不夠明確"],
  "tag_source": "manual",
  "sentence_marks": [
    {"revised_sentence": "具體某一句修改後的文字", "issue_note": "原句過於誇大,改為寫實描述"}
  ],
  "internal_structure_markup": "",
  "created_at": "2026-07-20T14:30:22",
  "version": 1
}
```

**本版新增兩欄位(矛盾修正)**:
- `tag_source`:`"manual" | "ai_suggested_confirmed" | "ai_suggested_modified"` —— AI建議標籤永遠發生在`create()`之前(見§4.5),此欄位記錄標籤最終來源,供誠實稽核,不代表事後更新
- `internal_structure_markup`:Phase7使用的內部結構標記版本,併入本schema而非獨立`_internal.json`檔案,確保封存邏輯自動涵蓋(見§4.4矛盾修正)

**不提供`update()`**:修正案例是歷史紀錄,一旦寫入不應被竄改。

### 4.2 端點

| 端點 | 行為 |
|---|---|
| `POST /revisions/create` | 建立新案例,成功後觸發§4.3保留政策檢查 + §5.1統計增量 |
| `GET /revisions` | 列出所有case_id(可選query篩選brand_id/ad_type_id,前端處理) |
| `GET /revision/{case_id}` | 取得單筆完整內容,含即時計算diff(見§4.4);讀取時同步檢查`ad_type_id`/引用是否404,標記`_ref_missing` |
| `DELETE /revision/{case_id}` | Collection.delete(),UI按住3秒;刪除前讀取category_tags觸發§5.1統計減量 |

### 4.3 保留政策(沿用`config.default.yaml`)

```yaml
revision_retention:
  max_count: 20
  max_months: 3
revision_category_presets:
  - "語氣過重"
  - "資訊錯誤"
  - "結構不佳"
  - "CTA不明確"
```

```
觸發:POST /revisions/create 成功後
1. revisions.list()依timestamp排序
2. 超過max_count或最舊項目超過max_months
   → 讀取內容→寫入_archive路徑→刪除原路徑(GitHub API操作,非safe_git本地mv,
     因是常態性資料整理非結構性遷移)
3. 失敗不影響本次建立成功的回應,僅記錄error.log
```

**封存不觸發統計扣減**(矛盾修正#4):`tag_frequency`永久保留、只增不減是Phase3核心承諾,封存只是移出「近期參考範圍」,不代表問題類別不曾發生。統計扣減僅發生於使用者**主動**`delete()`。

### 4.4 Diff運作邏輯(讀取時即時計算,不持久化)

```python
def literal_diff(original, revised):
    """difflib.SequenceMatcher逐段比對,純規則式,非語意理解,需誠實標註"""
    sm = difflib.SequenceMatcher(None, original, revised)
    return [{"type": tag, "original": original[i1:i2], "revised": revised[j1:j2]}
            for tag, i1, i2, j1, j2 in sm.get_opcodes()]
def block_diff(original, revised):
    """方案B:段落層級,用語一律「第N區塊」,不對應具名結構步驟,避免over-claim"""
    def split_blocks(text):
        return [b.strip() for b in re.split(r'(?<=[。!?\n])', text) if b.strip()]
    orig_blocks, rev_blocks = split_blocks(original), split_blocks(revised)
    sm = difflib.SequenceMatcher(None, orig_blocks, rev_blocks)
    return [{"type": tag, "block_index": i1,
             "original_block": orig_blocks[i1:i2], "revised_block": rev_blocks[j1:j2]}
            for tag, i1, i2, j1, j2 in sm.get_opcodes()]
```

方案A(精準結構diff,對應`sample_structure`具名步驟)延後至Phase7實作,寫入`internal_structure_markup`欄位,方案B保留不變供人工查看,兩者並存。

**跨collection懸空參照處理**(矛盾修正#3):`GET /revision/{case_id}`讀取時,對`ad_type_id`做輕量`get()`檢查,404則該欄位標記`"_ref_missing": true`,前端顯示「(原始資料已刪除)」,不噴錯不阻斷渲染。不做刪除時的級聯阻擋。

### 4.5 UI流程(AI建議標籤的正確時序,矛盾修正#1核心)

```
1. /generate結果畫面,AI生成文案為可編輯textarea
2. 使用者修改文字(不改則不觸發任何紀錄,僅明確按「儲存修正案例」才建檔)
3. 按「儲存修正案例」前,可選按「AI建議標籤」(Phase7功能,Phase2先只有手動):
   → 呼叫AI,建議結果顯示於畫面(尚未寫入任何檔案,此刻僅是UI暫存狀態)
   → 使用者可全採納/部分修改/忽略
4. 標籤選擇(案例層級):
   a. 手動:勾選/新增category_tags(自由文字,下拉顯示歷史用過標籤)
   b. 若上一步用了AI建議:tag_source記為ai_suggested_confirmed(全採納)或
      ai_suggested_modified(有修改);純手動則manual
5. 句子層級(選填):diff畫面點選特定句子,填issue_note
6. 按「儲存修正案例」→ 此時第一次且唯一一次POST /revisions/create,
   category_tags/tag_source帶入此刻最終確認值
7. 成功後顯示「已記錄」,畫面停留在/generate頁,不跳轉列表
```

**關鍵**:不存在「先create()、AI推論完再回頭update()」這個序列,AI建議永遠是create前的一個可選輸入來源,Phase2「無update()」規則完全不受影響。

### 4.6 例外處理

| 狀況 | 處理 |
|---|---|
| original/revised完全相同 | 前端「儲存修正案例」按鈕disable |
| category_tags與sentence_marks皆空 | 允許儲存,UI提示「建議至少填一項」非強制 |
| 保留政策封存失敗 | 靜默失敗不影響主流程,記error.log |

---

## 5. Phase 3:標籤統計

### 5.1 儲存位置(單一彙總檔)

`data/revision_stats/summary.json`:

```json
{
  "category_tag_counts": {"語氣過重": 12, "資訊錯誤": 3, "結構不佳": 5, "CTA不明確": 8},
  "total_cases": 20,
  "last_updated": "2026-07-20T15:00:00",
  "last_recomputed_from_scratch": "2026-07-20T10:00:00"
}
```

### 5.2 增量更新(觸發點明確化,矛盾修正#4)

| 觸發點 | 動作 |
|---|---|
| `POST /revisions/create`成功 | category_tags逐一+1,total_cases+1,覆寫summary.json |
| `DELETE /revision/{id}`成功**(使用者主動)** | 刪除前讀取category_tags逐一-1(降0則移除key),total_cases-1 |
| **保留政策自動封存** | **不觸發任何統計異動**(矛盾修正#4定案) |

案例本體寫入/刪除成功優先於統計數字即時精準——統計更新失敗只記error.log,不影響主流程。

### 5.3 手動重算端點(自癒機制)

```
GET /revision_stats/recompute
1. revisions.list()取全部案例,逐一get()讀category_tags
2. 從零重新統計,覆寫summary.json,last_recomputed_from_scratch更新
3. 回傳新結果供人工比對校正前後差異
```

使用時機:懷疑數字有誤(如曾用git指令繞過API改資料)。不設排程自動執行,O(N)操作接受手動觸發即可。

### 5.4 查詢端點

```
GET /revision_stats → 回傳summary.json,O(1)讀取
前端:依數值排序(高到低)文字列表,如「CTA不明確(8次)」,不做圖表
```

---

## 6. Phase 4:成效登記

### 6.1 Schema(`data/performance/{brand}/{copy_id}.json`)

```json
{
  "copy_id": "brand_a_20260719_01",
  "ad_type": "fb_feed_ad",
  "revision_case_id": "",
  "date_range": {"start": "", "end": ""},
  "spend": 0, "impressions": 0, "clicks": 0, "conversions": 0,
  "custom_metrics": {},
  "notes": "",
  "version": 1
}
```

`custom_metrics`為預留彈性欄位,不預先窮舉CTR/CPA,衍生計算交由DA Trainer的`StatsEngine`負責。

### 6.2 運作

- 文案卡片下方「登記成效」按鈕,跳出表單(花費/曝光/點擊/轉換必填,其餘選填)
- 本系統**不做統計計算**,只記錄原始數字
- `GET /performance/<brand>`回傳該品牌全部原始數據,供外部統計引擎讀取
- 讀取時對`revision_case_id`/`ad_type`做輕量404檢查,標記`_ref_missing`(同§4.4邏輯,矛盾修正#3統一處理方式)

---

## 7. Phase 5:對外 API

| 項目 | 內容 |
|---|---|
| 開放範圍 | 全部內部端點(brands/styles/ad_types/revisions/performance CRUD＋generate),對外統一加API Key驗證 |
| 認證 | 前期單一API Key,存`your-extensions/config.local.yaml`,檢查header`X-API-Key`;後期升級每呼叫方各自Key＋速率限制(本階段不做,不阻擋日後升級) |
| 日誌 | `logger.log(..., source="API")`,Phase1已預留參數,本階段正式啟用 |
| 端點邏輯 | 不變,僅外層加API Key middleware,內部UI呼叫路徑不受影響 |

---

## 8. Phase 6:DA Trainer 雙向整合

| 方向 | 內容 | 運作方式 |
|---|---|---|
| marketing-generator → DA Trainer | `revisions`資料作為DA Trainer刷題真實資料集 | DA Trainer呼叫`GET /revisions`(唯讀),轉換邏輯屬DA Trainer範疇 |
| DA Trainer → marketing-generator | `StatsEngine`供Phase4成效比較使用 | 不透過API,直接`from local_kit.stats_engine import StatsEngine`(程式碼共用) |

Phase4後續可能延伸「比較分析」端點呼叫`StatsEngine.t_test_independent()`,非本階段實作範圍,僅標註architectural readiness。

---

## 9. Phase 7:AI輔助推論

### 9.1 精準結構diff(方案A,Phase2 §4.4已預留欄位)

```
1. /generate內部版本在sample_structure步驟間插入標記(<!--step:1-->...)
2. 寫入revisions schema既有的internal_structure_markup欄位(矛盾修正#2,
   非獨立_internal.json檔案,確保封存邏輯自動涵蓋,不產生孤兒檔案)
3. 對使用者呈現時剝除標記,Phase2既有UI/流程不受影響
4. 方案B(段落diff)保留不變,兩者並存,方案A僅供AI推論使用
```

### 9.2 自動定標籤

| 項目 | 內容 |
|---|---|
| 觸發 | 手動,`/generate`結果頁按「AI建議標籤」,非自動執行 |
| 模型 | 免費/低成本模型 |
| 輸入 | 原始文案＋修改後文案＋internal_structure_markup |
| 輸出 | 建議category_tags(自由文字) |
| 誠實原則 | UI明確標示「AI建議,非規則比對」,視覺區分;見§4.5時序,AI建議永遠在create()之前,使用者確認後才寫入,tag_source記錄來源 |

---

## 10. Phase 8:Skill 封裝 ＋ start_all

### 10.1 Skill封裝

| 項目 | 內容 |
|---|---|
| 封裝單位 | 每個`ad_type_id`各自一份`skills/{ad_type_id}/SKILL.md` |
| 內容來源 | 直接由`ad_types.get(id)`欄位組成,屬既有資料另一種呈現 |
| 迭代機制 | `ad_type.version`遞增時,手動觸發`regenerate_skill(type_id)`重新產生對應SKILL.md |
| 範圍 | 本階段僅「廣告類型→SKILL.md」,其餘複用形式(如revisions分析邏輯封裝)留待未來按需擴充 |

### 10.2 `start_all.py`(非.bat,跨OS)

```
範圍:僅啟動marketing-generator與DA Trainer兩個server
實作:純粹依序執行兩專案各自啟動指令,無額外邏輯
```

---

## 11. 四項全域矛盾定案彙總

| # | 問題 | 定案 | 影響章節 |
|---|---|---|---|
| 1 | Phase2「無update()」vs Phase7「確認後寫入」 | AI建議永遠發生在create()之前,不存在事後更新;新增`tag_source`稽核欄位 | §4.1, §4.5, §9.2 |
| 2 | `{case_id}_internal.json`孤兒檔案風險 | 取消獨立檔案,改為`internal_structure_markup`欄位併入revisions schema,自動繼承封存邏輯 | §4.1, §9.1 |
| 3 | 跨collection懸空參照(ad_type/revision刪除後) | 軟性失效顯示(`_ref_missing`標記),不做刪除阻擋,維持collection獨立性 | §4.4, §6.2 |
| 4 | Phase2封存 vs Phase3統計扣減關係未定義 | 封存不扣減,只增不減;扣減僅發生於使用者主動delete() | §4.3, §5.2 |

---

## 12. 全部Phase現況總表

| Phase | 內容 | 狀態 |
|---|---|---|
| 1 | 目錄重建+品牌/文風JSON化+廣告類型管理(含5筆Google種子資料) | **已完成** |
| 2 | 修正案例庫(含矛盾修正後的schema) | 定案,待實作 |
| 3 | 標籤統計 | 定案,待實作 |
| 4 | 成效登記 | 定案,待實作 |
| 5 | 對外API | 定案,待實作 |
| 6 | DA Trainer整合 | 定案(依賴DA Trainer專案先動工) |
| 7 | AI輔助推論 | 定案(依賴Phase2+Phase5) |
| 8 | Skill封裝+start_all | 定案,待實作 |

---

## 13. 版本異動守則

`rules_changelog.md` 每行格式:

```
2026-07-17 | IG | wedding_ig.md v1.2 | 降低純文字貼文權重,加強首句提問結構 | 觸發原因:IG降觸及公告
```

不建立額外評分系統,commit message 僅標註 `[perf:high]` / `[perf:low]` 即足夠追溯。
