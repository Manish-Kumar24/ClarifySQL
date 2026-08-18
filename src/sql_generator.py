"""
Core NL -> SQL generation. Schema-grounded, single-turn, strict JSON output
so we reliably get just the SQL string back (no chatty prose to strip).

Also includes a self-repair loop: if the generated SQL fails to execute
(bad column reference, invalid aggregate nesting, etc.), the error message
is fed back to the model and it gets a bounded number of chances to fix it.
This matters in practice -- smaller/faster models produce syntactically
broken SQL more often, and "here's the exact error, fix it" is one of the
highest-leverage prompts you can give an LLM.
"""

from src import llm_client, schema_utils, sql_executor
import config

SYSTEM_PROMPT = """You are an expert SQL generator for SQLite databases.
Given a schema and a natural language question, produce a single, correct,
executable SQLite query that answers it.

Rules:
- Use ONLY tables/columns that exist in the given schema.
- Prefer explicit JOINs with ON clauses over implicit joins.
- Do NOT nest aggregate functions (e.g. MAX(COUNT(x)) is invalid SQLite).
  If you need "the group with the highest count", use
  `GROUP BY ... ORDER BY COUNT(x) DESC LIMIT 1` or a subquery that first
  computes counts per group, then filters/orders on that subquery.
- If the question (or a clarification note) says "per X", "for each X",
  "individually", "listed separately", or "not summed/combined", return
  one row per item -- do NOT wrap the value in SUM()/AVG()/COUNT() unless
  the question explicitly asks for a single combined total.
- For text equality/filter comparisons (e.g. WHERE department = 'Engineering'),
  use case-insensitive matching: `WHERE LOWER(column) = LOWER('value')` or
  `COLLATE NOCASE`. SQLite string comparison is case-sensitive by default,
  and you cannot know the exact casing convention used in the actual data
  (e.g. "Engineering" vs "engineering" vs "ENGINEERING") from the question
  alone -- guessing the wrong case silently returns zero rows instead of
  an error, which is worse than a slightly looser match. This applies to
  LIKE patterns too.
- Return STRICT JSON only, no markdown fences, in this exact shape:
{
  "sql": "SELECT ...",
  "assumptions": "any assumption you made to resolve ambiguity, or empty string"
}
"""

USER_PROMPT_TEMPLATE = """SCHEMA:
{schema}

QUESTION:
"{question}"
{extra_context}
Return the JSON now."""

REPAIR_SYSTEM_PROMPT = SYSTEM_PROMPT + """

You previously generated SQL that failed to execute. You will be given the
failed SQL and the exact database error. Fix it and return the same JSON
shape as before."""

REPAIR_USER_PROMPT_TEMPLATE = """SCHEMA:
{schema}

QUESTION:
"{question}"

PREVIOUSLY GENERATED SQL (failed):
{failed_sql}

DATABASE ERROR:
{error}

Return corrected JSON now."""


def _generate_once(nl_question: str, schema_text: str, extra_context: str = "") -> dict:
    user_prompt = USER_PROMPT_TEMPLATE.format(
        schema=schema_text, question=nl_question, extra_context=extra_context
    )
    result = llm_client.chat_json(SYSTEM_PROMPT, user_prompt)
    return {
        "sql": result.get("sql", "").strip().rstrip(";"),
        "assumptions": result.get("assumptions", ""),
    }


def _repair_once(nl_question: str, schema_text: str, failed_sql: str, error: str) -> dict:
    user_prompt = REPAIR_USER_PROMPT_TEMPLATE.format(
        schema=schema_text, question=nl_question, failed_sql=failed_sql, error=error
    )
    result = llm_client.chat_json(REPAIR_SYSTEM_PROMPT, user_prompt)
    return {
        "sql": result.get("sql", "").strip().rstrip(";"),
        "assumptions": result.get("assumptions", ""),
    }


def generate_sql(
    nl_question: str,
    repair_attempts: int = None,
    extra_context: str = "",
    db_path: str = None,
) -> dict:
    """
    Generates SQL, then validates it actually executes. On failure, retries
    up to `repair_attempts` times (default from config.SQL_REPAIR_ATTEMPTS),
    feeding the real database error back to the model each time.

    `extra_context`, if given, is injected verbatim into the prompt below
    the question -- used by the clarification flow to pass the user's raw
    clarifying answer directly, so a lossy paraphrase step upstream can't
    silently drop a constraint (e.g. "per order, not summed").

    `db_path`, if given, targets a specific database instead of the global
    default (config.DB_PATH) -- this is how the web UI runs generated SQL
    against a user-uploaded dataset instead of the bundled sample data.
    """
    if repair_attempts is None:
        repair_attempts = config.SQL_REPAIR_ATTEMPTS

    schema_text = schema_utils.get_schema_text(db_path)
    result = _generate_once(nl_question, schema_text, extra_context=extra_context)

    attempts_used = 0
    last_error = None
    for _ in range(repair_attempts):
        try:
            sql_executor.execute(result["sql"], db_path)
            break  # it runs fine, no repair needed
        except Exception as e:
            last_error = str(e)
            attempts_used += 1
            result = _repair_once(nl_question, schema_text, result["sql"], last_error)

    result["repair_attempts_used"] = attempts_used
    result["last_error_before_repair"] = last_error
    return result