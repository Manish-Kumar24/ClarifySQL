"""
Thin adapter so the rest of the codebase doesn't care which LLM backend
is running underneath.

Provider priority when T2SQL_PROVIDER=auto (the default):
    1. Groq      (fast, free tier, cloud)   -- needs GROQ_API_KEY
    2. Ollama    (free, fully local/offline) -- needs `ollama serve` running
    3. Anthropic (paid)                      -- needs ANTHROPIC_API_KEY

To use Groq (recommended -- free & fast):
    1. Get a free key at https://console.groq.com/keys
    2. export GROQ_API_KEY=gsk_...
    That's it -- auto-detection picks it up first.

To use Ollama (fully offline, no data leaves your machine):
    1. Install from https://ollama.com
    2. Pull a model:  ollama pull llama3.1:8b
    3. export T2SQL_PROVIDER=ollama   (or just don't set GROQ_API_KEY)

To use Anthropic (paid API):
    export T2SQL_PROVIDER=anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import json
import re
import socket
import time
import urllib.request
import urllib.error

import config


class LLMError(RuntimeError):
    pass


def _parse_retry_after_seconds(err_body: str, default: float = 3.0) -> float:
    """
    Groq's 429 response includes a hint like 'Please try again in 4.255s'
    or 'Please try again in 480ms'. Parse it so we wait exactly as long as
    needed instead of guessing with fixed exponential backoff.
    """
    match = re.search(r"try again in ([\d.]+)(ms|s)\b", err_body)
    if not match:
        return default
    value, unit = match.groups()
    seconds = float(value) / 1000.0 if unit == "ms" else float(value)
    return seconds + 0.25  # small safety buffer


def _ollama_reachable() -> bool:
    try:
        host = config.OLLAMA_HOST.replace("http://", "").replace("https://", "")
        host, _, port = host.partition(":")
        port = int(port) if port else 11434
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def resolve_provider() -> str:
    """Implements the priority order when T2SQL_PROVIDER=auto."""
    if config.PROVIDER != "auto":
        return config.PROVIDER

    if config.GROQ_API_KEY:
        return "groq"
    if _ollama_reachable():
        return "ollama"
    if config.ANTHROPIC_API_KEY:
        return "anthropic"

    raise LLMError(
        "No LLM provider available. Set one of:\n"
        "  GROQ_API_KEY       (free, fast -- https://console.groq.com/keys)\n"
        "  Ollama running locally (https://ollama.com, then `ollama pull llama3.1:8b`)\n"
        "  ANTHROPIC_API_KEY  (paid)"
    )


def _call_ollama(system_prompt: str, user_prompt: str) -> str:
    url = f"{config.OLLAMA_HOST}/api/chat"
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": config.TEMPERATURE},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["message"]["content"]
    except urllib.error.URLError as e:
        raise LLMError(
            f"Could not reach Ollama at {config.OLLAMA_HOST}. "
            f"Is `ollama serve` running and is the model pulled? "
            f"Original error: {e}"
        )


def _call_groq(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.TEMPERATURE,
        "max_tokens": config.MAX_TOKENS,
    }
    if json_mode:
        # Groq (OpenAI-compatible) supports forcing valid JSON output, which
        # meaningfully reduces parse failures vs. instruction-only prompting.
        payload["response_format"] = {"type": "json_object"}

    if "gpt-oss" in config.GROQ_MODEL or "qwen3" in config.GROQ_MODEL:
        # Reasoning models (gpt-oss-*, qwen3-*) spend tokens on hidden
        # internal reasoning before the actual answer, and default to
        # "medium" effort. For a short, deterministic SQL-generation task
        # that reasoning budget is wasted and can starve the actual JSON
        # output of tokens -- keeping effort low leaves more room for the
        # answer itself and speeds up every call.
        payload["reasoning_effort"] = "low"

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        # Cloudflare (which fronts api.groq.com) blocks requests with
        # urllib's default "Python-urllib/x.x" User-Agent as bot traffic
        # (HTTP 403, "error code: 1010"). A normal browser-style UA
        # avoids that entirely -- this has nothing to do with your key.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }

    max_retries = 5
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")

            if e.code == 429 and attempt < max_retries:
                # Groq's free tier has a fairly low tokens-per-minute limit,
                # and its error response tells you exactly how long to wait.
                # Parse that and sleep, rather than failing the whole query.
                wait_seconds = _parse_retry_after_seconds(err_body)
                time.sleep(wait_seconds)
                continue

            if e.code == 401:
                raise LLMError(
                    f"Groq API error (401): invalid or missing API key. "
                    f"Check GROQ_API_KEY in your .env file. Raw response: {err_body}"
                )
            elif e.code == 429:
                raise LLMError(
                    f"Groq API error (429): still rate-limited after "
                    f"{max_retries} retries. Your free-tier TPM budget is "
                    f"likely exhausted for this run -- wait a minute and "
                    f"retry, or switch GROQ_MODEL to a smaller model like "
                    f"llama-3.1-8b-instant which has a higher free-tier "
                    f"limit. Raw response: {err_body}"
                )
            elif e.code == 403 and "1010" in err_body:
                raise LLMError(
                    f"Groq API error (403, Cloudflare 1010): request was "
                    f"blocked as bot traffic before it reached Groq. This is "
                    f"a network/UA issue, not your API key -- if you still "
                    f"see this after pulling the latest llm_client.py, try "
                    f"again from a different network. Raw response: {err_body}"
                )
            else:
                raise LLMError(f"Groq API error ({e.code}): {err_body}")
        except urllib.error.URLError as e:
            raise LLMError(f"Could not reach Groq API: {e}")


def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise LLMError("Run `pip install anthropic` to use the Anthropic provider.")

    if not config.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.MAX_TOKENS,
        temperature=config.TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def chat(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    """Send a system+user prompt to the resolved provider, return raw text."""
    provider = resolve_provider()
    if provider == "groq":
        return _call_groq(system_prompt, user_prompt, json_mode=json_mode)
    elif provider == "ollama":
        return _call_ollama(system_prompt, user_prompt)
    elif provider == "anthropic":
        return _call_anthropic(system_prompt, user_prompt)
    else:
        raise LLMError(f"Unknown provider: {provider}")


def chat_json(system_prompt: str, user_prompt: str) -> dict:
    """Call the model expecting a strict JSON object back, parse and return it."""
    # Nudge every provider toward JSON-only output; Groq additionally gets a
    # hard JSON-mode flag which markedly cuts down on parse failures.
    json_system_prompt = system_prompt + "\n\nRespond with JSON only. No markdown fences, no commentary."
    raw = chat(json_system_prompt, user_prompt, json_mode=True)
    raw = raw.strip()
    # Strip markdown code fences if the model added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"Model did not return valid JSON.\nRaw output:\n{raw}\n\nError: {e}")