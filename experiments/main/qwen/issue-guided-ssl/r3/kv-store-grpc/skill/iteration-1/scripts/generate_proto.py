#!/usr/bin/env python3
"""
Generate a .proto file from a JSON configuration.

Usage: python generate_proto.py config.json output.proto

Config JSON format:
{
  "package": "kvstore",
  "service": "KVStore",
  "rpcs": [
    {
      "name": "Put",
      "request": {
        "name": "PutRequest",
        "fields": [{"name": "key", "type": "string", "number": 1}, ...]
      },
      "response": {
        "name": "PutResponse",
        "fields": [{"name": "value", "type": "int32", "number": 1}, ...]
      }
    }
  ],
  "extra_messages": [
    {"name": "SharedType", "fields": [{"name": "x", "type": "int32", "number": 1}]}
  ],
  "enums": [
    {"name": "Status", "values": [{"name": "OK", "number": 0}, {"name": "ERR", "number": 1}]}
  ]
}

Field types: string, int32, int64, float, double, bool, bytes, or any message/enum name defined in the file.
For repeated fields, set "repeated": true.
For map fields, set "map_key" and "map_value" instead of "type".
"""

import json
import sys


def render_message(msg, indent=0):
    """Render a message definition."""
    prefix = "  " * indent
    lines = [f"{prefix}message {msg['name']} {{"]
    for f in msg["fields"]:
        field_prefix = "  " * (indent + 1)
        if "map_key" in f and "map_value" in f:
            lines.append(f"{field_prefix}map<{f['map_key']}, {f['map_value']}> {f['name']} = {f['number']};")
        elif f.get("repeated"):
            lines.append(f"{field_prefix}repeated {f['type']} {f['name']} = {f['number']};")
        else:
            lines.append(f"{field_prefix}{f['type']} {f['name']} = {f['number']};")
    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def render_enum(enum, indent=0):
    """Render an enum definition."""
    prefix = "  " * indent
    lines = [f"{prefix}enum {enum['name']} {{"]
    for v in enum["values"]:
        lines.append(f"{prefix}  {v['name']} = {v['number']};")
    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def generate_proto(config):
    """Generate complete .proto file content."""
    lines = ['syntax = "proto3";', "", f"package {config['package']};", ""]

    # Render enums first (they may be referenced by messages)
    if "enums" in config:
        for enum in config["enums"]:
            lines.append(render_enum(enum))
            lines.append("")

    # Render extra/shared messages
    if "extra_messages" in config:
        for msg in config["extra_messages"]:
            lines.append(render_message(msg))
            lines.append("")

    # Collect all request/response messages
    all_messages = []
    for rpc in config["rpcs"]:
        all_messages.append(rpc["request"])
        all_messages.append(rpc["response"])

    # Render all RPC messages
    for msg in all_messages:
        lines.append(render_message(msg))
        lines.append("")

    # Render service
    lines.append(f"service {config['service']} {{")
    for rpc in config["rpcs"]:
        lines.append(f"  rpc {rpc['name']}({rpc['request']['name']}) returns ({rpc['response']['name']});")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: generate_proto.py config.json output.proto", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    proto_content = generate_proto(config)

    with open(sys.argv[2], "w") as f:
        f.write(proto_content)

    print(f"Generated {sys.argv[2]}")


if __name__ == "__main__":
    main()
