# CRM read-only API and dashboard

For `../crm_demo.db` (Invoice Me style data). This folder holds the API, the older dashboard (port 8001, no login) and the insights code.
The management portal with login is described in PORTAL_README.md.

## Start (Windows, PowerShell)
```
cd C:\Claude\Projects\CRM\crm_api
pip install -r requirements.txt
uvicorn crm_dashboard:app --host 0.0.0.0 --port 8001
```
Dashboard: http://localhost:8001/dashboard   API docs: http://localhost:8001/docs
n8n (Docker): http://host.docker.internal:8001

The database opens read-only, no endpoint accepts raw SQL, every endpoint returns at most 200 rows.
Another database file: set the environment variable `CRM_DB`.
"Today" is the latest order date in the data (see /health). Pass `as_of=YYYY-MM-DD` to override.

## Endpoints
Same as v1: /health /sales-monthly /sales-summary /sales-by-category /sales-by-warehouse /top-customers
/outstanding /outstanding-aging /low-stock /expenses /pending-work (updated for the new statuses and columns).

New: /sales-by-brand, /order-status, /salesman-performance, /credit-risk, /approvals-pending,
/returns-by-status, /returns-by-brand, /delivery-performance.
