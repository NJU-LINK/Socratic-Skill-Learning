#!/bin/bash
set -euo pipefail

create_test_tree() {
    local base="$1"

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/src/bin" "$base/.cargo" "$base/docs" "$base/examples" "$base/scripts"

    printf 'fn main() {\r\n    println!("Task Author");\r\n}\r\n' > "$base/src/main.rs"
    cat > "$base/src/lib.rs" <<'EOF'
pub fn add(left: i32, right: i32) -> i32 {
    left + right
}
EOF
    cat > "$base/src/bin/tool.rs" <<'EOF'
fn main() {
    println!("tool");
}
EOF

    printf '[package]\r\nname = "deterministic-bundle"\r\nversion = "0.1.0"\r\nedition = "2021"\r\n\r\n[dependencies]\r\nserde = "1"\r\n' > "$base/Cargo.toml"
    printf 'version = 3\n\n[[package]]\nname = "deterministic-bundle"\nversion = "0.1.0"\n[[package]]\nname = "serde"\nversion = "1.0.0"\n' > "$base/Cargo.lock"
    printf '# Deterministic Rust Snapshot\r\n\r\nThis README intentionally uses CRLF endings.\r\n' > "$base/README.md"
    cat > "$base/.cargo/config.toml" <<'EOF'
[build]
target-dir = "target"
EOF

    cat > "$base/scripts/release.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
echo "release"
EOF
    chmod 0755 "$base/scripts/release.sh"

    cat > "$base/scripts/check-format" <<'EOF'
#!/bin/bash
set -euo pipefail
echo "fmt"
EOF
    chmod 0755 "$base/scripts/check-format"

    mkdir -p "$base/vendor/serde/src" "$base/vendor/rand/src"
    printf '[package]\nname = "serde"\nversion = "1.0.0"\n' > "$base/vendor/serde/Cargo.toml"
    printf 'pub fn serialize() {}\n' > "$base/vendor/serde/src/lib.rs"
    printf '[package]\nname = "rand"\nversion = "0.8.0"\n' > "$base/vendor/rand/Cargo.toml"
    printf 'pub fn rng() {}\n' > "$base/vendor/rand/src/lib.rs"
    printf '[[package]]\nname = "serde"\nversion = "1.0.0"\n' > "$base/vendor/Cargo.lock"

    mkdir -p "$base/target/debug/deps" "$base/target/tmp-cache"
    printf '\x7fELFfake-binary' > "$base/target/debug/app"
    touch "$base/target/debug/deps/libserde.rlib"
    printf 'transient build notes\n' > "$base/target/debug/build.log.tmp"

    mkdir -p "$base/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin"
    printf 'cached toolchain metadata\n' > "$base/.rustup/settings.toml"
    touch "$base/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/bin/rustc"

    mkdir -p "$base/benchmarks/results" "$base/tmp"
    printf 'sample,tmp,data\n' > "$base/benchmarks/results/run-001.csv.tmp"
    printf 'temporary output\n' > "$base/tmp/scratch.tmp"

    mkdir -p "$base/docs/generated" "$base/build-cache"
    printf 'Generated API docs\n' > "$base/docs/generated/api.md"
    printf 'cache data\n' > "$base/build-cache/state.db"
    ln -s ../docs/generated/api.md "$base/examples/api-doc.md"
    ln -s ../build-cache "$base/examples/build-cache"
    ln -s /var/tmp/external-cache "$base/examples/external-cache"

    touch "$base/src/file with spaces.rs"
    touch "$base/src/file\$macro\!name.rs"

    local longname="rust_source_file_with_a_name_that_is_far_longer_than_most_people_would_use_"
    longname="${longname}but_is_helpful_for_testing_archive_handling_of_very_long_paths_and_gnu_tar_"
    longname="${longname}support_inside_a_deeply_nested_tree_for_reproducible_builds.rs"
    touch "$base/src/$longname"

    local nested="$base/crates"
    for _ in {1..18}; do
        nested="$nested/nested"
        mkdir -p "$nested"
    done
    printf 'pub const DEPTH: usize = 18;\n' > "$nested/deep.rs"

    printf 'text before\nnull \x00 bytes\nafter\n' > "$base/assets.mixed"
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde' > "$base/logo.png"

    chmod 0644 "$base/src/main.rs" "$base/src/lib.rs" "$base/src/bin/tool.rs" "$base/Cargo.toml" "$base/Cargo.lock" "$base/README.md"
    touch -t 199901010000 "$base/src/main.rs"
    touch -t 203012312359 "$base/README.md"
}

create_test_tree /app/src
echo "Created Rust source tree at /app/src"
