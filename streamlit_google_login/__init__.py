"""
Drop-in Google OAuth login for internal Streamlit data apps.

    from streamlit_google_login import require_login, logout

    email, credentials = require_login(
        scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        allowed_domain="markmi.ai",
    )
    st.button("Log out", on_click=logout)

Reads client_id/client_secret/redirect_uri from st.secrets["auth"] by
default (same [auth] convention Streamlit's own st.login() uses), or
pass them explicitly. There is no dev-mode fallback: calling this means
you want a real login, and a missing/incomplete config raises rather
than silently skipping authentication. An app that wants a no-login dev
path should check its own config before calling require_login(), not
rely on this library to guess that for it.

CSRF state is bound to the browser via a real cookie (see cookies.py),
not just a signed/timestamped token -- so a forwarded, not-yet-used
callback URL can't be used by someone else to log in as whoever
generated it. That binding was previously believed impossible on
Streamlit Community Cloud; it isn't -- see
markmi-ai-webapps/streamlit-cookie-repro for the validation.
"""
import os

import requests
import streamlit as st

from .cookies import read_cookies_with_retry, write_cookie

DEFAULT_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
_STATE_COOKIE_NAME = "sgl_oauth_state"
_STATE_COOKIE_MAX_AGE = 600
_SESSION_PREFIX = "_sgl_"


def logout():
    for key in list(st.session_state.keys()):
        if key.startswith(_SESSION_PREFIX):
            st.session_state.pop(key, None)


def _resolve_config(client_id, client_secret, redirect_uri):
    # st.secrets.get() raises StreamlitSecretNotFoundError -- not just a
    # missing key -- when no secrets.toml exists at all.
    try:
        auth = st.secrets.get("auth", {})
    except Exception:
        auth = {}
    client_id = client_id or auth.get("client_id")
    client_secret = client_secret or auth.get("client_secret")
    redirect_uri = redirect_uri or auth.get("redirect_uri")

    missing = [
        name
        for name, value in [("client_id", client_id), ("client_secret", client_secret), ("redirect_uri", redirect_uri)]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "streamlit_google_login.require_login(): missing OAuth config: "
            + ", ".join(missing)
            + ". Set st.secrets['auth'][...] or pass them as kwargs. There is no "
            "dev-mode fallback here -- an app that wants one should check its own "
            "config before calling require_login(), not rely on this raising."
        )
    return client_id, client_secret, redirect_uri


def _build_flow(client_id, client_secret, redirect_uri, scopes, state=None):
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    # PKCE is skipped: it's meant for public clients that can't hold a
    # secret, and its code_verifier can't survive a hard cross-site
    # redirect to Google and back anyway.
    return Flow.from_client_config(
        client_config,
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def require_login(
    scopes=None,
    *,
    allowed_domain=None,
    client_id=None,
    client_secret=None,
    redirect_uri=None,
    prompt="select_account",
    login_prompt="Please log in with your Google account to continue.",
):
    """Returns (email, credentials)."""
    scopes = scopes or DEFAULT_SCOPES
    client_id, client_secret, redirect_uri = _resolve_config(client_id, client_secret, redirect_uri)

    if redirect_uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

    if f"{_SESSION_PREFIX}credentials" in st.session_state:
        return st.session_state[f"{_SESSION_PREFIX}email"], st.session_state[f"{_SESSION_PREFIX}credentials"]

    params = st.query_params
    if "error" in params:
        error = params.get("error")
        st.query_params.clear()
        st.error(f"Google sign-in was not completed ({error}). Please try logging in again.")
        st.stop()

    if "code" in params:
        cookies = read_cookies_with_retry(retry_key="oauth_state", wait_for_key=_STATE_COOKIE_NAME)
        expected_state = cookies.get(_STATE_COOKIE_NAME)

        if not expected_state or params.get("state") != expected_state:
            st.query_params.clear()
            st.error("Login request expired or was tampered with. Please try logging in again.")
            st.stop()

        try:
            flow = _build_flow(client_id, client_secret, redirect_uri, scopes, state=params.get("state"))
            flow.fetch_token(code=params["code"])
            creds = flow.credentials
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=10,
            )
            resp.raise_for_status()
            email = resp.json().get("email", "")
        except Exception:
            st.query_params.clear()
            st.error("Login failed or the login link expired. Please try logging in again.")
            st.stop()

        st.query_params.clear()
        if allowed_domain and not email.lower().endswith(f"@{allowed_domain.lower()}"):
            st.error(f"Access is restricted to @{allowed_domain} accounts. You're logged in as {email}.")
            st.stop()

        st.session_state[f"{_SESSION_PREFIX}credentials"] = creds
        st.session_state[f"{_SESSION_PREFIX}email"] = email
        st.rerun()

    st.write(login_prompt)
    if f"{_SESSION_PREFIX}pending_auth_url" not in st.session_state:
        # Generated once per session, guarded by session_state: the
        # write below reports back through the component's value
        # channel, which triggers a rerun -- redoing this every rerun
        # would regenerate a new state/cookie each time and loop. Note
        # this cookie name is fixed, so two concurrent login attempts in
        # the same browser (two tabs) will race and one will fail with
        # "expired or tampered with" -- an inconvenience, not a security
        # issue (it fails closed), and out of scope for this library.
        flow = _build_flow(client_id, client_secret, redirect_uri, scopes)
        auth_url, state = flow.authorization_url(include_granted_scopes="true", prompt=prompt)
        write_cookie(
            _STATE_COOKIE_NAME,
            state,
            max_age=_STATE_COOKIE_MAX_AGE,
            secure=redirect_uri.startswith("https://"),
        )
        st.session_state[f"{_SESSION_PREFIX}pending_auth_url"] = auth_url
    st.link_button("Log in with Google", st.session_state[f"{_SESSION_PREFIX}pending_auth_url"])
    st.stop()
