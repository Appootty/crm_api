"""Nightly loader: newest dump zip -> new SQLite database -> checks -> publish as the current version.
Run as a Cloud Run Job (python loader.py). Exits non-zero on any problem so the failure alert fires.
Env: DUMPS_BUCKET|DUMPS_DIR, VERSIONS_BUCKET|VERSIONS_DIR, ROW_TOLERANCE (default 0.2),
     KEEP_VERSIONS (default 30), ALLOW_NO_NEW (set to 1 to accept a night with no new dump),
     MAX_ORDER_AGE_DAYS (default 7)."""
import csv, io, json, os, sqlite3, sys, tempfile, zipfile
from datetime import datetime, timedelta
from pathlib import Path

from crm_schema import SCHEMA, VIEWS
from store import open_store

REQUIRED = ["customers", "items", "sales_orders", "sales_order_lines", "payments"]
TOL = float(os.environ.get("ROW_TOLERANCE", "0.2"))
KEEP = int(os.environ.get("KEEP_VERSIONS", "30"))
MAX_AGE = int(os.environ.get("MAX_ORDER_AGE_DAYS", "7"))


def log(m):
    print(f"[loader] {m}", flush=True)


def fail(m):
    print(f"[loader] FAILED: {m}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---- adapter: dump -> {table: (columns, rows)}.  Replace for the real database format. ----
def read_synthetic_zip(zpath):
    data = {}
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            table = Path(name).stem
            reader = csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8", newline=""))
            header = next(reader)
            data[table] = (header, list(reader))
    return data


def build_db(data, path):
    con = sqlite3.connect(path)
    for table, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE {table} ({cols})")
        if table in data:
            header, rows = data[table]
            known = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            use = [c for c in header if c in known]
            idx = [header.index(c) for c in use]
            q = f"INSERT INTO {table} ({','.join(use)}) VALUES ({','.join('?' * len(use))})"
            con.executemany(q, ([(r[i] if r[i] != "" else None) for i in idx] for r in rows))
    con.executescript(VIEWS)
    con.commit()
    return con


def validate(con, prev_counts):
    missing = [t for t in REQUIRED if con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0]
    if missing:
        fail(f"required tables empty or missing: {missing}")
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        fail("integrity check failed")
    orphans = con.execute("SELECT COUNT(*) FROM sales_order_lines WHERE order_id NOT IN (SELECT id FROM sales_orders)").fetchone()[0]
    if orphans:
        fail(f"{orphans} order lines without an order")
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in SCHEMA}
    for t in ("sales_orders", "customers", "sales_order_lines"):
        old = prev_counts.get(t)
        if old and abs(counts[t] - old) > TOL * old:
            fail(f"{t} rows {counts[t]} vs previous {old}: change above {TOL:.0%}")
    last = con.execute("SELECT MAX(order_date) FROM sales_orders").fetchone()[0]
    if last and not os.environ.get("SKIP_STALE_CHECK"):
        try:
            if datetime.fromisoformat(last[:10]) < datetime.now() - timedelta(days=MAX_AGE):
                log(f"warning: newest order is {last} (older than {MAX_AGE} days)")
        except ValueError:
            pass
    return counts


def main():
    dumps, versions = open_store("DUMPS"), open_store("VERSIONS")
    zips = [(n, t) for n, t in dumps.list() if n.lower().endswith(".zip")]
    if not zips:
        fail("no dump files found")
    newest = zips[-1][0]
    meta = json.loads(versions.read_text("latest.json") or "{}")
    if meta.get("source") == newest and not os.environ.get("ALLOW_NO_NEW"):
        fail(f"no new dump since last run (still {newest})")
    log(f"using dump {newest}")
    tmp = Path(tempfile.mkdtemp())
    local_zip = tmp / "dump.zip"
    dumps.download(newest, local_zip)
    data = read_synthetic_zip(local_zip)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    db_path = tmp / f"crm-{stamp}.db"
    con = build_db(data, db_path)
    counts = validate(con, meta.get("counts", {}))
    con.close()
    name = f"versions/crm-{stamp}.db"
    versions.upload(db_path, name)
    versions.write_text("latest.json", json.dumps({"file": name, "source": newest, "built": stamp, "counts": counts}))
    log(f"published {name}: {counts['sales_orders']} orders, {counts['customers']} customers")
    old = [n for n, _ in versions.list("versions/")]
    for n in old[:-KEEP]:
        versions.delete(n)


if __name__ == "__main__":
    main()
