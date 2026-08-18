import sqlite3, config

BLOCKED_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "ATTACH", "PRAGMA")


class UnsafeSQLError(RuntimeError):
    pass

def is_read_only(sql: str) -> bool:
    upper = sql.strip().upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return False
    return not any(f" {kw} " in f" {upper} " or upper.startswith(kw) for kw in BLOCKED_KEYWORDS)

def execute(sql: str, db_path: str = None):
    if not is_read_only(sql):
        raise UnsafeSQLError(f"Refusing to execute non-read-only SQL: {sql}")

    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        return columns, rows
    finally:
        conn.close()

def results_match(rows_a, rows_b) -> bool:
    if len(rows_a) != len(rows_b):
        return False

    def row_to_set(row):
        return frozenset(str(v) for v in row)

    sets_a = [row_to_set(r) for r in rows_a]
    sets_b = [row_to_set(r) for r in rows_b]

    used = set()
    for a in sets_a:
        found = False
        for i, b in enumerate(sets_b):
            if i in used:
                continue
            if a.issubset(b):
                used.add(i)
                found = True
                break
        if not found:
            return False
    return True
