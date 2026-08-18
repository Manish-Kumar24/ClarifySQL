"""
Usage:
    python -m eval.evaluate
    python -m eval.evaluate --limit 5      # quick smoke test
    python -m eval.evaluate --verbose
"""

import argparse, json, os, sys, time, traceback, config

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import pipeline, sql_executor, llm_client

TEST_FILE = os.path.join(os.path.dirname(__file__), "test_queries.json")
PACING_DELAY_SECONDS = 1.0 if os.getenv("T2SQL_PROVIDER", "auto") != "ollama" else 0.0

def load_test_queries():
    with open(TEST_FILE, "r") as f:
        return json.load(f)

def score_one(question_row, generated_sql, verbose=False):
    try:
        exp_cols, exp_rows = sql_executor.execute(question_row["expected_sql"])
    except Exception as e:
        return False, f"expected_sql itself failed to execute: {e}"

    try:
        gen_cols, gen_rows = sql_executor.execute(generated_sql)
    except Exception as e:
        return False, f"generated SQL failed to execute: {e}"

    match = sql_executor.results_match(exp_rows, gen_rows)
    detail = "" if match else f"expected {exp_rows[:3]}... got {gen_rows[:3]}..."
    return match, detail


def run_eval(limit=None, verbose=False):
    queries = load_test_queries()
    if limit:
        queries = queries[:limit]

    results = {"without_clarification": [], "with_clarification": []}

    for q in queries:
        # --- WITHOUT clarification ---
        try:
            res = pipeline.run_without_clarification(q["question"])
            correct, detail = score_one(q, res.sql, verbose)
        except Exception as e:
            correct, detail, res = False, f"pipeline error: {e}", None
            if verbose:
                traceback.print_exc()

        results["without_clarification"].append({
            "id": q["id"], "question": q["question"], "is_ambiguous": q["is_ambiguous"],
            "correct": correct, "detail": detail,
            "sql": res.sql if res else None,
        })

        # --- WITH clarification ---
        def simulated_user(_clar_question, _answer=q["clarification_answer"]):
            return _answer or "no specific preference, use your best judgement"

        try:
            res2 = pipeline.run_with_clarification(q["question"], ask_fn=simulated_user)
            correct2, detail2 = score_one(q, res2.sql, verbose)
        except Exception as e:
            correct2, detail2, res2 = False, f"pipeline error: {e}", None
            if verbose:
                traceback.print_exc()

        results["with_clarification"].append({
            "id": q["id"], "question": q["question"], "is_ambiguous": q["is_ambiguous"],
            "correct": correct2, "detail": detail2,
            "clarification_triggered": res2.clarification_triggered if res2 else None,
            "sql": res2.sql if res2 else None,
        })

        if verbose:
            print(f"[{q['id']}] {q['question']}")
            print(f"   without-clar: {'OK ' if correct else 'FAIL'}  {detail}")
            print(f"   with-clar   : {'OK ' if correct2 else 'FAIL'}"
                  f"  (triggered={res2.clarification_triggered if res2 else '?'})  {detail2}")
            print()

        if PACING_DELAY_SECONDS:
            time.sleep(PACING_DELAY_SECONDS)

    return results


def summarize(results):
    def pct(lst):
        return 100.0 * sum(1 for r in lst if r["correct"]) / len(lst) if lst else 0.0

    def pct_subset(lst, ambiguous: bool):
        subset = [r for r in lst if r["is_ambiguous"] == ambiguous]
        return pct(subset), len(subset)

    wo = results["without_clarification"]
    wi = results["with_clarification"]

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Overall accuracy WITHOUT clarification: {pct(wo):.1f}%  ({len(wo)} queries)")
    print(f"Overall accuracy WITH clarification:    {pct(wi):.1f}%  ({len(wi)} queries)")
    print()

    amb_wo, n_amb = pct_subset(wo, True)
    amb_wi, _ = pct_subset(wi, True)
    unamb_wo, n_unamb = pct_subset(wo, False)
    unamb_wi, _ = pct_subset(wi, False)

    print(f"On AMBIGUOUS queries (n={n_amb}):")
    print(f"   without clarification: {amb_wo:.1f}%")
    print(f"   with clarification:    {amb_wi:.1f}%")
    print(f"   -> delta: {amb_wi - amb_wo:+.1f} points")
    print()
    print(f"On UNAMBIGUOUS queries (n={n_unamb}):")
    print(f"   without clarification: {unamb_wo:.1f}%")
    print(f"   with clarification:    {unamb_wi:.1f}%")
    print(f"   -> delta: {unamb_wi - unamb_wo:+.1f} points")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--out", type=str, default="eval/results.json")
    args = parser.parse_args()

    results = run_eval(limit=args.limit, verbose=args.verbose)
    summarize(results)

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {args.out}")
