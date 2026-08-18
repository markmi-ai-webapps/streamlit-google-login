# streamlit-google-login

Drop-in Google OAuth login for internal Streamlit data apps.

```python
import streamlit as st
from streamlit_google_login import require_login, logout

email, credentials = require_login(
    scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/spreadsheets"],
    allowed_domain="markmi.ai",
)

st.write(f"Logged in as {email}")
st.button("Log out", on_click=logout)

# credentials is a google.oauth2.credentials.Credentials for this user --
# use it for any downstream Google API call (Sheets, etc.) under their
# own permissions, never a shared service account.
```

## Config

Reads `client_id` / `client_secret` / `redirect_uri` from `st.secrets["auth"]`
by default (same `[auth]` convention Streamlit's own `st.login()` uses), or
pass them explicitly as kwargs. There's no dev-mode fallback: a missing or
incomplete config raises rather than silently skipping login. An app that
wants a no-login local/dev path should check its own config before calling
`require_login()`, not rely on this library to guess that for it.

```toml
# .streamlit/secrets.toml
[auth]
client_id = "..."
client_secret = "..."
redirect_uri = "https://your-app.streamlit.app/"
```

## Why this exists

Streamlit's own `st.login()` handles identity but doesn't expose the
underlying OAuth credentials for calling other Google APIs on the user's
behalf. Apps that need that (e.g. writing to a Sheet under the logged-in
user's own permissions) have to hand-roll the OAuth flow -- this package is
that flow, done once, so individual apps don't each reinvent it.

CSRF state is bound to the browser via a real cookie, not just a signed
token: a forwarded, not-yet-used callback URL can't be used to log in as
whoever generated it. That's validated to actually work on Streamlit
Community Cloud -- see `markmi-ai-webapps/streamlit-cookie-repro`. The
key finding: read the cookie via `CookieManager.get_all()`, not
`st.context.cookies` (Community Cloud's proxy drops app-set cookies before
they reach your backend), and retry a few times -- `get_all()`'s async
report-back can take close to a second in a fresh session.
