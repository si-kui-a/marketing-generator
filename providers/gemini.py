# providers/gemini.py — Google Gemini API adapter。
# 介面契約:generate(system_text, user_text, env) -> {"text": str}
# 零第三方依賴,僅urllib。金鑰只進URL query string(Gemini API設計如此),
# 禁止寫入任何log或例外訊息。
import json
import urllib.error
import urllib.request

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SEC = 120


def generate(system_text, user_text, env):
    model = env.get("MODEL", "gemini-2.5-flash")
    api_key = env.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    url = "%s/%s:generateContent?key=%s" % (API_BASE, model, api_key)
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            detail = err_body.get("error", {}).get("status", "")
            if e.code == 429:
                detail += " (rate limit exceeded,免費層額度已用盡,請稍後再試或考慮升級)"
        except Exception:
            pass
        raise RuntimeError("gemini HTTP %d %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("network error: %s" % getattr(e, "reason", "unknown"))
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # 可能因safety filter擋下或其他非預期回應結構
        finish_reason = data.get("candidates", [{}])[0].get("finishReason", "unknown")
        raise RuntimeError("gemini回應無法解析,finishReason: %s" % finish_reason)
    return {"text": text}
