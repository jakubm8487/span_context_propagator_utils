"""Utilities for serializing and deserializing W3C Trace Context and Baggage headers."""

from .core import (
    TraceContext,
    BaggageEntry,
    parse_traceparent,
    format_traceparent,
    parse_baggage,
    format_baggage,
    TraceContextError,
    BaggageError,
)

__all__ = [
    "TraceContext",
    "BaggageEntry",
    "parse_traceparent",
    "format_traceparent",
    "parse_baggage",
    "format_baggage",
    "TraceContextError",
    "BaggageError",
]
