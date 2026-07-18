# Deploying The Sterling Syndicate on Render

The repo ships a Render Blueprint (`render.yaml`) that provisions PostgreSQL,
the FastAPI API (Docker), and the React SPA as a **static site**.

## What gets created

| Service        | What it is                         | Plan | Sleeps? |
|----------------|------------------------------------|------|---------|
| `sterling-db`  | PostgreSQL 16 (+ pgvector)         | free | n/a (retention limits apply) |
| `sterling-api` | FastAPI backend (Docker)           | free | Yes — ~15 min idle → cold start |
| `sterling-web` | React SPA (**static site**, not nginx Docker) | free | **No** — static sites stay warm |

Live URLs (pinned in `render.yaml` — update if Render renames the services):

- App: `https://sterling-web-6u7n.onrender.com`
- API: `https://sterling-api-6u7n.onrender.com`
- Health: `https://sterling-api-6u7n.onrender.com/health`

The GitHub Actions `keepalive` workflow pings the API every ~12 minutes to reduce
free-tier sleep. If Actions are disabled, expect cold starts on the API.

## One-time: generate the encryption key

Render auto-generates `JWT_SECRET_KEY`, but the Fernet field-encryption key must
be created by you:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Deploy steps

1. **Sign in** at <https://dashboard.render.com> (GitHub login).
2. **New + → Blueprint**. Pick this repo (`sterling-syndicate` or your
   `sterling-syndicate-core-*` clone). Click **Apply**.
3. First build takes ~5–8 min (DB → API Docker → static web).
4. On **sterling-api → Environment**, set:
   - `FIELD_ENCRYPTION_KEY` = Fernet key **(required)**
   - `OPENAI_API_KEY` = optional, for AI drafts
   - `SIGNUP_INVITE_CODE` = optional; if set, signup requires that invite
   - `PAYMENT_STEPUP_TOTP_SECRET` = optional base32 TOTP secret (if set, step-up MFA is **forced on**)
     ```bash
     python -c "import secrets,base64; print(base64.b32encode(secrets.token_bytes(20)).decode())"
     ```
5. Confirm these are already set by the blueprint (edit if your URLs differ):
   - `FRONTEND_URL=https://sterling-web-6u7n.onrender.com`
   - `CORS_ORIGINS=https://sterling-web-6u7n.onrender.com`
   - `TRUST_PROXY=true`
   - `UVICORN_WORKERS=1`
6. On **sterling-web**, confirm `VITE_API_URL=https://sterling-api-6u7n.onrender.com`
   (baked at **build** time — change + redeploy the static site if the API host moves).
7. Open the web URL, sign up, and use the app.

## Auth model (cookie-only)

Login/signup set an **HttpOnly** cookie (`SameSite=None; Secure` in production).
The JWT is **not** returned in the JSON body. The SPA sends
`credentials: "include"` plus `X-Requested-With: XMLHttpRequest` (CSRF guard).

## Not deployed: DinD execution sandbox

`docker-compose.yml` includes rootless Docker-in-Docker for the Execution Agent.
Render has no privileged DinD, so it is excluded. `SANDBOX_ALLOW_SUBPROCESS_FALLBACK`
stays `false`. For sandboxed execution, run `docker compose up` on a VPS you control.

## Custom domain

Dashboard → sterling-web → Custom Domains. Then update API env:
`FRONTEND_URL`, `CORS_ORIGINS` (comma-separated), and rebuild the static site with
the matching `VITE_API_URL` if the API also moves.
