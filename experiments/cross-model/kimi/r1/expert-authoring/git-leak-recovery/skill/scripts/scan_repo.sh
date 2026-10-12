#!/usr/bin/env bash
# scan_repo.sh REPO [PATTERN]
#
# Universal leak locator. Scans EVERY object in EVERY git object database
# under REPO (reachable, unreachable, packed, loose, nested repos, submodule
# gitdirs) plus plaintext files in git metadata, and prints every hit with
# the extracted secret value and where the tainted object is referenced.
#
# Default PATTERN is the BRE  secret\[
#
# Nothing in git storage escapes this scan except objects reachable only via
# replace-ref indirection; those are reported separately below.
set -u
REPO="${1:-.}"
PATTERN="${2:-secret\[}"
EXTRACT="${PATTERN}[^]]*]"

gitdirs() {
  # Any directory that contains HEAD and objects/ is a gitdir. This catches
  # the main .git, nested repositories, and .git/modules/* submodule stores.
  find "$REPO" -name HEAD -type f 2>/dev/null | while read -r h; do
    gd=$(dirname "$h")
    [ -d "$gd/objects" ] && printf '%s\n' "$gd"
  done | sort -u
}

echo "=== object databases under $REPO ==="
gitdirs

echo "=== scanning all objects (reachable + unreachable) ==="
gitdirs | while read -r gd; do
  GIT_DIR="$gd" git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null |
  while read -r oid otype; do
    if GIT_DIR="$gd" git cat-file -p "$oid" 2>/dev/null | grep -aq "$PATTERN"; then
      echo "HIT $otype $oid   (gitdir: $gd)"
      GIT_DIR="$gd" git cat-file -p "$oid" 2>/dev/null | grep -ao "$EXTRACT" | sort -u | sed 's/^/    value: /'
      # Where is it referenced from?
      case "$otype" in
        blob)
          git -C "$REPO" rev-list --objects --all 2>/dev/null | grep "^$oid" | awk '{print "    path (reachable): "$2}'
          git -C "$REPO" ls-files -s 2>/dev/null | grep "$oid" | awk '{print "    path (INDEX/staged): "$4}'
          git -C "$REPO" log --all --oneline --find-object="$oid" 2>/dev/null | sed 's/^/    touched-by-commit: /'
          ;;
        commit)
          git -C "$REPO" branch --all --contains "$oid" 2>/dev/null | sed 's/^/    on-branch: /'
          git -C "$REPO" tag --contains "$oid" 2>/dev/null | sed 's/^/    in-tag-history: /'
          git -C "$REPO" stash list 2>/dev/null | grep -q . && GIT_DIR="$gd" git rev-parse -q --verify refs/stash 2>/dev/null | grep -q "$oid" && echo "    referenced by stash"
          ;;
      esac
    fi
  done
done

echo "=== plaintext leftovers in git metadata (reflogs, COMMIT_EDITMSG, packed-refs...) ==="
gitdirs | while read -r gd; do
  grep -ral "$PATTERN" "$gd" 2>/dev/null | grep -v '/objects/' | sed 's/^/    file: /'
done

echo "=== live worktree files ==="
grep -ral --exclude-dir=.git "$PATTERN" "$REPO" 2>/dev/null | sed 's/^/    file: /'

echo "=== structural inventory (decide cleanup from this) ==="
for gd in $(gitdirs); do
  echo "--- $gd ---"
  GIT_DIR="$gd" git stash list 2>/dev/null | sed 's/^/    stash: /'
  GIT_DIR="$gd" git replace -l 2>/dev/null | sed 's/^/    replace-ref: /'
  GIT_DIR="$gd" git for-each-ref 2>/dev/null | sed 's/^/    ref: /'
  GIT_DIR="$gd" git reflog 2>/dev/null | head -20 | sed 's/^/    reflog: /'
  [ -f "$gd/objects/info/alternates" ] && echo "    ALTERNATES: $(cat "$gd/objects/info/alternates")"
  [ -d "$gd/lost-found" ] && ls "$gd/lost-found" 2>/dev/null | sed 's/^/    lost-found: /'
done
