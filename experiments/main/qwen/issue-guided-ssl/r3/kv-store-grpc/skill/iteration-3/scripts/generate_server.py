#!/usr/bin/env python3
"""
Generate a Python gRPC server module from a JSON configuration.

Usage: python generate_server.py config.json output_server.py

The config JSON extends the proto config with server-specific details:
{
  "proto_module": "kv_store_pb2",       // Python module name (underscore form)
  "grpc_module": "kv_store_pb2_grpc",   // Python gRPC module name
  "service_name": "KVStore",
  "port": 5328,
  "max_workers": 10,
  "state": {
    "description": "nested_dict",        // State structure type
    "init_code": "self._store = {}",     // Python init code
    "lock": true                         // Whether to use threading.Lock
  },
  "rpcs": [
    {
      "name": "Put",
      "request": {"name": "PutRequest", ...},
      "response": {"name": "PutResponse", ...},
      "impl": "python code for the method body (indented)"
    }
  ]
}

The 'impl' field for each RPC contains the Python implementation code.
It should use 'request' to access fields and return the appropriate response message.
Available helpers: self._store (state), self._lock (if lock=true)
"""

import json
import sys
import textwrap


def generate_server(config):
    """Generate complete server.py content."""
    proto_module = config.get("proto_module", "")
    grpc_module = config.get("grpc_module", "")
    service_name = config.get("service_name", config.get("service", ""))
    port = config["port"]

    # Auto-derive module names from proto_file if not given
    if not proto_module and "proto_file" in config:
        base = config["proto_file"].replace("-", "_").replace(".proto", "")
        proto_module = f"{base}_pb2"
    if not grpc_module and proto_module:
        grpc_module = f"{proto_module}_grpc"
    max_workers = config.get("max_workers", 10)
    state = config.get("state", {})
    use_lock = state.get("lock", True)

    lines = []

    # Imports
    lines.append("import grpc")
    lines.append("from concurrent import futures")
    if use_lock:
        lines.append("import threading")
    lines.append(f"import {proto_module}")
    lines.append(f"import {grpc_module}")
    lines.append("")
    lines.append("")

    # Server class
    lines.append(f"class Server({grpc_module}.{service_name}Servicer):")
    lines.append("    def __init__(self):")

    # State initialization
    init_code = state.get("init_code", "self._store = {}")
    for init_line in init_code.split("\n"):
        lines.append(f"        {init_line.strip()}")

    if use_lock:
        lines.append("        self._lock = threading.Lock()")
    lines.append("")

    # RPC implementations
    for rpc in config["rpcs"]:
        method_name = rpc["name"]
        impl = rpc.get("impl", "")

        lines.append(f"    def {method_name}(self, request, context):")

        if use_lock:
            # Wrap implementation in lock
            impl_lines = impl.strip().split("\n")
            lines.append("        with self._lock:")
            for impl_line in impl_lines:
                lines.append(f"            {impl_line}")
        else:
            impl_lines = impl.strip().split("\n")
            for impl_line in impl_lines:
                lines.append(f"        {impl_line}")
        lines.append("")

    # Serve function
    lines.append("")
    lines.append("def serve():")
    lines.append(f"    server = grpc.server(futures.ThreadPoolExecutor(max_workers={max_workers}))")
    lines.append(f"    {grpc_module}.add_{service_name}Servicer_to_server(Server(), server)")
    lines.append("    server.add_insecure_port('[::]:" + str(port) + "')")
    lines.append("    server.start()")
    lines.append("    server.wait_for_termination()")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    serve()")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: generate_server.py config.json output_server.py", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    server_content = generate_server(config)

    with open(sys.argv[2], "w") as f:
        f.write(server_content)

    print(f"Generated {sys.argv[2]}")


if __name__ == "__main__":
    main()
