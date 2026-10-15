# Email Automation

Generate → review → **manually approve & send** → track replies → AI
classifies them → follow-ups → dashboard. **Nothing is ever sent
automatically**: the only sending path is `POST /api/emails/{id}/send`
with `confirm: true` and the exact recipient, subject and body the person
approved. Background work (reply checks, due follow-ups) only *reads* mail
and *creates drafts*.

## Gmail / OAuth setup

1. **Google Cloud Console** → create (or pick) a project → *APIs & Services*
   → *Library* → enable **Gmail API**.
2. *OAuth consent screen*:
   - **Internal** if the NGO uses Google Workspace (recommended: no
     verification, tokens don't expire).
   - Otherwise **External**, and add the NGO's Gmail address as a
     **test user**. In *Testing* mode Google expires refresh tokens after
     **7 days**, so you'll need to reconnect weekly unless the app is
     published and verified. `gmail.readonly` is a restricted scope;
     publishing for outside users requires Google's verification.
   - Scopes: `gmail.send`, `gmail.readonly`, `openid`, `email`.
3. *Credentials* → *Create credentials* → **OAuth client ID** → type
   **Web application**. Authorized redirect URI must match
   `GMAIL_REDIRECT_URI` exactly:
   - local: `http://localhost:8000/api/email/oauth/gmail/callback`
   - deployed: `https://<your-backend>.onrender.com/api/email/oauth/gmail/callback`
4. Backend `.env` (and Render env vars):

   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GMAIL_REDIRECT_URI=http://localhost:8000/api/email/oauth/gmail/callback
   FRONTEND_URL=http://localhost:5173
   TOKEN_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   APP_ACCESS_TOKEN=<long random string - strongly recommended when deployed>
   EMAIL_SYNC_MINUTES=10
   MAX_EMAILS_PER_HOUR=30
   ```
5. `pip install -r requirements.txt` (adds `cryptography`), restart the
   backend, open **Settings → Connect Gmail**, sign in, allow both
   permissions. If `APP_ACCESS_TOKEN` is set, enter it in Settings first.

**Token security:** refresh/access tokens are stored Fernet-encrypted
(`TOKEN_ENCRYPTION_KEY`, server env only) and never returned by any API.
The OAuth `state` is HMAC-signed and expires in 10 minutes. Changing the
key invalidates stored tokens (reconnect). Disconnect revokes the grant at
Google.

## APIs

| Endpoint | Purpose |
|---|---|
| `GET /api/email/account` | Provider config, connected mailbox, capabilities |
| `POST /api/email/oauth/{provider}/start` 🔒 | Returns Google authorization URL |
| `GET /api/email/oauth/{provider}/callback` | Google redirect target (signed state) |
| `DELETE /api/email/account` 🔒 | Disconnect + revoke |
| `POST /api/email/sync` 🔒 | Check replies + draft due follow-ups (never sends) |
| `GET/PATCH /api/email/settings` | Sender name, signature, follow-up intervals |
| `GET /api/email/templates`, `PATCH /templates/{id}`, `POST /templates/reset` | Default templates |
| `GET /api/email/meta` | Status / classification / type labels |
| `GET /api/emails`, `GET/PATCH/DELETE /api/emails/{id}` | List, view, edit draft, delete draft |
| `POST /api/emails/generate` | AI (Gemini) or template draft; with `thread_id` = in-thread follow-up |
| `POST /api/emails` | Manual draft |
| `POST /api/emails/{id}/duplicate` | Copy as a new conversation |
| `POST /api/emails/{id}/send` 🔒 | **The only send**: `confirm` + approved content (+ optional follow-up days) |
| `POST /api/emails/{id}/classification`, `/reclassify` | Manual override / re-run AI |
| `GET /api/email-threads`, `GET/PATCH /api/email-threads/{id}` | Conversations; set outcome status |
| `POST /api/email-threads/{id}/followup-draft` | Follow-up draft now |
| `GET/POST /api/followups`, `PATCH /api/followups/{id}`, `POST /api/followups/generate-due` | Schedule (3/7/14/30 days or date), cancel, draft due |
| `GET/POST /api/meetings`, `PATCH/DELETE /api/meetings/{id}` | Meetings |
| `GET /api/dashboard` | Existing fields + `outreach` metrics, `pipeline`, `email_followups` |

🔒 = requires `X-App-Access-Token` when `APP_ACCESS_TOKEN` is set.

## Database (all new tables; existing ones gain nothing)

`email_accounts`, `email_settings`, `email_templates`, `email_threads`,
`emails`, `email_events`, `reply_classifications`, `followups`,
`meetings`. Statuses are strings (no PostgreSQL enum migrations).
Timeline entries use the existing `activity_logs` (with `contact_id`), so
company and contact timelines show generated / draft saved / sent / reply
received / meeting scheduled / proposal sent / status updated.

## Tracking

- Email: Draft, Sent, Failed (send error or bounce). Conversation:
  No Reply, Replied, Positive/Neutral/Negative, Needs Follow-up, Meeting
  Requested/Scheduled, Proposal Requested/Sent, Partnership Confirmed,
  Closed. Outcomes move the company's lead status **forward only**; a
  negative reply never auto-marks a company Not Interested.
- Replies are classified by Gemini (classification, confidence,
  reasoning, meeting/proposal intent) or, without `GEMINI_API_KEY`, by
  keyword rules labelled as such. Staff can override; history is kept.
- Safeguards: recipients must be the company's saved contacts; hourly
  send cap; drafts can't be edited after sending.

## Limitations

- **Delivered / Opened / Clicked are not available with Gmail** (no API;
  no tracking pixels are added). Bounces and replies are tracked.
- Reply checks run in-process every `EMAIL_SYNC_MINUTES`; on Render's
  free tier the server sleeps when idle, so use **Check for replies**.
- Not live-tested against real Gmail (no OAuth client available while
  building). Verified with 37 automated tests using a fake provider and a
  full browser click-through on a fake mailbox. Do one real test send to
  your own address after connecting.
- One connected mailbox; Outlook is a new `EmailProvider` class.
- No user login - set `APP_ACCESS_TOKEN` for any public deployment.
