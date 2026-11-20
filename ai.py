"""Connector to an AI service of your choice, set on Limits -> Telegram -> Chat with the bot.

Providers: Google Gemini, OpenAI (ChatGPT), Anthropic Claude, or any OpenAI-compatible service
(Groq, OpenRouter, DeepSeek, Mistral, Together ...) at a web address you give. Pick the provider,
paste a key and a model name: no code change is needed for a new key or service.

Used by the Telegram bot for two jobs only:
  1. understand a free-text question -> one of the bot's commands (only the question text is sent);
  2. translate a finished answer into Hindi when you chose Hindi (the answer text, with your numbers,
     is then sent to the AI service; the bot checks every number survived the translation).
The key is stored only on the NAS in data/ai_key.txt (owner-only file), never in git or the logs.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

S = None   # server module

PROVIDERS = {
    "gemini": {"label": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta", "model_hint": "e.g. gemini-2.5-flash"},
    "openai": {"label": "OpenAI (ChatGPT)", "base": "https://api.openai.com/v1", "model_hint": "e.g. gpt-4o-mini"},
    "anthropic": {"label": "Anthropic Claude", "base": "https://api.anthropic.com/v1", "model_hint": "e.g. claude-haiku-5-5"},
    "compatible": {"label": "Any OpenAI-compatible (Groq, OpenRouter, DeepSeek, Mistral…)", "base": "",
                   "model_hint": "e.g. llama-3.3-70b-versatile (Groq)"},
}
EXAMPLE_BASES = {"Groq": "https://api.groq.com/openai/v1", "OpenRouter": "https://openrouter.ai/api/v1",
                 "DeepSeek": "https://api.deepseek.com/v1", "Mistral": "https://api.mistral.ai/v1",
                 "Together": "https://api.together.xyz/v1"}
TIMEOUT = 25
_status = {"last_ok": None, "last_error": None}


def _key_file():
    return os.path.join(S.DATA, "ai_key.txt")


def saved_key():
    try:
        with open(_key_file(), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def cfg():
    c = dict(S.load_state().get("ai") or {})
    c.setdefault("provider", "gemini")
    c.setdefault("model", "")
    c.setdefault("base_url", "")
    return c


def configured():
    c = cfg()
    return bool(saved_key() and c.get("model") and (c["provider"] != "compatible" or c.get("base_url")))


def status():
    c = cfg()
    k = saved_key()
    return {"provider": c["provider"], "model": c["model"], "base_url": c["base_url"], "key_tail": k[-4:] if k else None,
            "configured": configured(), "providers": {p: {"label": v["label"], "model_hint": v["model_hint"]} for p, v in PROVIDERS.items()},
            "example_bases": EXAMPLE_BASES, "last_ok": _status["last_ok"], "last_error": _status["last_error"]}


def _clean(body, need_key):
    p = body.get("provider")
    if p not in PROVIDERS:
        raise S.ApiError(400, "Choose a provider.")
    model = str(body.get("model") or "").strip()[:120]
    if not model or not re.fullmatch(r"[A-Za-z0-9._:/@+-]+", model):
        raise S.ApiError(400, "Enter the model name exactly as the provider lists it (letters, digits, . - _ : /).")
    base = str(body.get("base_url") or "").strip().rstrip("/")[:200]
    if p == "compatible":
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?", base):
            raise S.ApiError(400, "Enter the service's API address, starting with https:// (e.g. https://api.groq.com/openai/v1).")
    else:
        base = ""
    key = re.sub(r"\s+", "", str(body.get("key") or ""))[:300]
    if need_key and not key:
        raise S.ApiError(400, "Paste the API key.")
    return {"provider": p, "model": model, "base_url": base}, key


def _http(url, body, headers, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers=dict({"Content-Type": "application/json", "User-Agent": "tradeskill-portal"}, **headers),
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read() or b"{}")
            msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message")
        except ValueError:
            msg = None
        hint = {401: "the key was refused", 403: "the key has no access to this", 404: "model or address not found",
                429: "free limit reached for now (try later)"}.get(e.code, "HTTP %s" % e.code)
        raise S.ApiError(502, "AI service: %s%s" % (hint, (": " + str(msg)[:160]) if msg else ""))
    except Exception as e:  # noqa: BLE001
        raise S.ApiError(502, "AI service not reachable: %s" % str(e)[:120])


def _ask(c, key, system, user, max_tokens=300):
    p = c["provider"]
    if p == "gemini":
        j = _http("%s/models/%s:generateContent" % (PROVIDERS["gemini"]["base"], c["model"]),
                  {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens}},
                  {"x-goog-api-key": key})
        parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(x.get("text", "") for x in parts).strip()
    if p == "anthropic":
        j = _http(PROVIDERS["anthropic"]["base"] + "/messages",
                  {"model": c["model"], "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}],
                   "temperature": 0},
                  {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in j.get("content") or [] if b.get("type") == "text").strip()
    base = PROVIDERS["openai"]["base"] if p == "openai" else c["base_url"]
    j = _http(base + "/chat/completions",
              {"model": c["model"], "max_tokens": max_tokens, "temperature": 0,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
              {"Authorization": "Bearer " + key})
    return (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()


def ask(system, user, max_tokens=300):
    """One request to your saved AI service. Raises S.ApiError with a plain reason if it fails."""
    c = cfg()
    key = saved_key()
    if not configured():
        raise S.ApiError(409, "No AI service set yet (Limits -> Telegram -> Chat with the bot).")
    try:
        out = _ask(c, key, system, user, max_tokens)
    except S.ApiError as e:
        _status["last_error"] = "%s · %s" % (S.now_ist().strftime("%d %b %H:%M"), str(e)[:200])
        raise
    _status["last_ok"] = S.now_ist().strftime("%d %b %H:%M")
    return out


def models(body):
    """The model names this key can use (so you can pick one instead of guessing)."""
    c, key = _clean(dict(body, model=body.get("model") or "x"), need_key=False)
    key = key or saved_key()
    if not key:
        raise S.ApiError(400, "Paste the API key first.")
    p = c["provider"]
    if p == "gemini":
        j = _http(PROVIDERS["gemini"]["base"] + "/models?pageSize=200", None, {"x-goog-api-key": key})
        names = [m["name"].split("/", 1)[-1] for m in j.get("models") or [] if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    elif p == "anthropic":
        j = _http(PROVIDERS["anthropic"]["base"] + "/models?limit=100", None, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        names = [m["id"] for m in j.get("data") or []]
    else:
        base = PROVIDERS["openai"]["base"] if p == "openai" else c["base_url"]
        j = _http(base + "/models", None, {"Authorization": "Bearer " + key})
        names = [m["id"] for m in j.get("data") or []]
    return {"models": sorted(set(names))[:300]}


def test(body):
    """Try the settings in the form (or the saved key when the key box is empty) with a tiny question."""
    c, key = _clean(body, need_key=False)
    key = key or saved_key()
    if not key:
        raise S.ApiError(400, "Paste the API key first.")
    t0 = time.time()
    out = _ask(c, key, "Reply with exactly one word.", "Say OK.", max_tokens=20)
    return {"ok": True, "reply": out[:80], "secs": round(time.time() - t0, 1),
            "message": "Works: %s answered %r in %.1f s." % (PROVIDERS[c["provider"]]["label"], out[:30], time.time() - t0)}


def save(body, check_pw):
    """Save provider + model (+ address) and, when given, a new key. Needs the portal password; the key is tested first."""
    check_pw(body.get("password"))
    c, key = _clean(body, need_key=not saved_key())
    use = key or saved_key()
    _ask(c, use, "Reply with exactly one word.", "Say OK.", max_tokens=20)   # refuse settings that don't work
    if key:
        os.makedirs(S.DATA, exist_ok=True)
        tmp = _key_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(key)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, _key_file())
    with S._state_lock:
        st = S.load_state()
        st["ai"] = c
        S.save_state(st)
    _status["last_error"] = None
    out = status()
    out["message"] = "Saved and tested: %s · %s." % (PROVIDERS[c["provider"]]["label"], c["model"])
    return out


def forget(check_pw, password):
    check_pw(password)
    try:
        os.remove(_key_file())
    except OSError:
        pass
    out = status()
    out["message"] = "AI key removed. The bot now understands messages by keywords only."
    return out
