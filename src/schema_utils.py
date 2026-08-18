import sqlite3, config

def get_schema_text(db_path: str = None) -> str:
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]

    lines = []
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = cur.fetchall()  # cid, name, type, notnull, dflt_value, pk
        col_strs = [f"{c[1]} {c[2]}{' PK' if c[5] else ''}" for c in cols]
        lines.append(f"TABLE {t} ({', '.join(col_strs)})")

        cur.execute(f"PRAGMA foreign_key_list({t})")
        for fk in cur.fetchall():
            # id, seq, table, from, to, on_update, on_delete, match
            lines.append(f"  FK: {t}.{fk[3]} -> {fk[2]}.{fk[4]}")

    conn.close()
    return "\n".join(lines)


def find_ambiguous_columns(db_path: str = None) -> dict:
    """
    Returns {column_name: [table1, table2, ...]} for columns that appear
    in more than one table -- useful context for the clarification engine.
    """
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]

    col_to_tables = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        for c in cur.fetchall():
            col_to_tables.setdefault(c[1], []).append(t)

    conn.close()
    return {col: tbls for col, tbls in col_to_tables.items() if len(tbls) > 1}


if __name__ == "__main__":
    print(get_schema_text())
    print("\nAmbiguous columns across tables:")
    for col, tbls in find_ambiguous_columns().items():
        print(f"  {col}: {tbls}")