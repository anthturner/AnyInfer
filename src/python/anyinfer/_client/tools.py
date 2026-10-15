"""The tool-execution loop.

Deliberately minimal. This is a *loop*, not an agent framework: it dispatches the
tool calls a model asks for, feeds the results back, and stops. No planning, no memory, no
multi-agent constructs.

Two v1 choices worth stating:

- **Sequential dispatch.** Tools run one at a time. Parallel execution is deferred: it adds
  cancellation and ordering questions that no current consumer needs answered.
- **Errors become tool results, not exceptions.** A tool that raises produces an
  error-flagged `ToolResult`, giving the model a chance to
  recover. A failing tool is a normal event in a conversation; only loop-level failures
  (an unknown tool, or an exhausted round budget) raise.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from ..errors import ToolLoopError
from ..types.messages import Message, ToolCall, ToolResult
from ..types.requests import ToolSpec

__all__ = ["DEFAULT_MAX_ROUNDS", "Tool", "ToolMemo", "ToolRegistry", "tool"]

DEFAULT_MAX_ROUNDS = 8
"""Round bound. Without one, a model that keeps calling tools never terminates."""

_JSON_TYPES: Mapping[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass(frozen=True, slots=True)
class Tool:
    """A callable paired with the `ToolSpec` derived from its signature."""

    spec: ToolSpec
    """The declaration advertised to the model: name, description, and parameter schema."""

    func: Callable[..., Any]
    """The wrapped callable. May be ``async def``; the loop's dispatcher awaits its
    result."""

    @property
    def name(self) -> str:
        """The tool's name, as advertised to the model."""
        return self.spec.name

    def call(self, arguments: Mapping[str, Any]) -> Any:
        """Invoke the underlying function.

        An ``async def`` tool returns a coroutine here; the loop's dispatcher awaits it.
        """
        return self.func(**dict(arguments))


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Turn a function into a `Tool`, deriving its schema from the signature.

    Parameter types come from annotations and the description from the docstring, so a tool
    is declared once rather than being kept in sync with a hand-written schema:

    ```python
    @ai.tool
    def read_file(path: str) -> str:
        \"\"\"Read a project file.\"\"\"
        return Path(path).read_text()
    ```

    Args:
        func: The function to wrap, when used bare.
        name: Overrides the function's name.
        description: Overrides the docstring summary.

    Returns:
        A `Tool`, or a decorator producing one.

    Raises:
        ToolLoopError: If a parameter's annotation is not a supported JSON type.
    """

    def build(target: Callable[..., Any]) -> Tool:
        return Tool(
            spec=_spec_from_function(target, name=name, description=description),
            func=target,
        )

    if func is not None:
        return build(func)
    return build


def _spec_from_function(
    func: Callable[..., Any],
    *,
    name: str | None,
    description: str | None,
) -> ToolSpec:
    """Derive a tool spec from a function's signature and docstring."""
    signature = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:  # noqa: BLE001 — unresolvable annotations must not break declaration
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for parameter_name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        annotation = hints.get(parameter_name, parameter.annotation)
        properties[parameter_name] = _json_type(
            annotation, tool_name=name or func.__name__, parameter=parameter_name
        )
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter_name)

    summary = description or (inspect.getdoc(func) or "").strip().split("\n\n")[0]

    return ToolSpec(
        name=name or func.__name__,
        description=summary,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    )


def _json_type(annotation: Any, *, tool_name: str, parameter: str) -> dict[str, Any]:
    """Map a Python annotation onto a JSON-schema type.

    v1 supports the scalar and container types that map cleanly. Anything else is rejected
    at declaration time rather than producing a schema that silently misdescribes the tool.
    """
    if annotation is inspect.Parameter.empty:
        return {}

    origin = get_origin(annotation)
    if origin is not None:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if origin in (list, Sequence):
            item = args[0] if args else None
            schema: dict[str, Any] = {"type": "array"}
            if item is not None and item in _JSON_TYPES:
                schema["items"] = {"type": _JSON_TYPES[item]}
            return schema
        if origin in (dict, Mapping):
            return {"type": "object"}
        # Optional[T] and unions of one real type reduce to that type.
        if len(args) == 1:
            return _json_type(args[0], tool_name=tool_name, parameter=parameter)
        raise ToolLoopError(
            f"tool {tool_name!r} parameter {parameter!r} has an unsupported union type",
            hint="v1 tools support str, int, float, bool, list, and dict parameters",
        )

    json_type = _JSON_TYPES.get(annotation)
    if json_type is None:
        raise ToolLoopError(
            f"tool {tool_name!r} parameter {parameter!r} has unsupported type "
            f"{getattr(annotation, '__name__', annotation)!r}",
            hint="v1 tools support str, int, float, bool, list, and dict parameters",
        )
    return {"type": json_type}


class ToolMemo:
    """Exact, single-flight memo shared only by candidates in one arena run."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Future[ToolResult]] = {}
        self.hits = 0

    async def dispatch(
        self, key: str, call_id: str, execute: Callable[[], Awaitable[ToolResult]]
    ) -> ToolResult:
        """Execute once for an exact key; failures are removed rather than cached."""
        async with self._lock:
            task = self._inflight.get(key)
            owner = task is None
            if task is None:
                task = asyncio.ensure_future(execute())
                self._inflight[key] = task
        result = await task
        if result.is_error:
            async with self._lock:
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)
            if not owner:
                return await execute()
        elif not owner:
            async with self._lock:
                self.hits += 1
        return ToolResult(call_id=call_id, content=result.content, is_error=result.is_error)


class ToolRegistry:
    """The tools available to one loop, indexed by name."""

    def __init__(
        self,
        tools: Sequence[Tool | Callable[..., Any]],
        *,
        memo: ToolMemo | None = None,
        memo_mode: str = "off",
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._memo = memo
        self._memo_mode = memo_mode
        self.dispatched = 0
        for entry in tools:
            resolved = entry if isinstance(entry, Tool) else tool(entry)
            self._tools[resolved.name] = resolved

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Every tool's spec, for the generation request."""
        return tuple(t.spec for t in self._tools.values())

    async def dispatch(self, call: ToolCall) -> ToolResult:
        """Execute one tool call, converting failures into error-flagged results.

        Both plain and ``async def`` tools are supported: a coroutine returned by the
        tool is awaited here, so an async tool works identically through either client.

        Raises:
            ToolLoopError: If the model named a tool that does not exist — a loop-level
                fault the model cannot recover from by retrying.
        """
        entry = self._tools.get(call.name)
        if entry is None:
            known = ", ".join(sorted(self._tools)) or "(none)"
            raise ToolLoopError(
                f"the model called an unknown tool {call.name!r}",
                hint=f"registered tools: {known}",
            )

        async def execute() -> ToolResult:
            self.dispatched += 1
            try:
                output = entry.call(call.arguments)
                if inspect.isawaitable(output):
                    output = await output
            except Exception as exc:  # noqa: BLE001 — surfaced to the model
                return ToolResult(
                    call_id=call.id,
                    content=f"{type(exc).__name__}: {exc}",
                    is_error=True,
                )
            return ToolResult(call_id=call.id, content=_stringify(output))

        if self._memo is not None and self._memoizable(entry):
            arguments = json.dumps(
                call.arguments,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            key = f"{call.name}:{arguments}"
            return await self._memo.dispatch(key, call.id, execute)
        return await execute()

    def _memoizable(self, tool_entry: Tool) -> bool:
        """Whether this registry's arena policy permits memoizing a tool."""
        annotations = tool_entry.spec.annotations
        if self._memo_mode == "all":
            return True
        if self._memo_mode == "opt_in":
            return annotations.idempotent is True
        if self._memo_mode == "read_only":
            return annotations.read_only is True or annotations.idempotent is True
        return False


def _stringify(value: Any) -> str:
    """Render a tool's return value for the model."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def build_tool_turn(calls: Sequence[ToolCall], results: Sequence[ToolResult]) -> list[Message]:
    """Build the messages that close one tool round.

    The assistant's tool calls are echoed back before their results, because providers
    validate that every tool result answers a call in the preceding assistant turn.
    """
    messages: list[Message] = [Message(role="assistant", content=tuple(calls))]
    messages.extend(Message(role="tool", content=(result,)) for result in results)
    return messages
