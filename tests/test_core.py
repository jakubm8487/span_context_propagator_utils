import unittest

from span_context_propagator_utils import (
    BaggageEntry,
    BaggageError,
    TraceContext,
    TraceContextError,
    format_baggage,
    format_traceparent,
    parse_baggage,
    parse_traceparent,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


class TraceparentTests(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        header = "00-{}-{}-01".format(TRACE_ID, SPAN_ID)
        ctx = parse_traceparent(header)
        self.assertEqual(ctx.version, "00")
        self.assertEqual(ctx.trace_id, TRACE_ID)
        self.assertEqual(ctx.span_id, SPAN_ID)
        self.assertEqual(ctx.flags, 1)
        self.assertTrue(ctx.sampled)
        self.assertEqual(format_traceparent(ctx), header)

    def test_unsampled_flag(self):
        ctx = parse_traceparent("00-{}-{}-00".format(TRACE_ID, SPAN_ID))
        self.assertEqual(ctx.flags, 0)
        self.assertFalse(ctx.sampled)

    def test_unknown_version_is_accepted(self):
        ctx = parse_traceparent("01-{}-{}-01".format(TRACE_ID, SPAN_ID))
        self.assertEqual(ctx.version, "01")
        self.assertEqual(format_traceparent(ctx), "01-{}-{}-01".format(TRACE_ID, SPAN_ID))

    def test_version_ff_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("ff-{}-{}-01".format(TRACE_ID, SPAN_ID))

    def test_all_zero_trace_id_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("00-{}-{}-01".format("0" * 32, SPAN_ID))

    def test_all_zero_span_id_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("00-{}-{}-01".format(TRACE_ID, "0" * 16))

    def test_uppercase_hex_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("00-{}-{}-01".format(TRACE_ID.upper(), SPAN_ID))

    def test_wrong_length_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("00-{}-{}-01".format(TRACE_ID[:-1], SPAN_ID))

    def test_trailing_junk_rejected(self):
        with self.assertRaises(TraceContextError):
            parse_traceparent("00-{}-{}-01-extra".format(TRACE_ID, SPAN_ID))

    def test_format_rejects_zero_flags_overflow(self):
        ctx = TraceContext(
            version="00", trace_id=TRACE_ID, span_id=SPAN_ID, flags=0x100
        )
        with self.assertRaises(TraceContextError):
            format_traceparent(ctx)

    def test_format_rejects_zero_ids(self):
        ctx = TraceContext(
            version="00", trace_id="0" * 32, span_id=SPAN_ID, flags=0
        )
        with self.assertRaises(TraceContextError):
            format_traceparent(ctx)


class BaggageTests(unittest.TestCase):
    def test_round_trip_simple(self):
        entries = [BaggageEntry(key="user", value="alice")]
        header = format_baggage(entries)
        self.assertEqual(header, "user=alice")
        self.assertEqual(parse_baggage(header), entries)

    def test_round_trip_with_properties(self):
        entries = [
            BaggageEntry(
                key="user",
                value="alice",
                properties=(("tier", "gold"),),
            )
        ]
        header = format_baggage(entries)
        self.assertEqual(header, "user=alice;tier=gold")
        self.assertEqual(parse_baggage(header), entries)

    def test_percent_encoding_round_trip(self):
        entries = [BaggageEntry(key="note", value="a b,c=d")]
        header = format_baggage(entries)
        self.assertNotIn(" ", header)
        self.assertEqual(parse_baggage(header), entries)

    def test_multiple_members(self):
        entries = [
            BaggageEntry(key="a", value="1"),
            BaggageEntry(key="b", value="2", properties=(("x", "y"),)),
        ]
        header = format_baggage(entries)
        self.assertEqual(header, "a=1,b=2;x=y")
        self.assertEqual(parse_baggage(header), entries)

    def test_empty_header_yields_no_entries(self):
        self.assertEqual(parse_baggage(""), [])

    def test_stray_commas_are_skipped(self):
        entries = parse_baggage("a=1,,b=2,")
        self.assertEqual([e.key for e in entries], ["a", "b"])

    def test_missing_equals_rejected(self):
        with self.assertRaises(BaggageError):
            parse_baggage("novalue")

    def test_invalid_key_rejected(self):
        with self.assertRaises(BaggageError):
            parse_baggage("bad key=1")

    def test_truncated_percent_escape_rejected(self):
        with self.assertRaises(BaggageError):
            parse_baggage("a=%2")

    def test_invalid_percent_escape_rejected(self):
        with self.assertRaises(BaggageError):
            parse_baggage("a=%zz")

    def test_property_without_equals_rejected(self):
        with self.assertRaises(BaggageError):
            parse_baggage("a=1;flag")

    def test_format_rejects_invalid_key(self):
        with self.assertRaises(BaggageError):
            format_baggage([BaggageEntry(key="bad key", value="1")])

    def test_property_dict_last_write_wins(self):
        entry = BaggageEntry(
            key="a",
            value="1",
            properties=(("k", "first"), ("k", "second")),
        )
        self.assertEqual(entry.property_dict(), {"k": "second"})


if __name__ == "__main__":
    unittest.main()
