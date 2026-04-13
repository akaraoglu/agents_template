"""Small stdlib Zulip API client for the shared gateway service."""

from __future__ import annotations

import configparser
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ZulipApiError(RuntimeError):
    """Raised when the Zulip API returns an error response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload or {}


@dataclass(slots=True)
class ZulipCredentials:
    site: str
    email: str
    api_key: str


def load_zuliprc(path: str | Path) -> ZulipCredentials:
    """Load a standard Zulip rc file."""
    parser = configparser.ConfigParser()
    path = Path(path)
    with path.open() as handle:
        parser.read_file(handle)
    if "api" not in parser:
        raise ValueError(f"missing [api] section in {path}")
    section = parser["api"]
    required = ("site", "email", "key")
    missing = [field for field in required if not section.get(field)]
    if missing:
        raise ValueError(f"missing fields in {path}: {', '.join(missing)}")
    return ZulipCredentials(
        site=section["site"].rstrip("/"),
        email=section["email"],
        api_key=section["key"],
    )


class ZulipApiClient:
    """Minimal API wrapper for queue registration, event polling, and posting."""

    def __init__(self, credentials: ZulipCredentials, *, verify_tls: bool = True) -> None:
        self.credentials = credentials
        self.site = credentials.site.rstrip("/")
        token = urllib.parse.quote(f"{credentials.email}:{credentials.api_key}", safe="")
        basic = urllib.parse.unquote(token).encode()
        self.auth_header = "Basic " + __import__("base64").b64encode(basic).decode()
        self.ssl_context = ssl.create_default_context()
        if not verify_tls:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.site}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"

        data: bytes | None = None
        headers = {"Authorization": self.auth_header}
        if form is not None:
            encoded_form: dict[str, Any] = {}
            for key, value in form.items():
                if isinstance(value, (dict, list)):
                    encoded_form[key] = json.dumps(value)
                else:
                    encoded_form[key] = value
            data = urllib.parse.urlencode(encoded_form, doseq=True).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"msg": body}
            raise ZulipApiError(
                f"zulip API error for {path}: {payload.get('msg', body)}",
                status_code=exc.code,
                error_code=payload.get("code"),
                payload=payload,
            ) from exc
        except urllib.error.URLError as exc:
            raise ZulipApiError(f"failed to reach Zulip at {url}: {exc}") from exc

        if payload.get("result") != "success":
            raise ZulipApiError(
                f"zulip API failure for {path}: {payload.get('msg', 'unknown error')}",
                error_code=payload.get("code"),
                payload=payload,
            )
        return payload

    def register_message_queue(self, *, event_types: list[str] | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/register",
            form={"event_types": event_types or ["message"]},
        )

    def get_events(
        self,
        queue_id: str,
        last_event_id: int,
        *,
        timeout_seconds: int = 0,
        dont_block: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/events",
            params={
                "queue_id": queue_id,
                "last_event_id": str(last_event_id),
                "dont_block": "true" if dont_block else "false",
                "timeout": str(timeout_seconds),
            },
        )

    def send_stream_message(self, stream_name: str, topic: str, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/messages",
            form={"type": "stream", "to": stream_name, "topic": topic, "content": content},
        )

    def add_subscriptions(self, stream_names: list[str]) -> dict[str, Any]:
        subscriptions = [{"name": name} for name in stream_names]
        return self._request(
            "POST",
            "/api/v1/users/me/subscriptions",
            form={"subscriptions": subscriptions},
        )
