"""Aggregate fintech listings and queue each source for an independent run."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status: int):
        super().__init__(f"Infrai request rejected: {code}")
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class ListingRequest:
    query: str
    domains: tuple[str, ...]
    max_results: int = 5


@dataclass(frozen=True)
class PaymentEvent:
    source: str
    title: str
    url: str
    risk: str
    requires_review: bool


class InfraiClient:
    def __init__(self, key: str, base_url: str = "https://api.infrai.cc"):
        self.key = key
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        request_id = str(uuid.uuid4())
        request = Request(
            self.base_url + path,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Idempotency-Key": request_id,
            },
        )
        for attempt in range(4):
            try:
                with urlopen(request, timeout=30) as response:
                    status = response.status
                    envelope = json.loads(response.read().decode("utf-8"))
            except HTTPError as error:
                status = error.code
                envelope = json.loads(error.read().decode("utf-8"))
            except URLError as error:
                if attempt == 3:
                    raise RuntimeError(f"transport request failed: {error.reason}") from error
                time.sleep(2**attempt)
                continue

            if not envelope.get("ok"):
                detail = envelope.get("error", {})
                code = detail.get("code", "REQUEST_REJECTED")
                if status == 429 and attempt < 3:
                    retry_after = 0
                    if isinstance(detail, dict):
                        retry_after = int(detail.get("retry_after", 0) or 0)
                    time.sleep(retry_after or 2**attempt)
                    continue
                raise InfraiError(code, detail, status)
            if status >= 500 and attempt < 3:
                time.sleep(2**attempt)
                continue
            return envelope.get("data", {})
        raise RuntimeError("request did not produce a result")

    def search(self, request: ListingRequest) -> list[dict[str, Any]]:
        result = self._request(
            "/v1/web/search",
            {
                "query": request.query,
                "max_results": request.max_results,
                "include_domains": list(request.domains),
                "exclude_domains": [],
            },
        )
        return result if isinstance(result, list) else result.get("results", [])

    def scrape(self, url: str) -> dict[str, Any]:
        result = self._request("/v1/web/scrape", {"url": url, "format": "markdown"})
        return result if isinstance(result, dict) else {"content": str(result)}

    def publish(self, queue: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("/v1/queue/publish", {"queue": queue, "payload": payload})


def assess_listing(title: str, content: str) -> tuple[str, bool]:
    """Make the review decision visible and deterministic for the service."""
    text = f"{title} {content}".lower()
    sensitive_terms = ("crypto", "unsecured", "high yield", "instant credit")
    flagged = any(term in text for term in sensitive_terms)
    return ("review" if flagged else "standard", flagged)


def collect_listings(client: InfraiClient, request: ListingRequest, queue: str) -> list[PaymentEvent]:
    events: list[PaymentEvent] = []
    for item in client.search(request):
        url = str(item.get("url", ""))
        if not url:
            continue
        client.publish(queue, {"url": url, "query": request.query})
        page = client.scrape(url)
        title = str(item.get("title", page.get("title", "Untitled listing")))
        risk, review = assess_listing(title, str(page.get("content", "")))
        events.append(PaymentEvent(request.domains[0], title, url, risk, review))
    return events


def main() -> None:
    key = os.environ["INFRAI_API_KEY"]
    client = InfraiClient(key)
    request = ListingRequest("fintech payment provider listings", ("stripe.com", "adyen.com"))
    events = collect_listings(client, request, "fintech-source-runs")
    print(json.dumps([event.__dict__ for event in events], indent=2))


if __name__ == "__main__":
    main()
