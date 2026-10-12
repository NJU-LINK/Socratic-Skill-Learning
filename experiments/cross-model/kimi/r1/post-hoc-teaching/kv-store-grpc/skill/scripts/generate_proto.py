#!/usr/bin/env python3
"""
Helper script to generate gRPC Python bindings from a .proto file.

Usage:
    python generate_proto.py /app/service.proto

Notes:
- Generates *_pb2.py (messages) and *_pb2_grpc.py (servicer/stub)
- Import with: import service_pb2, service_pb2_grpc
- Protoc maps both '-' and '.' to '_' in module names:
  my-service.proto → my_service_pb2
  my.service.proto → my_service_pb2
"""

import subprocess
import sys
import re
from pathlib import Path


def generate_proto(proto_path: str) -> None:
    """Generate Python bindings for a proto file."""
    proto_file = Path(proto_path)
    if not proto_file.exists():
        print(f"Error: {proto_path} does not exist")
        sys.exit(1)
    
    work_dir = proto_file.parent
    proto_name = proto_file.name
    
    cmd = [
        "python", "-m", "grpc_tools.protoc",
        "--python_out=.",
        "--grpc_python_out=.",
        "-I.",
        proto_name
    ]
    
    print(f"Running: {' '.join(cmd)} in {work_dir}")
    result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    
    # Protoc maps both '-' and '.' to '_' in module names
    base_name = re.sub(r'[-.]', '_', proto_file.stem)
    pb2_file = work_dir / f"{base_name}_pb2.py"
    grpc_file = work_dir / f"{base_name}_pb2_grpc.py"
    
    print(f"Generated:")
    print(f"  - {pb2_file}")
    print(f"  - {grpc_file}")
    print(f"\nImport in Python:")
    print(f'  import {base_name}_pb2')
    print(f'  import {base_name}_pb2_grpc')
    print(f'\nIn server.py, use:')
    print(f'  import {base_name}_pb2')
    print(f'  import {base_name}_pb2_grpc')
    print(f'  class MyServicer({base_name}_pb2_grpc.ServiceNameServicer):')


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <proto_file>")
        sys.exit(1)
    
    generate_proto(sys.argv[1])
