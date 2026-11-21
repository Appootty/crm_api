"""
Insights endpoint: observations and recommendations computed from the data with fixed,
read-only queries (profitability, cash flow, wastage, workflow). Numbers come from SQL;
the wording is templated, so nothing here is invented by a language model.

GET /insights?as_of=YYYY-MM-DD
"""
from typing import Optional

from fastapi import APIRouter

from crm_api import query, latest_date, LIVE

router = APIRouter()


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else {}


def f(n):
    return f"{(n or 0):,.0f}"


def pct(a, b):
    return round(100.0 * (a or 0) / b, 1) if b else 0.0


@router.get("/insights")
def insights(as_of: Optional[str] = None):
    e = as_of or latest_date()
    P = {"e": e}
    out = []

    def add(cat, prio, title, obs, rec, ai=None, kind=None, value=None):
        out.append({"id": len(out) + 1, "category": cat, "priority": prio, "title": title, "observation": obs,
                    "recommendation": rec, "automation": ai, "impact_kind": kind, "impact_value": round(value or 0)})

    # ============================================================ PROFITABILITY
    r = one(f"""SELECT COUNT(*) n, COUNT(DISTINCT o.id) orders,
                  ROUND(SUM((i.sale_price*1.0 - l.unit_price)*l.quantity),0) leak
           FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id JOIN items i ON i.id=l.item_id
           WHERE o.{LIVE} AND l.unit_price < 0.7*i.sale_price AND o.order_date > date(:e,'-365 day')""", P)
    if r.get("n"):
        add("Profitability", "High", "Order lines priced far below list price",
            f"{r['n']} order lines on {r['orders']} orders in the last 12 months were priced more than 30% below the item's list price, giving away about {f(r['leak'])}.",
            "Block or require approval for any line more than 15% below list price. Show the list price next to the entered price in the order screen.",
            "Rule check on every new order: flag lines below the price floor and send them to the approver queue.", "profit", r["leak"])

    rows = query(f"""SELECT u.name, COUNT(*) n,
                  ROUND(SUM((CAST(h.old_value AS REAL)-CAST(h.new_value AS REAL))*l.quantity),0) leak
           FROM order_edit_history h JOIN users u ON u.id=h.edited_by JOIN sales_order_lines l ON l.id=h.line_id
           WHERE h.field='unit_price' AND CAST(h.old_value AS REAL) > CAST(h.new_value AS REAL)*1.12
             AND h.edited_at > date(:e,'-365 day') GROUP BY u.id ORDER BY leak DESC""", P)
    if rows:
        tot = sum(x["leak"] or 0 for x in rows)
        top = rows[0]
        add("Profitability", "High", "Salesman cutting prices after the order is taken",
            f"{top['name']} made {top['n']} large price reductions (over 12%) after orders were entered, worth about {f(top['leak'])}" + (f" - {pct(top['leak'], tot)}% of all such cuts ({f(tot)} in total)." if len(rows) > 1 else ". No other salesman shows this pattern."),
            "Review these orders with the salesman and the customers involved. Lock price edits after order confirmation, or send them for approval.",
            "Weekly anomaly report on order edits per salesman, sent to the manager.", "profit", top["leak"])

    rows = query(f"""SELECT i.category, ROUND(SUM(l.line_total),0) rev,
                  ROUND(SUM(l.line_total - l.quantity*i.cost_price)*100.0/SUM(l.line_total),1) m
           FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id JOIN items i ON i.id=l.item_id
           WHERE o.{LIVE} AND o.order_date > date(:e,'-365 day') GROUP BY i.category""", P)
    if rows:
        tot_rev = sum(x["rev"] for x in rows)
        avg_m = round(sum(x["m"] * x["rev"] for x in rows) / tot_rev, 1)
        low = sorted(rows, key=lambda x: x["m"])[:3]
        gain = sum(x["rev"] for x in low) * 0.02
        add("Profitability", "Medium", "Lowest-margin categories",
            f"Gross margin is {avg_m}% overall. The weakest categories are " + ", ".join(f"{x['category']} ({x['m']}%)" for x in low) +
            f", which together brought in {f(sum(x['rev'] for x in low))} in 12 months.",
            "Review list prices and supplier costs for these categories. A 2% price increase on them would add about " + f(gain) + " a year, before volume effects.",
            "Monthly margin report by category and brand, with the items whose margin fell most.", "profit", gain)

    rows = query(f"""SELECT c.class_type, ROUND(SUM(l.line_total),0) rev,
                  ROUND(SUM(l.line_total - l.quantity*i.cost_price)*100.0/SUM(l.line_total),1) m
           FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id JOIN items i ON i.id=l.item_id
           JOIN customers c ON c.id=o.customer_id
           WHERE o.{LIVE} AND o.order_date > date(:e,'-365 day') GROUP BY c.class_type ORDER BY m""", P)
    if len(rows) > 1:
        add("Profitability", "Medium", "Margin by customer class (discount tiers)",
            "Gross margin after discounts by class: " + ", ".join(f"{x['class_type']} {x['m']}%" for x in rows) +
            f". {rows[0]['class_type']} earns the least per unit sold.",
            "Check that the discount each class receives is justified by its volume and payment record. Consider tying the top-tier discount to payment on time.",
            "Quarterly class review: suggest upgrades and downgrades from sales volume and payment behaviour.")

    r = one(f"""WITH t AS (SELECT customer_id, SUM(total) s FROM sales_orders WHERE {LIVE} AND order_date > date(:e,'-90 day') GROUP BY 1 ORDER BY s DESC)
           SELECT (SELECT SUM(s) FROM (SELECT s FROM t LIMIT 10)) top10, (SELECT SUM(s) FROM t) tot, (SELECT COUNT(*) FROM t) n""", P)
    if r.get("tot"):
        share = pct(r["top10"], r["tot"])
        add("Profitability", "Low" if share < 35 else "Medium", "Dependence on a few customers",
            f"The 10 biggest customers account for {share}% of sales in the last 90 days, out of {r['n']} active customers.",
            "Protect these accounts with regular visits and early warning when their order pattern changes. Grow the mid-size accounts to spread the risk.",
            "Alert when a top-20 customer's order frequency or basket size drops compared with its own history.")

    # ============================================================ CASH FLOW
    r = one("""WITH d AS (SELECT o.customer_id cid, o.total - o.paid_amount bal, julianday(:e)-julianday(o.due_date) dd
                  FROM sales_orders o WHERE o.status='Delivered' AND o.total - o.paid_amount > 0.005)
           SELECT ROUND(SUM(bal),0) total, ROUND(SUM(CASE WHEN dd>30 THEN bal END),0) o30,
                  ROUND(SUM(CASE WHEN dd>90 THEN bal END),0) o90, COUNT(DISTINCT CASE WHEN dd>30 THEN cid END) c30 FROM d""", P)
    if r.get("total"):
        t5 = one("""WITH d AS (SELECT o.customer_id cid, SUM(o.total - o.paid_amount) bal FROM sales_orders o
                  WHERE o.status='Delivered' AND o.total - o.paid_amount > 0.005 AND julianday(:e)-julianday(o.due_date) > 30 GROUP BY 1 ORDER BY bal DESC LIMIT 5)
               SELECT ROUND(SUM(bal),0) s FROM d""", P)
        noemail = one("""SELECT COUNT(DISTINCT c.id) n, ROUND(SUM(o.total-o.paid_amount),0) bal FROM sales_orders o JOIN customers c ON c.id=o.customer_id
               WHERE o.status='Delivered' AND o.total - o.paid_amount > 0.005 AND julianday(:e)-julianday(o.due_date) > 30 AND c.email IS NULL""", P)
        add("Cash flow", "High", "Overdue invoices are tying up cash",
            f"Unpaid delivered invoices total {f(r['total'])}. Of this, {f(r['o30'])} is more than 30 days overdue ({r['c30']} customers) and {f(r['o90'])} is more than 90 days overdue. "
            f"Five customers hold {pct(t5.get('s'), r['o30'])}% of the 30+ day amount.",
            "Send reminders on a fixed schedule (at due date, +7, +21, +45 days) and call the largest accounts personally. Hold new orders from customers more than 60 days overdue.",
            "n8n workflow: draft a reminder email for each overdue invoice from /outstanding; a person approves before sending.", "cash", r["o30"])
        if noemail.get("n"):
            add("Cash flow", "Medium", "Overdue customers with no email address",
                f"{noemail['n']} customers with invoices more than 30 days overdue ({f(noemail['bal'])}) have no email on file, so automatic reminders cannot reach them.",
                "Collect email addresses for these customers on the next visit and make email mandatory in the New Customer form for credit customers.",
                "Daily check that lists credit customers with missing contact details.")

    r = one("""SELECT COUNT(*) n, ROUND(SUM(outstanding - max_credit_amount),0) over_amt FROM v_customer_balance
           WHERE max_credit_amount > 0 AND outstanding > max_credit_amount""")
    if r.get("n"):
        add("Cash flow", "High", "Customers over their credit limit",
            f"{r['n']} customers owe more than their maximum credit amount, by {f(r['over_amt'])} in total, and are still able to order.",
            "Stop confirming new orders for these customers until they pay down to the limit. Make the app check balance plus new order against the limit at order entry.",
            "Credit check on every order in 'Orders to confirm': show balance, limit and payment history to the approver.", "cash", r["over_amt"])

    rows = query("""SELECT c.class_type, ROUND(AVG(julianday(p.payment_date)-julianday(o.due_date)),1) late, COUNT(*) n
           FROM payments p JOIN sales_orders o ON o.id=p.order_id JOIN customers c ON c.id=o.customer_id
           WHERE p.method != 'Wallet' AND o.due_date IS NOT NULL AND c.max_credit_period_days > 0
             AND p.payment_date > date(:e,'-365 day') GROUP BY c.class_type ORDER BY late DESC""", P)
    r2 = one("""SELECT COUNT(*) n, SUM(CASE WHEN p.payment_date > o.due_date THEN 1 ELSE 0 END) late
           FROM payments p JOIN sales_orders o ON o.id=p.order_id JOIN customers c ON c.id=o.customer_id
           WHERE p.method != 'Wallet' AND o.due_date IS NOT NULL AND c.max_credit_period_days > 0 AND p.payment_date > date(:e,'-365 day')""", P)
    if rows and r2.get("n"):
        add("Cash flow", "Medium", "Payment behaviour by customer class",
            f"{pct(r2['late'], r2['n'])}% of credit payments in the last 12 months arrived after the due date. Average days relative to due date: " +
            ", ".join(f"{x['class_type']} {x['late']:+.1f}" for x in rows) + ".",
            "Offer a small early-payment discount (for example 1% if paid within 10 days) to the best customers, and shorten credit days for the classes that pay latest.",
            "Score each customer's payment behaviour monthly and suggest credit-period changes for approval.")

    r = one("""SELECT COUNT(*) n, ROUND(SUM(total),0) val, MIN(order_date) oldest FROM sales_orders
           WHERE status='Pending' AND order_date < date(:e,'-14 day')""", P)
    if r.get("n"):
        add("Cash flow", "Medium", "Orders stuck in Pending",
            f"{r['n']} orders worth {f(r['val'])} have been in Pending status for more than 14 days (oldest from {r['oldest']}). They are neither delivered nor cancelled.",
            "Decide each one: confirm, cancel or contact the customer. Add an automatic reminder to the approver when an order stays pending more than 3 days.",
            "Daily digest of pending orders by age to the approver, with the reason each was held.", "revenue", r["val"])

    # ============================================================ WASTAGE
    r = one("""SELECT ROUND(SUM(credit_amount),0) tot, COUNT(*) n,
                  ROUND(SUM(CASE WHEN reason LIKE 'Expired%' THEN credit_amount END),0) exp
           FROM sales_returns WHERE status != 'Cancelled Returns' AND return_date > date(:e,'-365 day')""", P)
    br = query("""SELECT i.brand, ROUND(SUM(rl.amount),0) amt FROM sales_return_lines rl JOIN sales_returns r ON r.id=rl.return_id
           JOIN items i ON i.id=rl.item_id WHERE r.status != 'Cancelled Returns' AND r.return_date > date(:e,'-365 day')
           GROUP BY i.brand ORDER BY amt DESC""", P)
    if r.get("tot") and br:
        sold = one(f"""SELECT ROUND(SUM(l.line_total),0) rev FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id JOIN items i ON i.id=l.item_id
               WHERE o.{LIVE} AND i.brand=:b AND o.order_date > date(:e,'-365 day')""", {"e": e, "b": br[0]["brand"]})
        all_sold = one(f"""SELECT ROUND(SUM(total),0) rev FROM sales_orders WHERE {LIVE} AND order_date > date(:e,'-365 day')""", P)
        add("Wastage", "High", "Returns concentrated in one brand, mostly expired stock",
            f"Approved or pending returns cost {f(r['tot'])} in the last 12 months. {pct(r['exp'], r['tot'])}% were expired or near-expiry goods. "
            f"{br[0]['brand']} accounts for {pct(br[0]['amt'], r['tot'])}% of returned value, a return rate of {pct(br[0]['amt'], sold.get('rev'))}% of its sales against {pct(r['tot'], all_sold.get('rev'))}% overall.",
            f"Raise a claim with the {br[0]['brand']} supplier, reduce order quantities for it, and ship oldest stock first. Ask customers with slow-moving shelves to order smaller, more frequent quantities.",
            "Alert when a brand's return rate passes twice the company average; draft the supplier claim from the return lines.", "waste", r["tot"])

    rows = query("""SELECT u.name, COUNT(*) del,
                  SUM(CASE WHEN r.reason='Damaged in transit' THEN 1 ELSE 0 END) dmg
           FROM deliveries d JOIN users u ON u.id=d.driver_id LEFT JOIN sales_returns r ON r.order_id=d.order_id
           WHERE d.delivered_at > date(:e,'-365 day') GROUP BY u.id""", P)
    if rows:
        rates = [(x["name"], pct(x["dmg"], x["del"]), x["dmg"]) for x in rows]
        avg = pct(sum(x["dmg"] for x in rows), sum(x["del"] for x in rows))
        worst = max(rates, key=lambda x: x[1])
        if avg > 0 and worst[1] >= 1.5 * avg:
            add("Wastage", "Medium", "Damage in transit varies by driver",
                f"{worst[0]} has {worst[2]} damaged-in-transit returns ({worst[1]}% of deliveries) against a fleet average of {avg}%.",
                "Check loading and handling for that route and vehicle. Add a photo at delivery for fragile items.")

    r = one("""WITH sold AS (SELECT l.item_id, o.warehouse_id wh, SUM(l.quantity) q FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id
                  WHERE o.status NOT IN ('Cancelled','Rejected') AND o.order_date > date(:e,'-90 day') GROUP BY 1,2)
           SELECT COUNT(*) n, ROUND(SUM(s.quantity*i.cost_price),0) cap FROM stock s JOIN items i ON i.id=s.item_id
           LEFT JOIN sold ON sold.item_id=s.item_id AND sold.wh=s.warehouse_id
           WHERE COALESCE(sold.q,0)=0 AND s.quantity > 2*i.reorder_level""", P)
    if r.get("n"):
        add("Wastage", "Medium", "Slow-moving stock tying up capital",
            f"{r['n']} item-and-warehouse combinations hold more than twice their reorder level but sold nothing in 90 days. Stock at cost: {f(r['cap'])}.",
            "Move or discount this stock, stop reordering it, and review whether these items should stay in the item master. Check expiry dates first.",
            "Monthly list of slow-moving items with suggested transfer between warehouses.", "cash", r["cap"])

    rows = query(f"""SELECT w.name wh, v.name item, v.quantity q, v.reorder_level rl,
                  COALESCE((SELECT SUM(l.line_total) FROM sales_order_lines l JOIN sales_orders o ON o.id=l.order_id
                            WHERE l.item_id=v.item_id AND o.warehouse_id=v.warehouse_id AND o.{LIVE}
                              AND o.order_date > date(:e,'-90 day')),0) rev
           FROM v_low_stock v JOIN warehouses w ON w.id=v.warehouse_id ORDER BY rev DESC""", P)
    if rows:
        add("Wastage", "Medium", "Low stock on items that sell",
            f"{len(rows)} items are at or below reorder level. They sold {f(sum(x['rev'] for x in rows))} in the last 90 days; the fastest are " +
            ", ".join(f"{x['item']} ({x['wh']})" for x in rows[:3]) + ".",
            "Raise purchase orders for these items now, sized from the last 90 days of sales plus supplier lead time. Stock-outs mean lost orders and unhappy customers.",
            "Daily draft purchase orders per supplier from /low-stock, for the buyer to approve.")

    # ============================================================ WORKFLOW
    rows = query("""SELECT u.name, COUNT(*) n, ROUND(AVG(julianday(d.delivered_at)-julianday(d.assigned_at)),2) avg_days,
                  SUM(CASE WHEN julianday(d.delivered_at)-julianday(d.assigned_at) > 3 THEN 1 ELSE 0 END) late
           FROM deliveries d JOIN users u ON u.id=d.driver_id
           WHERE d.delivered_at IS NOT NULL AND d.delivered_at > date(:e,'-90 day') GROUP BY u.id ORDER BY avg_days DESC""", P)
    if len(rows) > 1:
        fleet = round(sum(x["avg_days"] * x["n"] for x in rows[1:]) / sum(x["n"] for x in rows[1:]), 2)
        if rows[0]["avg_days"] > 1.5 * fleet:
            add("Workflow", "High", "One driver is much slower than the rest",
                f"{rows[0]['name']} takes {rows[0]['avg_days']} days on average from assignment to delivery, against {fleet} days for the other drivers. {rows[0]['late']} of their deliveries took more than 3 days.",
                "Review the route and load, and reassign part of it. Late delivery also pushes back the invoice date and therefore payment.",
                "Alert when any driver's 14-day average delivery time passes 1.5 times the fleet average.")

    r = one("""SELECT COUNT(*) n, SUM(CASE WHEN julianday(:e)-julianday(created_at) > 7 THEN 1 ELSE 0 END) old,
                  MIN(created_at) oldest FROM approval_requests WHERE status='Pending'""", P)
    d = one("""SELECT ROUND(AVG(julianday(decided_at)-julianday(created_at)),1) avg_days FROM approval_requests
           WHERE status != 'Pending' AND created_at > date(:e,'-365 day')""", P)
    if r.get("n"):
        add("Workflow", "Medium" if (r["old"] or 0) else "Low", "Approval backlog",
            f"{r['n']} approvals are waiting ({r['old']} for more than a week, oldest from {r['oldest']}). Decided requests took {d.get('avg_days')} days on average.",
            "Set a one-working-day target for registrations and order approvals. Send the approver a daily list and escalate anything older than 3 days.",
            "Daily approval digest with the key facts for each request so the approver can decide in one step.")

    r = one("""SELECT COUNT(*) n, SUM(CASE WHEN source IN ('WhatsApp','Phone','Email') THEN 1 ELSE 0 END) manual
           FROM sales_orders WHERE order_date > date(:e,'-90 day')""", P)
    if r.get("n"):
        hours = r["manual"] * 5 / 60 / 3
        add("Workflow", "Medium", "Many orders arrive by message, phone or email",
            f"{pct(r['manual'], r['n'])}% of orders in the last 90 days ({r['manual']} of {r['n']}) came by WhatsApp, phone or email and were typed in by hand.",
            f"Read these messages automatically and prepare a draft order for a person to check. At about 5 minutes per order this could save around {hours:.0f} staff hours a month.",
            "n8n workflow: read the order message, match customer and items, create a draft order, flag anything unclear.", "time", hours)

    r = one(f"""WITH a AS (SELECT customer_id, COUNT(*) n, SUM(total) s FROM sales_orders WHERE {LIVE}
                  AND order_date > date(:e,'-365 day') AND order_date <= date(:e,'-90 day') GROUP BY 1 HAVING COUNT(*) >= 3),
                  b AS (SELECT DISTINCT customer_id FROM sales_orders WHERE {LIVE} AND order_date > date(:e,'-90 day'))
           SELECT COUNT(*) n, ROUND(SUM(a.s),0) s FROM a JOIN customers c ON c.id=a.customer_id
           WHERE a.customer_id NOT IN (SELECT customer_id FROM b) AND c.status='Active'""", P)
    if r.get("n"):
        add("Workflow", "High", "Regular customers who stopped ordering",
            f"{r['n']} customers who ordered at least 3 times earlier in the year have placed no order in the last 90 days. Their sales in the 9 months before that were {f(r['s'])}.",
            "Have the responsible salesman call each one, starting with the largest. Ask what changed (price, service, a competitor) and record the answer.",
            "Weekly list of customers whose order gap is much longer than their normal rhythm, with a suggested talking point.", "revenue", r["s"])

    r = one("""SELECT COUNT(*) n, SUM(CASE WHEN status='Missed' THEN 1 ELSE 0 END) missed,
                  SUM(CASE WHEN status='Rescheduled' THEN 1 ELSE 0 END) resch,
                  SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) done, SUM(order_taken) orders
           FROM visits WHERE planned_date > date(:e,'-90 day') AND planned_date <= :e""", P)
    if r.get("n"):
        add("Workflow", "Low", "Visit plan results",
            f"In the last 90 days {r['n']} visits were planned: {pct(r['done'], r['n'])}% completed, {pct(r['missed'], r['n'])}% missed and {pct(r['resch'], r['n'])}% rescheduled. "
            f"{pct(r['orders'], r['done'])}% of completed visits led to an order.",
            "Plan routes by area to cut missed visits, and use visit time on customers with falling order rates rather than the steady ones.",
            "Suggest next week's visit list per salesman, ranked by overdue payments, falling orders and visit gap.")

    r = one("""SELECT COUNT(*) n FROM (SELECT phone FROM customers WHERE phone IS NOT NULL GROUP BY phone HAVING COUNT(*) > 1)""")
    t = one("""SELECT COUNT(*) n FROM customers WHERE class_type IN ('Platinum','Gold') AND trn_gst_no IS NULL AND status='Active'""")
    if r.get("n") or t.get("n"):
        add("Workflow", "Low", "Customer data quality",
            f"{r.get('n', 0)} phone numbers are shared by more than one customer record (likely duplicates), and {t.get('n', 0)} Platinum or Gold customers have no TRN/GST number on file.",
            "Merge the duplicate records so balances and history sit in one place. Make the tax number mandatory for large customers.",
            "Nightly duplicate check on new customers, shown to the approver during registration approval.")

    summary = {}
    for x in out:
        s = summary.setdefault(x["category"], {"count": 0, "high": 0})
        s["count"] += 1
        s["high"] += 1 if x["priority"] == "High" else 0
    kinds = {}
    for x in out:
        if x["impact_kind"]:
            kinds[x["impact_kind"]] = kinds.get(x["impact_kind"], 0) + x["impact_value"]
    order = {"High": 0, "Medium": 1, "Low": 2}
    cats = ["Profitability", "Cash flow", "Wastage", "Workflow"]
    out.sort(key=lambda x: (cats.index(x["category"]), order[x["priority"]]))
    return {"as_of": e, "summary": summary, "impact": kinds, "insights": out}
