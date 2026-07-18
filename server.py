# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# Day2 範圍:GET /brands、GET /brand/<name>、POST /generate、OPTIONS preflight。
import importlib
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
BRAND_DIR = os.path.join(ROOT, "data", "brand")
PROMPT_DIR = os.path.join(ROOT, "prompts")
WORK_DIR = os.path.join(ROOT, "work")

AD_TYPES = {"ig": "wedding_ig.md", "fb": "wedding_fb.md", "seo": "wedding_seo.md"}
VERSION_DELIM = "===VERSION==="
MAX_VERSIONS = 5


def _append_log(filename, line):
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, filename), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_env():
    # 每次呼叫即時讀取,改 .env 免重啟。金鑰僅存於行程記憶體,不落 log。
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


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # 瀏覽器 POST application/json 會先發 preflight,必須回應否則 /generate 全掛
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            _append_log("error.log", "%s | %s | %s" % (
                self.log_date_time_string(), self.path, repr(e)))
            self._send(500, {"error": "internal error, see work/error.log"})

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

    def _handle_brand(self, name):
        if not name or any(c in name for c in ("/", "\\", "..", "\x00")):
            self._send(400, {"error": "invalid brand name"})
            return
        fp = os.path.join(BRAND_DIR, "brand-%s.md" % name)
        if not os.path.isfile(fp):
            self._send(404, {"error": "brand not found"})
            return
        self._send(200, {"name": name, "content": _read_text(fp)})

    def _handle_generate(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 1_000_000:
            self._send(400, {"error": "invalid body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "body must be valid JSON"})
            return
        brand = body.get("brand", "")
        ad_type = body.get("ad_type", "")
        versions = body.get("versions", 1)
        if ad_type not in AD_TYPES:
            self._send(400, {"error": "ad_type must be one of: ig, fb, seo"})
            return
        if not isinstance(versions, int) or not (1 <= versions <= MAX_VERSIONS):
            self._send(400, {"error": "versions must be int 1..%d" % MAX_VERSIONS})
            return
        if not brand or any(c in brand for c in ("/", "\\", "..", "\x00")):
            self._send(400, {"error": "invalid brand name"})
            return
        brand_fp = os.path.join(BRAND_DIR, "brand-%s.md" % brand)
        if not os.path.isfile(brand_fp):
            self._send(404, {"error": "brand not found"})
            return
        env = _load_env()
        provider = env.get("PROVIDER", "")
        if not provider or not env.get("API_KEY") or not env.get("MODEL"):
            self._send(503, {"error": "設定未完成:請複製 .env.example 為 .env 並填入 PROVIDER / API_KEY / MODEL"})
            return
        # 模板即時讀取,改檔免重啟(spec §5 技術要點)
        system_text = _read_text(os.path.join(PROMPT_DIR, "system_base.md"))
        type_text = _read_text(os.path.join(PROMPT_DIR, AD_TYPES[ad_type]))
        brand_text = _read_text(brand_fp)
        user_text = (
            type_text
            + "\n\n---\n\n## 品牌資料(僅可使用以下內容,禁止補充未載明事實)\n\n"
            + brand_text
            + "\n\n---\n\n請產出 %d 個版本,版本之間僅以獨立一行「%s」分隔,不加編號標題,不加任何前後說明。"
            % (versions, VERSION_DELIM)
        )
        try:
            mod = importlib.import_module("providers.%s" % provider)
            result = mod.generate(system_text, user_text, env)
        except ModuleNotFoundError:
            self._send(400, {"error": "unknown provider: %s" % provider})
            return
        except Exception as e:
            # 只記錯誤類別與供應商回覆狀態,不記請求標頭,金鑰不落地
            _append_log("error.log", "%s | /generate | provider_error | %s" % (
                self.log_date_time_string(), repr(e)))
            self._send(502, {"error": "供應商呼叫失敗,詳見 work/error.log"})
            return
        text = result.get("text", "")
        parts = [p.strip() for p in text.split(VERSION_DELIM) if p.strip()]
        payload = {"versions": parts}
        if len(parts) != versions:
            payload["warning"] = "回傳版本數 %d 與要求 %d 不符,請人工檢視" % (len(parts), versions)
        self._send(200, payload)

    def log_message(self, fmt, *args):
        _append_log("activity.log", "%s | %s" % (
            self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("server.py listening on http://localhost:%d" % port)
    print("endpoints: GET /brands , GET /brand/<name> , POST /generate")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
