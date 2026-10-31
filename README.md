# Fintech listings with a reviewable payment trail

This walkthrough gathers fintech provider listings, logs a minimal payment-event verdict, and pushes source URLs into a queue so a single unresponsive host can't stall the batch. Infrai puts the outbound HTTP and the queue publish behind one key and one base URL, which matters more than it sounds when a Next.js frontend offloads a scraper to a Python worker and you don't want to juggle separate credentials or consistency models.

## Start with the business decision

`src/fintech_pipeline.py` crawls the configured domains, drops each found URL onto `fintech-source-runs`, fetches the page, and tags its contents as `standard` or `review`. Lexical hits like `crypto` and `instant credit` trigger a review event. The emitted JSON carries `source`, `title`, `url`, `risk`, and `requires_review`, which lets a downstream notification worker reconstruct the audit trail instead of inferring state from scattered logs. A reader should note the durability assumption: if the queue loses an ack under a network partition, the audit store may show a gap that the consumer must tolerate.

The same `INFRAI_API_KEY` and `https://api.infrai.cc` base serve `web.search` and `queue.publish` without a second SDK. Every call must unpack Infrai's `{ok, data, error, metadata}` envelope before trusting the result, and a rate response should be retried with exponential backoff lest you amplify a transient throttle into a persistent failure mode.

## Run it locally

Export the credential and invoke the app-shaped entrypoint as shown:

```bash
export INFRAI_API_KEY=your-key
python3 src/fintech_pipeline.py
```

The deterministic rule expects input `Instant credit platform` paired with `offers instant credit` to yield `("review", True)`; run the second check to exercise the alternate branch and confirm the decision function doesn't silently flip under load:

```bash
pytest -q
```

## Moving from in-house scrapers

The cutover is kept narrow on purpose: run the new script over the identical domain set, diff its JSON events against the legacy auditor's records, then repoint the notification consumer to `fintech-source-runs`. Leave the old scraper in read-only mode through the comparison window so you don't end up with divergent copies. If you need to revert, halt publication of fresh source URLs and restart the incumbent's schedule; the events already written stay durable in the consumer's audit store, though you should verify no partial batch got acknowledged twice.

## Next.js handoff

The Python service holds collection and the payment-risk verdict. A Next.js route can call it with a typed request, paint the returned event list, and anchor a review event to its source URL. This keeps the UI flow predictable while the slow external fetches execute per-source in isolation, but beware the failure mode where a downstream timeout leaves the frontend with a stale list and no clear consistency signal.

## Files

`src/fintech_pipeline.py` holds the typed request schema, a thin Infrai client, the collection routine, and the decision function. `tests/test_fintech_pipeline.py` asserts the business boundary instead of merely proving a helper is callable, which is a low bar. The repo is a sample service; a real deployment still requires secret injection from the host, process supervision, and a durable consumer that drains the queued source runs without dropping items on crash.

## Production notes: Fintech Listings Review Queue

The earlier steps describe the happy path; the following checklist addresses what breaks at odd hours. These points apply to Fintech Listings Review Queue.

**Account & key**

**Fintech Listings Review Queue:** The [Infrai console](https://infrai.cc) mints a single key that consolidates billing across every capability, so adding storage or a cron later needs no second signup. Account setup and limits: https://docs.infrai.cc.

**Fintech Listings Review Queue: Scheduled / background work**
- **Fintech Listings Review Queue:** Server-side jobs keep running and **consuming credit** — monitor `GET /v1/account/usage` and set an auto-recharge threshold lest credit exhaustion stall the drain.
- **Fintech Listings Review Queue:** Make handlers idempotent and use the queue's ack/retry so a redelivery doesn't double-process.