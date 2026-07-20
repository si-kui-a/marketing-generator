# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# Phase1:local_kit.Collection 統一管理 brands/styles/ad_types,GitHub Contents API 為唯一正本。
import base64
import difflib
import importlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import quote, unquote

# Windows 主控台預設編碼(如 zh-TW 的 cp950)無法輸出中文/emoji,強制 stdout/stderr
# 走 UTF-8,避免 local_kit 或本檔案任何 print() 因主控台編碼而讓整個請求 500。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT       = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(ROOT, "prompts")   # 模板仍保留本機(供離線編輯參考)
CHANGELOG  = os.path.join(ROOT, "rules_changelog.md")

sys.path.insert(0, os.path.join(ROOT, "local_kit"))
from json_collection import Collection   # noqa: E402
from config_loader import load_config    # noqa: E402
from logger import log as kit_log        # noqa: E402

AD_TYPES         = {"ig": "wedding_ig.md", "fb": "wedding_fb.md", "seo": "wedding_seo.md"}
VALID_PERF_TAGS  = {"high", "low", "未標記"}
VERSION_DELIM    = "===VERSION==="
MAX_VERSIONS     = 5
PROMPT_WHITELIST = set(AD_TYPES.values()) | {"system_base.md"}

# GitHub Contents API paths
GH_BRAND_PREFIX    = "data/brands/"
GH_STYLE_PREFIX    = "data/styles/"
GH_AD_TYPE_PREFIX  = "data/ad_types/"
GH_REVISION_PREFIX = "data/revisions/"
GH_ARCHIVE_PREFIX  = "data/archive/"
GH_TAG_FREQ_PATH   = "data/tag_frequency.json"

# 已知中文標籤 → 固定 slug 對照表(Master Spec §3.2 第一層)。
# 注意:本專案 spec §0 訂為「零依賴、純 Python 標準庫」,不可違反,故不引入 pypinyin
# (§3.2 描述的第二層拼音轉換)。不在表中的標籤一律直接走第四層 timestamp fallback,
# 犧牲slug可讀性以維持零依賴承諾,此為明確取捨,非遺漏。
STYLE_SLUG_TABLE = {
    "溫暖敘事": "warm_story",
    "急迫促銷": "urgent_promo",
    "輕奢質感": "luxury_refined",
}

BRAND_DEFAULTS = {
    "positioning": "(待填)", "target_audience": "(待填)",
    "selling_points": [], "legacy_notes": [],
}
STYLE_DEFAULTS = {"description": "(待填)", "sample_copy": ""}
AD_TYPE_DEFAULTS = {
    "platform": "(待填)", "characteristics": "(待填)", "length_guide": "(待填)",
    "cta_style": "(待填)", "sample_structure": [], "tags": [], "status": "active",
    "_raw_paste_pending_review": "",
}
# Master Spec §4.1:修正案例 schema。不提供 update()——歷史紀錄一旦寫入不可竄改,
# 見 json_collection.Collection 本身即無 update 方法,此為架構層級保證非僅約定。
REVISION_DEFAULTS = {
    "brand_id": "", "style_id": "", "ad_type_id": "",
    "original_text": "", "revised_text": "",
    "category_tags": [], "tag_source": "manual",
    "sentence_marks": [], "internal_structure_markup": "",
}


# ── 工具 ──────────────────────────────────────────────────────────────────────
def _append_log(filename, line, source="UI"):
    # Master Spec §2.8:logs/ 取代 work/,格式含來源前綴。Phase1 全部呼叫點皆屬 UI
    # 來源(尚無對外 API),source="API" 留待 Phase5 對外 API 開放時才會被實際傳入。
    kit_log(ROOT, filename, line, source)


def _load_env():
    env = {}
    fp = os.path.join(ROOT, ".env")
    if os.path.isfile(fp):
        with open(fp, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _read_local(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _safe_brand_name(name):
    return bool(name) and not any(c in name for c in ("/", "\\", "..", "\x00"))


def _safe_filename(name):
    return bool(name) and not re.search(r'[/\\:*?"<>|\x00]', name)


# ── GitHub Contents API ───────────────────────────────────────────────────────
def _gh_headers(token):
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _gh_get(env, path):
    """GET /repos/{owner}/{repo}/contents/{path}
    Returns (decoded_text, sha) or raises RuntimeError."""
    token = env.get("GITHUB_TOKEN", "")
    repo  = env.get("GITHUB_REPO", "")
    branch = env.get("GITHUB_BRANCH", "master")
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN 或 GITHUB_REPO 未設定")
    url = "https://api.github.com/repos/%s/contents/%s?ref=%s" % (repo, quote(path, safe="/"), branch)
    req = urllib.request.Request(url, headers=_gh_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise FileNotFoundError(path)
        raise RuntimeError("GitHub API %d" % e.code)


def _gh_list(env, prefix):
    """列出 prefix 下的檔案名稱清單。"""
    token = env.get("GITHUB_TOKEN", "")
    repo  = env.get("GITHUB_REPO", "")
    branch = env.get("GITHUB_BRANCH", "master")
    url = "https://api.github.com/repos/%s/contents/%s?ref=%s" % (repo, quote(prefix.rstrip("/"), safe="/"), branch)
    req = urllib.request.Request(url, headers=_gh_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            items = json.loads(r.read().decode("utf-8"))
        return [i["name"] for i in items if i["type"] == "file"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise RuntimeError("GitHub API %d" % e.code)
    except OSError:
        raise RuntimeError("GitHub connection timeout")


def _gh_put(env, path, content_str, message, sha=None):
    """PUT(新建或更新)檔案到 GitHub。"""
    token  = env.get("GITHUB_TOKEN", "")
    repo   = env.get("GITHUB_REPO", "")
    branch = env.get("GITHUB_BRANCH", "master")
    url    = "https://api.github.com/repos/%s/contents/%s" % (repo, quote(path, safe="/"))
    body   = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch":  branch,
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=_gh_headers(token),
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("GitHub API %d" % e.code)


def _gh_delete(env, path, message, sha):
    """DELETE 檔案從 GitHub。"""
    token  = env.get("GITHUB_TOKEN", "")
    repo   = env.get("GITHUB_REPO", "")
    branch = env.get("GITHUB_BRANCH", "master")
    url    = "https://api.github.com/repos/%s/contents/%s" % (repo, quote(path, safe="/"))
    body   = {"message": message, "sha": sha, "branch": branch}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=_gh_headers(token),
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("GitHub API %d" % e.code)


def _gh_check(env):
    """快速檢查 token + repo 是否可用。timeout 硬上限 8 秒。"""
    if not env.get("GITHUB_TOKEN") or not env.get("GITHUB_REPO"):
        return False
    try:
        _gh_list(env, GH_BRAND_PREFIX)
        return True
    except Exception:
        return False


def _append_changelog_gh(env, line):
    """追加一行到 GitHub 上的 rules_changelog.md。"""
    try:
        text, sha = _gh_get(env, "rules_changelog.md")
    except FileNotFoundError:
        text, sha = "", None
    new_text = text + line + "\n"
    _gh_put(env, "rules_changelog.md", new_text,
            "changelog: " + line[:60], sha)
    # 同步本機
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Collections ───────────────────────────────────────────────────────────────
brands    = Collection(GH_BRAND_PREFIX, "brand_id", BRAND_DEFAULTS, _gh_get, _gh_put, _gh_delete, _gh_list)
styles    = Collection(GH_STYLE_PREFIX, "style_id", STYLE_DEFAULTS, _gh_get, _gh_put, _gh_delete, _gh_list)
ad_types  = Collection(GH_AD_TYPE_PREFIX, "type_id", AD_TYPE_DEFAULTS, _gh_get, _gh_put, _gh_delete, _gh_list)
revisions = Collection(GH_REVISION_PREFIX, "case_id", REVISION_DEFAULTS, _gh_get, _gh_put, _gh_delete, _gh_list)


def _make_style_id(env, label):
    """label(中文標籤) → style_id(英文slug)。已知詞用固定表,否則 timestamp fallback,
    碰撞則附加流水號。不引入 pypinyin(見 STYLE_SLUG_TABLE 註解)。"""
    base = STYLE_SLUG_TABLE.get(label) or ("style_%d" % int(time.time()))
    slug = base
    n = 2
    while True:
        try:
            styles.get(env, slug)
        except FileNotFoundError:
            return slug
        slug = "%s_%d" % (base, n)
        n += 1


# ── Diff 邏輯(Master Spec §4.4,讀取時即時計算,不持久化)──────────────────────
def literal_diff(original, revised):
    """純規則式字元比對,非語意理解。UI呈現時需誠實標註此為文字比對演算法結果。"""
    sm = difflib.SequenceMatcher(None, original, revised)
    return [
        {"type": tag, "original": original[i1:i2], "revised": revised[j1:j2]}
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
    ]


def block_diff(original, revised):
    """方案B:段落層級diff。用語一律「第N區塊」,不對應sample_structure具名步驟。"""
    def split_blocks(text):
        return [b.strip() for b in re.split(r'(?<=[。！？\n])', text) if b.strip()]
    orig_blocks, rev_blocks = split_blocks(original), split_blocks(revised)
    sm = difflib.SequenceMatcher(None, orig_blocks, rev_blocks)
    return [
        {"type": tag, "block_index": i1,
         "original_block": orig_blocks[i1:i2], "revised_block": rev_blocks[j1:j2]}
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
    ]


# ── 啟動時判定一次降級狀態(Master Spec §2.2)──────────────────────────────────
# 刻意只在 import/啟動時算一次,不逐請求重算:若逐請求重算,長時間運行的
# process 會在別的流程(如另一個終端機執行遷移)悄悄把migration狀態改成
# moved後,對現有連線中的使用者「無預警開始擋寫入」;也會讓 Master Spec §3.4
# 「Step1→2→3 連續執行完」的設計失效(Step2 本身就是在 moved 狀態下寫入)。
# 未 verified 且未設 ALLOW_DEGRADED_START 時,讓 RuntimeError 直接往外拋、
# 中止啟動(config_loader.load_config 的既有行為),不在此吞掉。
_CONFIG = load_config(ROOT, allow_degraded_start=os.environ.get("ALLOW_DEGRADED_START") == "1")


# ── 修正案例保留政策(Master Spec §4.3)────────────────────────────────────────
def _check_retention_policy(env):
    """
    觸發於 POST /revisions/create 成功後。超過上限的最舊案例移至 _archive/。
    矛盾修正#4:此函式不觸發任何 tag_frequency 統計異動(Phase3範圍,封存≠刪除)。
    """
    max_count = _CONFIG.get("revision_retention", {}).get("max_count", 20)
    max_months = _CONFIG.get("revision_retention", {}).get("max_months", 3)
    ids = revisions.list(env)
    # 依timestamp排序(case_id本身即timestamp格式,字串排序即時間排序)
    ids_sorted = sorted(ids)
    now = datetime.now()
    to_archive = []
    if len(ids_sorted) > max_count:
        to_archive.extend(ids_sorted[:len(ids_sorted) - max_count])
    for cid in ids_sorted:
        if cid in to_archive:
            continue
        try:
            ts_str = cid.replace("rev_", "")
            ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            if (now - ts).days > max_months * 30:
                to_archive.append(cid)
        except ValueError:
            continue
    for cid in to_archive:
        try:
            content, sha = _gh_get(env, "data/revisions/%s.json" % cid)
            _gh_put(env, "data/revisions/_archive/%s.json" % cid, content,
                    "revision: archive %s [retention-policy]" % cid)
            _gh_delete(env, "data/revisions/%s.json" % cid,
                       "revision: remove archived %s from active [retention-policy]" % cid, sha)
        except Exception as e:
            _append_log("error.log", "archive_failed %s: %s" % (cid, e))
            continue  # 單筆失敗不影響其他筆


# ── Handler ───────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self, limit=2_000_000):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > limit:
            return None, "invalid body"
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (ValueError, UnicodeDecodeError):
            return None, "body must be valid JSON"

    def _env_or_503(self):
        env = _load_env()
        missing = [k for k in ("PROVIDER", "API_KEY", "MODEL", "GITHUB_TOKEN", "GITHUB_REPO")
                   if not env.get(k)]
        if missing:
            self._send(503, {"error": "設定未完成,.env 缺少:" + ", ".join(missing)})
            return None
        return env

    def _gh_env_or_503(self):
        env = _load_env()
        if not env.get("GITHUB_TOKEN") or not env.get("GITHUB_REPO"):
            self._send(503, {"error": "GITHUB_TOKEN / GITHUB_REPO 未設定"})
            return None
        return env

    def _degraded_or_503(self):
        """Master Spec §2.2:降級狀態於啟動時判定一次(見 _CONFIG),非逐請求重算——
        逐請求重算會讓「同一次連續執行完Step1→2→3」的設計目標(§3.4註解)變得不可能,
        因為Step2本身就是在data/brand仍為moved狀態下對Collection.create()寫入。"""
        if _CONFIG.get("_degraded_mode"):
            self._send(503, {
                "error": "系統處於降級模式(遷移未驗證完成),寫入操作暫停:%s"
                         % _CONFIG.get("_degraded_reason")
            })
            return True
        return False

    def do_GET(self):
        try:
            path = unquote(self.path)
            if path == "/brands":
                self._handle_brands()
            elif path.startswith("/brand/"):
                self._handle_brand(path[len("/brand/"):])
            elif path == "/prompts":
                self._handle_get_prompts()
            elif path.startswith("/prompt/"):
                self._handle_get_prompt(path[len("/prompt/"):])
            elif path == "/styles":
                self._handle_get_styles()
            elif path == "/ad_types":
                self._handle_ad_types()
            elif path.startswith("/ad_type/"):
                self._handle_ad_type(path[len("/ad_type/"):])
            elif path == "/revisions":
                self._handle_revisions()
            elif path.startswith("/revision/"):
                self._handle_revision_get(path[len("/revision/"):])
            elif path == "/health":
                env = _load_env()
                self._send(200, {"github": _gh_check(env)})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error"})

    def do_POST(self):
        try:
            path = unquote(self.path)
            if path == "/generate":
                self._handle_generate()
            elif path == "/archive":
                self._handle_archive()
            elif path == "/tag":
                self._handle_tag()
            elif path == "/brands/create":
                self._handle_brand_create()
            elif path == "/prompts/save":
                self._handle_prompt_save()
            elif path == "/styles/add":
                self._handle_style_add()
            elif path == "/ad_types/create":
                self._handle_ad_type_create()
            elif path == "/revisions/create":
                self._handle_revision_create()
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error"})

    def do_DELETE(self):
        try:
            path = unquote(self.path)
            if path.startswith("/brand/"):
                self._handle_brand_delete(path[len("/brand/"):])
            elif path.startswith("/style/"):
                self._handle_style_delete(path[len("/style/"):])
            elif path.startswith("/ad_type/"):
                self._handle_ad_type_delete(path[len("/ad_type/"):])
            elif path.startswith("/revision/"):
                self._handle_revision_delete(path[len("/revision/"):])
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error"})

    # ── 品牌:GET /brands /brand/<id>,POST /brands/create,DELETE /brand/<id> ──
    def _handle_brands(self):
        env = self._gh_env_or_503()
        if not env: return
        try:
            ids = brands.list(env)
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"brands": sorted(ids)})

    def _handle_brand(self, brand_id):
        if not _safe_brand_name(brand_id):
            self._send(400, {"error": "invalid brand name"}); return
        env = self._gh_env_or_503()
        if not env: return
        try:
            data = brands.get(env, brand_id)
        except FileNotFoundError:
            self._send(404, {"error": "brand not found"}); return
        except ValueError as e:
            self._send(500, {"error": str(e)}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, data)

    def _handle_brand_create(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        name     = body.get("name", "").strip()
        axis     = body.get("axis", "").strip()
        reviews  = body.get("reviews", "").strip()
        activity = body.get("activity", "").strip()
        extras   = body.get("extras", [])
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"}); return
        legacy_notes = [
            {"label": "Google 地圖評價", "content": reviews or "(待填)"},
            {"label": "活動頁面文案", "content": activity or "(待填)"},
        ] + [{"label": e.get("label", ""), "content": e.get("content", "") or "(待填)"}
             for e in (extras if isinstance(extras, list) else []) if e.get("label")]
        data = {"brand_id": name, "name": name, "positioning": axis or "(待填)"}
        try:
            brands.create(env, name, data, extra_fields={"legacy_notes": legacy_notes})
        except FileExistsError:
            self._send(409, {"error": "品牌已存在,請使用其他名稱"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"created": name})

    def _handle_brand_delete(self, brand_id):
        if not _safe_brand_name(brand_id):
            self._send(400, {"error": "invalid brand name"}); return
        env = self._gh_env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        try:
            brands.delete(env, brand_id)
        except FileNotFoundError:
            self._send(404, {"error": "brand not found"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"deleted": brand_id})

    # ── 模板:GET /prompts /prompt/<f>,POST /prompts/save(本機,未受Phase1影響) ──
    def _handle_get_prompts(self):
        files = [f for f in os.listdir(PROMPT_DIR) if f.endswith(".md")]
        self._send(200, {"prompts": sorted(files)})

    def _handle_get_prompt(self, filename):
        if filename not in PROMPT_WHITELIST:
            self._send(403, {"error": "file not in whitelist"}); return
        fp = os.path.join(PROMPT_DIR, filename)
        if not os.path.isfile(fp):
            self._send(404, {"error": "prompt not found"}); return
        self._send(200, {"filename": filename, "content": _read_local(fp)})

    def _handle_prompt_save(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        filename = body.get("filename", "")
        content  = body.get("content", "")
        summary  = body.get("summary", "內容更新").strip() or "內容更新"
        if filename not in PROMPT_WHITELIST:
            self._send(403, {"error": "file not in whitelist"}); return
        if not content.strip():
            self._send(400, {"error": "content is empty"}); return
        fp = os.path.join(PROMPT_DIR, filename)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        gh_path = "prompts/" + filename
        try:
            _, sha = _gh_get(env, gh_path)
        except FileNotFoundError:
            sha = None
        _gh_put(env, gh_path, content,
                "prompts: %s — %s [auto-backup]" % (filename, summary), sha)
        now  = datetime.now().strftime("%Y-%m-%d")
        line = "%s | prompts | %s | %s | 觸發原因:UI 編輯器存檔" % (now, filename, summary)
        _append_changelog_gh(env, line)
        self._send(200, {"saved": filename, "github": "pushed"})

    # ── 文風:GET /styles,POST /styles/add,DELETE /style/<id> ────────────────
    def _handle_get_styles(self):
        env = self._gh_env_or_503()
        if not env: return
        try:
            ids = styles.list(env)
            result = {}
            for sid in ids:
                try:
                    data = styles.get(env, sid)
                except ValueError:
                    continue  # 單筆損毀不阻斷整體列表
                result[sid] = {
                    "name": data.get("name", sid),
                    "description": data.get("description", ""),
                    "sample_copy": data.get("sample_copy", ""),
                }
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"styles": result})

    def _handle_style_add(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        label   = body.get("label", "").strip()
        example = body.get("example", "").strip()
        if not label:
            self._send(400, {"error": "label is required"}); return
        style_id = _make_style_id(env, label)
        data = {"style_id": style_id, "name": label, "sample_copy": example}
        try:
            styles.create(env, style_id, data)
        except FileExistsError:
            self._send(409, {"error": "文風已存在"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"added": label, "style_id": style_id})

    def _handle_style_delete(self, style_id):
        style_id = unquote(style_id)
        if not _safe_filename(style_id):
            self._send(400, {"error": "invalid style_id"}); return
        env = self._gh_env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        try:
            styles.delete(env, style_id)
        except FileNotFoundError:
            self._send(404, {"error": "style not found"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"deleted": style_id})

    # ── 廣告類型:GET /ad_types /ad_type/<id>,POST /ad_types/create,DELETE ──
    def _handle_ad_types(self):
        env = self._gh_env_or_503()
        if not env: return
        try:
            ids = ad_types.list(env)
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"ad_types": sorted(ids)})

    def _handle_ad_type(self, type_id):
        if not _safe_filename(type_id):
            self._send(400, {"error": "invalid type_id"}); return
        env = self._gh_env_or_503()
        if not env: return
        try:
            data = ad_types.get(env, type_id)
        except FileNotFoundError:
            self._send(404, {"error": "ad_type not found"}); return
        except ValueError as e:
            self._send(500, {"error": str(e)}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"type_id": type_id, "data": data})

    def _handle_ad_type_create(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        type_id   = body.get("type_id", "").strip()
        raw_paste = body.get("raw_paste", "").strip()
        if not _safe_filename(type_id):
            self._send(400, {"error": "invalid type_id"}); return
        data = {
            "type_id": type_id,
            "name": body.get("name", "").strip() or "(待填)",
            "platform": body.get("platform", "").strip() or "(待填)",
            "characteristics": body.get("characteristics", "").strip() or "(待填)",
            "length_guide": body.get("length_guide", "").strip() or "(待填)",
            "cta_style": body.get("cta_style", "").strip() or "(待填)",
            "sample_structure": body.get("sample_structure", []) or [],
            "tags": body.get("tags", []) or [],
        }
        try:
            ad_types.create(env, type_id, data, extra_fields={"_raw_paste_pending_review": raw_paste})
        except FileExistsError:
            self._send(409, {"error": "廣告類型已存在"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"created": type_id})

    def _handle_ad_type_delete(self, type_id):
        if not _safe_filename(type_id):
            self._send(400, {"error": "invalid type_id"}); return
        env = self._gh_env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        try:
            ad_types.delete(env, type_id)
        except FileNotFoundError:
            self._send(404, {"error": "ad_type not found"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"deleted": type_id})

    # ── 修正案例:GET /revisions /revision/<id>,POST /revisions/create,
    #             DELETE /revision/<id>(Master Spec §4,不提供 update()) ────────
    def _handle_revisions(self):
        env = self._gh_env_or_503()
        if not env: return
        try:
            ids = revisions.list(env)
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"revisions": ids})

    def _handle_revision_get(self, case_id):
        """含跨collection懸空參照軟性檢查(矛盾修正#3)。"""
        if not _safe_filename(case_id):
            self._send(400, {"error": "invalid case_id"}); return
        env = self._gh_env_or_503()
        if not env: return
        try:
            data = revisions.get(env, case_id)
        except FileNotFoundError:
            self._send(404, {"error": "revision not found"}); return
        except ValueError as e:
            self._send(500, {"error": str(e)}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        ad_type_id = data.get("ad_type_id", "")
        if ad_type_id:
            try:
                ad_types.get(env, ad_type_id)
                data["_ref_missing"] = False
            except FileNotFoundError:
                data["_ref_missing"] = True
            except Exception:
                pass  # GitHub連線問題不應影響主要資料回傳,略過此檢查
        data["_diff_literal"] = literal_diff(data.get("original_text", ""), data.get("revised_text", ""))
        data["_diff_block"] = block_diff(data.get("original_text", ""), data.get("revised_text", ""))
        self._send(200, {"case_id": case_id, "data": data})

    def _handle_revision_create(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        original = body.get("original_text", "").strip()
        revised = body.get("revised_text", "").strip()
        if not original or not revised:
            self._send(400, {"error": "original_text 與 revised_text 皆必填"}); return
        if original == revised:
            self._send(400, {"error": "原文與修改後文字相同,無需記錄"}); return
        case_id = "rev_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
        data = {
            "brand_id": body.get("brand_id", ""),
            "style_id": body.get("style_id", ""),
            "ad_type_id": body.get("ad_type_id", ""),
            "original_text": original,
            "revised_text": revised,
            "category_tags": body.get("category_tags", []) or [],
            "tag_source": body.get("tag_source", "manual"),
            "sentence_marks": body.get("sentence_marks", []) or [],
            "internal_structure_markup": "",  # Phase7才使用
        }
        data["created_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            obj = revisions.create(env, case_id, data)
        except FileExistsError as e:
            self._send(409, {"error": str(e)}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        # §4.3 保留政策檢查(失敗不影響本次建立成功)
        try:
            _check_retention_policy(env)
        except Exception as e:
            _append_log("error.log", "retention_policy_failed: %s" % e)
        self._send(200, {"created": case_id, "data": obj})

    def _handle_revision_delete(self, case_id):
        """不經過safe_git,走日常CRUD路徑(Master Spec §4.1/§2.3)。"""
        if not _safe_filename(case_id):
            self._send(400, {"error": "invalid case_id"}); return
        env = self._gh_env_or_503()
        if not env: return
        if self._degraded_or_503(): return
        try:
            revisions.delete(env, case_id)
        except FileNotFoundError:
            self._send(404, {"error": "revision not found"}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        self._send(200, {"deleted": case_id})

    # ── POST /generate ────────────────────────────────────────────────────────
    def _handle_generate(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        brand       = body.get("brand", "")
        ad_type     = body.get("ad_type", "")
        versions    = body.get("versions", 1)
        style_label = body.get("style_label", "")   # 現為 style_id
        style_free  = body.get("style_free", "")
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"}); return
        if not isinstance(versions, int) or not (1 <= versions <= MAX_VERSIONS):
            self._send(400, {"error": "versions must be int 1..%d" % MAX_VERSIONS}); return
        if not _safe_brand_name(brand):
            self._send(400, {"error": "invalid brand name"}); return
        try:
            brand_data = brands.get(env, brand)
        except FileNotFoundError:
            # Master Spec §3.5:brand不存在時/generate直接回400,不靜默用空字串繼續
            self._send(400, {"error": "brand not found"}); return
        except ValueError as e:
            self._send(500, {"error": str(e)}); return
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        brand_readable = (
            "品牌名稱:%s\n定位:%s\n目標客群:%s\n賣點:%s\n"
            % (brand_data.get("name", ""), brand_data.get("positioning", ""),
               brand_data.get("target_audience", ""),
               "、".join(brand_data.get("selling_points", [])) or "(待填)")
        )
        for note in brand_data.get("legacy_notes", []):
            brand_readable += "%s:%s\n" % (note.get("label", ""), note.get("content", ""))
        style_block = ""
        if style_label:
            try:
                style_data = styles.get(env, style_label)
                style_name = style_data.get("name", style_label)
                style_desc = style_data.get("description", "")
                sample     = style_data.get("sample_copy", "")
                style_block = "\n\n## 文風指定\n文風標籤:%s" % style_name
                if style_desc and style_desc != "(待填)":
                    style_block += "\n風格說明:%s" % style_desc
                if sample:
                    style_block += "\n參考範例(僅供文風參考,禁止複製內容):\n%s" % sample
            except (FileNotFoundError, ValueError, RuntimeError):
                pass  # 文風不存在/讀取失敗時靜默略過,不阻斷生成
        if style_free:
            style_block += "\n\n## 補充文風描述\n%s" % style_free
        system_text = _read_local(os.path.join(PROMPT_DIR, "system_base.md"))
        type_text   = _read_local(os.path.join(PROMPT_DIR, AD_TYPES[ad_type]))
        user_text = (
            type_text + style_block
            + "\n\n---\n\n## 品牌資料(僅可使用以下內容,禁止補充未載明事實)\n\n"
            + brand_readable
            + "\n\n---\n\n請產出 %d 個版本,版本之間僅以獨立一行「%s」分隔,不加編號標題,不加任何前後說明。"
            % (versions, VERSION_DELIM)
        )
        try:
            mod    = importlib.import_module("providers.%s" % env["PROVIDER"])
            result = mod.generate(system_text, user_text, env)
        except ModuleNotFoundError:
            self._send(400, {"error": "unknown provider: %s" % env["PROVIDER"]}); return
        except Exception as e:
            _append_log("error.log", "%s | /generate | provider_error | %s" % (
                self.log_date_time_string(), repr(e)))
            self._send(502, {"error": "供應商呼叫失敗,詳見 logs/error.log"}); return
        text  = result.get("text", "")
        parts = [p.strip() for p in text.split(VERSION_DELIM) if p.strip()]
        payload = {"versions": parts}
        if len(parts) != versions:
            payload["warning"] = "回傳版本數 %d 與要求 %d 不符,請人工檢視" % (len(parts), versions)
        self._send(200, payload)

    # ── POST /archive ─────────────────────────────────────────────────────────
    def _handle_archive(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        brand      = body.get("brand_id", "")
        ad_type    = body.get("ad_type", "")
        content    = body.get("content", "")
        perf_tag   = body.get("performance_tag", "")
        struct_tags= body.get("structure_tags", [])
        notes      = body.get("notes", "")
        prompt_ver = body.get("prompt_version", "")
        if not _safe_brand_name(brand):
            self._send(400, {"error": "invalid brand_id"}); return
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"}); return
        if perf_tag not in VALID_PERF_TAGS:
            self._send(400, {"error": "performance_tag must be one of: high, low, 未標記"}); return
        if not content.strip():
            self._send(400, {"error": "content is empty"}); return
        now      = datetime.now()
        filename = "%s-%s-%s.md" % (now.strftime("%Y%m%d_%H%M%S"), brand, ad_type)
        gh_path  = GH_ARCHIVE_PREFIX + now.strftime("%Y/") + filename
        file_text = (
            "---\nbrand_id: %s\nprompt_version: %s\nperformance_tag: %s\n"
            "structure_tags: %s\nnotes: \"%s\"\n---\n\n%s\n"
        ) % (brand, prompt_ver, perf_tag,
             json.dumps(struct_tags, ensure_ascii=False),
             notes.replace('"', '\\"'), content)
        _gh_put(env, gh_path, file_text,
                "archive: %s %s [auto-backup]" % (brand, ad_type))
        self._send(200, {"archived": filename})

    # ── POST /tag ─────────────────────────────────────────────────────────────
    def _handle_tag(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        filename = body.get("filename", "")
        perf_tag = body.get("performance_tag", "")
        if not _safe_filename(filename) or not filename.endswith(".md"):
            self._send(400, {"error": "invalid filename"}); return
        if perf_tag not in VALID_PERF_TAGS:
            self._send(400, {"error": "performance_tag must be one of: high, low, 未標記"}); return
        year = filename[:4] if len(filename) >= 4 else ""
        gh_path = GH_ARCHIVE_PREFIX + year + "/" + filename if year.isdigit() else None
        if not gh_path:
            self._send(400, {"error": "cannot infer year from filename"}); return
        try:
            text, sha = _gh_get(env, gh_path)
        except FileNotFoundError:
            self._send(404, {"error": "archive file not found"}); return
        new_text = re.sub(r"(?m)^performance_tag: .+$",
                          "performance_tag: " + perf_tag, text, count=1)
        _gh_put(env, gh_path, new_text,
                "tag: %s → %s [auto-backup]" % (filename, perf_tag), sha)
        try:
            freq_text, freq_sha = _gh_get(env, GH_TAG_FREQ_PATH)
            freq = json.loads(freq_text)
        except (FileNotFoundError, ValueError):
            freq, freq_sha = {}, None
        freq[perf_tag] = freq.get(perf_tag, 0) + 1
        _gh_put(env, GH_TAG_FREQ_PATH,
                json.dumps(freq, ensure_ascii=False, indent=2),
                "freq: update tag_frequency [auto-backup]", freq_sha)
        self._send(200, {"tagged": filename, "performance_tag": perf_tag})

    def log_message(self, fmt, *args):
        _append_log("activity.log", "%s | %s" % (
            self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("server.py Phase1 listening on http://localhost:%d" % port)
    print("GET  /brands /brand/<id> /prompts /prompt/<f> /styles /ad_types /ad_type/<id> /health")
    print("POST /brands/create /prompts/save /styles/add /ad_types/create /generate /archive /tag")
    print("DEL  /brand/<id> /style/<id> /ad_type/<id>")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
