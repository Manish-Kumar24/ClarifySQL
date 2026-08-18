"""
Central config for the project.

PROVIDER controls which LLM backend is used. Default is "auto", which picks
the first available provider in priority order:

  1. Groq   -- free tier, cloud-hosted, runs Llama models FAST (this is why
               it's first: same Llama models you wanted, much less waiting)
  2. Ollama -- free, fully local/offline, for when you don't want to send
               data over the network, or don't have a Groq key
  3. Anthropic -- paid, only used if explicitly selected or if it's the only
               provider configured

Set T2SQL_PROVIDER explicitly (e.g. "ollama") to force one and skip the
auto-detection.
"""

import os


def _load_dotenv(path: str = None) -> None:
    """
    Minimal .env loader -- no extra pip dependency needed. Reads KEY=VALUE
    lines from a .env file next to this config.py and sets them into
    os.environ, but only if that key isn't already set in the real
    environment (so `export GROQ_API_KEY=...` in your shell always wins
    over the .env file, which is the expected behavior).
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

# --- LLM Provider ---
# "auto"      -> pick the best available provider using the priority order above
# "groq"      -> free tier, cloud, fast Llama models (needs GROQ_API_KEY)
# "ollama"    -> free, fully local Llama models (needs Ollama running)
# "anthropic" -> paid API, only use if you have credits/billing set up
PROVIDER = os.getenv("T2SQL_PROVIDER", "auto")

# Groq settings (cloud, free tier -- get a key at https://console.groq.com/keys)
# NOTE: Groq deprecated ALL Llama chat models (llama-3.1-8b-instant,
# llama-3.3-70b-versatile) on Aug 16, 2026. Their current lineup no longer
# includes any Llama model. openai/gpt-oss-20b is Groq's own recommended
# migration target for 8b-instant (fast, high free-tier throughput) --
# it's not a Llama model, but there currently isn't a Llama alternative on
# Groq. If you want a genuine Llama model, use the Ollama provider instead
# (fully local, e.g. `ollama pull llama3.1:8b`), or set GROQ_MODEL to
# openai/gpt-oss-120b or qwen/qwen3.6-27b for more quality at Groq's cost
# of lower free-tier throughput.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Ollama settings (local)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Anthropic settings (optional, paid)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Database ---
DB_PATH = os.getenv("T2SQL_DB_PATH", os.path.join(os.path.dirname(__file__), "db", "sample.db"))

# --- Generation settings ---
MAX_TOKENS = 2000  # gpt-oss models spend tokens on hidden reasoning before
                    # the actual answer, so this needs more headroom than a
                    # plain non-reasoning model would (was 800)
TEMPERATURE = 0.0  # deterministic SQL generation

# --- Clarification engine ---
# If True, the pipeline will attempt to detect ambiguity and ask a
# clarifying question before finalizing SQL.
CLARIFICATION_ENABLED_DEFAULT = True

# --- Self-repair ---
# If a generated query fails to execute (bad column, invalid SQL, etc.),
# retry this many times by feeding the error back to the model and asking
# it to fix it. Set to 0 to disable.
SQL_REPAIR_ATTEMPTS = int(os.getenv("T2SQL_REPAIR_ATTEMPTS", "1"))