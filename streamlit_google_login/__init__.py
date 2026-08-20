"""
Drop-in Google OAuth login for internal Streamlit data apps.

    from streamlit_google_login import require_login, logout

    email, credentials = require_login(scopes=[], allowed_domain="example.com")
    st.button("Log out", on_click=logout)

scopes are additional scopes beyond identity; openid/userinfo.email are
always requested too (see _BASE_SCOPES).

Config comes from st.secrets["auth"] or kwargs -- no dev-mode fallback,
missing/incomplete config raises.

CSRF state and the PKCE code_verifier are both bound to the browser via
real cookies (see cookies.py), not just signed tokens, so a forwarded
callback URL can't be replayed by someone else. PKCE is used even
though this is a confidential client, per RFC 9700 guidance.
"""
from __future__ import annotations

from .flow import logout, require_login

__all__ = ["logout", "require_login"]
