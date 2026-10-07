"""The Kylas HTTP client, ported from the loyalty app (app/integrations/kylas/client.py).

THE KEY. It comes from settings.kylas_api_key (.env only), goes out as the `api-key` header and
nowhere else: never logged, never in an error message, never stored, never sent to a browser.
repr() of the client hides it. No key means "not configured": nothing is sent.

HOW A CREATE ENDS decides what happens next (the loyalty app's four outcomes):

  CREATED    2xx with a lead id. Done.
  RETRYABLE  certainly did NOT create a lead: never connected, or 429. Send again later.
  PERMANENT  4xx: Kylas read the request and refused it. Sending it again cannot succeed.
  UNKNOWN    it may have landed: a read timeout, a dropped response, a 2xx without an id, or a
             5xx (EESPL rule: on a 5xx we search before sending again, unlike the loyalty app,
             which re-sent). Never re-sent blindly; app.crm.kylas_push searches by phone first.

Reads (searches, GETs) only ever return "answered" or "no answer"; they never raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

from app.config import settings

SEARCH_PAGE_SIZE = 100
_ERROR_BODY_LIMIT = 300

#: what the deal search asks for; the authoritative read is always GET /deals/{id}
DEAL_SEARCH_FIELDS = ["id", "pipeline", "pipelineStage", "updatedAt", "convertedLeads"]
#: what the timeout-recovery search asks for
LEAD_SEARCH_FIELDS = ["id", "phoneNumbers", "customFieldValues", "ownerId", "createdAt"]


class Outcome(str, Enum):
    CREATED = "created"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class CreateResult:
    outcome: Outcome
    lead_id: int | None = None
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class SearchResult:
    """ok=False: the search did not answer and proves nothing. last_page is True only when
    Kylas says so, or the page came back short: "not found" is never concluded from a
    truncated list (that is how a second lead would get created)."""

    ok: bool
    items: tuple = ()
    last_page: bool = False
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class GetResult:
    """ok=False: no answer. ok=True with body=None: Kylas says it does not exist (404)."""

    ok: bool
    body: Any = None
    status_code: int | None = None
    error: str | None = None


@dataclass
class KylasClient:
    api_key: str | None = None
    base_url: str = ""
    timeout: float = 20
    transport: httpx.BaseTransport | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None and settings.kylas_api_key is not None:
            self.api_key = settings.kylas_api_key.get_secret_value()
        self.base_url = (self.base_url or settings.kylas_base_url).rstrip("/")
        self.timeout = self.timeout or settings.kylas_timeout_seconds

    def __repr__(self) -> str:  # the key must never reach a log through repr()
        return f"<KylasClient {self.base_url} configured={self.is_configured}>"

    __str__ = __repr__

    def _short(self, response: httpx.Response) -> str:
        """A response body for an error message, with the key scrubbed should Kylas echo it."""
        text = _short(response)
        if self.api_key and self.api_key.strip():
            text = text.replace(self.api_key, "***")
        return text

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _http(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport)

    def _headers(self, body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "api-key": self.api_key or ""}
        if body:
            headers["Content-Type"] = "application/json"
        return headers

    # --- create -----------------------------------------------------------------------------

    def create_lead(self, payload: dict) -> CreateResult:
        if not self.is_configured:
            return CreateResult(Outcome.NOT_CONFIGURED, error="Kylas API key is not set")
        try:
            with self._http() as http:
                response = http.post("/leads", json=payload, headers=self._headers(body=True))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            return CreateResult(Outcome.RETRYABLE, error=f"connect failed: {type(exc).__name__}")
        except httpx.TransportError as exc:
            return CreateResult(Outcome.UNKNOWN, error=f"no response: {type(exc).__name__}")
        status = response.status_code
        if 200 <= status < 300:
            lead_id = _int(_json(response).get("id") if isinstance(_json(response), dict) else None)
            if lead_id is None:
                return CreateResult(
                    Outcome.UNKNOWN, status_code=status, error="2xx without a lead id"
                )
            return CreateResult(Outcome.CREATED, lead_id=lead_id, status_code=status)
        detail = f"HTTP {status}: {self._short(response)}"
        if status == 429:
            return CreateResult(Outcome.RETRYABLE, status_code=status, error=detail)
        if status >= 500:
            return CreateResult(Outcome.UNKNOWN, status_code=status, error=detail)
        return CreateResult(Outcome.PERMANENT, status_code=status, error=detail)

    # --- reads ------------------------------------------------------------------------------

    def _search(self, path: str, body: dict, page: int, size: int) -> SearchResult:
        if not self.is_configured:
            return SearchResult(ok=False, error="Kylas API key is not set")
        try:
            with self._http() as http:
                response = http.post(
                    path,
                    params={"sort": "updatedAt,desc", "page": page, "size": size},
                    json=body,
                    headers=self._headers(body=True),
                )
        except httpx.TransportError as exc:
            return SearchResult(ok=False, error=f"search failed: {type(exc).__name__}")
        status = response.status_code
        if not 200 <= status < 300:
            return SearchResult(
                ok=False, status_code=status, error=f"search HTTP {status}: {self._short(response)}"
            )
        data = _json(response)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list):
            return SearchResult(ok=False, status_code=status, error="search: no content list")
        if isinstance(data.get("last"), bool):
            last = data["last"]
        elif isinstance(data.get("totalPages"), int):
            last = page >= data["totalPages"] - 1
        else:
            last = len(content) < size
        return SearchResult(ok=True, items=tuple(content), last_page=last, status_code=status)

    def search_lead_by_phone(self, phone: str, page: int = 0, size: int = SEARCH_PAGE_SIZE):
        """POST /search/lead, multi-field match on the phone (loyalty: _search_body)."""
        return self._search(
            "/search/lead", {"fields": LEAD_SEARCH_FIELDS, "jsonRule": _rule(phone)}, page, size
        )

    def search_deals(self, page: int = 0, size: int = SEARCH_PAGE_SIZE) -> SearchResult:
        """POST /search/deal, most recently updated first (loyalty: search_deals)."""
        return self._search(
            "/search/deal", {"fields": DEAL_SEARCH_FIELDS, "jsonRule": _rule("")}, page, size
        )

    def get(self, path: str) -> GetResult:
        """A GET (lead, deal or a setup list). Never raises."""
        if not self.is_configured:
            return GetResult(ok=False, error="Kylas API key is not set")
        try:
            with self._http() as http:
                response = http.get(path, headers=self._headers())
        except httpx.TransportError as exc:
            return GetResult(ok=False, error=f"GET failed: {type(exc).__name__}")
        status = response.status_code
        if status == 404:
            return GetResult(ok=True, status_code=status, body=None)
        if not 200 <= status < 300:
            return GetResult(
                ok=False, status_code=status, error=f"GET HTTP {status}: {self._short(response)}"
            )
        data = _json(response)
        if data is None:
            return GetResult(ok=False, status_code=status, error="GET returned non-JSON")
        return GetResult(ok=True, status_code=status, body=data)

    def get_lead(self, lead_id: int) -> GetResult:
        return self.get(f"/leads/{int(lead_id)}")

    def get_deal(self, deal_id: int) -> GetResult:
        return self.get(f"/deals/{int(deal_id)}")


def _rule(value: str) -> dict:
    return {
        "condition": "AND",
        "rules": [
            {
                "id": "multi_field",
                "field": "multi_field",
                "type": "multi_field",
                "input": "multi_field",
                "operator": "multi_field",
                "value": value,
            }
        ],
        "valid": True,
    }


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _short(response: httpx.Response) -> str:
    return (response.text or "").strip().replace("\n", " ")[:_ERROR_BODY_LIMIT]


def client() -> KylasClient:
    """The client every sender uses; a seam so tests can hand in a stub transport."""
    return KylasClient()
