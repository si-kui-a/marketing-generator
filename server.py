# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# 第二輪完整版:品牌 CRUD、prompts UI 編輯、文風管理、auto git commit。
import importlib
import json
import os
import re
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

ROOT        = os.path.dirname(os.path.abspath(__file__))
BRAND_DIR   = os.path.join(ROOT, "data", "brand")
PROMPT_DIR  = os.path.join(ROOT, "prompts")
ARCHIVE_DIR = os.path.join(ROOT, "data", "archive")
STYLES_FP   = os.path.join(ROOT, "config", "styles.json")
CHANGELOG   = os.path.join(ROOT, "rules_changelog.md")
WORK_DIR    = os.path.join(ROOT, "work")

AD_TYPES        = {"ig": "wedding_ig.md", "fb": "wedding_fb.md", "seo": "wedding_seo.md"}
VALID_PERF_TAGS = {"high", "low", "未標記"}
VERSION_DELIM   = "===VERSION==="
MAX_VERSIONS    = 5
PROMPT_WHITELIST = set(AD_TYPES.values()) | {"system_base.md"}


def _append_log(filename, line):
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, filename), "a", encoding="utf-8") as f:
        f.write(line + "\n")


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


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _safe_brand_name(name):
    return bool(name) and not any(c in name for c in ("/", "\\", "..", "\x00"))


def _safe_filename(name):
    return bool(name) and not re.search(r'[/\\:*?"<>|\x00]', name)


def _append_changelog(filename, summary):
    now = datetime.now().strftime("%Y-%m-%d")
    line = "%s | prompts | %s | %s | 觸發原因:UI 編輯器存檔" % (now, filename, summary)
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _git_commit_prompts(filename):
    """只 add prompts/ 目錄,禁止 git add -A,避免意外納入 .env。"""
    try:
        subprocess.run(["git", "add", "prompts/", "rules_changelog.md"],
                       cwd=ROOT, capture_output=True, timeout=30)
        r = subprocess.run(
            ["git", "commit", "-m", "prompts: UI edit %s [perf:未標記]" % filename],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if r.returncode == 0:
            return {"git": "committed", "detail": r.stdout.strip()}
        return {"git": "nothing_to_commit"}
    except Exception as e:
        return {"git": "error", "detail": str(e)}


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
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error"})

    # ── GET /brands ───────────────────────────────────────────────────────────
    def _handle_brands(self):
        names = sorted(
            f[len("brand-"):-len(".md")]
            for f in os.listdir(BRAND_DIR)
            if f.startswith("brand-") and f.endswith(".md")
        )
        self._send(200, {"brands": names})

    # ── GET /brand/<name> ─────────────────────────────────────────────────────
    def _handle_brand(self, name):
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"})
            return
        fp = os.path.join(BRAND_DIR, "brand-%s.md" % name)
        if not os.path.isfile(fp):
            self._send(404, {"error": "brand not found"})
            return
        self._send(200, {"name": name, "content": _read_text(fp)})

    # ── POST /brands/create ───────────────────────────────────────────────────
    def _handle_brand_create(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        name      = body.get("name", "").strip()
        axis      = body.get("axis", "").strip()       # 本次文案主軸
        reviews   = body.get("reviews", "").strip()    # Google 地圖評價
        activity  = body.get("activity", "").strip()   # 活動頁面文案
        extras    = body.get("extras", [])              # [{label, content}]
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"})
            return
        fp = os.path.join(BRAND_DIR, "brand-%s.md" % name)
        if os.path.isfile(fp):
            self._send(409, {"error": "品牌已存在,請使用其他名稱"})
            return
        if not isinstance(extras, list):
            extras = []
        lines = [
            "---",
            "brand_id: %s" % name,
            "status: 已填",
            "---",
            "",
            "# %s" % name,
            "",
            "## 本次文案主軸",
            axis or "(待填)",
            "",
            "## Google 地圖評價",
            reviews or "(待填)",
            "",
            "## 活動頁面文案",
            activity or "(待填)",
        ]
        for ex in extras:
            label   = str(ex.get("label", "")).strip()
            content = str(ex.get("content", "")).strip()
            if label:
                lines += ["", "## %s" % label, content or "(待填)"]
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._send(200, {"created": name})

    # ── DELETE /brand/<name> ──────────────────────────────────────────────────
    def _handle_brand_delete(self, name):
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"})
            return
        fp = os.path.join(BRAND_DIR, "brand-%s.md" % name)
        if not os.path.isfile(fp):
            self._send(404, {"error": "brand not found"})
            return
        os.remove(fp)
        self._send(200, {"deleted": name})

    # ── GET /prompts ──────────────────────────────────────────────────────────
    def _handle_get_prompts(self):
        files = [f for f in os.listdir(PROMPT_DIR) if f.endswith(".md")]
        self._send(200, {"prompts": sorted(files)})

    # ── GET /prompt/<filename> ────────────────────────────────────────────────
    def _handle_get_prompt(self, filename):
        if filename not in PROMPT_WHITELIST:
            self._send(403, {"error": "file not in whitelist"})
            return
        fp = os.path.join(PROMPT_DIR, filename)
        if not os.path.isfile(fp):
            self._send(404, {"error": "prompt not found"})
            return
        self._send(200, {"filename": filename, "content": _read_text(fp)})

    # ── POST /prompts/save ────────────────────────────────────────────────────
    def _handle_prompt_save(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        filename = body.get("filename", "")
        content  = body.get("content", "")
        summary  = body.get("summary", "內容更新").strip() or "內容更新"
        if filename not in PROMPT_WHITELIST:
            self._send(403, {"error": "file not in whitelist"})
            return
        if not content.strip():
            self._send(400, {"error": "content is empty"})
            return
        fp = os.path.join(PROMPT_DIR, filename)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        _append_changelog(filename, summary)
        git_result = _git_commit_prompts(filename)
        self._send(200, {"saved": filename, "git": git_result})

    # ── GET /styles ───────────────────────────────────────────────────────────
    def _handle_get_styles(self):
        styles = {}
        if os.path.isfile(STYLES_FP):
            try:
                styles = json.loads(_read_text(STYLES_FP))
            except ValueError:
                styles = {}
        self._send(200, {"styles": styles})

    # ── POST /styles/add ──────────────────────────────────────────────────────
    def _handle_style_add(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        label   = body.get("label", "").strip()
        example = body.get("example", "").strip()
        if not label:
            self._send(400, {"error": "label is required"})
            return
        styles = {}
        if os.path.isfile(STYLES_FP):
            try:
                styles = json.loads(_read_text(STYLES_FP))
            except ValueError:
                styles = {}
        styles[label] = example
        with open(STYLES_FP, "w", encoding="utf-8") as f:
            json.dump(styles, f, ensure_ascii=False, indent=2)
        self._send(200, {"added": label})

    # ── POST /generate ────────────────────────────────────────────────────────
    def _handle_generate(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        brand       = body.get("brand", "")
        ad_type     = body.get("ad_type", "")
        versions    = body.get("versions", 1)
        style_label = body.get("style_label", "")   # 選單選項
        style_free  = body.get("style_free", "")    # 自由輸入
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"})
            return
        if not isinstance(versions, int) or not (1 <= versions <= MAX_VERSIONS):
            self._send(400, {"error": "versions must be int 1..%d" % MAX_VERSIONS})
            return
        if not _safe_brand_name(brand):
            self._send(400, {"error": "invalid brand name"})
            return
        brand_fp = os.path.join(BRAND_DIR, "brand-%s.md" % brand)
        if not os.path.isfile(brand_fp):
            self._send(404, {"error": "brand not found"})
            return
        env = _load_env()
        if not env.get("PROVIDER") or not env.get("API_KEY") or not env.get("MODEL"):
            self._send(503, {"error": "設定未完成:請複製 .env.example 為 .env 並填入 PROVIDER / API_KEY / MODEL"})
            return
        # 文風注入
        style_block = ""
        if style_label:
            styles = {}
            if os.path.isfile(STYLES_FP):
                try:
                    styles = json.loads(_read_text(STYLES_FP))
                except ValueError:
                    pass
            example = styles.get(style_label, "")
            style_block = "\n\n## 文風指定\n文風標籤:%s" % style_label
            if example:
                style_block += "\n參考範例(僅供文風參考,禁止複製內容):\n%s" % example
        if style_free:
            style_block += "\n\n## 補充文風描述\n%s" % style_free
        system_text = _read_text(os.path.join(PROMPT_DIR, "system_base.md"))
        type_text   = _read_text(os.path.join(PROMPT_DIR, AD_TYPES[ad_type]))
        brand_text  = _read_text(brand_fp)
        user_text = (
            type_text
            + style_block
            + "\n\n---\n\n## 品牌資料(僅可使用以下內容,禁止補充未載明事實)\n\n"
            + brand_text
            + "\n\n---\n\n請產出 %d 個版本,版本之間僅以獨立一行「%s」分隔,不加編號標題,不加任何前後說明。"
            % (versions, VERSION_DELIM)
        )
        try:
            mod    = importlib.import_module("providers.%s" % env["PROVIDER"])
            result = mod.generate(system_text, user_text, env)
        except ModuleNotFoundError:
            self._send(400, {"error": "unknown provider: %s" % env["PROVIDER"]})
            return
        except Exception as e:
            _append_log("error.log", "%s | /generate | provider_error | %s" % (
                self.log_date_time_string(), repr(e)))
            self._send(502, {"error": "供應商呼叫失敗,詳見 work/error.log"})
            return
        text  = result.get("text", "")
        parts = [p.strip() for p in text.split(VERSION_DELIM) if p.strip()]
        payload = {"versions": parts}
        if len(parts) != versions:
            payload["warning"] = "回傳版本數 %d 與要求 %d 不符,請人工檢視" % (len(parts), versions)
        self._send(200, payload)

    # ── POST /archive ─────────────────────────────────────────────────────────
    def _handle_archive(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
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
        if not isinstance(struct_tags, list):
            self._send(400, {"error": "structure_tags must be array"}); return
        now      = datetime.now()
        year_dir = os.path.join(ARCHIVE_DIR, now.strftime("%Y"))
        os.makedirs(year_dir, exist_ok=True)
        filename = "%s-%s-%s.md" % (now.strftime("%Y%m%d_%H%M%S"), brand, ad_type)
        file_text = (
            "---\nbrand_id: %s\nprompt_version: %s\nperformance_tag: %s\n"
            "structure_tags: %s\nnotes: \"%s\"\n---\n\n%s\n"
        ) % (brand, prompt_ver, perf_tag,
             json.dumps(struct_tags, ensure_ascii=False),
             notes.replace('"', '\\"'), content)
        with open(os.path.join(year_dir, filename), "w", encoding="utf-8") as f:
            f.write(file_text)
        self._send(200, {"archived": filename})

    # ── POST /tag ─────────────────────────────────────────────────────────────
    def _handle_tag(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err}); return
        filename = body.get("filename", "")
        perf_tag = body.get("performance_tag", "")
        if not _safe_filename(filename) or not filename.endswith(".md"):
            self._send(400, {"error": "invalid filename"}); return
        if perf_tag not in VALID_PERF_TAGS:
            self._send(400, {"error": "performance_tag must be one of: high, low, 未標記"}); return
        target = None
        for root, _, files in os.walk(ARCHIVE_DIR):
            if filename in files:
                target = os.path.join(root, filename); break
        if not target:
            self._send(404, {"error": "archive file not found"}); return
        text = _read_text(target)
        new_text = re.sub(r"(?m)^performance_tag: .+$",
                          "performance_tag: " + perf_tag, text, count=1)
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_text)
        freq = {}
        if os.path.isfile(os.path.join(ROOT, "data", "tag_frequency.json")):
            try:
                freq = json.loads(_read_text(os.path.join(ROOT, "data", "tag_frequency.json")))
            except ValueError:
                freq = {}
        freq[perf_tag] = freq.get(perf_tag, 0) + 1
        with open(os.path.join(ROOT, "data", "tag_frequency.json"), "w", encoding="utf-8") as f:
            json.dump(freq, f, ensure_ascii=False, indent=2)
        self._send(200, {"tagged": filename, "performance_tag": perf_tag})

    def log_message(self, fmt, *args):
        _append_log("activity.log", "%s | %s" % (
            self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("server.py listening on http://localhost:%d" % port)
    print("endpoints: GET /brands /brand/<n> /prompts /prompt/<f> /styles")
    print("           POST /brands/create /prompts/save /styles/add /generate /archive /tag")
    print("           DELETE /brand/<n>")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
