#!/usr/bin/env python3

import argparse
import html
import json
import os
import shutil
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename


DEFAULT_STATE_DIR = Path("/srv/devpkg-index")
BOOTSTRAP_DIR = Path("/opt/devpkg-index/bootstrap/packages")
SESSION_FILE = Path.home() / ".devpkg-index-session.json"


def distribution_name(filename: str) -> str | None:
    try:
        if filename.endswith(".whl"):
            name, _, _, _ = parse_wheel_filename(filename)
            return canonicalize_name(str(name))
        if filename.endswith(".tar.gz") or filename.endswith(".zip"):
            name, _ = parse_sdist_filename(filename)
            return canonicalize_name(str(name))
    except Exception:
        return None
    return None


def packages_dir(state_dir: Path) -> Path:
    return state_dir / "packages"


def users_file(state_dir: Path) -> Path:
    return state_dir / "users.json"


def require_initialized(state_dir: Path) -> None:
    if not users_file(state_dir).exists():
        raise SystemExit("Index is not initialized. Run `devpkg-index init` first.")


def read_users(state_dir: Path) -> dict[str, str]:
    require_initialized(state_dir)
    return json.loads(users_file(state_dir).read_text())


def render_simple_root(state_dir: Path) -> str:
    names = sorted(
        {
            distribution_name(path.name)
            for path in packages_dir(state_dir).iterdir()
            if path.is_file() and distribution_name(path.name)
        }
    )
    links = "\n".join(
        f'<a href="/{"simple"}/{name}/">{html.escape(name)}</a><br />' for name in names
    )
    return f"<html><body>{links}</body></html>"


def render_project_page(state_dir: Path, project_name: str) -> str:
    normalized = canonicalize_name(project_name)
    links = []
    for path in sorted(packages_dir(state_dir).iterdir()):
        if not path.is_file():
            continue
        if distribution_name(path.name) != normalized:
            continue
        href = f"/packages/{quote(path.name)}"
        links.append(f'<a href="{href}">{html.escape(path.name)}</a><br />')
    return f"<html><body>{''.join(links)}</body></html>"


class SimpleIndexHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        state_dir = Path(self.server.state_dir)

        if path in {"/simple", "/simple/"}:
            body = render_simple_root(state_dir).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/simple/"):
            project = path[len("/simple/") :].strip("/")
            body = render_project_page(state_dir, unquote(project)).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/packages/"):
            filename = unquote(path[len("/packages/") :])
            file_path = packages_dir(state_dir) / filename
            if not file_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Package file not found")
                return
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown path")

    def log_message(self, format_string: str, *args) -> None:
        sys.stderr.write("devpkg-index: " + format_string % args + "\n")


def cmd_init(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    package_root = packages_dir(state_dir)
    package_root.mkdir(parents=True, exist_ok=True)

    for source in BOOTSTRAP_DIR.glob("*"):
        target = package_root / source.name
        if not target.exists():
            shutil.copy2(source, target)

    users_file(state_dir).write_text(json.dumps({"releasebot": "releasebot-pass"}, indent=2))
    print(f"Initialized index state in {state_dir}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    users = read_users(state_dir)
    if users.get(args.username) != args.password:
        raise SystemExit("Authentication failed.")

    SESSION_FILE.write_text(json.dumps({"username": args.username, "state_dir": str(state_dir)}))
    print(f"Logged in as {args.username}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    require_initialized(state_dir)
    if not SESSION_FILE.exists():
        raise SystemExit("Not logged in. Run `devpkg-index login` first.")

    session = json.loads(SESSION_FILE.read_text())
    if session.get("state_dir") != str(state_dir):
        raise SystemExit("Login session does not match the selected state directory.")

    destination = packages_dir(state_dir)
    uploaded = []
    for pattern in args.artifacts:
        matches = list(Path.cwd().glob(pattern))
        if not matches:
            matches = [Path(pattern)]
        for path in matches:
            if not path.is_file():
                raise SystemExit(f"Artifact not found: {path}")
            shutil.copy2(path, destination / path.name)
            uploaded.append(path.name)

    print("Uploaded artifacts:")
    for name in uploaded:
        print(f"- {name}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    require_initialized(state_dir)

    server = ThreadingHTTPServer((args.host, args.port), SimpleIndexHandler)
    server.state_dir = str(state_dir)
    print(f"Serving local index on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authenticated local package index workflow")
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("DEVPKG_INDEX_STATE_DIR", str(DEFAULT_STATE_DIR)),
        help="Directory used for index state and hosted packages.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the index state")
    init_parser.set_defaults(func=cmd_init)

    login_parser = subparsers.add_parser("login", help="Store an authenticated upload session")
    login_parser.add_argument("--username", required=True)
    login_parser.add_argument("--password", required=True)
    login_parser.set_defaults(func=cmd_login)

    upload_parser = subparsers.add_parser("upload", help="Upload built artifacts to the index")
    upload_parser.add_argument("artifacts", nargs="+", help="Files or glob patterns to upload")
    upload_parser.set_defaults(func=cmd_upload)

    start_parser = subparsers.add_parser("start", help="Start the local simple index server")
    start_parser.add_argument("--host", default="0.0.0.0")
    start_parser.add_argument("--port", type=int, default=3141)
    start_parser.set_defaults(func=cmd_start)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
