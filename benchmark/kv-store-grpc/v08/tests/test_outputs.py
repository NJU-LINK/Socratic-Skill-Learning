import importlib.util
import pathlib
import subprocess
import sys
import time

import grpc
from google.protobuf.descriptor import FieldDescriptor


ROOT = pathlib.Path("/app")
PROTO_PATH = ROOT / "kv-store.proto"
SERVER_PATH = ROOT / "server.py"


def load_module(name: str, path: pathlib.Path):
    path_str = str(path.parent)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_grpc_python(*code_parts: str) -> subprocess.CompletedProcess[str]:
    code = "\n".join(code_parts)
    return subprocess.run(
        ["python3", "-c", code],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


def wait_for_server() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        channel = grpc.insecure_channel("127.0.0.1:5328")
        try:
            grpc.channel_ready_future(channel).result(timeout=1)
            return
        except grpc.FutureTimeoutError:
            time.sleep(0.2)
        finally:
            channel.close()
    raise AssertionError("gRPC server on port 5328 did not become ready")


def test_required_files_and_schema() -> None:
    assert PROTO_PATH.exists(), "proto file missing"
    assert SERVER_PATH.exists(), "server.py missing"


def test_generated_bindings_exist_and_expose_enum() -> None:
    pb2_path = ROOT / "kv_store_pb2.py"
    pb2_grpc_path = ROOT / "kv_store_pb2_grpc.py"
    assert pb2_path.exists(), "kv_store_pb2.py missing"
    assert pb2_grpc_path.exists(), "kv_store_pb2_grpc.py missing"

    kv_store_pb2 = load_module("kv_store_pb2", pb2_path)

    service = kv_store_pb2.DESCRIPTOR.services_by_name["KVStore"]
    methods = {method.name: method for method in service.methods}
    assert set(methods) == {"GetVal", "SetVal", "CheckAndSet"}
    assert methods["GetVal"].input_type.name == "GetValRequest"
    assert methods["GetVal"].output_type.name == "GetValResponse"
    assert methods["SetVal"].input_type.name == "SetValRequest"
    assert methods["SetVal"].output_type.name == "SetValResponse"
    assert methods["CheckAndSet"].input_type.name == "CheckAndSetRequest"
    assert methods["CheckAndSet"].output_type.name == "CheckAndSetResponse"

    get_req = kv_store_pb2.DESCRIPTOR.message_types_by_name["GetValRequest"]
    assert [(field.name, field.type) for field in get_req.fields] == [
        ("key", FieldDescriptor.TYPE_STRING),
    ]

    get_resp = kv_store_pb2.DESCRIPTOR.message_types_by_name["GetValResponse"]
    assert [(field.name, field.type) for field in get_resp.fields] == [
        ("val", FieldDescriptor.TYPE_INT32),
    ]

    set_req = kv_store_pb2.DESCRIPTOR.message_types_by_name["SetValRequest"]
    assert [(field.name, field.type) for field in set_req.fields] == [
        ("key", FieldDescriptor.TYPE_STRING),
        ("value", FieldDescriptor.TYPE_INT32),
    ]

    set_resp = kv_store_pb2.DESCRIPTOR.message_types_by_name["SetValResponse"]
    assert [(field.name, field.type) for field in set_resp.fields] == [
        ("val", FieldDescriptor.TYPE_INT32),
    ]

    cas_req = kv_store_pb2.DESCRIPTOR.message_types_by_name["CheckAndSetRequest"]
    assert [(field.name, field.type) for field in cas_req.fields] == [
        ("key", FieldDescriptor.TYPE_STRING),
        ("expected_val", FieldDescriptor.TYPE_INT32),
        ("new_val", FieldDescriptor.TYPE_INT32),
    ]

    status_enum = kv_store_pb2.DESCRIPTOR.enum_types_by_name["CheckAndSetStatus"]
    assert {value.name: value.number for value in status_enum.values} == {
        "SUCCESS": 0,
        "MISSING": 1,
        "MISMATCH": 2,
    }

    cas_resp = kv_store_pb2.DESCRIPTOR.message_types_by_name["CheckAndSetResponse"]
    assert len(cas_resp.fields) == 2
    assert cas_resp.fields[0].name == "val"
    assert cas_resp.fields[0].type == FieldDescriptor.TYPE_INT32
    assert cas_resp.fields[1].name == "status"
    assert cas_resp.fields[1].type == FieldDescriptor.TYPE_ENUM
    assert cas_resp.fields[1].enum_type.name == "CheckAndSetStatus"

    assert kv_store_pb2.SUCCESS == 0
    assert kv_store_pb2.MISSING == 1
    assert kv_store_pb2.MISMATCH == 2


def test_grpc_dependencies_installed_by_solution() -> None:
    result = subprocess.run(
        ["python3", "-m", "pip", "show", "grpcio", "grpcio-tools"],
        check=True,
        text=True,
        capture_output=True,
    )
    blocks = {}
    for block in result.stdout.strip().split("\n---\n"):
        package = {}
        for line in block.splitlines():
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            package[key] = value
        if "Name" in package:
            blocks[package["Name"]] = package

    assert blocks["grpcio"]["Version"] == "1.73.0"
    assert blocks["grpcio-tools"]["Version"] == "1.73.0"


def test_server_implements_expected_class_name() -> None:
    server_module = load_module("server", SERVER_PATH)
    assert hasattr(server_module, "Server")


def test_runtime_semantics_for_compare_and_set() -> None:
    wait_for_server()

    result = run_grpc_python(
        "import kv_store_pb2",
        "import kv_store_pb2_grpc",
        "import grpc",
        "channel = grpc.insecure_channel('127.0.0.1:5328')",
        "stub = kv_store_pb2_grpc.KVStoreStub(channel)",
        "missing = stub.CheckAndSet(kv_store_pb2.CheckAndSetRequest(key='ghost', expected_val=7, new_val=8))",
        "assert missing.val == 0, missing",
        "assert missing.status == kv_store_pb2.MISSING, missing",
        "set_resp = stub.SetVal(kv_store_pb2.SetValRequest(key='alpha', value=11))",
        "assert set_resp.val == 11, set_resp",
        "mismatch = stub.CheckAndSet(kv_store_pb2.CheckAndSetRequest(key='alpha', expected_val=10, new_val=20))",
        "assert mismatch.val == 11, mismatch",
        "assert mismatch.status == kv_store_pb2.MISMATCH, mismatch",
        "after_mismatch = stub.GetVal(kv_store_pb2.GetValRequest(key='alpha'))",
        "assert after_mismatch.val == 11, after_mismatch",
        "success = stub.CheckAndSet(kv_store_pb2.CheckAndSetRequest(key='alpha', expected_val=11, new_val=20))",
        "assert success.val == 20, success",
        "assert success.status == kv_store_pb2.SUCCESS, success",
        "after_success = stub.GetVal(kv_store_pb2.GetValRequest(key='alpha'))",
        "assert after_success.val == 20, after_success",
        "other_key = stub.GetVal(kv_store_pb2.GetValRequest(key='beta'))",
        "assert other_key.val == 0, other_key",
        "channel.close()",
    )
    assert result.returncode == 0
