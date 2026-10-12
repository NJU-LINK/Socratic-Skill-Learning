#!/usr/bin/env python3
"""Toolchain-verified proto3<->Python bindings probe (kv-store-grpc family).

Generated-code behavior (exception classes, dict-kwarg conversion, presence
semantics) is BACKEND-SPECIFIC. This probe re-validates every claim of the
SKILL.md "proto3 <-> Python bindings reference" against the CURRENT toolchain,
so a variant re-runs it in one invocation after pinning its own
grpcio-tools/protobuf versions.

Verified on: grpcio-tools 1.73.0, protobuf 6.33.6 (upb backend),
Python 3.13.1. Findings that corrected earlier teaching:
  * repeated-field reassignment raises AttributeError (not TypeError), message
    "Assignment not allowed to map, or repeated field ..."
  * map-container reassignment raises the same AttributeError family
  * nested-message constructor DOES accept a dict kwarg on upb (converted);
    unknown dict keys raise ValueError ("Protocol message ... has no ...")
  * scalar HasField raises ValueError ("... does not have presence.")
19 claims total. Negative expectations never abort the suite: expect_error
captures ANY exception, classifies it, and records the actual class+message.

Usage:  python3 bindings_probe.py     # requires grpcio-tools installed
(If you extend the suite, update this count to match the reported n/n.)
"""
import os
import subprocess
import sys
import tempfile

PROBE_PROTO = '''\
syntax = "proto3";
package probe;
enum Color { RED = 0; GREEN = 1; BLUE = 2; }
message Inner { string name = 1; }
message Outer {
  Color color = 1;
  repeated int32 xs = 2;
  repeated Inner items = 3;
  Inner inner = 4;
  map<string, int32> counts = 5;
  oneof choice { string a = 6; int32 b = 7; }
}
'''


def main():
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")

    def expect_error(name, fn, *classes):
        """Capture ANY exception, classify it, never abort the suite."""
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            got = type(exc)
            check(name, got in classes, f"{got.__name__}: {str(exc)[:70]}")
            return
        check(name, False, "no exception raised")

    with tempfile.TemporaryDirectory() as d:
        proto_path = os.path.join(d, "probe.proto")
        with open(proto_path, "w") as fh:
            fh.write(PROBE_PROTO)
        subprocess.run(
            [sys.executable, "-m", "grpc_tools.protoc",
             f"-I{d}", f"--python_out={d}", proto_path],
            check=True,
        )
        sys.path.insert(0, d)
        import probe_pb2 as p  # noqa: PLC0415

        # --- enums ---------------------------------------------------------
        check("Enum.GREEN == 1 (plain int)", p.Color.GREEN == 1, f"{p.Color.GREEN!r}")
        check("Enum.Name(2) == 'BLUE'", p.Color.Name(2) == "BLUE", p.Color.Name(2))
        check("Enum.Value('RED') == 0", p.Color.Value("RED") == 0, p.Color.Value("RED"))
        o = p.Outer(color=7)
        o2 = p.Outer.FromString(o.SerializeToString())
        check("open enum: undeclared int 7 round-trips", o2.color == 7, f"color={o2.color}")
        check("enum getter returns int", isinstance(o2.color, int), type(o2.color).__name__)

        # --- repeated scalar ----------------------------------------------
        o = p.Outer(xs=[1, 2])
        check("ctor accepts keyword list for repeated", list(o.xs) == [1, 2], list(o.xs))
        expect_error("repeated reassignment raises", lambda: setattr(o, "xs", [3]), AttributeError)
        o.xs.append(3)
        check("repeated .append() works", list(o.xs) == [1, 2, 3], list(o.xs))

        # --- repeated composite --------------------------------------------
        o = p.Outer()
        it = o.items.add()
        it.name = "x"
        check("repeated composite .add() returns submessage", o.items[0].name == "x", o.items[0].name)

        # --- nested message ------------------------------------------------
        o = p.Outer(inner=p.Inner(name="n"))
        check("nested ctor takes message INSTANCE", o.inner.name == "n", o.inner.name)
        o = p.Outer(inner={"name": "n"})
        check("nested ctor ALSO accepts dict kwarg (converted on upb)",
              o.inner.name == "n", f"name={o.inner.name!r}")
        expect_error("nested ctor rejects dict with UNKNOWN key",
                     lambda: p.Outer(inner={"nope": 1}), ValueError)

        # --- map ------------------------------------------------------------
        o = p.Outer()
        o.counts["k"] = 5
        check("map is MutableMapping (assign/items)",
              o.counts["k"] == 5 and dict(o.counts.items()) == {"k": 5}, dict(o.counts.items()))
        expect_error("map container reassign raises", lambda: setattr(o, "counts", {"x": 1}), AttributeError)

        # --- presence --------------------------------------------------------
        o = p.Outer()
        check("unset message field HasField False", o.HasField("inner") is False, "")
        o.inner.name = "x"
        check("set message field HasField True", o.HasField("inner") is True, "")
        expect_error("scalar HasField raises", lambda: o.HasField("color"), ValueError)
        o.a = "hi"
        check("WhichOneof -> 'a'", o.WhichOneof("choice") == "a", o.WhichOneof("choice"))
        check("unset oneof -> None", p.Outer().WhichOneof("choice") is None, "")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} probes passed; failures: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())