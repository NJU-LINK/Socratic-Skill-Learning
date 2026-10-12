# Proto3 to Python Mechanics Reference

## Enum

Proto3 requires first value to be 0 (default):
```protobuf
enum OpType {
  OP_UNSPECIFIED = 0;
  OP_INCREMENT = 1;
  OP_DECREMENT = 2;
}
message MutateRequest {
  string key = 1;
  OpType op = 2;
  int32 delta = 3;
}
```

Python access:
```python
# Enum field is an int
if request.op == pb.OP_INCREMENT:
    pass

# Name lookup
name = pb.OpType.Name(request.op)  # "OP_INCREMENT"

# Number lookup
value = pb.OpType.Value("OP_INCREMENT")  # 1
```

## Repeated Fields

```protobuf
message BatchRequest {
  repeated string keys = 1;
  repeated int32 values = 2;
}
```

Python access:
```python
# Iterate directly
for key in request.keys:
    pass

# Length
num_keys = len(request.keys)

# Copy to list (if mutation needed)
key_list = list(request.keys)

# Response construction
return pb.BatchResponse(keys=["a", "b", "c"])

# Or extend
resp = pb.BatchResponse()
resp.keys.extend(["a", "b"])
```

## Nested Messages

```protobuf
message Entry {
  string key = 1;
  int32 value = 2;
}

message BatchPutRequest {
  string namespace = 1;
  repeated Entry entries = 2;
}
```

Python access:
```python
# Construct nested message
entry = pb.Entry(key="k", value=42)

# Or using namespace if nested inside another message
# entry = pb.BatchPutRequest.Entry(key="k", value=42)

# Access nested fields
for entry in request.entries:
    store[entry.key] = entry.value
```

## Map Fields

```protobuf
message Snapshot {
  map<string, int32> items = 1;
}
```

Python access:
```python
# Iterate
for key, value in request.items.items():
    pass

# Copy to dict (mutable)
items_dict = dict(request.items)

# Response: assign dict
return pb.Snapshot(items={"a": 1, "b": 2})
```

## Presence (HasField)

**Critical**: proto3 scalar fields have NO presence by default. Cannot distinguish "not sent" from "sent with default value".

To enable presence, use `optional`:
```protobuf
message UpdateRequest {
  string key = 1;
  optional int32 value = 2;  # Now has presence
}
```

Python access:
```python
if request.HasField("value"):
    # Client explicitly sent value
    store[key] = request.value
else:
    # Field not sent - skip update
    pass
```

**Rules**:
- Message fields always have presence: `request.HasField("sub_message")` works without `optional`
- Scalar fields without `optional`: `HasField` raises `ValueError`
- Use `optional` when task requires distinguishing "not provided" from "default value"

## oneof

```protobuf
message Conditional {
  oneof choice {
    int32 delta = 1;
    int32 absolute = 2;
  }
}
```

Python access:
```python
which = request.WhichOneof("choice")
if which == "delta":
    value += request.delta
elif which == "absolute":
    value = request.absolute
else:
    # None set
    pass
```

## Regeneration Rule

After editing proto:
1. Delete old `_pb2.py` and `_pb2_grpc.py` to avoid stale descriptor errors
2. Regenerate: `python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <file>.proto`
3. Module name still derives from proto filename (dashes→underscores), independent of `package` statement

## Python Type Summary

| Proto Type | Python Type | Notes |
|------------|-------------|-------|
| `string` | `str` | UTF-8 |
| `int32` | `int` | C int range |
| `int64` | `int` | Python int unbounded |
| `bool` | `bool` | |
| `enum` | `int` | Compare with pb.ENUM_VALUE |
| `repeated T` | `RepeatedScalarContainer` | Iterate, `len()`, `list()` copy |
| `map<K,V>` | `MessageMap` | `dict()` copy for mutation |
| message | message class | `HasField()` always works |
| `optional T` | `T` | `HasField()` to check presence |
| `oneof` | fields | `WhichOneof()` to check |
