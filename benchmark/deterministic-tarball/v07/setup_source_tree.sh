#!/bin/bash
set -euo pipefail

create_monorepo() {
    local base="$1"
    local nested
    local longname

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/manifest"
    cat > "$base/manifest/packages.txt" <<'EOF'
packages/app-shell
packages/inventory-service
packages/reporting-cli
EOF

    cat > "$base/README.md" <<'EOF'
# Warehouse Monorepo

Deterministic packaging fixture.
EOF

    cat > "$base/package.json" <<'EOF'
{
  "name": "warehouse-monorepo",
  "private": true,
  "packageManager": "pnpm@9.1.0"
}
EOF

    cat > "$base/pnpm-lock.yaml" <<'EOF'
lockfileVersion: '9.0'
importers:
  .: {}
EOF

    cat > "$base/poetry.lock" <<'EOF'
[[package]]
name = "requests"
version = "2.32.0"
EOF

    mkdir -p "$base/.git/objects/pack"
    printf 'ref: refs/heads/main\n' > "$base/.git/HEAD"
    touch "$base/.git/objects/pack/pack-test.idx"

    mkdir -p "$base/scripts"
    printf '#!/bin/bash\necho "release"\n' > "$base/scripts/release.sh"
    chmod 0755 "$base/scripts/release.sh"

    mkdir -p "$base/config"
    printf 'name: reporting\nlevel: stable\n' > "$base/config/reporting.yml"
    printf 'LEGACY=1\r\nKEEP_CRLF=1\r\n' > "$base/config/legacy.env"

    mkdir -p "$base/notes"
    printf 'outside manifest stays crlf\r\nsecond line\r\n' > "$base/notes/external-crlf.txt"

    mkdir -p "$base/packages/app-shell/src" "$base/packages/app-shell/dist/assets" \
        "$base/packages/app-shell/coverage/html" "$base/packages/app-shell/.venv/bin" \
        "$base/packages/app-shell/tmp/cache" "$base/packages/app-shell/.cache/state" \
        "$base/packages/app-shell/dist/tmp" "$base/packages/app-shell/secrets"
    printf 'export const main = () => "app-shell";\r\n' > "$base/packages/app-shell/src/index.ts"
    printf '# App Shell\r\n\r\nWindows endings here.\r\n' > "$base/packages/app-shell/README.md"
    printf 'console.log("bundle");\n' > "$base/packages/app-shell/dist/app.js"
    printf '{\r\n  "build": "2026-06-03",\r\n  "target": "prod"\r\n}\r\n' > "$base/packages/app-shell/dist/assets/build-info.json"
    printf 'temporary bundle\n' > "$base/packages/app-shell/dist/tmp/debug.tmp"
    printf 'lcov noise\n' > "$base/packages/app-shell/coverage/html/index.html"
    printf '#!/bin/sh\nexit 0\n' > "$base/packages/app-shell/.venv/bin/activate"
    printf 'remove me\n' > "$base/packages/app-shell/tmp/cache/session.log"
    printf 'cached data\n' > "$base/packages/app-shell/.cache/state/store.json"
    printf 'deploy_token=shh\n' > "$base/packages/app-shell/secrets/deploy.key"
    chmod 0600 "$base/packages/app-shell/secrets/deploy.key"
    printf 'with spaces\r\n' > "$base/packages/app-shell/src/file with spaces.txt"
    printf 'special chars\r\n' > "$base/packages/app-shell/src/file\$special!chars.md"

    mkdir -p "$base/packages/inventory-service/src" "$base/packages/inventory-service/dist/wheels" \
        "$base/packages/inventory-service/dist/data" "$base/packages/inventory-service/coverage/raw" \
        "$base/packages/inventory-service/.venv/lib" "$base/packages/inventory-service/temp/jobs" \
        "$base/packages/inventory-service/src/__pycache__" "$base/packages/inventory-service/keys"
    printf '#!/usr/bin/env python3\r\nprint("inventory")\r\n' > "$base/packages/inventory-service/src/main.py"
    chmod 0755 "$base/packages/inventory-service/src/main.py"
    printf 'from .main import run\r\n' > "$base/packages/inventory-service/src/__init__.py"
    printf 'bytecode\n' > "$base/packages/inventory-service/src/__pycache__/main.cpython-312.pyc"
    printf 'wheel-bytes\n' > "$base/packages/inventory-service/dist/wheels/inventory_service-1.4.2-py3-none-any.whl"
    printf 'id,value\n1,42\n' > "$base/packages/inventory-service/dist/data/export.csv"
    printf 'job temp\n' > "$base/packages/inventory-service/temp/jobs/run.log"
    printf 'coverage noise\n' > "$base/packages/inventory-service/coverage/raw/coverage.log"
    printf 'venv noise\n' > "$base/packages/inventory-service/.venv/lib/site.py"
    printf 'top secret\n' > "$base/packages/inventory-service/keys/service.pem"
    chmod 0600 "$base/packages/inventory-service/keys/service.pem"
    printf 'object file\n' > "$base/packages/inventory-service/src/module.o"
    printf 'Text line\nBinary: \x00\x01\x02\n' > "$base/packages/inventory-service/dist/data/mixed.bin"

    nested="$base/packages/inventory-service/dist/deep"
    for _ in {1..22}; do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    printf 'deep inventory payload\n' > "$nested/final.txt"

    mkdir -p "$base/packages/reporting-cli/bin" "$base/packages/reporting-cli/dist/templates" \
        "$base/packages/reporting-cli/dist/reports" "$base/packages/reporting-cli/coverage/unit" \
        "$base/packages/reporting-cli/.venv/cache" "$base/packages/reporting-cli/tmp/output"
    printf '#!/bin/bash\necho report\n' > "$base/packages/reporting-cli/bin/report.sh"
    chmod 0755 "$base/packages/reporting-cli/bin/report.sh"
    printf 'title: weekly summary\r\nowner: ops\r\n' > "$base/packages/reporting-cli/dist/templates/default.yaml"
    printf 'quarterly data\n' > "$base/packages/reporting-cli/dist/reports/q2.txt"
    printf 'coverage result\n' > "$base/packages/reporting-cli/coverage/unit/index.txt"
    printf 'venv cache\n' > "$base/packages/reporting-cli/.venv/cache/wheels.txt"
    printf 'tmp output\n' > "$base/packages/reporting-cli/tmp/output/build.tmp"
    ln -s ../../config/reporting.yml "$base/packages/reporting-cli/current-config"
    ln -s /etc/hostname "$base/packages/reporting-cli/host-link"

    mkdir -p "$base/packages/shared-ui/dist/chunks" "$base/packages/shared-ui/docs"
    printf 'shared ui is not manifest-scoped\r\n' > "$base/packages/shared-ui/docs/guide.txt"
    printf 'chunk outside manifest\n' > "$base/packages/shared-ui/dist/chunks/runtime.js"

    mkdir -p "$base/vendor/reference-data"
    printf 'vendor readme\r\n' > "$base/vendor/reference-data/README.txt"

    longname='release_notes_for_a_very_large_generated_artifact_that_should_still_be_kept_even_when_the_tree_contains_hundreds_of_files_and_complex_paths_to_exercise_gnu_tar_handling_with_long_names_and_monorepo_layouts.txt'
    printf 'long generated artifact\r\n' > "$base/packages/app-shell/dist/assets/$longname"

    for i in $(seq 1 120); do
        printf 'console.log("chunk %03d");\n' "$i" > "$base/packages/app-shell/dist/assets/chunk-$i.js"
    done

    for i in $(seq 1 90); do
        printf 'artifact %03d\n' "$i" > "$base/packages/inventory-service/dist/data/generated-$i.txt"
    done

    for i in $(seq 1 60); do
        printf 'report %03d\r\n' "$i" > "$base/packages/reporting-cli/dist/reports/report-$i.txt"
    done

    touch "$base/packages/app-shell/src/readonly.txt"
    chmod 0444 "$base/packages/app-shell/src/readonly.txt"
    touch -t 199901010000 "$base/packages/app-shell/src/index.ts"
    touch -t 203012312359 "$base/packages/reporting-cli/dist/reports/q2.txt"
}

create_monorepo /app/src
echo "Created monorepo fixture at /app/src"
