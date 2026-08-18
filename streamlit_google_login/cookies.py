"""
Cookie read/write, validated against real Streamlit Community Cloud
infrastructure (see markmi-ai-webapps/streamlit-cookie-repro).

Two things came out of that investigation:

- Writing via CookieManager.set() works fine, everywhere, including
  Community Cloud.
- Reading via st.context.cookies does NOT work reliably there: Community
  Cloud's proxy drops cookies your app set before they reach your
  backend's HTTP request, even though the browser genuinely has them.
  Read via CookieManager.get_all() instead -- it asks the browser
  directly via document.cookie, never touching that proxy.
- get_all() can still legitimately return {} on its first call(s) in a
  fresh session, before its async component channel has reported back.
  That's not "the cookie is missing", it's "hasn't answered yet" --
  retry a bounded number of times via st.rerun() rather than concluding
  absence from one fast attempt.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from extra_streamlit_components import CookieManager

_MAX_RETRIES = 20
_RETRY_DELAY_SECONDS = 0.2


def _cookie_manager() -> CookieManager:
    import extra_streamlit_components as stx

    return stx.CookieManager()


def write_cookie(name: str, value: str, *, secure: bool) -> None:
    _cookie_manager().set(
        name,
        value,
        key=f"_sgl_set_{name}",
        max_age=600,  # seconds
        same_site="lax",
        secure=secure,
    )


def read_cookies_with_retry(wait_for_key: str) -> dict[str, str]:
    """Returns the full browser cookie dict, retrying via st.rerun() up
    to _MAX_RETRIES times until wait_for_key shows up in it, rather
    than stopping on an incomplete-but-nonempty dict.
    """
    attempts_key = f"_sgl_read_attempts_{wait_for_key}"
    st.session_state.setdefault(attempts_key, 0)

    cookies = _cookie_manager().get_all(key=f"_sgl_get_all_{wait_for_key}") or {}

    if wait_for_key not in cookies and st.session_state[attempts_key] < _MAX_RETRIES:
        st.session_state[attempts_key] += 1
        time.sleep(_RETRY_DELAY_SECONDS)
        st.rerun()

    return cookies
