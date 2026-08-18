"""
Clarification Engine
---------------------
Given a natural-language question and the DB schema, decides whether the
question is ambiguous enough that generating SQL directly is risky, and if
so, produces a single, targeted clarifying question.

Ambiguity is detected via the LLM itself (schema-grounded), rather than
hand-written regex rules, so it generalizes to new schemas. We prompt for
strict JSON so the pipeline can parse it reliably.

Ambiguity classes we specifically prompt the model to check for:
  1. Column/attribute exists in multiple tables with different meaning
     (e.g. "amount" -> orders.amount vs payments.amount)
  2. Vague quantifiers without a concrete number ("top", "recent", "a few")
  3. Vague/relative time references with no resolvable anchor
  4. Ambiguous entity reference (a name/term that could map to >1 table
     or column)
  5. Missing filter that materially changes the result (e.g. "cancelled
     orders" -- cancelled per orders.status or per payments.status?)
"""

from dataclasses import dataclass

import config
from src import llm_client, schema_utils

SYSTEM_PROMPT = """You are an ambiguity checker for a text-to-SQL system.
Given a database schema and a user's natural language question, decide if
the question is genuinely ambiguous with respect to THIS schema -- i.e.
there are two or more reasonably different SQL queries that could satisfy
the wording, and picking the wrong one would give a misleading answer.

Do NOT flag a question as ambiguous just because it's simple. Only flag it
when the schema itself creates a real fork in interpretation (e.g. a column
name exists in more than one table with different meaning, a vague
quantifier with no number, an unresolvable relative date, etc).

Respond with STRICT JSON only, no markdown fences, no commentary, in this
exact shape:
{
  "ambiguous": true or false,
  "reason": "short internal explanation of why (or why not)",
  "clarification_question": "a single, concrete question to ask the user to resolve the ambiguity, or empty string if not ambiguous"
}

WORKED EXAMPLES (follow this exact pattern of judgment):

Question: "What's the total amount for order 10?"
-> ambiguous: true. "amount" exists in both orders (order total) and
payments (amount actually paid), and these can differ (partial refunds).
clarification_question: "Do you mean the order total from the orders
table, or the amount actually paid according to the payments table?"

Question: "Show me the top products."
-> ambiguous: true. "top" has no number and no metric (by revenue? by
units sold? by rating?). clarification_question: "How many products, and
ranked by what -- units sold, revenue, or rating?"

Question: "List all customers from Delhi."
-> ambiguous: false. "city" is unambiguous, exists only in customers, and
"Delhi" is a concrete filter value. No fork in interpretation.

Question: "How many orders are in 'shipped' status?"
-> ambiguous: false. Even though "status" also exists in payments, the
question explicitly says "orders" AND the concrete value 'shipped' only
makes sense as an order status, not a payment status (payments use
success/failed/refunded). Context fully resolves it.

Question: "Which products have good reviews?"
-> ambiguous: true. "good" is a vague qualitative term with no defined
threshold -- a rating of 3+? 4+? 4.5+? Different thresholds return
genuinely different product sets. clarification_question: "What rating
counts as 'good' -- 3 and above, 4 and above, or something else?"
"""

USER_PROMPT_TEMPLATE = """SCHEMA:
{schema}

KNOWN AMBIGUOUS COLUMN NAMES (appear in multiple tables): {ambiguous_cols}

USER QUESTION:
"{question}"

Return the JSON now."""


@dataclass
class ClarificationResult:
    ambiguous: bool
    reason: str
    question: str


def check_ambiguity(nl_question: str, db_path: str = None) -> ClarificationResult:
    schema_text = schema_utils.get_schema_text(db_path)
    ambiguous_cols = list(schema_utils.find_ambiguous_columns(db_path).keys())

    user_prompt = USER_PROMPT_TEMPLATE.format(
        schema=schema_text,
        ambiguous_cols=ambiguous_cols,
        question=nl_question,
    )
    result = llm_client.chat_json(SYSTEM_PROMPT, user_prompt)

    return ClarificationResult(
        ambiguous=bool(result.get("ambiguous", False)),
        reason=result.get("reason", ""),
        question=result.get("clarification_question", ""),
    )


def resolve_with_answer(nl_question: str, clarification_question: str, user_answer: str) -> str:
    """
    Folds the clarification Q&A back into a single, disambiguated
    natural-language question that the SQL generator can consume directly.
    """
    system_prompt = (
        "You rewrite an ambiguous question into a single, fully specified "
        "question by incorporating the user's clarifying answer. Output ONLY "
        "the rewritten question, nothing else."
    )
    user_prompt = (
        f"Original question: {nl_question}\n"
        f"Clarifying question asked: {clarification_question}\n"
        f"User's answer: {user_answer}\n\n"
        "Rewritten, fully specified question:"
    )
    return llm_client.chat(system_prompt, user_prompt).strip()
