import sqlite3
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: sqlite_query.py <db> <sql>")
        return 2
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.execute(sys.argv[2])
    rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        print(row)
    if not rows:
        print(f"(no rows; columns={[d[0] for d in cur.description or []]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
