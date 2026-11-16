"""Core serialization logic for W3C Trace Context and Baggage headers.

This module deliberately stays close to the W3C specifications so that the
caller can decide policy (sampling, validation strictness) rather than the
library baking it in. The one policy choice made here is that parsing is
strict: malformed headers raise instead of returning partial data, because a
silently dropped trace id is much harder to debug than an exception at the
boundary where the header arrived.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class TraceContextError(ValueError):
    """Raised when a traceparent or tracestate header is malformed."""


class BaggageError(ValueError):
    """Raised when a baggage header is malformed."""


# W3C Trace Context: version(2) "-" trace-id(32) "-" parent-id(16) "-" flags(2)
_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-"
    r"(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-"
    r"(?P<flags>[0-9a-f]{2})$"
)

# Version 00 has no trailing fields; ff is forbidden by the spec.
_VERSION_FORBIDDEN = "ff"

_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _is_hex(value: str) -> bool:
    return bool(value) and _HEX_RE.match(value) is not None


@dataclass(frozen=True)
class TraceContext:
    """A parsed W3C trace context.

    ``trace_id`` and ``span_id`` are stored as lowercase hex strings without
    separators, matching the wire format exactly so that round-tripping is
    lossless. ``flags`` is kept as an integer so callers can test the sampled
    bit with a bitwise AND instead of string comparison.
    """

    version: str
    trace_id: str
    span_id: str
    flags: int

    @property
    def sampled(self) -> bool:
        """True when the least significant flag bit is set."""
        return bool(self.flags & 0x01)


def format_traceparent(ctx: TraceContext) -> str:
    """Serialize a :class:`TraceContext` to a traceparent header value.

    The version is preserved as given so that future versions carrying extra
    fields are not silently downgraded to ``00``.
    """
    if not _is_hex(ctx.version) or len(ctx.version) != 2:
        raise TraceContextError("version must be two lowercase hex digits")
    if ctx.version == _VERSION_FORBIDDEN:
        raise TraceContextError("version ff is reserved and must not be used")
    if not _is_hex(ctx.trace_id) or len(ctx.trace_id) != 32:
        raise TraceContextError("trace_id must be 32 lowercase hex digits")
    if ctx.trace_id == "0" * 32:
        raise TraceContextError("trace_id must not be all zeroes")
    if not _is_hex(ctx.span_id) or len(ctx.span_id) != 16:
        raise TraceContextError("span_id must be 16 lowercase hex digits")
    if ctx.span_id == "0" * 16:
        raise TraceContextError("span_id must not be all zeroes")
    if not 0 <= ctx.flags <= 0xFF:
        raise TraceContextError("flags must fit in one byte")
    return "{}-{}-{}-{:02x}".format(
        ctx.version, ctx.trace_id, ctx.span_id, ctx.flags
    )


def parse_traceparent(value: str) -> TraceContext:
    """Parse a traceparent header value.

    Only version ``00`` is fully understood; higher versions are accepted as
    long as their first four fields match the v00 layout, which is what the
    spec requires of forward-compatible parsers.
    """
    if not isinstance(value, str):
        raise TraceContextError("traceparent must be a string")
    match = _TRACEPARENT_RE.match(value)
    if match is None:
        raise TraceContextError("traceparent does not match the W3C layout")
    version = match.group("version")
    if version == _VERSION_FORBIDDEN:
        raise TraceContextError("version ff is forbidden")
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if trace_id == "0" * 32:
        raise TraceContextError("trace_id must not be all zeroes")
    if span_id == "0" * 16:
        raise TraceContextError("span_id must not be all zeroes")
    flags = int(match.group("flags"), 16)
    return TraceContext(
        version=version, trace_id=trace_id, span_id=span_id, flags=flags
    )


@dataclass(frozen=True)
class BaggageEntry:
    """A single baggage member: a key, a value, and optional properties.

    Properties are stored as a tuple of ``(key, value)`` pairs to keep the
    dataclass hashable and to preserve ordering, which matters because the
    spec does not require a canonical property order.
    """

    key: str
    value: str
    properties: Tuple[Tuple[str, str], ...] = ()

    def property_dict(self) -> Dict[str, str]:
        """Return properties as a dict, last write winning on duplicates."""
        return dict(self.properties)


_BAGGAGE_KEY_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]+$")


def _percent_decode(value: str) -> str:
    """Decode %XX escapes, raising on malformed sequences.

    ``urllib.parse.unquote`` is lenient and leaves bad escapes untouched,
    which would let a malformed header through unnoticed. We decode by hand
    so that a stray ``%`` is a hard error.
    """
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "%":
            if i + 2 >= len(value) + 1:
                raise BaggageError("truncated percent escape")
            hex_part = value[i + 1 : i + 3]
            if len(hex_part) != 2 or not _is_hex(hex_part.lower()):
                raise BaggageError("invalid percent escape")
            out.append(chr(int(hex_part, 16)))
            i += 3
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_UNRESERVED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
)


def _percent_encode(value: str) -> str:
    """Encode everything outside the unreserved set.

    The baggage spec allows a wider set than RFC 3986 unreserved, but encoding
    more than strictly necessary is always valid and avoids a second table.
    """
    out = []
    for ch in value:
        if ch in _UNRESERVED:
            out.append(ch)
        else:
            for byte in ch.encode("utf-8"):
                out.append("%{:02X}".format(byte))
    return "".join(out)


def format_baggage(entries: List[BaggageEntry]) -> str:
    """Serialize baggage entries to a header value.

    Entries are joined with ``,`` and properties with ``;``. Values and
    property values are percent-encoded; keys and property keys are not,
    because the spec restricts them to a token-safe alphabet already.
    """
    parts = []
    for entry in entries:
        if not _BAGGAGE_KEY_RE.match(entry.key):
            raise BaggageError("invalid baggage key: {!r}".format(entry.key))
        piece = "{}={}".format(entry.key, _percent_encode(entry.value))
        for prop_key, prop_value in entry.properties:
            if not _BAGGAGE_KEY_RE.match(prop_key):
                raise BaggageError(
                    "invalid baggage property key: {!r}".format(prop_key)
                )
            piece += ";{}={}".format(prop_key, _percent_encode(prop_value))
        parts.append(piece)
    return ",".join(parts)


def parse_baggage(value: str) -> List[BaggageEntry]:
    """Parse a baggage header value into a list of entries.

    Empty members produced by stray commas are skipped rather than rejected,
    because real proxies do emit them and the spec says receivers may ignore
    them. Everything else that is malformed raises.
    """
    if value is None:
        raise BaggageError("baggage must be a string")
    if value == "":
        return []
    entries: List[BaggageEntry] = []
    for raw_member in value.split(","):
        member = raw_member.strip()
        if member == "":
            continue
        segments = member.split(";")
        head = segments[0].strip()
        if "=" not in head:
            raise BaggageError("baggage member missing '='")
        key, _, raw_value = head.partition("=")
        key = key.strip()
        if not _BAGGAGE_KEY_RE.match(key):
            raise BaggageError("invalid baggage key: {!r}".format(key))
        decoded_value = _percent_decode(raw_value.strip())
        properties: List[Tuple[str, str]] = []
        for segment in segments[1:]:
            segment = segment.strip()
            if segment == "":
                continue
            if "=" not in segment:
                raise BaggageError("baggage property missing '='")
            prop_key, _, prop_raw = segment.partition("=")
            prop_key = prop_key.strip()
            if not _BAGGAGE_KEY_RE.match(prop_key):
                raise BaggageError(
                    "invalid baggage property key: {!r}".format(prop_key)
                )
            properties.append((prop_key, _percent_decode(prop_raw.strip())))
        entries.append(
            BaggageEntry(key=key, value=decoded_value, properties=tuple(properties))
        )
    return entries
