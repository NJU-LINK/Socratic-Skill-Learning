#!/usr/bin/env bash
# verify_package.sh -- detect BYTE-LEVEL DRIFT in any shipped package file.
#
# HONEST SCOPE: this detects ACCIDENTAL drift -- transcription errors,
# stale copies, one-token typos that ship by mistake, edits made to a copy
# instead of the source. It is NOT a security boundary: anyone who can
# rewrite the shipped files can rewrite SHA256SUMS too, so adversarial
# tampering is out of scope. The trust anchor is the committed revision;
# this script only makes "faithful copy" checkable by any fresh consumer
# in one command, before anything is run.
#
# Usage (from the package root or anywhere):
#   bash scripts/verify_package.sh           # verify: exit 0 OK, 1 on drift
#   bash scripts/verify_package.sh --write   # author-only: regenerate the
#                                            # manifest after an INTENTIONAL
#                                            # package change
#
# The manifest hashes every shipped file except SHA256SUMS itself
# (self-hash is the irreducible anchor). Run it against the MOUNTED package
# copy -- for the accidental-drift class that is exactly the right target.
set -euo pipefail
cd "$(dirname "$0")/.."

FILES=(
  SKILL.md
  scripts/audioproc.py
  scripts/run_audio_pipeline.sh
  scripts/check_pipeline.py
  scripts/extract_peaks.awk
  scripts/verify_package.sh
)

if [ "${1:-}" = "--write" ]; then
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  for f in "${FILES[@]}"; do
    [ -f "$f" ] || { echo "MISSING: $f" >&2; exit 1; }
    sha256sum "$f"
  done > "$tmp"
  mv "$tmp" SHA256SUMS
  echo "SHA256SUMS regenerated ($(wc -l < SHA256SUMS) entries)."
  exit 0
fi

[ -f SHA256SUMS ] || {
  echo "MISSING SHA256SUMS -- run 'bash scripts/verify_package.sh --write' after an intentional change" >&2
  exit 1
}

# Normalize the manifest first: guarantee a trailing newline. Without it,
# the POSIX `while read` EOF gotcha silently drops the FINAL manifest entry
# (read returns nonzero at EOF, so the body never runs for a newline-less
# last line). Payload files are hashed by their real bytes, so this can
# never hide content drift -- it only fixes the manifest's own formatting.
norm="$(mktemp)"
tmp="$(mktemp)"
trap 'rm -f "$tmp" "$norm"' EXIT
if [ -n "$(tail -c 1 SHA256SUMS)" ]; then
  { cat SHA256SUMS; echo; } > "$norm"        # manifest lacks final newline
else
  cp SHA256SUMS "$norm"
fi

missing=0
while read -r _hash _path; do
  if [ ! -f "$_path" ]; then
    echo "MISSING FILE: $_path" >&2
    missing=1
    continue
  fi
  printf '%s  %s\n' "$(sha256sum "$_path" | cut -d' ' -f1)" "$_path"
done < "$norm" > "$tmp"
[ "$missing" -eq 0 ] || exit 1

if diff -u "$norm" "$tmp"; then
  echo "PACKAGE INTEGRITY OK"
  exit 0
else
  echo "PACKAGE DRIFT DETECTED (see diff above) -- every shipped file must match SHA256SUMS" >&2
  exit 1
fi