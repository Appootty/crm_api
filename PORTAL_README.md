# Management portal

Sign-in page plus five tabs: Overview, Sales and products, Cash and credit, Operations, Insights and recommendations.
Everything (pages and data endpoints) needs a login. The older dashboard (`crm_dashboard.py`, port 8001) is unchanged and has no login, so do not publish it.

## Start (Windows, PowerShell)
```
cd C:\Claude\Projects\CRM\crm_api
pip install -r requirements.txt
uvicorn portal:app --host 0.0.0.0 --port 8002
```
Open http://localhost:8002 and sign in. The first user is `admin`; change its password straight away:
```
python manage_users.py passwd admin
python manage_users.py add jane "Jane Smith"        (asks for a password)
python manage_users.py list
python manage_users.py remove jane
```
Passwords are stored only as salted hashes in `portal_users.json`. Keep that file, and the hidden `.portal_secret` file
(signs the sign-in cookie), out of any shared or public location.

## n8n and other machines
Browsers sign in with the cookie. For n8n set an environment variable before starting the server and send it as a header:
```
$env:CRM_API_KEY = "a-long-random-string"
uvicorn portal:app --host 0.0.0.0 --port 8002
```
n8n HTTP Request node: header `X-API-Key: <the same string>`, URL `http://host.docker.internal:8002/outstanding`.

## Settings (environment variables)
CRM_DB (database file), CRM_API_KEY (machine access), CRM_SECRET_KEY (cookie signing key, use a fixed value in the cloud),
PORTAL_SESSION_HOURS (default 8), PORTAL_USERS (path of the users file).

## Safeguards
Five wrong passwords lock that user and address for 10 minutes. The cookie is HttpOnly and SameSite=Lax, and marked Secure
when served over HTTPS. Serve it over HTTPS in the cloud (Cloud Run does this).
