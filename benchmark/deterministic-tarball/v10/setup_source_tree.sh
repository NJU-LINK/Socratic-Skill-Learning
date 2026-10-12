#!/bin/bash
set -euo pipefail

create_site_tree() {
    local base="$1"
    local long_name
    local nested

    rm -rf "$base"
    mkdir -p "$base"

    mkdir -p "$base/public/assets/js" "$base/public/assets/css" "$base/public/assets/img"
    mkdir -p "$base/public/blog/2026/launch" "$base/public/downloads"
    mkdir -p "$base/themes/aurora/layouts" "$base/themes/aurora/partials"
    mkdir -p "$base/cgi-bin" "$base/.well-known/acme-challenge"
    mkdir -p "$base/drafts/posts" "$base/preview-cache/pages"
    mkdir -p "$base/.secrets" "$base/.cache" "$base/.config/site"

    printf '<!doctype html>\r\n<html>\r\n<body>\r\n<h1>Seed2Family</h1>\r\n</body>\r\n</html>\r\n' > "$base/public/index.html"
    printf 'body {\r\n  background: #f6f7fb;\r\n}\r\n' > "$base/public/assets/css/site.css"
    printf 'window.site = {"theme":"aurora"};\r\n' > "$base/public/assets/js/site.js"
    printf '{\r\n  "name": "aurora",\r\n  "version": 3\r\n}\r\n' > "$base/themes/aurora/theme.json"
    printf '<section>\nLaunch notes\n</section>\n' > "$base/public/blog/2026/launch/post.html"
    printf 'User-agent: *\nDisallow:\n' > "$base/public/robots.txt"
    printf 'token-for-acme\n' > "$base/.well-known/acme-challenge/site-token"

    printf '#!/usr/bin/env bash\r\nprintf "Content-Type: text/plain\\r\\n\\r\\n"\r\nprintf "status=ok\\n"\r\n' > "$base/cgi-bin/health-check"
    chmod 0755 "$base/cgi-bin/health-check"
    printf '%s\n' '#!/usr/bin/env python3' 'print("Content-Type: application/json\\n")' "print('{\"ok\": true}')" > "$base/cgi-bin/status.py"
    chmod 0700 "$base/cgi-bin/status.py"

    printf 'source map should be omitted\n' > "$base/public/assets/js/site.js.map"
    printf 'cached preview\n' > "$base/preview-cache/pages/home.html"
    printf 'draft copy\n' > "$base/drafts/posts/launch-plan.md"
    printf 'secret config\n' > "$base/.secrets/secret.txt"
    printf 'cache details\n' > "$base/.cache/cache.txt"
    printf 'hidden config\n' > "$base/.config/site/dev.json"

    printf 'PNG\x00\x01\x02\n' > "$base/public/assets/img/logo.bin"
    printf 'Download payload\n' > "$base/public/downloads/package.txt"
    printf 'Notes with spaces\n' > "$base/public/assets/js/file with spaces.js"
    printf 'console.log("special");\n' > "$base/public/assets/js/file\$special!chars.js"

    long_name="launch_notes_with_a_name_that_pushes_the_ustar_limits_without_crossing_them_"
    long_name="${long_name}for_reproducible_archiving_checks_and_path_sorting_expectations_"
    long_name="${long_name}inside_the_public_tree_documentation_reference_page.html"
    printf '<p>Long path content</p>\n' > "$base/public/${long_name}"

    nested="$base/public/deep"
    for i in $(seq 1 18); do
        nested="$nested/level-$i"
        mkdir -p "$nested"
    done
    printf '<p>Deep page</p>\n' > "$nested/final.html"

    ln -s ../index.html "$base/public/blog/home-link"
    ln -s ../../assets/css/site.css "$base/public/blog/2026/launch/site-style"
    ln -s /etc/hosts "$base/public/hosts-link"
    ln -s ../../themes/aurora/theme.json "$base/public/assets/theme-link.json"
    ln -s missing/preview.html "$base/public/broken-preview"
    ln -s ../drafts/posts/missing-plan.md "$base/public/drafts-link"
    ln -s ../public/index.html "$base/.well-known/index-link"

    chmod 0600 "$base/public/robots.txt"
    chmod 0666 "$base/public/assets/css/site.css"
    chmod 0640 "$base/public/assets/js/site.js"
    touch -t 200101010000 "$base/public/index.html"
    touch -t 201402030405 "$base/themes/aurora/theme.json"
    touch -t 203012312359 "$base/cgi-bin/health-check"
}

create_site_tree /app/site-src
echo "Created website source tree at /app/site-src"
