"""Arena execution — running one request across several targets and judging the result.

Split out of `async_client.py` for the same reason as `generation.py`: arena fan-out,
its spend reservation, and the tool-loop arena variant are a self-contained concern that
had no reason to sit in the same file as routing, spend, and the model store.

Mixed into `AsyncClient`, not usable alone — see `generation.py`'s docstring for why this
is a mixin and what that does and does not buy.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .._usage import merge_usage
from ..capabilities.ledger import SpendLedger
from ..context_request import ContextRequest
from ..errors import (
    AllTargetsFailedError,
    AnyInferError,
    ConfigError,
    ToolLoopError,
)
from ..evaluate.arena import ArenaResult, Candidate, candidate_envelope, select_candidates
from ..events.telemetry import (
    ArenaCompleted,
    ParameterDropped,
    TelemetryEvent,
)
from ..manifest import ManifestBuilder
from ..registry import ProviderDescriptor
from ..routing.policy import Route
from ..session import Session
from ..types.capabilities import (
    ModelCapabilities,
)
from ..types.events import (
    StreamEnded,
    StreamEvent,
    TextDelta,
)
from ..types.messages import (
    user,
)
from ..types.requests import (
    ArenaPolicy,
    CachePolicy,
    GenerationRequest,
    HistoryPolicy,
    ReasoningEffort,
    Repair,
    ResolvedTarget,
    Sampling,
    SchemaSpec,
    SpendPolicy,
    SupportsJSONSchema,
    Target,
    ToolChoice,
    ToolSpec,
)
from ..types.results import (
    AttemptRecord,
    Generation,
    Usage,
)
from .messages import MessagesInput, _coerce_messages, _spend_prechecked
from .providers import AdapterPool
from .tools import (
    Tool,
    ToolMemo,
    ToolRegistry,
    build_tool_turn,
)


class ArenaExecutionMixin:
    """Arena fan-out and judging. Mixed into `AsyncClient`; not usable alone."""

    if TYPE_CHECKING:
        # Declared, never defined — `AsyncClient` supplies these. See `generation.py`.
        _arena: ArenaPolicy | None
        _arenas: Mapping[str, ArenaPolicy]
        _ledger: SpendLedger | None
        _pool: AdapterPool
        _spend_policy: SpendPolicy | None

        def resolve(self, target: Target) -> ResolvedTarget: ...

        # Supplied by SpendGovernanceMixin, a sibling on the same class.
        def _estimate_request_cost(
            self, request: GenerationRequest, capabilities: ModelCapabilities | None
        ) -> Decimal | None: ...

        def _enforce_spend_ceiling(
            self,
            estimate: Decimal | None,
            *,
            policy: SpendPolicy,
            request_id: str,
            unknown: bool,
            unknown_message: str,
            unknown_hint: str | None = None,
            over_request_message: str,
            over_request_hint: str | None = None,
            over_total_message: Callable[[Decimal, Decimal], str],
            over_total_hint: str | None = None,
        ) -> None: ...

        async def generate(
            self,
            messages: MessagesInput,
            *,
            target: Target | None = None,
            route: Route | Target | Sequence[Target] | None = None,
            schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None = None,
            tools: Sequence[ToolSpec] = (),
            tool_choice: ToolChoice = "auto",
            sampling: Sampling | None = None,
            reasoning: ReasoningEffort | None = None,
            timeout_s: float | None = None,
            repair: Repair | None = None,
            history: HistoryPolicy | None = None,
            cache: CachePolicy | None = None,
            arena: ArenaPolicy | None = None,
            context: ContextRequest | None = None,
            provider_options: Mapping[str, Mapping[str, Any]] | None = None,
            metadata: Mapping[str, str] | None = None,
            max_response_bytes: int | None = None,
            max_input_part_bytes: int | None = None,
            max_input_bytes: int | None = None,
            session: Session | None = None,
            manifest: bool | None = None,
        ) -> Generation: ...

        async def _generate_request(
            self,
            request: GenerationRequest,
            route: Route,
            *,
            session: Session | None = None,
            manifest: bool | None = None,
        ) -> Generation: ...

        def _build_request(
            self,
            messages: MessagesInput,
            *,
            schema: SchemaSpec | SupportsJSONSchema | Mapping[str, Any] | None,
            tools: Sequence[ToolSpec],
            tool_choice: ToolChoice,
            sampling: Sampling | None,
            reasoning: ReasoningEffort | None,
            timeout_s: float | None,
            repair: Repair | None,
            history: HistoryPolicy | None,
            cache: CachePolicy | None,
            provider_options: Mapping[str, Mapping[str, Any]] | None,
            metadata: Mapping[str, str] | None,
            max_response_bytes: int | None,
            max_input_part_bytes: int | None = None,
            max_input_bytes: int | None = None,
            arena: ArenaPolicy | None = None,
            context: ContextRequest | None = None,
        ) -> GenerationRequest: ...

        def _capabilities_for(
            self, descriptor: ProviderDescriptor, resolved: ResolvedTarget
        ) -> ModelCapabilities: ...

        def _emit(
            self, event: TelemetryEvent, *, builder: ManifestBuilder | None = None
        ) -> None: ...

    def _effective_arena(
        self,
        arena: ArenaPolicy | None,
        target: Target | None,
        route: Route | Target | Sequence[Target] | None,
    ) -> ArenaPolicy | None:
        """Resolve request, named, then client-default arena policy without routing."""
        if arena is not None:
            return arena
        if route is None and isinstance(target, str) and target in self._arenas:
            return self._arenas[target]
        if target is None and route is None:
            return self._arena
        return None

    async def _arena_stream(
        self, request: GenerationRequest, policy: ArenaPolicy
    ) -> AsyncGenerator[StreamEvent, None]:
        """Buffer arena branches, then expose only the selected answer as one stream."""
        result = await self._run_arena(request, policy)
        if result.text:
            yield TextDelta(result.text)
        yield StreamEnded(result)

    async def _run_arena(
        self,
        request: GenerationRequest,
        policy: ArenaPolicy,
        *,
        manifest: bool | None = None,
        spend_multiplier: int = 1,
    ) -> Generation:
        """Fan out fixed independent routes, then select after every branch completes."""
        arena_id = uuid.uuid4().hex
        self._reserve_arena_spend(arena_id, request, policy, candidate_multiplier=spend_multiplier)
        semaphore = asyncio.Semaphore(policy.concurrency)
        branch_request = replace(request, arena=None)

        async def candidate(target: str) -> tuple[Candidate, tuple[AttemptRecord, ...]]:
            started = time.monotonic()
            try:
                resolved = self.resolve(target)
            except (AnyInferError, ValueError) as exc:
                error = exc if isinstance(exc, AnyInferError) else ConfigError(str(exc))
                return (
                    Candidate(
                        ResolvedTarget("unresolved", target),
                        error=error.snapshot(),
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    (),
                )
            try:
                async with semaphore:
                    token = _spend_prechecked.set(True)
                    try:
                        generation = await self._generate_request(
                            branch_request,
                            Route(targets=(target,)),
                            manifest=manifest,
                        )
                    finally:
                        _spend_prechecked.reset(token)
                return (
                    Candidate(
                        resolved,
                        generation=generation,
                        valid=(generation.structured is not None)
                        if request.schema is not None
                        else None,
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    generation.attempts,
                )
            except AnyInferError as exc:
                attempts = exc.attempts if isinstance(exc, AllTargetsFailedError) else ()
                return (
                    Candidate(
                        resolved,
                        error=exc.snapshot(),
                        valid=False if request.schema is not None else None,
                        elapsed_ms=(time.monotonic() - started) * 1000.0,
                    ),
                    attempts,
                )

        try:
            rows = await asyncio.gather(*(candidate(target) for target in policy.targets))
            candidates = tuple(row[0] for row in rows)
            successful = tuple(item for item in candidates if item.generation is not None)
            if len(successful) < policy.min_candidates:
                attempts = tuple(attempt for row in rows for attempt in row[1])
                raise AllTargetsFailedError(
                    f"arena produced {len(successful)} candidates; "
                    f"{policy.min_candidates} required",
                    attempts=attempts,
                    hint="fix a failed target or lower arena min_candidates",
                )

            winner, strategy, agreement, degradation = select_candidates(
                candidates, policy, has_schema=request.schema is not None
            )
            calls = len(policy.targets)
            judge_generation: Generation | None = None
            if policy.strategy in ("judge", "synthesize"):
                judge_generation, judged_winner, judge_reason = await self._arena_verdict(
                    request, policy, candidates
                )
                calls += 1
                if policy.strategy == "judge" and judged_winner is not None:
                    winner = judged_winner
                    strategy = "judge"
                    degradation = None
                elif policy.strategy == "synthesize" and judge_generation is not None:
                    strategy = "synthesize"
                    degradation = None
                else:
                    degradation = judge_reason or "the arena verdict could not be applied"

            if winner is None or winner.generation is None:
                raise AllTargetsFailedError("arena had no selectable candidate")
            if degradation:
                self._emit(
                    ParameterDropped(
                        arena_id,
                        winner.target,
                        "arena.strategy",
                        degradation,
                    )
                )

            complete = len(successful) == len(candidates)
            usages = [item.generation.usage for item in successful if item.generation is not None]
            if judge_generation is not None:
                usages.append(judge_generation.usage)
            aggregate = merge_usage(usages) if complete else Usage()
            arena_result = ArenaResult(
                candidates=candidates,
                winner=winner,
                strategy=strategy,
                agreement=agreement,
                synthesized=(judge_generation if policy.strategy == "synthesize" else None),
                calls=calls,
                usage=aggregate,
                usage_complete=complete,
            )
            promoted = (
                judge_generation
                if policy.strategy == "synthesize" and judge_generation is not None
                else winner.generation
            )
            if promoted is None:
                raise RuntimeError("arena selected a candidate without a generation")
            self._emit(
                ArenaCompleted(
                    arena_id,
                    len(candidates),
                    arena_result.strategy,
                    arena_result.agreement,
                    arena_result.calls,
                    arena_result.memoized_tool_calls,
                    arena_result.synthesized is not None,
                )
            )
            return replace(promoted, arena=arena_result)
        finally:
            if self._ledger is not None:
                self._ledger.release(arena_id)

    async def _arena_verdict(
        self,
        request: GenerationRequest,
        policy: ArenaPolicy,
        candidates: tuple[Candidate, ...],
    ) -> tuple[Generation | None, Candidate | None, str | None]:
        """Run the one bounded judge or synthesis call and interpret its result."""
        default = (
            "Choose the strongest candidate. Return its one-based index and a brief reason."
            if policy.strategy == "judge"
            else "Synthesize one accurate answer from the candidates."
        )
        envelope = candidate_envelope(candidates, reveal_targets=policy.reveal_targets)
        prompt = f"{policy.instructions or default}\n\n{envelope}"
        schema: Mapping[str, Any] | SchemaSpec | None
        if policy.strategy == "judge":
            schema = {
                "type": "object",
                "properties": {
                    "pick": {"type": "integer", "minimum": 1},
                    "why": {"type": "string"},
                },
                "required": ["pick", "why"],
                "additionalProperties": False,
            }
        else:
            schema = request.schema
        judge_request = replace(
            request,
            messages=(user(prompt),),
            schema=SchemaSpec.coerce(schema) if schema is not None else None,
            tools=(),
            tool_choice="none",
            arena=None,
        )
        token = _spend_prechecked.set(True)
        try:
            generation = await self._generate_request(
                judge_request, Route(targets=(str(policy.judge_target),))
            )
        except AnyInferError as exc:
            return None, None, f"arena {policy.strategy} call failed: {exc.detail}"
        finally:
            _spend_prechecked.reset(token)
        if policy.strategy == "synthesize":
            return generation, None, None
        structured = generation.structured
        pick = structured.get("pick") if isinstance(structured, Mapping) else None
        if isinstance(pick, int) and 1 <= pick <= len(candidates):
            selected = candidates[pick - 1]
            if selected.generation is not None:
                return generation, selected, None
        return generation, None, "arena judge returned an unusable candidate index"

    def _reserve_arena_spend(
        self,
        arena_id: str,
        request: GenerationRequest,
        policy: ArenaPolicy,
        *,
        candidate_multiplier: int,
    ) -> None:
        """Reserve the summed high estimate before any arena branch dispatches."""
        spend = self._spend_policy
        if spend is None or not spend.active:
            return
        total = Decimal(0)
        unknown: list[str] = []
        weighted = [(target, candidate_multiplier) for target in policy.targets]
        if policy.judge_target is not None:
            weighted.append((policy.judge_target, 1))
        for target, multiplier in weighted:
            try:
                resolved = self.resolve(target)
                descriptor = self._pool.descriptor_for(resolved.provider_id)
                capabilities = self._capabilities_for(descriptor, resolved)
                estimate = self._estimate_request_cost(request, capabilities)
            except (AnyInferError, ValueError):
                estimate = None
            if estimate is None:
                unknown.append(str(target))
            else:
                total += estimate * multiplier
        self._enforce_spend_ceiling(
            total,
            policy=spend,
            request_id=arena_id,
            unknown=bool(unknown),
            unknown_message=(
                f"the summed cost of this {len(policy.targets)}-candidate arena cannot "
                f"be estimated because pricing is unknown for {', '.join(unknown)}"
            ),
            unknown_hint="supply trusted pricing or set spend on_unknown='allow'",
            over_request_message=(
                f"the summed estimate {total} for {len(policy.targets)} arena candidates "
                f"exceeds the per-request ceiling {spend.max_request_usd}"
            ),
            over_total_message=lambda spent, reserved: (
                f"this client has spent {spent}, reserved {reserved}, and this "
                f"{len(policy.targets)}-candidate arena could cost {total}, above "
                f"the total ceiling {spend.max_total_usd}"
            ),
        )

    async def _run_tools_arena(
        self,
        messages: MessagesInput,
        *,
        tools: Sequence[Tool | Any],
        policy: ArenaPolicy,
        max_rounds: int,
        kwargs: Mapping[str, Any],
    ) -> Generation:
        """Run one isolated tool conversation per arena candidate."""
        template_registry = ToolRegistry(list(tools))
        base_request = self._build_request(
            messages,
            schema=kwargs.get("schema"),
            tools=template_registry.specs,
            tool_choice=kwargs.get("tool_choice", "auto"),
            sampling=kwargs.get("sampling"),
            reasoning=kwargs.get("reasoning"),
            timeout_s=kwargs.get("timeout_s"),
            repair=kwargs.get("repair"),
            history=kwargs.get("history"),
            cache=kwargs.get("cache"),
            provider_options=kwargs.get("provider_options"),
            metadata=kwargs.get("metadata"),
            max_response_bytes=kwargs.get("max_response_bytes"),
            arena=policy,
        )
        arena_id = uuid.uuid4().hex
        self._reserve_arena_spend(arena_id, base_request, policy, candidate_multiplier=max_rounds)
        memo = ToolMemo()
        semaphore = asyncio.Semaphore(policy.concurrency)

        async def branch(target: str) -> Candidate:
            started = time.monotonic()
            try:
                resolved = self.resolve(target)
            except (AnyInferError, ValueError) as exc:
                error = exc if isinstance(exc, AnyInferError) else ConfigError(str(exc))
                return Candidate(
                    ResolvedTarget("unresolved", target),
                    error=error.snapshot(),
                    rounds=0,
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
            registry = ToolRegistry(list(tools), memo=memo, memo_mode=policy.memoize_tools)
            conversation = list(_coerce_messages(messages))
            rounds = 0
            try:
                async with semaphore:
                    token = _spend_prechecked.set(True)
                    try:
                        for rounds in range(1, max_rounds + 1):
                            result = await self.generate(
                                conversation,
                                target=target,
                                tools=registry.specs,
                                arena=None,
                                **dict(kwargs),
                            )
                            if result.finish_reason != "tool_calls" or not result.tool_calls:
                                return Candidate(
                                    resolved,
                                    generation=result,
                                    valid=(result.structured is not None)
                                    if base_request.schema is not None
                                    else None,
                                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                                    rounds=rounds,
                                    tool_calls=registry.dispatched,
                                )
                            outputs = [await registry.dispatch(call) for call in result.tool_calls]
                            conversation.extend(build_tool_turn(result.tool_calls, outputs))
                    finally:
                        _spend_prechecked.reset(token)
                raise ToolLoopError(
                    f"the tool loop ran {max_rounds} rounds without a final answer"
                )
            except AnyInferError as exc:
                return Candidate(
                    resolved,
                    error=exc.snapshot(),
                    valid=False if base_request.schema is not None else None,
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                    rounds=rounds,
                    tool_calls=registry.dispatched,
                )

        try:
            candidates = tuple(
                await asyncio.gather(*(branch(target) for target in policy.targets))
            )
            successful = tuple(item for item in candidates if item.generation is not None)
            if len(successful) < policy.min_candidates:
                raise AllTargetsFailedError(
                    f"arena produced {len(successful)} completed tool loops; "
                    f"{policy.min_candidates} required"
                )
            winner, strategy, agreement, degradation = select_candidates(
                candidates, policy, has_schema=base_request.schema is not None
            )
            calls = sum(item.rounds or 0 for item in candidates)
            verdict: Generation | None = None
            if policy.strategy in ("judge", "synthesize"):
                verdict, selected, reason = await self._arena_verdict(
                    base_request, policy, candidates
                )
                calls += 1
                if policy.strategy == "judge" and selected is not None:
                    winner, strategy, degradation = selected, "judge", None
                elif policy.strategy == "synthesize" and verdict is not None:
                    strategy, degradation = "synthesize", None
                else:
                    degradation = reason or "the arena verdict could not be applied"
            if winner is None or winner.generation is None:
                raise AllTargetsFailedError("arena had no selectable completed tool loop")
            if degradation:
                self._emit(
                    ParameterDropped(arena_id, winner.target, "arena.strategy", degradation)
                )
            complete = len(successful) == len(candidates)
            usages = [item.generation.usage for item in successful if item.generation is not None]
            if verdict is not None:
                usages.append(verdict.usage)
            arena_result = ArenaResult(
                candidates=candidates,
                winner=winner,
                strategy=strategy,
                agreement=agreement,
                synthesized=verdict if policy.strategy == "synthesize" else None,
                calls=calls,
                memoized_tool_calls=memo.hits,
                usage=merge_usage(usages) if complete else Usage(),
                usage_complete=complete,
            )
            promoted = (
                verdict
                if policy.strategy == "synthesize" and verdict is not None
                else winner.generation
            )
            if promoted is None:
                raise RuntimeError("arena selected a candidate without a generation")
            self._emit(
                ArenaCompleted(
                    arena_id,
                    len(candidates),
                    strategy,
                    agreement,
                    calls,
                    memo.hits,
                    verdict is not None and policy.strategy == "synthesize",
                )
            )
            return replace(promoted, arena=arena_result)
        finally:
            if self._ledger is not None:
                self._ledger.release(arena_id)
