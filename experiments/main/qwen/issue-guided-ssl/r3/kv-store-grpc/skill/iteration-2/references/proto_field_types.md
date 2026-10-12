# Proto3 Field Types Reference

## Scalar Types
| Proto Type | Python Type | Default Value | Notes |
|-----------|-------------|---------------|-------|
| `double` | float | 0.0 | 64-bit IEEE float |
| `float` | float | 0.0 | 32-bit IEEE float |
| `int32` | int | 0 | Variable-length encoding, inefficient for negative |
| `int64` | int | 0 | Variable-length encoding, inefficient for negative |
| `uint32` | int | 0 | Variable-length encoding |
| `uint64` | int | 0 | Variable-length encoding |
| `sint32` | int | 0 | ZigZag encoding, efficient for negatives |
| `sint64` | int | 0 | ZigZag encoding, efficient for negatives |
| `fixed32` | int | 0 | Always 4 bytes |
| `fixed64` | int | 0 | Always 8 bytes |
| `sfixed32` | int | 0 | Always 4 bytes |
| `sfixed64` | int | 0 | Always 8 bytes |
| `bool` | bool | False | |
| `string` | str | "" | UTF-8 or ASCII |
| `bytes` | bytes | b"" | Arbitrary byte sequence |

## Field Rules
- Field numbers start at 1 (not 0)
- Field numbers 19000-19999 are reserved (cannot use)
- Each field in a message must have a unique number
- In proto3, all fields are optional with defaults

## Complex Field Types
- `repeated Type name = N;` — list of values
- `map<KeyType, ValueType> name = N;` — key-value pairs (KeyType must be scalar)
- Nested messages: define message inside another message or reference by name

## Naming Conventions
- Message names: PascalCase (e.g., `PutRequest`)
- Field names: snake_case (e.g., `namespace_id`)
- Service names: PascalCase (e.g., `KVStore`)
- RPC names: PascalCase (e.g., `Fetch`)
- Enum values: UPPER_SNAKE_CASE (e.g., `STATUS_OK`)

## Generated Python Module Names
- `my-service.proto` → `my_service_pb2.py`, `my_service_pb2_grpc.py`
- Hyphens in filename become underscores in Python module names
- Always import using the underscore form
