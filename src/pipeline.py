"""
Orchestrates the end-to-end flow:

  WITHOUT clarification:  question -> SQL directly
  WITH clarification:     question -> ambiguity check -> (maybe) ask -> SQL

`ask_fn` is injected so the same pipeline works for:
  - interactive CLI (asks a human via input())
  - offline evaluation (looks up a pre-recorded answer from test data)
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from src import clarification_engine, sql_generator


@dataclass
class PipelineResult:
    final_question: str
    sql: str
    assumptions: str
    clarification_triggered: bool
    clarification_question: Optional[str] = None
    clarification_answer: Optional[str] = None
    ambiguity_reason: str = ""


def run_without_clarification(nl_question: str) -> PipelineResult:
    gen = sql_generator.generate_sql(nl_question)
    return PipelineResult(
        final_question=nl_question,
        sql=gen["sql"],
        assumptions=gen["assumptions"],
        clarification_triggered=False,
    )


def run_with_clarification(
    nl_question: str,
    ask_fn: Callable[[str], str],
) -> PipelineResult:
    check = clarification_engine.check_ambiguity(nl_question)

    if not check.ambiguous:
        gen = sql_generator.generate_sql(nl_question)
        return PipelineResult(
            final_question=nl_question,
            sql=gen["sql"],
            assumptions=gen["assumptions"],
            clarification_triggered=False,
            ambiguity_reason=check.reason,
        )

    user_answer = ask_fn(check.question)
    resolved_question = clarification_engine.resolve_with_answer(
        nl_question, check.question, user_answer
    )
    # Pass the raw Q&A alongside the paraphrase -- the paraphrase step is
    # itself an LLM call and can compress away a specific constraint (e.g.
    # "per order, not summed"). Giving the generator both the clean
    # rewritten question AND the user's literal answer means a lossy
    # paraphrase doesn't silently erase the constraint.
    extra_context = (
        f"\nADDITIONAL CONTEXT -- the user was asked a clarifying question "
        f"and answered it directly (treat this as authoritative, it may "
        f"contain details not fully captured in the QUESTION above):\n"
        f'Clarifying question: "{check.question}"\n'
        f'User\'s answer: "{user_answer}"\n'
    )
    gen = sql_generator.generate_sql(resolved_question, extra_context=extra_context)
    return PipelineResult(
        final_question=resolved_question,
        sql=gen["sql"],
        assumptions=gen["assumptions"],
        clarification_triggered=True,
        clarification_question=check.question,
        clarification_answer=user_answer,
        ambiguity_reason=check.reason,
    )
