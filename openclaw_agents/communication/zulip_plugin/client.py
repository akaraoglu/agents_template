"""Fresh stdlib Zulip API helpers for the foundation runtime."""

from __future__ import annotations

import configparser
import json
import re
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


@dataclass(frozen=True, slots=True)
class ZulipCredentials:
    site: str
    email: str
    api_key: str


def _parse_credentials_block(block: str) -> ZulipCredentials:
    parser = configparser.ConfigParser()
    parser.read_string("[api]\n" + block.strip() + "\n")
    section = parser["api"]
    required = ("site", "email", "key")
    missing = [field for field in required if not section.get(field)]
    if missing:
        raise ValueError(f"credential block is missing fields: {', '.join(missing)}")
    return ZulipCredentials(
        site=section["site"].rstrip("/"),
        email=section["email"],
        api_key=section["key"],
    )


def load_credentials_bundle(path: str | Path) -> dict[str, ZulipCredentials]:
    """Load the local multi-account credential bundle keyed by email."""

    payload = Path(path).read_text(encoding="utf-8")
    blocks = [block.strip() for block in re.split(r"(?m)^\[api\]\s*$", payload) if block.strip()]
    credentials: dict[str, ZulipCredentials] = {}
    for block in blocks:
        record = _parse_credentials_block(block)
        credentials[record.email] = record
    return credentials


class ZulipApiClient:
    """Minimal Zulip client for the foundation bridge."""

    def __init__(self, credentials: ZulipCredentials, *, verify_tls: bool = True) -> None:
        self.credentials = credentials
        self.site = credentials.site.rstrip("/")
        import base64

        token = base64.b64encode(f"{credentials.email}:{credentials.api_key}".encode("utf-8")).decode("ascii")
        self.auth_header = f"Basic {token}"
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
            encoded: dict[str, Any] = {}
            for key, value in form.items():
                if isinstance(value, (dict, list)):
                    encoded[key] = json.dumps(value)
                else:
                    encoded[key] = value
            data = urllib.parse.urlencode(encoded, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
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

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/users/me")

    def register_queue(self, *, event_types: list[str] | None = None) -> dict[str, Any]:
        return self._request("POST", "/api/v1/register", form={"event_types": event_types or ["message"]})

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

    def send_private_message(self, recipients: list[str], content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/messages",
            form={"type": "private", "to": recipients, "content": content},
        )

    def send_stream_message(self, stream_name: str, topic_name: str, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/messages",
            form={"type": "stream", "to": stream_name, "topic": topic_name, "content": content},
        )

    def edit_message(self, message_id: int | str, content: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/v1/messages/{message_id}",
            form={"content": content},
        )

    def add_reaction(self, message_id: int | str, emoji_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/messages/{message_id}/reactions",
            form={"emoji_name": emoji_name},
        )

    def remove_reaction(self, message_id: int | str, emoji_name: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/v1/messages/{message_id}/reactions",
            params={"emoji_name": emoji_name},
        )

    def ensure_subscriptions(self, stream_names: list[str]) -> dict[str, Any]:
        subscriptions = [{"name": name} for name in stream_names]
        return self._request(
            "POST",
            "/api/v1/users/me/subscriptions",
            form={"subscriptions": subscriptions},
        )
