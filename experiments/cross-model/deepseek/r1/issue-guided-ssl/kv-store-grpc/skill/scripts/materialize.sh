#!/usr/bin/env bash
# materialize.sh — instantiate template fills into clean, runnable files.
#
# Usage:
#   materialize.sh <out_dir>                  # frozen v01 package templates
#   materialize.sh <out_dir> <template_dir>   # variant templates (your copies)
#   KV_TMPL_DIR=<dir> materialize.sh <out_dir>   # same as the 2-arg form
#
# Strips the SLOT fill-guide header block and every inline SLOT annotation
# deterministically, so a solver never hand-strips template markers (the
# iteration-2 trajectory showed hand-stripping silently lost
# `syntax = "proto3";`). Output names: canonical kv-store.proto / server.py
# for the standard template names; for other explicit-source template names
# the .tmpl suffix is stripped.
#
# TOPOLOGY RULE (variant path): the frozen package tree (e.g. /skill) is
# READ-ONLY — never edit templates in place. For a variant, copy
# service.proto.tmpl + server.py.tmpl into a scratch dir, refill the
# SLOT-marked lines IN THE COPIES (service name, RPC list, message fields,
# module names, port), then run THIS SCRIPT with the scratch dir as the
# explicit template source.
#
# Assertion policy:
#   - default (frozen v01) sources: COMPLETE v01 gates — all four RPC lines
#     plus class/registrar/thread-pool/wait_for_termination needles — so a
#     future package edit cannot silently amputate the seed;
#   - explicit template_dir: STRUCTURAL family invariants only (syntax +
#     >=1 service + >=1 rpc for the proto; class +
#     add_<X>Servicer_to_server + ThreadPoolExecutor +
#     wait_for_termination for the server), so any in-family variant passes
#     without pretending to validate variant-specific names.
set -euo pipefail

pkg="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${1:?usage: materialize.sh <out_dir> [template_dir]}"
tmpl_dir="${2:-${KV_TMPL_DIR:-$pkg/templates}}"

python3 - "$pkg" "$out" "$tmpl_dir" <<'PY'
import glob, os, re, sys

pkg, out, tmpl_dir = sys.argv[1], sys.argv[2], sys.argv[3]
DEFAULT_SOURCES = (os.path.realpath(tmpl_dir) == os.path.realpath(os.path.join(pkg, "templates")))


def strip_slots(text):
    """Remove the ==== fill-guide header block and all inline SLOT: … tails,
    keeping every code/schema line otherwise intact."""
    lines = []
    in_header = False
    for ln in text.splitlines():
        if ln.startswith("// ====") or ln.startswith("# ===="):
            in_header = not in_header
            continue
        if in_header:
            continue
        ln = re.sub(r"\s*(//|#)\s*SLOT:.*$", "", ln)
        lines.append(ln)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)) + "\n"


def pick(canonical, glob_pat):
    """Prefer the canonical template filename; else any matching template."""
    can = os.path.join(tmpl_dir, canonical)
    if os.path.exists(can):
        return can
    hits = sorted(glob.glob(os.path.join(tmpl_dir, glob_pat)))
    return hits[0] if hits else None


def load(canonical, glob_pat, canonical_out):
    path = pick(canonical, glob_pat)
    if path is None:
        sys.exit("FATAL: no template matching %s in %s" % (glob_pat, tmpl_dir))
    with open(path) as f:
        text = strip_slots(f.read())
    base = os.path.basename(path)
    base = base[:-5] if base.endswith(".tmpl") else base
    out_name = canonical_out if base in ("service.proto", "server.py") else base
    return out_name, text


proto_name, ptext = load("service.proto.tmpl", "*.proto.tmpl", "kv-store.proto")
server_name, stext = load("server.py.tmpl", "*.py.tmpl", "server.py")

if DEFAULT_SOURCES:
    # Complete gates for the frozen v01 seed fill.
    for needle in ('syntax = "proto3";', "service KVStore",
                   "rpc Put(PutRequest)", "rpc Fetch(FetchRequest)",
                   "rpc Delete(DeleteRequest)", "rpc ListNamespaceTotal(ListNamespaceTotalRequest)"):
        assert needle in ptext, "materialized proto lost: %s" % needle
    for needle in ("class Server(", "add_KVStoreServicer_to_server",
                   "wait_for_termination()", "ThreadPoolExecutor"):
        assert needle in stext, "materialized server lost: %s" % needle
else:
    # Structural family invariants — variant-safe.
    assert 'syntax = "proto3";' in ptext, "materialized proto lost: syntax"
    assert re.search(r"^\s*service\s+\w+\s*\{", ptext, re.M), "materialized proto lost: service"
    assert re.search(r"^\s*rpc\s+\w+", ptext, re.M), "materialized proto lost: rpc"
    assert re.search(r"^\s*class\s+\w+", stext, re.M), "materialized server lost: class"
    assert re.search(r"add_\w+Servicer_to_server\s*\(", stext), "materialized server lost: registrar"
    assert "wait_for_termination()" in stext, "materialized server lost: wait_for_termination"
    assert "ThreadPoolExecutor" in stext, "materialized server lost: ThreadPoolExecutor"

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, proto_name), "w") as f:
    f.write(ptext)
with open(os.path.join(out, server_name), "w") as f:
    f.write(stext)
print("materialized %s and %s (sources: %s)" % (os.path.join(out, proto_name), os.path.join(out, server_name), tmpl_dir))
PY