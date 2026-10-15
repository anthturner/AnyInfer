"""The Relay's backpressure vocabulary: status codes, backoff headers, and what they leak.

Before this, `app.py` answered every `RelayError` with 404 — including "mode='forward'
requires provider_settings", which is a 400 — and there was no 429, no `Retry-After`, and
no rate-limit header on any response.

The load-bearing test in this module is `test_a_tenants_headers_are_identical_whether...`.
Emitted numbers are the last place the tenant side channel could reopen: `RelayRegistry`
deliberately returns an identical error for "no such route" and "another tenant's route" so
a prober cannot enumerate tenants, and a `RateLimit-Remaining` computed from process-wide
load would hand that same information back in a header. It gets its own test rather than a
side assertion, because it is the security property.
"""

from __future__ import annotations

import warnings

import pytest
from starlette.testclient import TestClient

from anyinfer_confidential import (
    KeyRing,
    TemplateVault,
    generate_key,
    generate_signing_keypair,
    issue_license,
    seal_template,
)
from anyinfer_confidential.admission import TenantLimits
from anyinfer_confidential.app import RELAY_RATE_LIMIT_HEADERS, build_app
from anyinfer_confidential.relay import Relay, RelayRegistry, RelayRoute

ACME_TOKEN = "acme-token-value"
OTHER_TOKEN = "other-token-value"
TOKENS = {ACME_TOKEN: "acme", OTHER_TOKEN: "other"}


def _relay(*, tenants: tuple[str, ...] = ("acme", "other")) -> Relay:
    key = generate_key()
    private_key, public_key = generate_signing_keypair()
    blob = issue_license("acme", private_key=private_key, valid_days=30)
    vault = TemplateVault(
        key_ring=KeyRing({"k1": key}), license_public_key=public_key, license_blob=blob
    )
    template = seal_template("Summarize for {audience}", key=key, template_id="s", key_id="k1")
    registry = RelayRegistry()
    for tenant in tenants:
        registry.register(
            tenant,
            RelayRoute(routing_key="summarize", template=template, target="ollama:qwen3:8b"),
        )
    return Relay(vault=vault, registry=registry)


def _app(relay: Relay) -> TestClient:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TestClient(build_app(relay, tokens=TOKENS))


def _post(client: TestClient, token: str = ACME_TOKEN, **body: object) -> object:
    payload = {"routing_key": "summarize", "slots": {"audience": "engineers"}, **body}
    return client.post(
        "/v1/relay/assemble", headers={"Authorization": f"Bearer {token}"}, json=payload
    )


# ---- the error taxonomy --------------------------------------------------------------------


def test_an_unknown_route_is_still_a_404_with_its_uniform_message() -> None:
    """Unchanged, deliberately: this message must not distinguish absent from other-tenant."""
    response = _post(_app(_relay()), routing_key="no-such-route")
    assert response.status_code == 404


def test_another_tenants_route_answers_identically_to_a_missing_one() -> None:
    """Same routing key, two tenants: one owns it, one does not, and both hear the same thing.

    The message echoes the routing key the caller themselves supplied, which reveals
    nothing they did not already know. What must not differ is the answer for a key that
    exists somewhere versus one that exists nowhere — that difference is what would let a
    prober enumerate another tenant's routing keys one guess at a time.
    """
    relay = _relay(tenants=("acme",))
    client = _app(relay)

    owned_by_someone_else = _post(client, OTHER_TOKEN, routing_key="summarize")
    owned_by_nobody = _post(client, OTHER_TOKEN, routing_key="summarize-x")

    assert owned_by_someone_else.status_code == owned_by_nobody.status_code == 404
    assert owned_by_someone_else.json()["error"].replace("summarize", "K") == (
        owned_by_nobody.json()["error"].replace("summarize-x", "K")
    ), "the two answers differ by more than the caller's own echoed input"


def test_forward_mode_over_http_is_a_400() -> None:
    """Refused at the HTTP edge, before the relay: credentials are not accepted on the wire."""
    response = _post(_app(_relay()), mode="forward")
    assert response.status_code == 400
    assert "not available over HTTP" in response.json()["error"]


def test_a_malformed_body_is_a_400_rather_than_a_404() -> None:
    client = _app(_relay())
    response = client.post(
        "/v1/relay/assemble",
        headers={"Authorization": f"Bearer {ACME_TOKEN}"},
        json={"slots": {}},  # no routing_key
    )
    assert response.status_code == 400


async def test_in_process_forward_without_settings_raises_the_bad_request_class() -> None:
    """The typed half of the same split: an embedder without ASGI gets it as data.

    Previously indistinguishable from "no such route", which told a caller to go looking
    for a provisioning problem that did not exist.
    """
    from anyinfer_confidential.relay import RelayBadRequestError, RelayError

    with pytest.raises(RelayBadRequestError) as caught:
        await _relay().handle(tenant_id="acme", routing_key="summarize", slots={}, mode="forward")
    assert isinstance(caught.value, RelayError), "still catchable by callers of the base class"


# ---- 429 and its headers --------------------------------------------------------------------


def test_a_saturated_tenant_is_refused_in_milliseconds() -> None:
    """A tenant at its cap with a full queue hears back at once, not after its wait budget."""
    import asyncio

    from anyinfer_confidential.admission import AdmissionController, RelayThrottledError

    controller = AdmissionController()
    controller.set_limits(
        "acme", TenantLimits(max_in_flight=1, max_waiting=1, max_wait_s=30.0)
    )

    async def drive() -> tuple[str, float]:
        async def hold() -> None:
            async with controller.admit("acme", estimate=1.0):
                await asyncio.sleep(0.3)

        running = [asyncio.create_task(hold()) for _ in range(2)]  # one in flight, one queued
        await asyncio.sleep(0.02)
        started = asyncio.get_running_loop().time()
        try:
            async with controller.admit("acme", estimate=1.0):
                return "admitted", 0.0
        except RelayThrottledError as exc:
            elapsed = asyncio.get_running_loop().time() - started
            return exc.info.reason, elapsed
        finally:
            await asyncio.gather(*running)

    reason, elapsed = asyncio.run(drive())
    assert reason == "tenant-queue-full"
    assert elapsed < 0.1, "a full queue must refuse immediately, not consume max_wait_s"


def test_retry_after_is_digits_only() -> None:
    """`parse_retry_after` refuses HTTP-dates, so a date here is silently dropped by us."""
    from anyinfer_confidential.admission import RelayThrottledError, ThrottleInfo
    from anyinfer_confidential.app import _throttled_response

    response = _throttled_response(
        RelayThrottledError(ThrottleInfo("tenant-in-flight", 3.2, remaining=0))
    )
    assert response.status_code == 429
    assert response.headers["retry-after"].isdigit()
    assert int(response.headers["retry-after"]) == 4, "a rounded-down backoff retries into the wall"


def test_a_zero_second_estimate_still_advertises_a_whole_second() -> None:
    """`Retry-After: 0` is an invitation to hot-loop."""
    from anyinfer_confidential.admission import RelayThrottledError, ThrottleInfo
    from anyinfer_confidential.app import _throttled_response

    response = _throttled_response(RelayThrottledError(ThrottleInfo("provider-window", 0.0)))
    assert int(response.headers["retry-after"]) >= 1


# ---- budget headers on a success --------------------------------------------------------------


def test_a_configured_tenant_learns_its_own_budget_before_hitting_the_wall() -> None:
    """The avoidance half: a 429 arrives too late to avoid the round trip it refused."""
    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=4))
    response = _post(_app(relay))

    assert response.status_code == 200
    assert response.headers["ratelimit-limit"] == "4"
    assert response.headers["ratelimit-remaining"] == "4"


def test_an_unconfigured_tenant_gets_no_header_rather_than_a_guessed_one() -> None:
    """An empty dialect honestly declared beats a guessed one — `RateLimitHeaders`' rule."""
    response = _post(_app(_relay()))
    assert response.status_code == 200
    assert "ratelimit-limit" not in response.headers
    assert "ratelimit-remaining" not in response.headers


def test_a_tenants_headers_are_identical_whether_another_tenant_is_idle_or_saturated() -> None:
    """The security property, and the reason emitted numbers are per-tenant by construction.

    A `RateLimit-Remaining` derived from process-wide state would let one tenant poll in a
    loop and read another tenant's traffic volume straight off its own response headers —
    exactly the enumeration `RelayRegistry.resolve`'s uniform error message prevents.
    """
    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=4))
    relay.admission().set_limits("other", TenantLimits(max_in_flight=4))
    client = _app(relay)

    idle = _post(client).headers

    # Saturate the *other* tenant's budget without touching acme's.
    controller = relay.admission()
    for _ in range(4):
        controller._in_flight["other"] = controller._in_flight.get("other", 0) + 1
    assert controller.remaining("other") == 0

    saturated = _post(client).headers

    assert idle["ratelimit-limit"] == saturated["ratelimit-limit"]
    assert idle["ratelimit-remaining"] == saturated["ratelimit-remaining"]


# ---- the declared dialect ------------------------------------------------------------------


def test_the_emitted_headers_match_the_dialect_this_package_declares() -> None:
    """The drift guard between what the app writes and what a client is told to read.

    A half-finished rename — emitter updated, constant not — otherwise leaves a client
    reading `None` forever with nothing failing.
    """
    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=4))
    headers = _post(_app(relay)).headers

    dialect = RELAY_RATE_LIMIT_HEADERS()
    assert dialect.limit_requests in headers
    assert dialect.requests_remaining in headers
    assert not dialect.requests_remaining.startswith("x-"), "no bespoke X- names"


def test_core_parses_what_this_app_emits() -> None:
    """Round trip: the emit side and core's parse side must agree on spelling.

    This is the payoff for using the IETF draft names — an AnyInfer client pointed at a
    Relay paces itself with no new client code.
    """
    from anyinfer.routing.limits import RateLimiter
    from anyinfer.types.requests import RateLimits

    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=4))
    headers = dict(_post(_app(relay)).headers)

    limiter = RateLimiter(
        RateLimits(requests_per_minute=60, respect_headers=True),
        dialect=RELAY_RATE_LIMIT_HEADERS(),
        provider_id="relay",
    )
    limiter.observe(headers)
    assert limiter.reads_headers, "the declared dialect must be complete enough to act on"


# ---- the multi-tenant warning -----------------------------------------------------------------


def test_a_multi_tenant_relay_with_no_limits_warns_once() -> None:
    """The exact gap that motivated admission control, so it is not silent."""
    with pytest.warns(UserWarning, match="admission limits"):
        build_app(_relay(), tokens=TOKENS)


def test_a_single_tenant_relay_stays_silent() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_app(_relay(tenants=("acme",)), tokens={ACME_TOKEN: "acme"})


def test_a_configured_multi_tenant_relay_stays_silent() -> None:
    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=4))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_app(relay, tokens=TOKENS)


# ---- provisioning limits from the registry file -----------------------------------------


def test_a_registry_file_can_carry_a_tenants_limits(tmp_path: object) -> None:
    """One provisioning document should describe capacity as well as routes."""
    import json
    from pathlib import Path

    from anyinfer_confidential.relay import load_registry

    key = generate_key()
    template = seal_template("Hi {audience}", key=key, template_id="t", key_id="k1")
    path = Path(str(tmp_path)) / "registry.json"
    path.write_text(
        json.dumps(
            {
                "tenants": {
                    "acme": {
                        "limits": {"max_in_flight": 3, "max_waiting": 9},
                        "routes": [
                            {
                                "routing_key": "summarize",
                                "target": "ollama:m",
                                "template": json.loads(template.to_json()),
                            }
                        ],
                    }
                }
            }
        )
    )

    registry = load_registry(path)
    assert registry.limits()["acme"].max_in_flight == 3
    assert registry.resolve("acme", "summarize").target == "ollama:m"


def test_a_bare_route_list_still_means_routes_only(tmp_path: object) -> None:
    """The original shape stays valid: this file is under configuration management."""
    import json
    from pathlib import Path

    from anyinfer_confidential.relay import load_registry

    key = generate_key()
    template = seal_template("Hi {audience}", key=key, template_id="t", key_id="k1")
    path = Path(str(tmp_path)) / "registry.json"
    path.write_text(
        json.dumps(
            {
                "tenants": {
                    "acme": [
                        {
                            "routing_key": "summarize",
                            "target": "ollama:m",
                            "template": json.loads(template.to_json()),
                        }
                    ]
                }
            }
        )
    )

    registry = load_registry(path)
    assert registry.limits() == {}
    assert registry.resolve("acme", "summarize").target == "ollama:m"


def test_malformed_limits_fail_the_load_rather_than_being_skipped(tmp_path: object) -> None:
    """A relay that started while silently ignoring half its provisioning is worse."""
    import json
    from pathlib import Path

    from anyinfer_confidential.relay import RelayError, load_registry

    path = Path(str(tmp_path)) / "registry.json"
    path.write_text(
        json.dumps({"tenants": {"acme": {"limits": {"max_in_flight": 0}, "routes": []}}})
    )
    with pytest.raises(RelayError, match="malformed limits"):
        load_registry(path)


def test_a_relay_installs_the_limits_its_registry_was_provisioned_with() -> None:
    from anyinfer_confidential.relay import RelayRegistry

    registry = RelayRegistry()
    registry.set_limits("acme", TenantLimits(max_in_flight=5))
    relay = Relay(vault=_relay()._vault, registry=registry)
    assert relay.admission().limits_for("acme").max_in_flight == 5


# ---- the provider's own window ------------------------------------------------------------


async def test_an_exhausted_provider_window_refuses_with_the_providers_own_number() -> None:
    """Passed through, not estimated: it is the caller's own BYOK quota, so it leaks nothing.

    Refusing beats waiting here because core's limiter would sleep out the window while
    still holding this tenant's admission slot — one provider window idling a tenant's
    whole capacity for its duration.
    """
    import anyinfer as ai
    from anyinfer.routing.limits import RateLimiter

    from anyinfer_confidential.admission import RelayThrottledError

    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=2, max_wait_s=5.0))

    exhausted = RateLimiter(
        ai.RateLimits(requests_per_minute=60, respect_headers=True),
        dialect=ai.RateLimitHeaders(requests_remaining="x-remaining", requests_reset="x-reset"),
        provider_id="openai",
    )
    exhausted.observe({"x-remaining": "0", "x-reset": "45"})

    with pytest.raises(RelayThrottledError) as caught:
        relay._refuse_if_the_provider_says_wait({"openai": exhausted}, "acme")

    assert caught.value.info.reason == "provider-window"
    assert caught.value.info.retry_after_s == pytest.approx(45.0, abs=2.0), (
        "the provider's own reset must pass through unjittered and unrounded"
    )


async def test_a_window_shorter_than_the_queueing_budget_is_waited_out_not_refused() -> None:
    """Below the budget, waiting is cheaper than a refused round trip."""
    import anyinfer as ai
    from anyinfer.routing.limits import RateLimiter

    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=2, max_wait_s=30.0))

    brief = RateLimiter(
        ai.RateLimits(requests_per_minute=60, respect_headers=True),
        dialect=ai.RateLimitHeaders(requests_remaining="x-remaining", requests_reset="x-reset"),
        provider_id="openai",
    )
    brief.observe({"x-remaining": "0", "x-reset": "2"})

    relay._refuse_if_the_provider_says_wait({"openai": brief}, "acme")  # does not raise


async def test_a_clear_window_never_refuses() -> None:
    import anyinfer as ai
    from anyinfer.routing.limits import RateLimiter

    relay = _relay()
    relay.admission().set_limits("acme", TenantLimits(max_in_flight=2))
    clear = RateLimiter(ai.RateLimits(requests_per_minute=60), provider_id="openai")
    relay._refuse_if_the_provider_says_wait({"openai": clear}, "acme")
