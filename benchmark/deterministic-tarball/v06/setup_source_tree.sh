#!/bin/bash
set -euo pipefail

base="/app/sdk"

rm -rf "$base"
mkdir -p \
    "$base/bin" \
    "$base/cache/generated/indexes" \
    "$base/docs" \
    "$base/examples" \
    "$base/include/sdk" \
    "$base/lib" \
    "$base/libexec" \
    "$base/tmp/session" \
    "$base/tools" \
    "$base/versions/2025.04/bin" \
    "$base/versions/2025.04/include/sdk" \
    "$base/versions/2025.04/lib" \
    "$base/versions/2025.04/share/doc/sdk" \
    "$base/versions/2025.04/share/examples"

mkdir -p "$base/.git/objects" "$base/keys" "$base/src/__pycache__"

printf '#!/usr/bin/env bash\r\nexport SDK_HOME="$(dirname "$0")/.."\r\necho sdk runtime\r\n' > "$base/versions/2025.04/bin/sdk-env.sh"
chmod 0755 "$base/versions/2025.04/bin/sdk-env.sh"

printf '#pragma once\r\n#define SDK_RELEASE "2025.04"\r\n' > "$base/versions/2025.04/include/sdk/api.h"
printf 'SDK overview\r\nUse the release build only.\r\n' > "$base/versions/2025.04/share/doc/sdk/guide.txt"
printf 'sample_config=true\n' > "$base/versions/2025.04/share/examples/default.conf"
printf 'notes: stable sdk\n' > "$base/docs/NOTES.md"
printf 'cache artifact\n' > "$base/cache/generated/indexes/current.json"
printf 'temporary scratch\n' > "$base/tmp/session/build.tmp"
printf 'compiled object placeholder\n' > "$base/tools/helper.o"
printf 'compiled python placeholder\n' > "$base/src/__pycache__/sdk.cpython-312.pyc"
printf 'internal token\n' > "$base/keys/release.token"
chmod 0600 "$base/keys/release.token"
printf 'ref: refs/heads/main\n' > "$base/.git/HEAD"
touch "$base/.git/objects/pack-placeholder"

printf 'Text before binary\n\x00\x01\x02after\n' > "$base/libexec/plugin.bin"
chmod 0755 "$base/libexec/plugin.bin"
printf '\x7fELFSDKpayload' > "$base/versions/2025.04/lib/libseedsdk.so.4.2.1"
chmod 0755 "$base/versions/2025.04/lib/libseedsdk.so.4.2.1"

touch "$base/docs/old-manifest.txt"
touch "$base/docs/future-manifest.txt"
chmod 0444 "$base/docs/old-manifest.txt"
touch -t 199812310101 "$base/docs/old-manifest.txt"
touch -t 203501020304 "$base/docs/future-manifest.txt"

segment1="components-with-very-long-identifiers-for-pax-validation"
segment2="sdk-assets-that-should-still-be-addressable-by-links"
segment3="release-build-containing-another-level-of-length-stress"
long_dir="$base/versions/2025.04/share/$segment1/$segment2/$segment3"
mkdir -p "$long_dir"
long_file="artifact-manifest-with-a-name-that-exceeds-the-usual-ustar-comfort-zone-and-requires-pax-handling.txt"
printf 'long path payload\r\nsecond line\r\n' > "$long_dir/$long_file"

ln -s ../versions/2025.04/bin/sdk-env.sh "$base/bin/sdk"
ln -s sdk "$base/bin/default-sdk"
ln -s default-sdk "$base/bin/current-sdk"
ln -s ../versions/2025.04/lib/libseedsdk.so.4.2.1 "$base/lib/libseedsdk.so.4"
ln -s libseedsdk.so.4 "$base/lib/libseedsdk.so"
ln -s ../../versions/2025.04/include/sdk "$base/include/current"
ln -s ../tmp/session "$base/examples/build-cache"
ln -s ../keys/release.token "$base/examples/dev-token-link"
ln -s ../docs/missing-release-notes.txt "$base/docs/latest-release-notes"
ln -s /opt/runtime/global-sdk.conf "$base/docs/system-sdk.conf"
ln -s ../versions/2025.04/share/$segment1/$segment2/$segment3/$long_file "$base/docs/long-manifest-link"
ln -s ../docs/long-manifest-link "$base/examples/duplicate-long-manifest-link"

echo "Created symlink-heavy SDK tree at $base"
