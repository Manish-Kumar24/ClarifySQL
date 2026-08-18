"""
Interactive command line interface.

    python cli.py                     # clarification ON (default)
    python cli.py --no-clarify        # clarification OFF, direct generation

Type your question in plain English. Type 'exit' to quit.
"""

import argparse

from src import pipeline, sql_executor, llm_client
import config


def ask_human(question: str) -> str:
    print(f"\n  Clarifying question: {question}")
    return input("  Your answer: ").strip()


def print_result(res, elapsed=None):
    print("\n--- Generated SQL ---")
    print(res.sql)
    if res.assumptions:
        print(f"\n(assumption made: {res.assumptions})")
    if res.clarification_triggered:
        print(f"\n(clarification used -> resolved question: \"{res.final_question}\")")

    try:
        cols, rows = sql_executor.execute(res.sql)
        print("\n--- Results ---")
        if cols:
            print(" | ".join(cols))
            print("-" * 40)
        for r in rows[:20]:
            print(r)
        if len(rows) > 20:
            print(f"... ({len(rows) - 20} more rows)")
        if not rows:
            print("(no rows returned)")
    except Exception as e:
        print(f"\n[!] Could not execute generated SQL: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-clarify", action="store_true", help="Disable the clarification engine")
    args = parser.parse_args()

    clarify_enabled = not args.no_clarify

    print("ClarifySQL")
    try:
        resolved = llm_client.resolve_provider()
        model_name = {"groq": config.GROQ_MODEL, "ollama": config.OLLAMA_MODEL,
                      "anthropic": config.ANTHROPIC_MODEL}.get(resolved, "?")
        print(f"Provider: {resolved} (model: {model_name})")
    except llm_client.LLMError as e:
        print(f"[!] {e}")
        return
    print(f"Clarification: {'ON' if clarify_enabled else 'OFF'}")
    print("Type your question, or 'exit' to quit.\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break

        try:
            if clarify_enabled:
                res = pipeline.run_with_clarification(question, ask_fn=ask_human)
            else:
                res = pipeline.run_without_clarification(question)
            print_result(res)
        except llm_client.LLMError as e:
            print(f"\n[!] LLM error: {e}")
        except Exception as e:
            print(f"\n[!] Unexpected error: {e}")

        print()


if __name__ == "__main__":
    main()
