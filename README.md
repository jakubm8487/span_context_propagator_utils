# span_context_propagator_utils

Serializes and deserializes `trace_id`, `span_id`, and flags into and from W3C
Trace Context (`traceparent`) and Baggage header values.

```python
from span_context_propagator_utils import (
    BaggageEntry,
    TraceContext,
    format_baggage,
    format_traceparent,
    parse_baggage,
    parse_traceparent,
)

ctx = parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
assert ctx.sampled
assert format_traceparent(ctx) == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

entries = parse_baggage("user=alice;tier=gold,note=a%20b")
assert entries[0] == BaggageEntry(key="user", value="alice", properties=(("tier", "gold"),))
assert format_baggage(entries) == "user=alice;tier=gold,note=a%20b"
```

## Why this exists

Trace context and baggage travel as plain strings on the wire, and the two
formats have opposite failure modes. A traceparent is fixed-width and easy to
validate; baggage is a comma-separated list where values may be percent-encoded
and may carry semicolon-delimited properties. Reimplementing both at each
service boundary invites drift, so this library centralises the parsing and
formatting with one deliberate trade-off: **parsing is strict**. A malformed
traceparent or baggage member raises `TraceContextError` or `BaggageError`
rather than returning partial data, because a silently dropped trace id is far
harder to debug than an exception at the point the header arrived.

## The awkward edge

Baggage members are separated by `,` and properties by `;`, but both characters
are also legal inside percent-encoded values. This library encodes anything
outside the RFC 3986 unreserved set when formatting, and rejects malformed
percent escapes when parsing instead of passing them through. That means a
header produced by a lenient peer, for example one containing a bare `%`, will
raise rather than round-trip. Version `ff` of traceparent is reserved by the
spec and is rejected on both parse and format; unknown non-`ff` versions are
accepted and preserved so a forward-compatible proxy does not downgrade them.
