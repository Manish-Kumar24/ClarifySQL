"""
Turns uploaded files into a queryable SQLite database.

Supported inputs:
  - .csv                 -> one table, named after the file
  - .xlsx / .xls          -> one table per sheet
  - .db / .sqlite / .sqlite3 -> used directly (must be the only file uploaded)

Sessions are held in memory only (SESSIONS: session_id -> temp file path).
This is fine for a local portfolio demo; it means uploaded datasets don't
survive a backend restart, which /api/ask and /api/resolve surface as a
clear 404 rather than a silent wrong-answer.
"""

import io
import os
import re
import sqlite3
import tempfile
import uuid

import pandas as pd

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25MB per file -- generous for a demo
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
CSV_EXTENSIONS = {".csv"}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}

# session_id -> path to that session's temp SQLite file
SESSIONS: dict[str, str] = {}


def _sanitize_table_name(name: str) -> str:
    """SQL identifiers can't contain most punctuation or start with a digit."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    if not name:
        name = "table1"
    if name[0].isdigit():
        name = f"t_{name}"
    return name.lower()


def _dedupe_name(name: str, used: set) -> str:
    if name not in used:
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    return f"{name}_{i}"


def _sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Raw CSV/Excel headers are often messy for SQL: spaces ("Annual Salary"),
    special characters ("Salary ($)"), inconsistent casing, or duplicates.
    Writing those straight into SQLite makes them nearly impossible for the
    LLM to reference reliably (it would have needed to guess exact quoting).
    Sanitize to clean snake_case identifiers, preserving readability.
    """
    used = set()
    new_columns = []
    for col in df.columns.astype(str):
        clean = _sanitize_table_name(col)  # same rules apply to column names
        clean = _dedupe_name(clean, used)
        used.add(clean)
        new_columns.append(clean)
    df = df.copy()
    df.columns = new_columns
    return df


async def load_files_to_sqlite(files) -> tuple[str, list[dict]]:
    """
    Returns (session_id, tables) where tables is
    [{"name": str, "columns": [str], "row_count": int}, ...]
    """
    filenames = [f.filename or "" for f in files]
    extensions = [os.path.splitext(fn)[1].lower() for fn in filenames]

    # Special case: a single SQLite file is used as-is, no conversion.
    if len(files) == 1 and extensions[0] in SQLITE_EXTENSIONS:
        content = await files[0].read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)}MB)")
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        with os.fdopen(fd, "wb") as f:
            f.write(content)

        # Validate it's actually a readable SQLite DB with at least one table.
        try:
            conn = sqlite3.connect(tmp_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            table_names = [r[0] for r in cur.fetchall()]
            if not table_names:
                raise ValueError("Uploaded SQLite file has no tables")
            tables = []
            for t in table_names:
                cur.execute(f"PRAGMA table_info({t})")
                cols = [c[1] for c in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                count = cur.fetchone()[0]
                tables.append({"name": t, "columns": cols, "row_count": count})
            conn.close()
        except sqlite3.DatabaseError:
            os.remove(tmp_path)
            raise ValueError("Uploaded file is not a valid SQLite database")

        session_id = uuid.uuid4().hex
        SESSIONS[session_id] = tmp_path
        return session_id, tables

    # Otherwise: treat every file as tabular data (CSV or Excel), load each
    # into its own table (or one table per sheet, for Excel) in a fresh DB.
    for ext in extensions:
        if ext not in CSV_EXTENSIONS | EXCEL_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{ext}'. Upload .csv, .xlsx, .xls, "
                f"or a single .db/.sqlite file."
            )

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(tmp_path)

    tables = []
    used_names = set()

    for file, ext in zip(files, extensions):
        content = await file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            conn.close()
            os.remove(tmp_path)
            raise ValueError(f"File '{file.filename}' too large (max {MAX_FILE_SIZE_BYTES // (1024*1024)}MB)")

        base_name = _sanitize_table_name(os.path.splitext(file.filename or "table")[0])

        if ext in CSV_EXTENSIONS:
            df = pd.read_csv(io.BytesIO(content))
            df = _sanitize_columns(df)
            table_name = _dedupe_name(base_name, used_names)
            used_names.add(table_name)
            df.to_sql(table_name, conn, index=False, if_exists="replace")
            tables.append({
                "name": table_name,
                "columns": list(df.columns.astype(str)),
                "row_count": len(df),
            })
        else:  # Excel -- one table per sheet
            sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
            for sheet_name, df in sheets.items():
                df = _sanitize_columns(df)
                if len(sheets) == 1:
                    table_name = base_name
                else:
                    table_name = f"{base_name}_{_sanitize_table_name(sheet_name)}"
                table_name = _dedupe_name(table_name, used_names)
                used_names.add(table_name)
                df.to_sql(table_name, conn, index=False, if_exists="replace")
                tables.append({
                    "name": table_name,
                    "columns": list(df.columns.astype(str)),
                    "row_count": len(df),
                })

    conn.close()

    if not tables:
        os.remove(tmp_path)
        raise ValueError("No tables could be extracted from the uploaded file(s)")

    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = tmp_path
    return session_id, tables


def cleanup_session(session_id: str) -> None:
    path = SESSIONS.pop(session_id, None)
    if path and os.path.exists(path):
        os.remove(path)