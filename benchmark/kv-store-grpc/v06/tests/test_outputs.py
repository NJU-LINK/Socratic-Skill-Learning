import re
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, "/app")


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"Port {port} is not listening on {host}")


def test_proto_file_creation():
    proto_path = Path("/app/kv-store.proto")
    assert proto_path.exists(), f"Proto file {proto_path} was not created"
    content = proto_path.read_text()

    rpc_names = re.findall(r"rpc\s+(\w+)\s*\(", content)
    assert rpc_names == ["GetVal", "SetVal"], f"Unexpected RPCs defined: {rpc_names}"
    assert "service KVStore" in content
    assert "message GetValRequest" in content
    assert "message GetValResponse" in content
    assert "int32 val = 1;" in content
    assert "message SetValRequest" in content
    assert "string key = 1;" in content
    assert "int32 value = 2;" in content
    assert "message SetValResponse" in content
    assert "PutNumber" not in content
    assert "ReadNumber" not in content
    assert "ResetAll" not in content
    assert "SnapshotTotal" not in content


def test_required_files_exist():
    assert Path("/app/kv_store_pb2.py").exists()
    assert Path("/app/kv_store_pb2_grpc.py").exists()

    server_path = Path("/app/server.py")
    assert server_path.exists()
    server_source = server_path.read_text()
    assert "class Server" in server_source
    assert "def GetVal" in server_source
    assert "def SetVal" in server_source
    assert "5328" in server_source


def test_generated_bindings_match_contract():
    import kv_store_pb2
    import kv_store_pb2_grpc

    assert hasattr(kv_store_pb2, "GetValRequest")
    assert hasattr(kv_store_pb2, "GetValResponse")
    assert hasattr(kv_store_pb2, "SetValRequest")
    assert hasattr(kv_store_pb2, "SetValResponse")
    assert not hasattr(kv_store_pb2, "PutNumberRequest")
    assert not hasattr(kv_store_pb2, "ResetAllRequest")

    assert kv_store_pb2.GetValRequest.DESCRIPTOR.fields_by_name["key"].number == 1
    assert kv_store_pb2.GetValResponse.DESCRIPTOR.fields_by_name["val"].number == 1
    assert kv_store_pb2.SetValRequest.DESCRIPTOR.fields_by_name["key"].number == 1
    assert kv_store_pb2.SetValRequest.DESCRIPTOR.fields_by_name["value"].number == 2
    assert kv_store_pb2.SetValResponse.DESCRIPTOR.fields_by_name["val"].number == 1
    assert hasattr(kv_store_pb2_grpc, "KVStoreStub")


def test_grpc_packages_installed():
    import grpc

    assert grpc.__version__ == "1.73.0"


@pytest.fixture(scope="module")
def grpc_client():
    import grpc
    import kv_store_pb2_grpc

    wait_for_port("127.0.0.1", 5328)
    channel = grpc.insecure_channel("127.0.0.1:5328")
    stub = kv_store_pb2_grpc.KVStoreStub(channel)
    yield stub
    channel.close()


def test_server_responds_to_grpc(grpc_client):
    import kv_store_pb2

    response = grpc_client.GetVal(kv_store_pb2.GetValRequest(key="missing-key"))
    assert hasattr(response, "val")
    assert response.val == 0


def test_kv_store_semantics(grpc_client):
    import kv_store_pb2

    assert grpc_client.GetVal(kv_store_pb2.GetValRequest(key="alpha")).val == 0

    assert grpc_client.SetVal(kv_store_pb2.SetValRequest(key="alpha", value=7)).val == 7
    assert grpc_client.GetVal(kv_store_pb2.GetValRequest(key="alpha")).val == 7

    assert grpc_client.SetVal(kv_store_pb2.SetValRequest(key="beta", value=5)).val == 5
    assert grpc_client.GetVal(kv_store_pb2.GetValRequest(key="beta")).val == 5

    assert grpc_client.SetVal(kv_store_pb2.SetValRequest(key="alpha", value=11)).val == 11
    assert grpc_client.GetVal(kv_store_pb2.GetValRequest(key="alpha")).val == 11
    assert grpc_client.GetVal(kv_store_pb2.GetValRequest(key="beta")).val == 5
