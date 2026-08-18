import streamlit
import pytest


class Stopped(Exception):
    """Raised by the st.stop() mock -- mirrors Streamlit halting the script."""


class Rerun(Exception):
    """Raised by the st.rerun() mock -- mirrors Streamlit restarting the script."""


@pytest.fixture(autouse=True)
def streamlit_mocks(monkeypatch):
    """Replaces the parts of the streamlit module our code touches with
    plain, isolated test doubles. st.session_state/st.query_params only
    ever get dict-style access (get/[]/in/clear/setdefault/pop/keys) in
    this codebase, so plain dicts are sufficient stand-ins. st.stop()
    and st.rerun() raise here instead of no-op'ing (their real behavior
    outside a running app), so tests can assert control flow actually
    halted where the code expects it to.
    """
    monkeypatch.setattr(streamlit, "session_state", {})
    monkeypatch.setattr(streamlit, "query_params", {})
    monkeypatch.setattr(streamlit, "error", lambda *a, **kw: None)
    monkeypatch.setattr(streamlit, "write", lambda *a, **kw: None)
    monkeypatch.setattr(streamlit, "link_button", lambda *a, **kw: None)

    def _stop():
        raise Stopped

    def _rerun():
        raise Rerun

    monkeypatch.setattr(streamlit, "stop", _stop)
    monkeypatch.setattr(streamlit, "rerun", _rerun)
