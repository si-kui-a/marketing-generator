# providers/anthropic.py — Anthropic Messages API adapter(spec §4)。
# 介面契約:generate(system_text, user_text, env) -> {"text": str}
# 零第三方依賴,僅 urllib。金鑰只進請求標頭,禁止寫入任何 log 或例外訊息。
import json
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 4000
TIMEOUT_SEC = 120


def generate(system_text, user_text, env):
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({
            "model": env["MODEL"],
            "max_tokens": MAX_TOKENS,
            "system": system_text,
            "messages": [{"role": "user", "content": user_text}],
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": env["API_KEY"],
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 只透出狀態碼與 API 錯誤型別,不透出請求內容
        detail = ""
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            detail = err_body.get("error", {}).get("type", "")
        except Exception:
            pass
        raise RuntimeError("anthropic HTTP %d %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("network error: %s" % getattr(e, "reason", "unknown"))
    return {"text": data["content"][0]["text"]}
