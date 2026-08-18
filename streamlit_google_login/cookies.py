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
import time

import streamlit as st

_MAX_RETRIES = 8
_RETRY_DELAY_SECONDS = 0.2


def _cookie_manager():
    import extra_streamlit_components as stx

    return stx.CookieManager()


def write_cookie(name, value, *, max_age, secure):
    _cookie_manager().set(
        name,
        value,
        key=f"_sgl_set_{name}",
        max_age=max_age,
        same_site="lax",
        secure=secure,
    )


def read_cookies_with_retry(*, retry_key, wait_for_key=None):
    """Returns the full browser cookie dict. May call st.rerun() up to
    _MAX_RETRIES times if the component hasn't reported back yet.

    An empty {} unambiguously means "hasn't reported yet". A non-empty
    dict is ambiguous if you're waiting on one specific cookie among
    others that may already be present -- pass wait_for_key so the
    retry keeps going until that specific key shows up (or retries run
    out), instead of stopping early on an incomplete-but-nonempty dict.
    """
    attempts_key = f"_sgl_read_attempts_{retry_key}"
    st.session_state.setdefault(attempts_key, 0)

    cookies = _cookie_manager().get_all(key=f"_sgl_get_all_{retry_key}")
    resolved = (wait_for_key in cookies) if wait_for_key is not None else bool(cookies)

    if not resolved and st.session_state[attempts_key] < _MAX_RETRIES:
        st.session_state[attempts_key] += 1
        time.sleep(_RETRY_DELAY_SECONDS)
        st.rerun()

    return cookies or {}
