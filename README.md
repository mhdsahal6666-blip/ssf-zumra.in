# zumra-mcp

> **FastAPI + FastMCP backend** for managing **SSF Theyyottuchira Unit — Zumra (സുംറ)** Thursday night family gathering bookings, backed by **Firebase Firestore**.

---

## Project Structure

```
zumra back/
├── main.py               # FastAPI app + FastMCP server & tools
├── firebase_service.py   # Firestore read/write operations
├── requirements.txt      # Python dependencies
├── Dockerfile            # Multi-stage production image
└── .env.example          # Environment variable template
```

---

## MCP Tools Exposed

| Tool | Description |
|---|---|
| `get_this_week_zumra` | Returns the **live** slot (or next booked Thursday) with host details for **SSF Theyyottuchira Unit** |
| `list_zumra_slots` | Dynamically returns Thursdays for any given `year` (2026, 2027, 2028, 2029...) defaulting to `datetime.now().year`, with optional `month` and `only_available` filters |
| `book_zumra_thursday` | Books any available Thursday (auto-creates slot in Firestore on-the-fly for any future year like 2028+). No `ward` field. |
| `replace_zumra_host` | Direct no-UI host replacement/swap & slot repair without PIN prompt |
| `cancel_zumra_booking` | Resets a booked slot back to `available` without PIN prompt |

MCP endpoint (Streamable HTTP): **`POST /mcp`**  
Health check: **`GET /health`**

---

## Firestore Collection: `thursday_slots`

Each document ID = the Thursday date (`YYYY-MM-DD`):

```json
{
  "date":       "2027-01-07",
  "dateLabel":  "January 7, 2027 • Thursday",
  "month":      "January 2027",
  "year":       2027,
  "status":     "available",
  "headName":   "",
  "houseName":  "",
  "phone":      "",
  "prayerNote": ""
}
```

`status` lifecycle: `available` → `booked` → `live` → `completed`

---

## Local Development

### 1. Install dependencies
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — set FIREBASE_SERVICE_ACCOUNT_JSON or place serviceAccountKey.json here
```

### 3. Run
```bash
python main.py
# Server: http://localhost:8000
# MCP:    http://localhost:8000/mcp
# Health: http://localhost:8000/health
```

---

## Docker

```bash
# Build
docker build -t zumra-mcp .

# Run (inject Firebase credentials via env)
docker run -p 8000:8000 \
  -e FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}' \
  zumra-mcp
```

---

## Deployment

### Koyeb / Render
1. Push to GitHub.
2. Create a new **Web Service** pointing at this repo.
3. Set environment variables in the dashboard:
   - `FIREBASE_SERVICE_ACCOUNT_JSON` — minified JSON string (or `FIREBASE_API_KEY`)
4. The platform injects `PORT` automatically; the server reads it.

### Hugging Face Spaces (Docker SDK)
1. Create a new Space → **Docker** SDK.
2. Push all files. HF Spaces maps port **7860** by default — set `PORT=7860` in Space secrets.

---

## Connecting to Gemini Connectors

Add this MCP server in Gemini / Antigravity connectors:

- **URL**: `https://your-deployment-url/mcp`
- **Transport**: Streamable HTTP

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FIREBASE_PROJECT_ID` | Yes | `muth-18e58` | Firebase Project ID |
| `FIREBASE_API_KEY` | Yes | `AIzaSyAE...` | Direct Web API Key (connects directly without service account) |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Optional | — | Minified Service Account JSON (if using Admin SDK) |
| `FIREBASE_KEY_PATH` | Optional | `serviceAccountKey.json` | Local fallback key file path |
| `PORT` | No | `8000` | Server listen port |
