# providers/gemini.py — Google Gemini API adapter。
# 介面契約:generate(system_text, user_text, env) -> {"text": str}
# 零第三方依賴,僅urllib。金鑰透過x-goog-api-key header傳遞(非URL query string),
# 禁止寫入任何log或例外訊息。
import json
import urllib.error
import urllib.request

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SEC = 120


def generate(system_text, user_text, env):
    """
    驗證方式:x-goog-api-key header(Google現行標準,非URL query參數)。
    理由:URL參數會使金鑰進入伺服器存取日誌、代理紀錄等多處,header方式無此外洩面。
    對齊Google 2026年9月起Standard Key全面失效、遷移至Auth Key的時程——
    Auth Key與Standard Key在呼叫端寫法完全同構,此改動本身不因遷移而需要
    進一步調整程式碼,差異僅在Google後台簽發的金鑰格式(AQ.Ab...而非AIza...)。
    """
    model = env.get("MODEL", "gemini-flash-latest")
    api_key = env.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    url = "%s/%s:generateContent" % (API_BASE, model)
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
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
