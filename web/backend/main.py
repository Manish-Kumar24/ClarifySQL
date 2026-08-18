"""
Minimal FastAPI backend for the web UI. Wraps the existing pipeline --
no business logic lives here, this is purely an HTTP shell around
src/clarification_engine.py, src/sql_generator.py, src/sql_executor.py.

Run:
    cd web/backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
"""

import os
import sys

# Add project root to sys.path so `import config` and `from src import ...`
# work the same way they do everywhere else in this project.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src import clarification_engine, sql_generator, sql_executor, llm_client, schema_utils
import config
from dataset_loader import load_files_to_sqlite, SESSIONS, cleanup_session

app = FastAPI(title="ClarifySQL")

# Local dev only -- Vite's default port. Wide open on purpose since this
# is a portfolio demo, not a service handling real user data.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    use_clarification: bool = True
    session_id: Optional[str] = None  # None = use the bundled sample dataset


class ResolveRequest(BaseModel):
    question: str
    clarification_question: str
    answer: str
    session_id: Optional[str] = None


def _resolve_db_path(session_id: Optional[str]) -> Optional[str]:
    """None means 'use config.DB_PATH' (the bundled sample dataset)."""
    if session_id is None:
        return None
    if session_id not in SESSIONS:
        raise HTTPException(
            404,
            "Unknown session_id -- your uploaded dataset may have expired "
            "(the backend restarted, since uploads are held in memory only). "
            "Please re-upload your file.",
        )
    return SESSIONS[session_id]


def _run_sql_and_format(sql: str, db_path: Optional[str]):
    columns, rows = sql_executor.execute(sql, db_path)
    return {"columns": columns, "rows": rows}


@app.get("/api/health")
def health():
    try:
        provider = llm_client.resolve_provider()
    except llm_client.LLMError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "provider": provider}


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...)):
    """
    Accepts one or more files (.csv, .xlsx/.xls, or .db/.sqlite/.sqlite3),
    converts them into a fresh, isolated SQLite database, and returns a
    session_id. Pass that session_id in /api/ask and /api/resolve to run
    questions against this dataset instead of the bundled sample data.

    - Multiple CSV/Excel files -> one table per file (or per sheet, for
      Excel workbooks with multiple sheets), so questions can join across
      them if the schema supports it.
    - A single .db/.sqlite file -> used directly, no conversion needed.
    """
    if not files:
        raise HTTPException(400, "No files uploaded")

    try:
        session_id, tables = await load_files_to_sqlite(files)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to process uploaded file(s): {e}")

    db_path = SESSIONS[session_id]
    schema_preview = schema_utils.get_schema_text(db_path)

    return {
        "session_id": session_id,
        "tables": tables,
        "schema_preview": schema_preview,
    }


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    cleanup_session(session_id)
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskRequest):
    """
    First step. If use_clarification=True and the question is ambiguous,
    returns a clarifying question instead of SQL -- the frontend then
    calls /api/resolve with the user's answer.
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "question is empty")

    db_path = _resolve_db_path(req.session_id)

    try:
        if req.use_clarification:
            check = clarification_engine.check_ambiguity(question, db_path=db_path)
            if check.ambiguous:
                return {
                    "status": "clarification_needed",
                    "clarification_question": check.question,
                    "ambiguity_reason": check.reason,
                }

        gen = sql_generator.generate_sql(question, db_path=db_path)
        result = _run_sql_and_format(gen["sql"], db_path)
        return {
            "status": "done",
            "sql": gen["sql"],
            "assumptions": gen["assumptions"],
            "clarification_used": False,
            **result,
        }
    except llm_client.LLMError as e:
        raise HTTPException(502, f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(500, f"Failed to generate/execute SQL: {e}")


@app.post("/api/resolve")
def resolve(req: ResolveRequest):
    """Second step, only called after /api/ask returned clarification_needed."""
    db_path = _resolve_db_path(req.session_id)

    try:
        resolved_question = clarification_engine.resolve_with_answer(
            req.question, req.clarification_question, req.answer
        )
        # Pass the raw Q&A too, not just the paraphrase -- see pipeline.py
        # for why (the paraphrase step can drop a specific constraint).
        extra_context = (
            f"\nADDITIONAL CONTEXT -- the user was asked a clarifying "
            f"question and answered it directly (treat this as "
            f"authoritative):\n"
            f'Clarifying question: "{req.clarification_question}"\n'
            f'User\'s answer: "{req.answer}"\n'
        )
        gen = sql_generator.generate_sql(
            resolved_question, extra_context=extra_context, db_path=db_path
        )
        result = _run_sql_and_format(gen["sql"], db_path)
        return {
            "status": "done",
            "sql": gen["sql"],
            "assumptions": gen["assumptions"],
            "resolved_question": resolved_question,
            "clarification_used": True,
            **result,
        }
    except llm_client.LLMError as e:
        raise HTTPException(502, f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(500, f"Failed to generate/execute SQL: {e}")
