"""
Read-only lookup endpoints for the voice assistant (n8n calls these as tools).

- Built on the same read-only database connection as crm_api.py (nothing here can write).
- Fixed, parameterised queries only. Small result sets (a few rows) so answers can be spoken.
- Every answer says which data it comes from (as_of / data_version) so the assistant can say how fresh it is.
- salesman_id, when given, limits the answer to that salesman's customers and orders.
  In n8n, fill salesman_id from the signed-in user's data, never from what the model decides.
"""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from crm_api import query, latest_date
from dbsource import version_info

router = APIRouter(prefix="/tools", tags=["voice tools"])
LIVE = "o.status NOT IN ('Cancelled','Rejected')"
STATUSES = {s.lower(): s for s in ("New", "Pending", "Processed", "Delivered", "Cancelled", "Rejected")}


def _clean(text: str, n: int = 30) -> str:
    return re.sub(r"[%_\\]", "", (text or "").strip().lower())[:n]


def _tokens(text: str, max_tokens: int = 6):
    toks = [t for t in (_clean(x) for x in re.split(r"\s+", (text or "").strip())) if t]
    if not toks:
        raise HTTPException(400, "Give some text to search for")
    return toks[:max_tokens]


def _like_all(toks, cols, prefix):
    """Every word must appear in at least one of the columns."""
    conds, params = [], {}
    for i, t in enumerate(toks):
        k = f"{prefix}{i}"
        conds.append("(" + " OR ".join(f"LOWER({c}) LIKE :{k}" for c in cols) + ")")
        params[k] = f"%{t}%"
    return " AND ".join(conds), params


def _wrap(rows, **extra):
    return {"as_of": latest_date(), "data_version": version_info().get("version"), **extra,
            "count": len(rows), "results": rows}


@router.get("/salesmen")
def salesmen(name: Optional[str] = None):
    """Find a salesman by name (id, phone, warehouse)."""
    sql = ("SELECT u.id AS salesman_id, u.name, u.phone, w.name AS warehouse FROM users u "
           "LEFT JOIN warehouses w ON w.id = u.warehouse_id WHERE u.role = 'salesman' AND u.active = 1")
    p = {}
    if name:
        where, p = _like_all(_tokens(name), ["u.name"], "n")
        sql += " AND " + where
    return _wrap(query(sql + " ORDER BY u.name LIMIT 10", p))


@router.get("/stock")
def stock(item: str, warehouse: Optional[str] = None):
    """Stock of an item by warehouse, with price. 'item' is free text such as 'jasmine rice 20kg'."""
    where, p = _like_all(_tokens(item), ["i.name", "i.brand", "i.category", "i.sku"], "t")
    items = query("SELECT i.id AS item_id, i.sku, i.name, i.brand, i.unit, i.sale_price, i.reorder_level "
                  f"FROM items i WHERE i.active = 1 AND {where} ORDER BY i.name LIMIT 5", p)
    if not items:
        return _wrap([], message="No matching item in the item master")
    ids = [r["item_id"] for r in items]
    sql = ("SELECT s.item_id, w.name AS warehouse, s.quantity FROM stock s JOIN warehouses w ON w.id = s.warehouse_id "
           f"WHERE s.item_id IN ({','.join('?' for _ in ids)})")
    params = list(ids)
    if warehouse:
        w = _clean(warehouse)
        sql += " AND (LOWER(w.name) LIKE ? OR LOWER(w.city) LIKE ?)"
        params += [f"%{w}%", f"%{w}%"]
    by = {}
    for s in query(sql + " ORDER BY w.name", tuple(params)):
        by.setdefault(s["item_id"], []).append({"warehouse": s["warehouse"], "quantity": s["quantity"]})
    for r in items:
        st = by.get(r["item_id"], [])
        r["stock"] = st
        r["total_quantity"] = sum(x["quantity"] for x in st)
        r["at_or_below_reorder_level"] = any(x["quantity"] <= r["reorder_level"] for x in st)
    return _wrap(items, note="More than one match means the caller should be asked which item they mean" if len(items) > 1 else None)


@router.get("/customer")
def customer(name: str, salesman_id: Optional[int] = None):
    """Find a customer by name, code or city and give balance, credit limit and payment position."""
    where, p = _like_all(_tokens(name), ["c.name", "c.code", "c.city", "c.contact_person"], "t")
    p["e"] = latest_date()
    scope = ""
    if salesman_id is not None:
        scope, p["sid"] = " AND c.salesman_id = :sid", salesman_id
    rows = query(f"""
        SELECT c.id AS customer_id, c.code, c.name, c.city, c.status, c.class_type, c.contact_person, c.phone,
               c.max_credit_amount, c.max_credit_period_days, c.salesman_id, u.name AS salesman,
               b.outstanding, c.wallet_balance,
               (SELECT COUNT(*) FROM sales_orders o WHERE o.customer_id = c.id AND o.status = 'Delivered'
                  AND o.total - o.paid_amount > 0.01) AS unpaid_orders,
               (SELECT MAX(CAST(julianday(:e) - julianday(o.due_date) AS INTEGER)) FROM sales_orders o
                  WHERE o.customer_id = c.id AND o.status = 'Delivered' AND o.total - o.paid_amount > 0.01) AS max_days_overdue,
               (SELECT MAX(o.order_date) FROM sales_orders o WHERE o.customer_id = c.id AND {LIVE}) AS last_order_date
        FROM customers c LEFT JOIN v_customer_balance b ON b.customer_id = c.id LEFT JOIN users u ON u.id = c.salesman_id
        WHERE {where}{scope} ORDER BY c.name LIMIT 5""", p)
    return _wrap(rows, note="More than one match means ask which customer" if len(rows) > 1 else None)


@router.get("/orders")
def orders(customer_id: Optional[int] = None, salesman_id: Optional[int] = None, status: Optional[str] = None,
           days: int = Query(30, ge=1, le=365), limit: int = Query(10, ge=1, le=25)):
    """Recent orders, newest first. Filter by customer, salesman and/or status."""
    conds = ["o.order_date > date(:e, '-' || :d || ' day')", "o.order_date <= :e"]
    p = {"e": latest_date(), "d": days, "n": limit}
    if customer_id is not None:
        conds.append("o.customer_id = :c")
        p["c"] = customer_id
    if salesman_id is not None:
        conds.append("o.salesman_id = :s")
        p["s"] = salesman_id
    if status:
        st = STATUSES.get(status.strip().lower())
        if not st:
            raise HTTPException(400, "status must be one of: " + ", ".join(STATUSES.values()))
        conds.append("o.status = :st")
        p["st"] = st
    rows = query(f"""
        SELECT o.order_no, o.invoice_no, c.name AS customer, u.name AS salesman, o.order_date, o.status,
               o.payment_status, o.source, o.total, o.paid_amount,
               CASE WHEN o.status = 'Delivered' THEN ROUND(o.total - o.paid_amount, 2) END AS outstanding
        FROM sales_orders o JOIN customers c ON c.id = o.customer_id LEFT JOIN users u ON u.id = o.salesman_id
        WHERE {' AND '.join(conds)} ORDER BY o.order_date DESC, o.id DESC LIMIT :n""", p)
    return _wrap(rows)


@router.get("/order-detail")
def order_detail(number: str, salesman_id: Optional[int] = None):
    """One order with its lines. 'number' is the order or invoice number (the end of it is enough)."""
    num = number.strip().upper()[:40]
    if len(num) < 3:
        raise HTTPException(400, "Order number is too short")
    rows = query("""
        SELECT o.id AS order_id, o.order_no, o.invoice_no, c.name AS customer, u.name AS salesman, o.salesman_id,
               o.order_date, o.delivered_date, o.due_date, o.status, o.payment_status, o.source,
               o.subtotal, o.discount, o.tax_amount, o.total, o.paid_amount, o.notes
        FROM sales_orders o JOIN customers c ON c.id = o.customer_id LEFT JOIN users u ON u.id = o.salesman_id
        WHERE UPPER(o.order_no) = :n OR UPPER(o.invoice_no) = :n
           OR UPPER(o.order_no) LIKE '%' || :n OR UPPER(o.invoice_no) LIKE '%' || :n
        ORDER BY (UPPER(o.order_no) = :n OR UPPER(o.invoice_no) = :n) DESC, o.id DESC LIMIT 1""", {"n": num})
    if not rows or (salesman_id is not None and rows[0]["salesman_id"] != salesman_id):
        return _wrap([], message="Order not found")
    o = rows[0]
    o.pop("salesman_id")
    o["lines"] = query("""SELECT i.name AS item, i.unit, l.quantity, l.unit_price, l.discount_pct, l.line_total
                          FROM sales_order_lines l JOIN items i ON i.id = l.item_id WHERE l.order_id = ?
                          ORDER BY l.id LIMIT 30""", (o["order_id"],))
    return _wrap([o])


@router.get("/overdue")
def overdue(customer_id: Optional[int] = None, salesman_id: Optional[int] = None,
            min_days: int = Query(0, ge=0, le=730), limit: int = Query(10, ge=1, le=25)):
    """Unpaid delivered orders past their due date, biggest first, with totals for the whole selection."""
    conds = ["o.status = 'Delivered'", "o.total - o.paid_amount > 0.01", "julianday(:e) - julianday(o.due_date) >= :m"]
    p = {"e": latest_date(), "m": min_days}
    if customer_id is not None:
        conds.append("o.customer_id = :c")
        p["c"] = customer_id
    if salesman_id is not None:
        conds.append("o.salesman_id = :s")
        p["s"] = salesman_id
    where = " AND ".join(conds)
    totals = query(f"SELECT COUNT(*) AS orders, ROUND(COALESCE(SUM(o.total - o.paid_amount), 0), 2) AS outstanding "
                   f"FROM sales_orders o WHERE {where}", p)[0]
    rows = query(f"""
        SELECT o.invoice_no, c.name AS customer, c.phone, o.due_date, o.total, o.paid_amount,
               ROUND(o.total - o.paid_amount, 2) AS outstanding,
               CAST(julianday(:e) - julianday(o.due_date) AS INTEGER) AS days_overdue
        FROM sales_orders o JOIN customers c ON c.id = o.customer_id
        WHERE {where} ORDER BY outstanding DESC LIMIT {int(limit)}""", p)
    return _wrap(rows, totals=totals)


@router.get("/visits")
def visits(salesman_id: Optional[int] = None, date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
           limit: int = Query(15, ge=1, le=30)):
    """Planned customer visits. Without a date: upcoming planned visits from the data date onward."""
    p = {"e": latest_date(), "n": limit}
    conds = []
    if date:
        conds.append("v.planned_date = :d")
        p["d"] = date
    else:
        conds += ["v.status = 'Planned'", "v.planned_date >= :e"]
    if salesman_id is not None:
        conds.append("v.salesman_id = :s")
        p["s"] = salesman_id
    rows = query(f"""
        SELECT v.planned_date, v.status, c.name AS customer, c.city, c.phone, u.name AS salesman,
               b.outstanding, v.notes
        FROM visits v JOIN customers c ON c.id = v.customer_id LEFT JOIN users u ON u.id = v.salesman_id
        LEFT JOIN v_customer_balance b ON b.customer_id = c.id
        WHERE {' AND '.join(conds)} ORDER BY v.planned_date, c.name LIMIT :n""", p)
    return _wrap(rows)


@router.get("/salesman-summary")
def salesman_summary(salesman_id: int, days: int = Query(30, ge=1, le=365)):
    """A salesman's orders, sales, visits and unpaid balance over the last N days."""
    p = {"e": latest_date(), "d": days, "s": salesman_id}
    o = query(f"""SELECT COUNT(*) AS orders, ROUND(COALESCE(SUM(o.total), 0), 2) AS sales,
                         ROUND(COALESCE(SUM(o.paid_amount), 0), 2) AS paid_so_far
                  FROM sales_orders o WHERE o.salesman_id = :s AND {LIVE}
                    AND o.order_date > date(:e, '-' || :d || ' day') AND o.order_date <= :e""", p)[0]
    v = query("""SELECT SUM(status = 'Completed') AS visits_completed, SUM(status = 'Missed') AS visits_missed,
                        SUM(status = 'Planned') AS visits_planned, SUM(order_taken = 1) AS visits_with_order
                 FROM visits WHERE salesman_id = :s AND planned_date > date(:e, '-' || :d || ' day')
                   AND planned_date <= :e""", p)[0]
    u = query("""SELECT COUNT(*) AS unpaid_orders, ROUND(COALESCE(SUM(total - paid_amount), 0), 2) AS unpaid_total
                 FROM sales_orders WHERE salesman_id = :s AND status = 'Delivered' AND total - paid_amount > 0.01""", p)[0]
    name = query("SELECT name FROM users WHERE id = ?", (salesman_id,))
    return _wrap([{"salesman": name[0]["name"] if name else None, "days": days, **o, **v, **u}])
