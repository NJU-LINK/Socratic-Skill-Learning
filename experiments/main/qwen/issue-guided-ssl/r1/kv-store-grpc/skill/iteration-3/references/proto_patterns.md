# Proto Authoring Patterns

## Basic Structure

Every proto file follows this skeleton:

```protobuf
syntax = "proto3";
package <package_name>;

service <ServiceName> {
  rpc <MethodA>(<RequestA>) returns (<ResponseA>);
  rpc <MethodB>(<RequestB>) returns (<ResponseB>);
}

message <RequestA> { ... }
message <ResponseA> { ... }
```

## Field Types Reference

### Scalar Types
| Proto Type | Python Type | Default Value |
|------------|-------------|---------------|
| `string`   | `str`       | `""`          |
| `int32`    | `int`       | `0`           |
| `int64`    | `int`       | `0`           |
| `float`    | `float`     | `0.0`         |
| `double`   | `float`     | `0.0`         |
| `bool`     | `bool`      | `False`       |
| `bytes`    | `bytes`     | `b""`         |

### Complex Types

**Nested messages:**
```protobuf
message Address {
  string street = 1;
  string city = 2;
}
message Person {
  string name = 1;
  Address address = 2;
}
```

**Repeated fields (lists):**
```protobuf
message BatchRequest {
  repeated string keys = 1;
  repeated int32 values = 2;
}
```

**Enum fields:**
```protobuf
enum Color {
  RED = 0;    // First value MUST be 0 in proto3
  GREEN = 1;
  BLUE = 2;
}
message Item {
  Color color = 1;
}
```

**Map fields:**
```protobuf
message Config {
  map<string, string> settings = 1;
  map<int32, string> indexed_items = 2;
}
```

**Oneof (mutually exclusive fields):**
```protobuf
message Filter {
  oneof criterion {
    string name_filter = 1;
    int32 id_filter = 2;
  }
}
```

## Naming Conventions

- **Proto filename**: Can use hyphens (`kv-store.proto`), but Python modules use underscores (`kv_store_pb2`)
- **Package**: lowercase, no separators (`kvstore`)
- **Service**: PascalCase (`KVStore`, `UserService`)
- **RPC methods**: PascalCase (`Put`, `Fetch`, `ListNamespaceTotal`)
- **Messages**: PascalCase (`PutRequest`, `FetchResponse`)
- **Fields**: snake_case (`namespace`, `key`, `value`)

## Multiple Services

```protobuf
service ReadService {
  rpc Get(GetRequest) returns (GetResponse);
}
service WriteService {
  rpc Set(SetRequest) returns (SetResponse);
}
```

Each service generates its own Servicer and Stub classes.

## Code Generation Command

```bash
python -m grpc_tools.protoc \
  -I<proto_dir> \
  --python_out=<output_dir> \
  --grpc_python_out=<output_dir> \
  <proto_dir>/<file>.proto
```

The `-I` flag specifies the import search path. Output files are named:
- `<filename_without_ext>_pb2.py`
- `<filename_without_ext>_pb2_grpc.py`

Where `<filename_without_ext>` has hyphens replaced with underscores.
