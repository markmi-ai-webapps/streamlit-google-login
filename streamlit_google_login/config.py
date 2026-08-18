"""OAuth config resolution: kwargs, falling back to st.secrets["auth"]."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

_LOCALHOST_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Config:
    client_id: str
    client_secret: str
    redirect_uri: str

    @property
    def secure(self) -> bool:
        return self.redirect_uri.startswith("https://")

    @property
    def is_local_http(self) -> bool:
        parsed = urlparse(self.redirect_uri)
        return parsed.scheme == "http" and parsed.hostname in _LOCALHOST_HOSTS

    @classmethod
    def resolve(cls, client_id: str | None, client_secret: str | None, redirect_uri: str | None) -> Config:
        # st.secrets.get() raises StreamlitSecretNotFoundError -- not just a
        # missing key -- when no secrets.toml exists at all.
        try:
            auth = st.secrets.get("auth", {})
        except StreamlitSecretNotFoundError:
            auth = {}

        client_id = client_id or auth.get("client_id")
        client_secret = client_secret or auth.get("client_secret")
        redirect_uri = redirect_uri or auth.get("redirect_uri")

        missing_field_names = [
            name
            for name, value in [("client_id", client_id), ("client_secret", client_secret), ("redirect_uri", redirect_uri)]
            if not value
        ]
        if missing_field_names:
            raise RuntimeError(
                "streamlit_google_login.require_login(): missing OAuth config: "
                + ", ".join(missing_field_names)
                + ". Set st.secrets['auth'][...] or pass them as kwargs. There is no "
                "dev-mode fallback here -- an app that wants one should check its own "
                "config before calling require_login(), not rely on this raising."
            )
        return cls(client_id, client_secret, redirect_uri)
