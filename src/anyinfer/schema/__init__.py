"""Structured-output subsystem: mechanism choice, projection, validation, repair."""

from ..types.requests import SchemaSpec
from .mechanism import SCHEMA_PROMPT_TEMPLATE, choose_mechanism, system_prompt_for
from .project import ITEM_LIMIT_THRESHOLD, identity_projection, repetition_safe_projection
from .repair import REPAIR_PROMPT, build_repair_messages
from .validate import MAX_REPORTED_ERRORS, extract_json, format_errors, validate

__all__ = [
    "ITEM_LIMIT_THRESHOLD",
    "MAX_REPORTED_ERRORS",
    "REPAIR_PROMPT",
    "SCHEMA_PROMPT_TEMPLATE",
    "SchemaSpec",
    "build_repair_messages",
    "choose_mechanism",
    "extract_json",
    "format_errors",
    "identity_projection",
    "repetition_safe_projection",
    "system_prompt_for",
    "validate",
]
