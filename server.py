# server.py — 唯一對外溝通節點。零第三方依賴,僅 Python 標準庫。
# Day1 範圍:GET /brands、GET /brand/<name>。其餘端點 Day2/Day3 擴充。
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
BRAND_DIR = os.path.join(ROOT, "data", "brand")
WORK_DIR = os.path.join(ROOT, "work")


def _append_log(filename, line):
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, filename), "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # 解決 file:// 開啟前端呼叫 localhost 的 CORS 問題(spec §5)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = unquote(self.path)
            if path == "/brands":
                self._handle_brands()
            elif path.startswith("/brand/"):
                self._handle_brand(path[len("/brand/"):])
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # 任何未預期錯誤:回 500 並寫 error.log
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
        # 安全:拒絕空名與路徑跳脫字元
        if not name or any(c in name for c in ("/", "\\", "..", "\x00")):
            self._send(400, {"error": "invalid brand name"})
            return
        fp = os.path.join(BRAND_DIR, "brand-%s.md" % name)
        if not os.path.isfile(fp):
            self._send(404, {"error": "brand not found"})
            return
        with open(fp, "r", encoding="utf-8") as f:
            self._send(200, {"name": name, "content": f.read()})

    # 活動與錯誤分離:HTTP 存取流水寫 activity.log,不進 error.log
    def log_message(self, fmt, *args):
        _append_log("activity.log", "%s | %s" % (
            self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print("server.py listening on http://localhost:%d" % port)
    print("endpoints: GET /brands , GET /brand/<name>")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
