"""
Read-only CRM API (for crm_demo.db, the Invoice Me style data).

- Opens the database in SQLite read-only mode (writes are impossible).
- Only fixed, parameterised queries. No endpoint accepts raw SQL.
- Every endpoint is capped at MAX_ROWS rows.

Run:  uvicorn crm_dashboard:app --host 0.0.0.0 --port 8001
Docs: http://localhost:8001/docs
"""
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from dbsource import current_db, version_info

DB_PATH = Path(os.environ.get("CRM_DB", Path(__file__).resolve().parent.parent / "crm_demo.db"))
MAX_ROWS = 200
TIMEOUT_SECONDS = 5
LIVE = "status NOT IN ('Cancelled','Rejected')"  # orders that count as sales

app = FastAPI(title="CRM read-only API", version="2.0")


def query(sql: str, params=()):
    """Run one SELECT on a read-only connection with a time limit."""
    try:
        path = current_db(DB_PATH)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if not path.exists():
        raise HTTPException(500, f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    start = time.time()
    conn.set_progress_handler(lambda: 1 if time.time() - start > TIMEOUT_SECONDS else 0, 10000)
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchmany(MAX_ROWS)]
    except sqlite3.Error as e:
        raise HTTPException(500, f"Query failed: {e}")
    finally:
        conn.close()


def latest_date() -> str:
    """The data is a snapshot, so 'today' = the latest order date, not the real date."""
    return query("SELECT MAX(order_date) AS d FROM sales_orders")[0]["d"]


@app.get("/health")
def health():
    try:
        name = current_db(DB_PATH).name
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"status": "ok", "db": name, "data_up_to": latest_date(), **version_info()}


# ------------------------------------------------------------------ sales
@app.get("/sales-monthly")
def sales_monthly(months: int = Query(12, ge=1, le=36)):
    """Orders and sales per month (all orders except cancelled and rejected), newest first."""
    return query(
        f"""SELECT substr(order_date,1,7) AS month, COUNT(*) AS orders, ROUND(SUM(total),2) AS sales
            FROM sales_orders WHERE {LIVE} GROUP BY 1 ORDER BY 1 DESC LIMIT ?""", (months,))


@app.get("/sales-summary")
def sales_summary(days: int = Query(7, ge=1, le=365), as_of: Optional[str] = None):
    """Sales for the last N days vs the N days before, with % change."""
    end = as_of or latest_date()
    sql = f"""
    WITH p AS (
      SELECT
        SUM(CASE WHEN order_date >  date(:e, '-' || :n || ' day') AND order_date <= :e THEN total END) AS cur,
        SUM(CASE WHEN order_date >  date(:e, '-' || (2*:n) || ' day')
                  AND order_date <= date(:e, '-' || :n || ' day') THEN total END) AS prev,
        SUM(CASE WHEN order_date >  date(:e, '-' || :n || ' day') AND order_date <= :e THEN 1 END) AS cur_orders,
        SUM(CASE WHEN order_date >  date(:e, '-' || (2*:n) || ' day')
                  AND order_date <= date(:e, '-' || :n || ' day') THEN 1 END) AS prev_orders
      FROM sales_orders WHERE {LIVE})
    SELECT :e AS as_of, :n AS days,
           ROUND(COALESCE(cur,0),2) AS current_sales, ROUND(COALESCE(prev,0),2) AS previous_sales,
           COALESCE(cur_orders,0) AS current_orders, COALESCE(prev_orders,0) AS previous_orders,
           CASE WHEN prev > 0 THEN ROUND((cur - prev) * 100.0 / prev, 1) END AS change_pct
    FROM p"""
    return query(sql, {"e": end, "n": days})


@app.get("/sales-by-category")
def sales_by_category(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    """Revenue, quantity and gross margin per item category."""
    end = as_of or latest_date()
    return query(
        f"""SELECT i.category, SUM(l.quantity) AS units, ROUND(SUM(l.line_total),2) AS revenue,
                   ROUND(SUM(l.line_total - l.quantity * i.cost_price),2) AS gross_margin,
                   ROUND(SUM(l.line_total - l.quantity * i.cost_price) * 100.0 / SUM(l.line_total),1) AS margin_pct
            FROM sales_order_lines l JOIN sales_orders o ON o.id = l.order_id JOIN items i ON i.id = l.item_id
            WHERE o.{LIVE} AND o.order_date > date(?, '-' || ? || ' day') AND o.order_date <= ?
            GROUP BY i.category ORDER BY revenue DESC""", (end, days, end))


@app.get("/sales-by-brand")
def sales_by_brand(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    """Brand-wise business (Product Overview screen)."""
    end = as_of or latest_date()
    return query(
        f"""SELECT i.brand, SUM(l.quantity) AS units, ROUND(SUM(l.line_total),2) AS revenue,
                   ROUND(SUM(l.line_total - l.quantity * i.cost_price),2) AS gross_margin
            FROM sales_order_lines l JOIN sales_orders o ON o.id = l.order_id JOIN items i ON i.id = l.item_id
            WHERE o.{LIVE} AND o.order_date > date(?, '-' || ? || ' day') AND o.order_date <= ?
            GROUP BY i.brand ORDER BY revenue DESC""", (end, days, end))


@app.get("/sales-by-warehouse")
def sales_by_warehouse(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    end = as_of or latest_date()
    return query(
        f"""SELECT w.name AS warehouse, COUNT(*) AS orders, ROUND(SUM(o.total),2) AS sales
            FROM sales_orders o JOIN warehouses w ON w.id = o.warehouse_id
            WHERE o.{LIVE} AND o.order_date > date(?, '-' || ? || ' day') AND o.order_date <= ?
            GROUP BY w.name ORDER BY sales DESC""", (end, days, end))


@app.get("/order-status")
def order_status(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    """Order counts and value by status for the last N days (My Orders screen)."""
    end = as_of or latest_date()
    return query(
        """SELECT status, COUNT(*) AS orders, ROUND(SUM(total),2) AS value FROM sales_orders
           WHERE order_date > date(?, '-' || ? || ' day') AND order_date <= ?
           GROUP BY status ORDER BY orders DESC""", (end, days, end))


@app.get("/top-customers")
def top_customers(limit: int = Query(10, ge=1, le=100), days: int = Query(90, ge=1, le=730), as_of: Optional[str] = None):
    end = as_of or latest_date()
    return query(
        f"""SELECT c.id AS customer_id, c.name, c.city, c.class_type, COUNT(*) AS orders,
                   ROUND(SUM(o.total),2) AS sales, MAX(o.order_date) AS last_order
            FROM sales_orders o JOIN customers c ON c.id = o.customer_id
            WHERE o.{LIVE} AND o.order_date > date(?, '-' || ? || ' day') AND o.order_date <= ?
            GROUP BY c.id ORDER BY sales DESC LIMIT ?""", (end, days, end, limit))


@app.get("/salesman-performance")
def salesman_performance(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    """Orders, sales, collections and price edits per salesman."""
    end = as_of or latest_date()
    return query(
        f"""SELECT u.id AS salesman_id, u.name, COUNT(*) AS orders, ROUND(SUM(o.total),2) AS sales,
                   ROUND(SUM(o.paid_amount),2) AS collected,
                   (SELECT COUNT(*) FROM order_edit_history h
                     WHERE h.edited_by = u.id AND h.field = 'unit_price'
                       AND h.edited_at > date(:e, '-' || :n || ' day') AND h.edited_at <= :e) AS price_edits
            FROM sales_orders o JOIN users u ON u.id = o.salesman_id
            WHERE o.{LIVE} AND o.order_date > date(:e, '-' || :n || ' day') AND o.order_date <= :e
            GROUP BY u.id ORDER BY sales DESC""", {"e": end, "n": days})


# ------------------------------------------------------------------ money owed
@app.get("/outstanding")
def outstanding(min_days_overdue: int = Query(0, ge=0, le=730), limit: int = Query(50, ge=1, le=200),
                as_of: Optional[str] = None):
    """Delivered invoices that are unpaid and past due, biggest balance first, with contact details for reminder drafts."""
    end = as_of or latest_date()
    return query(
        """SELECT o.order_no, o.invoice_no, c.id AS customer_id, c.name AS customer, c.class_type, c.contact_person,
                  c.email, c.phone, o.delivered_date, o.due_date, o.total, o.paid_amount,
                  ROUND(o.total - o.paid_amount, 2) AS balance,
                  CAST(julianday(?) - julianday(o.due_date) AS INTEGER) AS days_overdue
           FROM sales_orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.status = 'Delivered' AND o.total - o.paid_amount > 0.005
             AND julianday(?) - julianday(o.due_date) >= ?
           ORDER BY balance DESC LIMIT ?""", (end, end, min_days_overdue, limit))


@app.get("/outstanding-aging")
def outstanding_aging(as_of: Optional[str] = None):
    """Total unpaid balance grouped into overdue-age buckets."""
    end = as_of or latest_date()
    return query(
        """SELECT CASE
                    WHEN julianday(:e) - julianday(due_date) <= 0  THEN '0 not yet due'
                    WHEN julianday(:e) - julianday(due_date) <= 30 THEN '1 overdue 1-30'
                    WHEN julianday(:e) - julianday(due_date) <= 60 THEN '2 overdue 31-60'
                    WHEN julianday(:e) - julianday(due_date) <= 90 THEN '3 overdue 61-90'
                    ELSE '4 overdue 90+' END AS bucket,
                  COUNT(*) AS orders, ROUND(SUM(total - paid_amount),2) AS balance
           FROM sales_orders WHERE status = 'Delivered' AND total - paid_amount > 0.005
           GROUP BY bucket ORDER BY bucket""", {"e": end})


@app.get("/credit-risk")
def credit_risk(limit: int = Query(20, ge=1, le=200)):
    """Customers whose unpaid invoices exceed their max credit amount."""
    return query(
        """SELECT customer_id, name, class_type, max_credit_amount, outstanding,
                  ROUND(outstanding - max_credit_amount, 2) AS over_limit, wallet_balance
           FROM v_customer_balance WHERE max_credit_amount > 0 AND outstanding > max_credit_amount
           ORDER BY over_limit DESC LIMIT ?""", (limit,))


# ------------------------------------------------------------------ stock and expenses
@app.get("/low-stock")
def low_stock(warehouse_id: Optional[int] = None, limit: int = Query(50, ge=1, le=200), as_of: Optional[str] = None):
    """Items at or below reorder level, with units sold in the last 90 days and supplier."""
    end = as_of or latest_date()
    return query(
        f"""SELECT w.name AS warehouse, v.item_id, v.name AS item, v.brand, v.quantity, v.reorder_level,
                   s.name AS supplier,
                   COALESCE((SELECT SUM(l.quantity) FROM sales_order_lines l JOIN sales_orders o ON o.id = l.order_id
                             WHERE l.item_id = v.item_id AND o.warehouse_id = v.warehouse_id AND o.{LIVE}
                               AND o.order_date > date(?, '-90 day') AND o.order_date <= ?), 0) AS sold_last_90d
            FROM v_low_stock v JOIN warehouses w ON w.id = v.warehouse_id
            JOIN items i ON i.id = v.item_id LEFT JOIN suppliers s ON s.id = i.supplier_id
            WHERE (? IS NULL OR v.warehouse_id = ?)
            ORDER BY (v.reorder_level - v.quantity) DESC LIMIT ?""", (end, end, warehouse_id, warehouse_id, limit))


@app.get("/expenses")
def expenses(days: int = Query(30, ge=1, le=730), as_of: Optional[str] = None):
    """Expenses by category for the last N days."""
    end = as_of or latest_date()
    return query(
        """SELECT category, COUNT(*) AS entries, ROUND(SUM(amount),2) AS total FROM expenses
           WHERE expense_date > date(?, '-' || ? || ' day') AND expense_date <= ?
           GROUP BY category ORDER BY total DESC""", (end, days, end))


# ------------------------------------------------------------------ workflow screens
@app.get("/pending-work")
def pending_work():
    """Counts like the app's home screen, plus approvals and returns."""
    return query(
        """SELECT
             (SELECT COUNT(*) FROM sales_orders WHERE status='Pending') AS orders_to_confirm,
             (SELECT COUNT(*) FROM sales_orders WHERE status='New') AS new_orders,
             (SELECT COUNT(*) FROM customers WHERE status='Pending confirmation') AS customers_to_confirm,
             (SELECT COUNT(*) FROM v_low_stock) AS low_stock_items,
             (SELECT COUNT(*) FROM approval_requests WHERE status='Pending') AS pending_approvals,
             (SELECT COUNT(*) FROM sales_returns WHERE status IN ('Not yet received in Warehouse','Received in Warehouse')) AS open_returns""")


@app.get("/approvals-pending")
def approvals_pending(limit: int = Query(30, ge=1, le=200), as_of: Optional[str] = None):
    """Open approval requests (registrations, class and credit changes, orders), oldest first."""
    end = as_of or latest_date()
    return query(
        """SELECT a.id, a.request_type, c.name AS customer, u.name AS requested_by, a.order_id, a.created_at,
                  CAST(julianday(?) - julianday(a.created_at) AS INTEGER) AS days_waiting, a.details
           FROM approval_requests a LEFT JOIN customers c ON c.id = a.customer_id LEFT JOIN users u ON u.id = a.requested_by
           WHERE a.status = 'Pending' ORDER BY a.created_at LIMIT ?""", (end, limit))


@app.get("/returns-by-status")
def returns_by_status():
    return query(
        """SELECT status, COUNT(*) AS returns, ROUND(SUM(credit_amount),2) AS credit_amount
           FROM sales_returns GROUP BY status ORDER BY returns DESC""")


@app.get("/returns-by-brand")
def returns_by_brand(days: int = Query(180, ge=1, le=730), as_of: Optional[str] = None):
    """Returned value per brand with the main reason, for quality and supplier follow-up."""
    end = as_of or latest_date()
    return query(
        """SELECT i.brand, COUNT(DISTINCT r.id) AS returns, SUM(rl.quantity) AS units, ROUND(SUM(rl.amount),2) AS amount,
                  (SELECT r2.reason FROM sales_returns r2 JOIN sales_return_lines l2 ON l2.return_id = r2.id
                    JOIN items i2 ON i2.id = l2.item_id WHERE i2.brand = i.brand GROUP BY r2.reason
                    ORDER BY COUNT(*) DESC LIMIT 1) AS main_reason
           FROM sales_return_lines rl JOIN sales_returns r ON r.id = rl.return_id JOIN items i ON i.id = rl.item_id
           WHERE r.return_date > date(?, '-' || ? || ' day') AND r.return_date <= ?
           GROUP BY i.brand ORDER BY amount DESC""", (end, days, end))


@app.get("/delivery-performance")
def delivery_performance(days: int = Query(90, ge=1, le=730), as_of: Optional[str] = None):
    """Average days from assignment to delivery per driver."""
    end = as_of or latest_date()
    return query(
        """SELECT u.id AS driver_id, u.name AS driver, COUNT(*) AS deliveries,
                  ROUND(AVG(julianday(d.delivered_at) - julianday(d.assigned_at)),2) AS avg_days,
                  SUM(CASE WHEN d.attempts > 1 THEN 1 ELSE 0 END) AS failed_first_attempt
           FROM deliveries d JOIN users u ON u.id = d.driver_id
           WHERE d.delivered_at IS NOT NULL AND d.delivered_at > date(?, '-' || ? || ' day') AND d.delivered_at <= ?
           GROUP BY u.id ORDER BY avg_days DESC""", (end, days, end))
