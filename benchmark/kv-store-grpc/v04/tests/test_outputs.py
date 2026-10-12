import importlib.util
import pathlib
import random
import socket
import sys
import time
import uuid

import grpc
import pytest


APP_DIR = pathlib.Path("/app")
PROTO_PATH = APP_DIR / "profile-records.proto"
PB2_PATH = APP_DIR / "profile_records_pb2.py"
PB2_GRPC_PATH = APP_DIR / "profile_records_pb2_grpc.py"
SERVER_PATH = APP_DIR / "server.py"


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def grpc_modules():
    assert PROTO_PATH.exists(), f"missing {PROTO_PATH}"
    assert PB2_PATH.exists(), f"missing {PB2_PATH}"
    assert PB2_GRPC_PATH.exists(), f"missing {PB2_GRPC_PATH}"
    pb2 = load_module("profile_records_pb2", PB2_PATH)
    pb2_grpc = load_module("profile_records_pb2_grpc", PB2_GRPC_PATH)
    return pb2, pb2_grpc


@pytest.fixture(scope="module")
def running_server():
    assert SERVER_PATH.exists(), f"missing {SERVER_PATH}"
    wait_for_port("127.0.0.1", 5328)
    yield


def test_proto_schema_contents(grpc_modules):
    pb2, _ = grpc_modules

    file_descriptor = pb2.DESCRIPTOR
    assert file_descriptor.name == "profile-records.proto"

    service = file_descriptor.services_by_name.get("ProfileStore")
    assert service is not None
    assert set(service.methods_by_name) == {"UpsertProfile", "GetProfile", "ResetProfile"}

    profile_message = file_descriptor.message_types_by_name.get("Profile")
    assert profile_message is not None

    age_field = profile_message.fields_by_name.get("age")
    assert age_field is not None
    assert age_field.type == age_field.TYPE_INT32
    assert age_field.label == age_field.LABEL_OPTIONAL

    scores_field = profile_message.fields_by_name.get("scores")
    assert scores_field is not None
    assert scores_field.type == scores_field.TYPE_INT32
    assert scores_field.label == scores_field.LABEL_REPEATED

    upsert_request = file_descriptor.message_types_by_name.get("UpsertProfileRequest")
    assert upsert_request is not None
    assert upsert_request.fields_by_name["profile_id"].type == upsert_request.fields_by_name["profile_id"].TYPE_STRING
    assert upsert_request.fields_by_name["profile"].message_type is profile_message

    get_request = file_descriptor.message_types_by_name.get("GetProfileRequest")
    assert get_request is not None
    assert get_request.fields_by_name["profile_id"].type == get_request.fields_by_name["profile_id"].TYPE_STRING

    reset_request = file_descriptor.message_types_by_name.get("ResetProfileRequest")
    assert reset_request is not None
    assert reset_request.fields_by_name["profile_id"].type == reset_request.fields_by_name["profile_id"].TYPE_STRING


def test_server_class_exists():
    server_source = SERVER_PATH.read_text()
    assert "class Server(" in server_source


def test_real_grpc_server_reachable(running_server):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        assert sock.connect_ex(("127.0.0.1", 5328)) == 0


def make_profile_case(rng: random.Random, prefix: str):
    profile_id = f"{prefix}-{uuid.uuid4().hex[:10]}"
    age = rng.randint(1, 120)
    score_count = rng.randint(0, 6)
    scores = [rng.randint(-50, 150) for _ in range(score_count)]
    return profile_id, age, scores


def test_profile_store_long_lived_sequence(running_server, grpc_modules):
    pb2, pb2_grpc = grpc_modules
    channel_a = grpc.insecure_channel("127.0.0.1:5328")
    grpc.channel_ready_future(channel_a).result(timeout=10)
    stub_a = pb2_grpc.ProfileStoreStub(channel_a)

    channel_b = grpc.insecure_channel("127.0.0.1:5328")
    grpc.channel_ready_future(channel_b).result(timeout=10)
    stub_b = pb2_grpc.ProfileStoreStub(channel_b)

    rng = random.Random(20260603)
    first_id, first_age, first_scores = make_profile_case(rng, "first")
    second_id, second_age, second_scores = make_profile_case(rng, "second")
    third_id, third_age, third_scores = make_profile_case(rng, "third")
    missing_id = f"missing-{uuid.uuid4().hex}"

    missing = stub_a.GetProfile(pb2.GetProfileRequest(profile_id=missing_id))
    assert missing.profile.age == 0
    assert list(missing.profile.scores) == []

    first_write = stub_a.UpsertProfile(
        pb2.UpsertProfileRequest(
            profile_id=first_id,
            profile=pb2.Profile(age=first_age, scores=first_scores),
        )
    )
    assert first_write.profile.age == first_age
    assert list(first_write.profile.scores) == first_scores

    second_write = stub_b.UpsertProfile(
        pb2.UpsertProfileRequest(
            profile_id=second_id,
            profile=pb2.Profile(age=second_age, scores=second_scores),
        )
    )
    assert second_write.profile.age == second_age
    assert list(second_write.profile.scores) == second_scores

    third_write = stub_a.UpsertProfile(
        pb2.UpsertProfileRequest(
            profile_id=third_id,
            profile=pb2.Profile(age=third_age, scores=third_scores),
        )
    )
    assert third_write.profile.age == third_age
    assert list(third_write.profile.scores) == third_scores

    first_read_from_other_channel = stub_b.GetProfile(pb2.GetProfileRequest(profile_id=first_id))
    assert first_read_from_other_channel.profile.age == first_age
    assert list(first_read_from_other_channel.profile.scores) == first_scores

    second_read = stub_a.GetProfile(pb2.GetProfileRequest(profile_id=second_id))
    assert second_read.profile.age == second_age
    assert list(second_read.profile.scores) == second_scores

    updated_first_scores = list(reversed(first_scores)) + [rng.randint(-50, 150)]
    updated_first_age = first_age + 1
    updated_first = stub_b.UpsertProfile(
        pb2.UpsertProfileRequest(
            profile_id=first_id,
            profile=pb2.Profile(age=updated_first_age, scores=updated_first_scores),
        )
    )
    assert updated_first.profile.age == updated_first_age
    assert list(updated_first.profile.scores) == updated_first_scores

    reread_first = stub_a.GetProfile(pb2.GetProfileRequest(profile_id=first_id))
    assert reread_first.profile.age == updated_first_age
    assert list(reread_first.profile.scores) == updated_first_scores

    reset_second = stub_a.ResetProfile(pb2.ResetProfileRequest(profile_id=second_id))
    assert reset_second.profile.age == 0
    assert list(reset_second.profile.scores) == []

    read_second_after_reset = stub_b.GetProfile(pb2.GetProfileRequest(profile_id=second_id))
    assert read_second_after_reset.profile.age == 0
    assert list(read_second_after_reset.profile.scores) == []

    third_still_present = stub_b.GetProfile(pb2.GetProfileRequest(profile_id=third_id))
    assert third_still_present.profile.age == third_age
    assert list(third_still_present.profile.scores) == third_scores

    reset_missing = stub_b.ResetProfile(pb2.ResetProfileRequest(profile_id=missing_id))
    assert reset_missing.profile.age == 0
    assert list(reset_missing.profile.scores) == []

    first_still_present = stub_a.GetProfile(pb2.GetProfileRequest(profile_id=first_id))
    assert first_still_present.profile.age == updated_first_age
    assert list(first_still_present.profile.scores) == updated_first_scores

    channel_a.close()
    channel_b.close()
