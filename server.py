# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# Day3 完整版:GET /brands /brand, POST /generate /archive /tag, OPTIONS preflight。
import importlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
BRAND_DIR   = os.path.join(ROOT, "data", "brand")
PROMPT_DIR  = os.path.join(ROOT, "prompts")
ARCHIVE_DIR = os.path.join(ROOT, "data", "archive")
BACKUP_DIR  = os.path.join(ROOT, "data", "_local_backup")
TAG_FREQ_FP = os.path.join(ROOT, "data", "tag_frequency.json")
WORK_DIR    = os.path.join(ROOT, "work")

AD_TYPES = {"ig": "wedding_ig.md", "fb": "wedding_fb.md", "seo": "wedding_seo.md"}
VALID_PERF_TAGS = {"high", "low", "未標記"}
VERSION_DELIM = "===VERSION==="
MAX_VERSIONS = 5


# ── 共用工具 ──────────────────────────────────────────────────────────────────
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
    # 允許中文、英數、底線、連字號、點
    import re
    return bool(name) and not re.search(r'[/\\:*?"<>|\x00]', name)


# ── 備份(spec §8) ─────────────────────────────────────────────────────────────
def _auto_backup():
    """
    優先 git commit;失敗則降級為時間戳資料夾複製。
    Git 失敗類型:未安裝、未 init、user.name/email 未設定。
    """
    try:
        r_add = subprocess.run(
            ["git", "add", "-A"], cwd=ROOT,
            capture_output=True, text=True, timeout=30
        )
        r_cm = subprocess.run(
            ["git", "commit", "-m", "auto: /samples/confirm backup [perf:未標記]"],
            cwd=ROOT, capture_output=True, text=True, timeout=30
        )
        if r_cm.returncode == 0:
            return {"method": "git", "detail": r_cm.stdout.strip()}
        # commit 失敗但 add 成功時 reset,避免殘留 index 汙染
        subprocess.run(["git", "reset"], cwd=ROOT, capture_output=True, timeout=10)
        raise RuntimeError(r_cm.stderr.strip())
    except Exception as e:
        # 降級:時間戳複製
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        dst = os.path.join(BACKUP_DIR, ts)
        os.makedirs(dst, exist_ok=True)
        for sub in ("data/archive", "data/sample", "data/brand"):
            src = os.path.join(ROOT, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dst, sub.replace("/", os.sep)),
                                dirs_exist_ok=True)
        return {"method": "local_backup", "path": dst, "git_error": str(e)}


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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self, limit=1_000_000):
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
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error, see work/error.log"})

    def do_POST(self):
        try:
            path = unquote(self.path)
            if path == "/generate":
                self._handle_generate()
            elif path == "/archive":
                self._handle_archive()
            elif path == "/tag":
                self._handle_tag()
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error, see work/error.log"})

    # ── GET /brands ───────────────────────────────────────────────────────────
    def _handle_brands(self):
        if not os.path.isdir(BRAND_DIR):
            self._send(500, {"error": "data/brand directory missing"})
            return
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

    # ── POST /generate ────────────────────────────────────────────────────────
    def _handle_generate(self):
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        brand    = body.get("brand", "")
        ad_type  = body.get("ad_type", "")
        versions = body.get("versions", 1)
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
        system_text = _read_text(os.path.join(PROMPT_DIR, "system_base.md"))
        type_text   = _read_text(os.path.join(PROMPT_DIR, AD_TYPES[ad_type]))
        brand_text  = _read_text(brand_fp)
        user_text = (
            type_text
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
        """
        寫入 data/archive/YYYY/日期-品牌-類型.md,含 YAML frontmatter(嚴格五欄位)。
        spec §6:performance_tag 必填,不可為空字串。
        """
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        brand       = body.get("brand_id", "")
        ad_type     = body.get("ad_type", "")
        content     = body.get("content", "")
        perf_tag    = body.get("performance_tag", "")
        struct_tags = body.get("structure_tags", [])
        notes       = body.get("notes", "")
        prompt_ver  = body.get("prompt_version", "")
        if not _safe_brand_name(brand):
            self._send(400, {"error": "invalid brand_id"})
            return
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"})
            return
        if perf_tag not in VALID_PERF_TAGS:
            self._send(400, {"error": "performance_tag must be one of: high, low, 未標記"})
            return
        if not content.strip():
            self._send(400, {"error": "content is empty"})
            return
        if not isinstance(struct_tags, list):
            self._send(400, {"error": "structure_tags must be array"})
            return
        now       = datetime.now()
        year      = now.strftime("%Y")
        date_str  = now.strftime("%Y%m%d_%H%M%S")
        filename  = "%s-%s-%s.md" % (date_str, brand, ad_type)
        year_dir  = os.path.join(ARCHIVE_DIR, year)
        os.makedirs(year_dir, exist_ok=True)
        filepath  = os.path.join(year_dir, filename)
        tags_yaml = json.dumps(struct_tags, ensure_ascii=False)
        file_text = (
            "---\n"
            "brand_id: %s\n"
            "prompt_version: %s\n"
            "performance_tag: %s\n"
            "structure_tags: %s\n"
            "notes: \"%s\"\n"
            "---\n\n%s\n"
        ) % (brand, prompt_ver, perf_tag, tags_yaml, notes.replace('"', '\\"'), content)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(file_text)
        self._send(200, {"archived": filename})

    # ── POST /tag ─────────────────────────────────────────────────────────────
    def _handle_tag(self):
        """
        更新 archive 檔的 performance_tag,並同步累加 tag_frequency.json(純計數)。
        spec §6:tag_frequency.json 為「純計數,非語意」,禁止加入排序邏輯。
        """
        body, err = self._read_body()
        if err:
            self._send(400, {"error": err})
            return
        filename = body.get("filename", "")
        perf_tag = body.get("performance_tag", "")
        if not _safe_filename(filename) or not filename.endswith(".md"):
            self._send(400, {"error": "invalid filename"})
            return
        if perf_tag not in VALID_PERF_TAGS:
            self._send(400, {"error": "performance_tag must be one of: high, low, 未標記"})
            return
        # 找檔案(跨年份子目錄搜尋)
        target = None
        for root, _, files in os.walk(ARCHIVE_DIR):
            if filename in files:
                target = os.path.join(root, filename)
                break
        if not target:
            self._send(404, {"error": "archive file not found"})
            return
        text = _read_text(target)
        # 只替換 frontmatter 中的 performance_tag 行,不改其他內容
        import re
        new_text = re.sub(
            r"(?m)^performance_tag: .+$",
            "performance_tag: " + perf_tag,
            text,
            count=1
        )
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_text)
        # 累加 tag_frequency.json(純計數)
        freq = {}
        if os.path.isfile(TAG_FREQ_FP):
            try:
                freq = json.loads(_read_text(TAG_FREQ_FP))
            except ValueError:
                freq = {}
        freq[perf_tag] = freq.get(perf_tag, 0) + 1
        with open(TAG_FREQ_FP, "w", encoding="utf-8") as f:
            json.dump(freq, f, ensure_ascii=False, indent=2)
        self._send(200, {"tagged": filename, "performance_tag": perf_tag})

    def log_message(self, fmt, *args):
        _append_log("activity.log", "%s | %s" % (
            self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("server.py listening on http://localhost:%d" % port)
    print("endpoints: GET /brands /brand/<name>  POST /generate /archive /tag")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
