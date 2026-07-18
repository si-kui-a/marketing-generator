# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# v3 GitHub 優先架構:品牌、文風、模板資料統一經 GitHub Contents API 讀寫。
import base64
import importlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import quote, unquote

ROOT       = os.path.dirname(os.path.abspath(__file__))
PROMPT_DIR = os.path.join(ROOT, "prompts")   # 模板仍保留本機(供離線編輯參考)
WORK_DIR   = os.path.join(ROOT, "work")
CHANGELOG  = os.path.join(ROOT, "rules_changelog.md")

AD_TYPES         = {"ig": "wedding_ig.md", "fb": "wedding_fb.md", "seo": "wedding_seo.md"}
VALID_PERF_TAGS  = {"high", "low", "未標記"}
VERSION_DELIM    = "===VERSION==="
MAX_VERSIONS     = 5
PROMPT_WHITELIST = set(AD_TYPES.values()) | {"system_base.md"}

# GitHub Contents API paths
GH_BRAND_PREFIX   = "data/brand/"
GH_ARCHIVE_PREFIX = "data/archive/"
GH_STYLES_PATH    = "config/styles.json"
GH_TAG_FREQ_PATH  = "data/tag_frequency.json"


# ── 工具 ──────────────────────────────────────────────────────────────────────
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


def _load_styles(env):
    try:
        text, _ = _gh_get(env, GH_STYLES_PATH)
        return json.loads(text)
    except (FileNotFoundError, ValueError):
        return {}


def _save_styles(env, styles, sha=None):
    text = json.dumps(styles, ensure_ascii=False, indent=2)
    _gh_put(env, GH_STYLES_PATH, text,
            "data: update styles.json [auto-backup]", sha)


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
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error"})

    # ── GET /brands ───────────────────────────────────────────────────────────
    def _handle_brands(self):
        env = _load_env()
        if not env.get("GITHUB_TOKEN") or not env.get("GITHUB_REPO"):
            self._send(503, {"error": "GITHUB_TOKEN / GITHUB_REPO 未設定"}); return
        try:
            files = _gh_list(env, GH_BRAND_PREFIX)
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e}); return
        names = sorted(
            f[len("brand-"):-len(".md")]
            for f in files
            if f.startswith("brand-") and f.endswith(".md")
        )
        self._send(200, {"brands": names})

    # ── GET /brand/<name> ─────────────────────────────────────────────────────
    def _handle_brand(self, name):
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"}); return
        env = _load_env()
        try:
            content, _ = _gh_get(env, GH_BRAND_PREFIX + "brand-%s.md" % name)
            self._send(200, {"name": name, "content": content})
        except FileNotFoundError:
            self._send(404, {"error": "brand not found"})

    # ── POST /brands/create ───────────────────────────────────────────────────
    def _handle_brand_create(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        name     = body.get("name", "").strip()
        axis     = body.get("axis", "").strip()
        reviews  = body.get("reviews", "").strip()
        activity = body.get("activity", "").strip()
        extras   = body.get("extras", [])
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"}); return
        gh_path = GH_BRAND_PREFIX + "brand-%s.md" % name
        try:
            _gh_get(env, gh_path)
            self._send(409, {"error": "品牌已存在,請使用其他名稱"}); return
        except FileNotFoundError:
            pass
        lines = [
            "---", "brand_id: %s" % name, "status: 已填", "---", "",
            "# %s" % name, "",
            "## 本次文案主軸", axis or "(待填)", "",
            "## Google 地圖評價", reviews or "(待填)", "",
            "## 活動頁面文案", activity or "(待填)",
        ]
        for ex in (extras if isinstance(extras, list) else []):
            label = str(ex.get("label", "")).strip()
            if label:
                lines += ["", "## %s" % label, str(ex.get("content", "")).strip() or "(待填)"]
        content = "\n".join(lines) + "\n"
        _gh_put(env, gh_path, content,
                "brand: add %s [auto-backup]" % name)
        self._send(200, {"created": name})

    # ── DELETE /brand/<name> ──────────────────────────────────────────────────
    def _handle_brand_delete(self, name):
        if not _safe_brand_name(name):
            self._send(400, {"error": "invalid brand name"}); return
        env = _load_env()
        gh_path = GH_BRAND_PREFIX + "brand-%s.md" % name
        try:
            _, sha = _gh_get(env, gh_path)
        except FileNotFoundError:
            self._send(404, {"error": "brand not found"}); return
        _gh_delete(env, gh_path, "brand: delete %s [auto-backup]" % name, sha)
        self._send(200, {"deleted": name})

    # ── GET /prompts ──────────────────────────────────────────────────────────
    def _handle_get_prompts(self):
        files = [f for f in os.listdir(PROMPT_DIR) if f.endswith(".md")]
        self._send(200, {"prompts": sorted(files)})

    # ── GET /prompt/<filename> ────────────────────────────────────────────────
    def _handle_get_prompt(self, filename):
        if filename not in PROMPT_WHITELIST:
            self._send(403, {"error": "file not in whitelist"}); return
        fp = os.path.join(PROMPT_DIR, filename)
        if not os.path.isfile(fp):
            self._send(404, {"error": "prompt not found"}); return
        self._send(200, {"filename": filename, "content": _read_local(fp)})

    # ── POST /prompts/save ────────────────────────────────────────────────────
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
        # 寫本機
        fp = os.path.join(PROMPT_DIR, filename)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        # 同步 GitHub
        gh_path = "prompts/" + filename
        try:
            _, sha = _gh_get(env, gh_path)
        except FileNotFoundError:
            sha = None
        _gh_put(env, gh_path, content,
                "prompts: %s — %s [auto-backup]" % (filename, summary), sha)
        # changelog
        now  = datetime.now().strftime("%Y-%m-%d")
        line = "%s | prompts | %s | %s | 觸發原因:UI 編輯器存檔" % (now, filename, summary)
        _append_changelog_gh(env, line)
        self._send(200, {"saved": filename, "github": "pushed"})

    # ── GET /styles ───────────────────────────────────────────────────────────
    def _handle_get_styles(self):
        env = _load_env()
        if not env.get("GITHUB_TOKEN") or not env.get("GITHUB_REPO"):
            self._send(503, {"error": "GITHUB_TOKEN / GITHUB_REPO 未設定"}); return
        try:
            self._send(200, {"styles": _load_styles(env)})
        except RuntimeError as e:
            self._send(502, {"error": "GitHub 連線失敗:%s" % e})

    # ── POST /styles/add ──────────────────────────────────────────────────────
    def _handle_style_add(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        label   = body.get("label", "").strip()
        example = body.get("example", "").strip()
        if not label:
            self._send(400, {"error": "label is required"}); return
        try:
            text, sha = _gh_get(env, GH_STYLES_PATH)
            styles = json.loads(text)
        except FileNotFoundError:
            styles, sha = {}, None
        styles[label] = example
        _save_styles(env, styles, sha)
        self._send(200, {"added": label})

    # ── DELETE /style/<label> ─────────────────────────────────────────────────
    def _handle_style_delete(self, label):
        label = unquote(label)
        env   = _load_env()
        try:
            text, sha = _gh_get(env, GH_STYLES_PATH)
            styles = json.loads(text)
        except FileNotFoundError:
            self._send(404, {"error": "styles not found"}); return
        if label not in styles:
            self._send(404, {"error": "style not found"}); return
        del styles[label]
        _save_styles(env, styles, sha)
        self._send(200, {"deleted": label})

    # ── POST /generate ────────────────────────────────────────────────────────
    def _handle_generate(self):
        body, err = self._read_body()
        if err: self._send(400, {"error": err}); return
        env = self._env_or_503()
        if not env: return
        brand       = body.get("brand", "")
        ad_type     = body.get("ad_type", "")
        versions    = body.get("versions", 1)
        style_label = body.get("style_label", "")
        style_free  = body.get("style_free", "")
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"}); return
        if not isinstance(versions, int) or not (1 <= versions <= MAX_VERSIONS):
            self._send(400, {"error": "versions must be int 1..%d" % MAX_VERSIONS}); return
        if not _safe_brand_name(brand):
            self._send(400, {"error": "invalid brand name"}); return
        try:
            brand_text, _ = _gh_get(env, GH_BRAND_PREFIX + "brand-%s.md" % brand)
        except FileNotFoundError:
            self._send(404, {"error": "brand not found"}); return
        style_block = ""
        if style_label:
            styles = _load_styles(env)
            example = styles.get(style_label, "")
            style_block = "\n\n## 文風指定\n文風標籤:%s" % style_label
            if example:
                style_block += "\n參考範例(僅供文風參考,禁止複製內容):\n%s" % example
        if style_free:
            style_block += "\n\n## 補充文風描述\n%s" % style_free
        system_text = _read_local(os.path.join(PROMPT_DIR, "system_base.md"))
        type_text   = _read_local(os.path.join(PROMPT_DIR, AD_TYPES[ad_type]))
        user_text = (
            type_text + style_block
            + "\n\n---\n\n## 品牌資料(僅可使用以下內容,禁止補充未載明事實)\n\n"
            + brand_text
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
            self._send(502, {"error": "供應商呼叫失敗,詳見 work/error.log"}); return
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
        # 搜尋 archive 下各年份
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
        # 累加 tag_frequency
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
    print("server.py v3 GitHub-first listening on http://localhost:%d" % port)
    print("GET  /brands /brand/<n> /prompts /prompt/<f> /styles /health")
    print("POST /brands/create /prompts/save /styles/add /generate /archive /tag")
    print("DEL  /brand/<n> /style/<label>")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
