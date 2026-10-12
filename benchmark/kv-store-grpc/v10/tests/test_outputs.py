import importlib.util
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path

import grpc
import pytest


APP_DIR = Path("/app")
PROTO_PATH = APP_DIR / "inventory.proto"
PB2_PATH = APP_DIR / "inventory_pb2.py"
PB2_GRPC_PATH = APP_DIR / "inventory_pb2_grpc.py"
SERVER_PATH = APP_DIR / "server.py"
PORT = 5328
INT_FIELD_TYPES = {
    3,
    4,
    5,
    6,
    7,
    13,
    15,
    16,
    17,
    18,
}


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fields_of_type(message_descriptor, field_type: int):
    return [field for field in message_descriptor.fields if field.type == field_type]


def integer_fields(message_descriptor):
    return [field for field in message_descriptor.fields if field.type in INT_FIELD_TYPES]


def request_message(pb2, method_descriptor):
    return getattr(pb2, method_descriptor.input_type.name)


def make_request(pb2, method_descriptor, item_name: str, quantity: int | None = None):
    message_class = request_message(pb2, method_descriptor)
    string_fields = fields_of_type(method_descriptor.input_type, 9)
    int_fields = integer_fields(method_descriptor.input_type)

    kwargs = {}
    assert len(string_fields) == 1
    kwargs[string_fields[0].name] = item_name

    if quantity is None:
        assert len(int_fields) == 0
    else:
        assert len(int_fields) == 1
        kwargs[int_fields[0].name] = quantity

    return message_class(**kwargs)


def parse_write_response(response, method_descriptor):
    bool_fields = fields_of_type(method_descriptor.output_type, 8)
    int_fields = integer_fields(method_descriptor.output_type)
    assert len(bool_fields) == 1
    assert len(int_fields) == 1
    return getattr(response, bool_fields[0].name), getattr(response, int_fields[0].name)


def parse_get_response(response, method_descriptor):
    bool_fields = fields_of_type(method_descriptor.output_type, 8)
    int_fields = integer_fields(method_descriptor.output_type)
    assert len(bool_fields) == 0
    assert len(int_fields) == 1
    return getattr(response, int_fields[0].name)


@pytest.fixture(scope="module")
def grpc_modules():
    assert PROTO_PATH.exists(), f"missing {PROTO_PATH}"
    assert PB2_PATH.exists(), f"missing {PB2_PATH}"
    assert PB2_GRPC_PATH.exists(), f"missing {PB2_GRPC_PATH}"
    pb2 = load_module("inventory_pb2", PB2_PATH)
    pb2_grpc = load_module("inventory_pb2_grpc", PB2_GRPC_PATH)
    service = pb2.DESCRIPTOR.services_by_name.get("InventoryService")
    assert service is not None
    return pb2, pb2_grpc, service


@pytest.fixture(scope="module")
def running_server():
    assert SERVER_PATH.exists(), f"missing {SERVER_PATH}"
    wait_for_port("127.0.0.1", PORT)
    yield


def test_solution_installed_required_packages():
    import grpc_tools  # noqa: F401

    assert metadata.version("grpcio") == "1.73.0"
    assert metadata.version("grpcio-tools") == "1.73.0"


def test_proto_schema_matches_inventory_contract(grpc_modules):
    pb2, _, service = grpc_modules

    assert pb2.DESCRIPTOR.name == "inventory.proto"
    assert set(service.methods_by_name) == {"StockItem", "ReserveItem", "ReleaseItem", "GetStock"}

    for method_name in ("StockItem", "ReserveItem", "ReleaseItem"):
        method = service.methods_by_name[method_name]
        assert len(fields_of_type(method.input_type, 9)) == 1
        assert len(integer_fields(method.input_type)) == 1
        assert len(fields_of_type(method.output_type, 8)) == 1
        assert len(integer_fields(method.output_type)) == 1

    get_stock = service.methods_by_name["GetStock"]
    assert len(fields_of_type(get_stock.input_type, 9)) == 1
    assert len(integer_fields(get_stock.input_type)) == 0
    assert len(fields_of_type(get_stock.output_type, 8)) == 0
    assert len(integer_fields(get_stock.output_type)) == 1


def test_server_class_exists():
    content = SERVER_PATH.read_text()
    for snippet in ["class Server(", "def StockItem", "def ReserveItem", "def ReleaseItem", "def GetStock"]:
        assert snippet in content


def test_real_grpc_server_is_listening(running_server):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        assert sock.connect_ex(("127.0.0.1", PORT)) == 0


def test_inventory_sequence_and_failed_reservation_keeps_stock(running_server, grpc_modules):
    pb2, pb2_grpc, service = grpc_modules
    channel_a = grpc.insecure_channel(f"127.0.0.1:{PORT}")
    channel_b = grpc.insecure_channel(f"127.0.0.1:{PORT}")
    grpc.channel_ready_future(channel_a).result(timeout=10)
    grpc.channel_ready_future(channel_b).result(timeout=10)
    stub_a = pb2_grpc.InventoryServiceStub(channel_a)
    stub_b = pb2_grpc.InventoryServiceStub(channel_b)

    item_name = f"widget-{uuid.uuid4().hex}"
    methods = service.methods_by_name

    missing = stub_a.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(missing, methods["GetStock"]) == 0

    stocked = stub_a.StockItem(make_request(pb2, methods["StockItem"], item_name, 10))
    assert parse_write_response(stocked, methods["StockItem"]) == (True, 10)

    reserved = stub_b.ReserveItem(make_request(pb2, methods["ReserveItem"], item_name, 4))
    assert parse_write_response(reserved, methods["ReserveItem"]) == (True, 6)

    still_available = stub_a.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(still_available, methods["GetStock"]) == 6

    failed = stub_b.ReserveItem(make_request(pb2, methods["ReserveItem"], item_name, 7))
    assert parse_write_response(failed, methods["ReserveItem"]) == (False, 6)

    unchanged = stub_a.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(unchanged, methods["GetStock"]) == 6

    released = stub_b.ReleaseItem(make_request(pb2, methods["ReleaseItem"], item_name, 3))
    assert parse_write_response(released, methods["ReleaseItem"]) == (True, 9)

    final_stock = stub_a.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(final_stock, methods["GetStock"]) == 9

    channel_a.close()
    channel_b.close()


def test_concurrent_reservations_do_not_oversubscribe_inventory(running_server, grpc_modules):
    pb2, pb2_grpc, service = grpc_modules
    methods = service.methods_by_name
    item_name = f"burst-{uuid.uuid4().hex}"

    setup_channel = grpc.insecure_channel(f"127.0.0.1:{PORT}")
    grpc.channel_ready_future(setup_channel).result(timeout=10)
    setup_stub = pb2_grpc.InventoryServiceStub(setup_channel)

    stocked = setup_stub.StockItem(make_request(pb2, methods["StockItem"], item_name, 5))
    assert parse_write_response(stocked, methods["StockItem"]) == (True, 5)

    start_event = threading.Event()

    def reserve_once():
        channel = grpc.insecure_channel(f"127.0.0.1:{PORT}")
        try:
            grpc.channel_ready_future(channel).result(timeout=10)
            stub = pb2_grpc.InventoryServiceStub(channel)
            start_event.wait(timeout=5)
            response = stub.ReserveItem(make_request(pb2, methods["ReserveItem"], item_name, 1), timeout=10)
            return parse_write_response(response, methods["ReserveItem"])
        finally:
            channel.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(reserve_once) for _ in range(8)]
        time.sleep(0.3)
        start_event.set()
        results = [future.result(timeout=15) for future in futures]

    success_results = [remaining for success, remaining in results if success]
    failure_results = [remaining for success, remaining in results if not success]

    assert len(success_results) == 5
    assert len(failure_results) == 3
    assert sorted(success_results) == [0, 1, 2, 3, 4]
    assert failure_results == [0, 0, 0]

    after_burst = setup_stub.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(after_burst, methods["GetStock"]) == 0

    another_failed = setup_stub.ReserveItem(make_request(pb2, methods["ReserveItem"], item_name, 1))
    assert parse_write_response(another_failed, methods["ReserveItem"]) == (False, 0)

    released = setup_stub.ReleaseItem(make_request(pb2, methods["ReleaseItem"], item_name, 2))
    assert parse_write_response(released, methods["ReleaseItem"]) == (True, 2)

    final_stock = setup_stub.GetStock(make_request(pb2, methods["GetStock"], item_name))
    assert parse_get_response(final_stock, methods["GetStock"]) == 2

    setup_channel.close()
