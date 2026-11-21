# Push-to-talk voice assistant for the management portal

New files only (nothing existing was changed): `portal_voice.py` (entry point), `voice_widget.js` (the button),
`voice_proxy.py` (relay to n8n), `voice_tools.py` (lookup endpoints for the n8n agent), this file.

```
Browser (Talk button, signed in) --audio--> /voice/ask (portal) --audio + who--> n8n webhook
n8n: transcribe -> AI agent -> tools = /tools/* on the portal (X-API-Key) -> answer JSON -> portal -> browser
```
The browser never sees the n8n address or any secret. n8n learns who is asking from the portal, not from the browser.

## 1. Try it locally (no n8n needed to see the button)
```
cd C:\Claude\Projects\CRM\crm_api
uvicorn portal_voice:app --host 0.0.0.0 --port 8002
```
Open http://localhost:8002 and sign in. The round microphone button (bottom right) is greyed out until N8N_VOICE_URL is set.
Click "Talk to assistant" (under the menu) once to start a conversation: speak, pause, and the question is sent automatically; the answer appears (and is read aloud
if "Read aloud" is ticked), then it listens again. Click "End conversation" to end. It also ends after 45 seconds of silence.
Each conversation has its own memory in n8n, so follow-up questions work.
Microphones work on http://localhost and on any https:// address, but not on plain http:// elsewhere.

## 2. Switch it on (environment variables, set before starting the portal)
```
$env:CRM_API_KEY      = "a-long-random-string"        # n8n tools use this (already supported by the portal)
$env:N8N_VOICE_URL    = "https://YOUR-N8N/webhook/voice-query"
$env:N8N_VOICE_SECRET = "another-long-random-string"  # n8n checks it
```
Optional: N8N_VOICE_TIMEOUT (seconds, default 60), VOICE_RATE_PER_MIN (default 12 per user).
While building in n8n use the "Test URL" (webhook-test) and click "Listen for test event" first; switch to the Production URL when active.

## 3. Build the n8n workflow
Nodes, in order:

1. **Webhook** - POST, path `voice-query`, Respond: "Using 'Respond to Webhook' Node". The audio arrives as binary field `audio`;
   the text fields are in `body`: `session`, `user`, `name`, `role`, and `salesman_id` (only for users that have one).
2. **IF (check secret)** - `{{ $json.headers['x-voice-secret'] }}` equals your N8N_VOICE_SECRET. False branch: Respond to Webhook, status 401.
3. **OpenAI > "Transcribe a Recording"** (rename the node **Transcribe**), binary property `audio`. Returns `text`.
   Test with your callers' real accents and languages; set the language option if they all use one.
4. **AI Agent** (Tools Agent), chat model Anthropic (Sonnet is enough). Prompt "Define below":
   `{{ $('Transcribe').item.json.text }}`
   Memory: **Window Buffer Memory**, session key `{{ $('Webhook').item.json.body.session }}`, window 6.
   System message (starting point):
   ```
   You are the voice assistant for a food distribution company's management portal. You answer questions about
   stock, customers, orders, overdue balances, visits and salesmen using ONLY the tools. Never guess or calculate
   numbers yourself: quote what the tools return. If an item or customer name matches several records, ask which one.
   Every tool result has as_of / data_version: mention "as of <date>" when you give stock or balances, because the data
   is a copy and may be a day old. You cannot change anything; say so if asked. Keep answers to one or two short
   sentences, easy to read aloud. Money has no currency symbol in the data; say "AED" only if the user does.
   Reply with JSON only: {"answer": "<short spoken answer>", "table": null}
   or, for lists of 3 or more rows: {"answer": "...", "table": {"columns": ["..."], "rows": [["..."]]}}
   ```
5. **HTTP Request Tool** nodes for the agent (one per row). Base URL = your portal, e.g. `https://YOUR-PORTAL`.
   Authentication: header `X-API-Key` = CRM_API_KEY. Query parameters marked "model" are filled by the agent; mark "fixed" ones
   with an expression, so the model cannot change them: `salesman_id` = `{{ $('Webhook').item.json.body.salesman_id }}`
   (empty for managers, which means "all"; for a salesman it limits every answer to his own customers and orders).

   | Tool name | Path | Model fills | Fixed | Use for |
   |---|---|---|---|---|
   | find_salesman | /tools/salesmen | name | | Turn a salesman's name into an id |
   | stock_lookup | /tools/stock | item, warehouse (optional) | | Stock and price of an item by warehouse |
   | find_customer | /tools/customer | name | salesman_id | Customer details, balance, credit limit, days overdue |
   | recent_orders | /tools/orders | customer_id, status, days, limit | salesman_id | Recent orders |
   | order_detail | /tools/order-detail | number | salesman_id | One order with its lines |
   | overdue_balances | /tools/overdue | customer_id, min_days, limit | salesman_id | Unpaid orders past due, with totals |
   | visit_plan | /tools/visits | date (YYYY-MM-DD, optional) | salesman_id | Planned customer visits |
   | salesman_summary | /tools/salesman-summary | salesman_id (managers only), days | | A salesman's orders, sales, visits |
   Add the existing endpoints (/sales-summary, /top-customers, /low-stock, /outstanding-aging ...) as more tools for management questions.
   Give each tool a clear description ("Use to find the stock of an item. Pass a few words of the item name, e.g. 'jasmine rice 20kg'.").
6. **Code** node (answer shaping):
   ```javascript
   const raw = ($input.first().json.output || $input.first().json.text || "").trim();
   let out;
   try { out = JSON.parse(raw.replace(/^```(?:json)?\s*|\s*```$/g, "").trim()); }
   catch (e) { out = { answer: raw, table: null }; }
   return [{ json: { transcript: $('Transcribe').first().json.text, answer: out.answer || raw, table: out.table || null } }];
   ```
7. **Respond to Webhook** - respond with "First incoming item" (JSON). The portal expects `transcript`, `answer`, `table`.

Tip: pin the webhook's data after one real recording so you can build the remaining nodes without speaking each time.

## 4. Cloud (Cloud Run)
- Set the same environment variables on the portal service: CRM_API_KEY, N8N_VOICE_URL, N8N_VOICE_SECRET (use Secret Manager for the two secrets).
- The existing Dockerfile starts `portal:app`. To get the voice button, the start command must be `portal_voice:app`
  (change the last line of the Dockerfile, or set the Cloud Run container command). The files in this folder are already
  included in the image (.dockerignore only excludes secrets, databases and the old dashboard).
- n8n must be reachable from the portal over HTTPS, and the portal must be reachable from n8n (for the tools).
- Voice only works on https:// pages, which Cloud Run provides.

## 5. Who can ask what
- Every portal user signed in can use voice. To make a portal user a salesman (answers limited to his own customers, orders,
  visits), add `"salesman_id": 5` to that user's record in the users file. Managers have none and see everything.
- /voice/ask rejects the API key (it needs a real signed-in user), limits recordings to about 3 MB, and limits questions per minute.
- The tools only read the database copy; nothing in this feature can write to your data.

## Limits to know
- Answers are only as fresh as the database copy the portal loads (see "Data up to" on the portal).
- Expect 3 to 6 seconds per question (upload, transcription, the agent calling tools, reply).
- The "Read aloud" option uses the browser's own voice; for a nicer voice, return an audio URL from n8n later.

## Using your own photo for the assistant
The assistant is drawn as an illustrated portrait. To use a photo instead, save a square-ish headshot in this folder
(next to portal.py) as `voice_avatar.png`, `voice_avatar.jpg` or `voice_avatar.webp`, then refresh the portal (Ctrl+F5).
It is shown as a round picture in the menu with the same listening, thinking and speaking rings.
Use a picture you have the right to use: a licensed stock photo, a photo of a colleague who agreed, or an AI-generated
face of a fictional person. Do not use a photo of a real person without their permission. Delete the file to return to the drawing.
