#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

python3 /app/run_pipeline.py
EOF

cat > /app/run_pipeline.py <<'EOF'
#!/usr/bin/env python3
import ctypes
from dataclasses import dataclass
from pathlib import Path


PAGE_SIZE = 65536
BYTE_COUNT = 16


def to_u32(value: int) -> int:
    return value & 0xFFFFFFFF


def to_i32(value: int) -> int:
    value &= 0xFFFFFFFF
    if value & 0x80000000:
        value -= 0x100000000
    return value


def read_u32(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def read_i32(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            if shift < 32 and byte & 0x40:
                value |= -1 << shift
            return to_i32(value), offset


def read_name(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = read_u32(data, offset)
    end = offset + length
    return data[offset:end].decode("utf-8"), end


@dataclass
class WasmFunction:
    type_index: int
    locals_types: list[int]
    code: bytes


class WasmModule:
    def __init__(self, wasm: bytes) -> None:
        if wasm[:4] != b"\x00asm" or wasm[4:8] != b"\x01\x00\x00\x00":
            raise ValueError("invalid wasm header")
        self.types: list[tuple[list[int], list[int]]] = []
        self.function_type_indices: list[int] = []
        self.functions: list[WasmFunction] = []
        self.memory_pages = 0
        self.globals_meta: list[tuple[int, int, bytes]] = []
        self.exports: dict[str, tuple[int, int]] = {}
        self.start_function: int | None = None
        self.data_segments: list[tuple[int, bytes]] = []
        self.global_values: list[int] = []
        self.memory = bytearray()
        self._parse(wasm)
        self._instantiate()

    def _iter_sections(self, wasm: bytes):
        offset = 8
        while offset < len(wasm):
            section_id = wasm[offset]
            offset += 1
            size, offset = read_u32(wasm, offset)
            end = offset + size
            yield section_id, wasm[offset:end]
            offset = end

    def _parse_type_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for _ in range(count):
            if payload[offset] != 0x60:
                raise ValueError("unsupported function type")
            offset += 1
            param_count, offset = read_u32(payload, offset)
            params = list(payload[offset : offset + param_count])
            offset += param_count
            result_count, offset = read_u32(payload, offset)
            results = list(payload[offset : offset + result_count])
            offset += result_count
            self.types.append((params, results))

    def _parse_function_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for _ in range(count):
            type_index, offset = read_u32(payload, offset)
            self.function_type_indices.append(type_index)

    def _parse_memory_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        if count == 0:
            return
        flags = payload[offset]
        offset += 1
        minimum, offset = read_u32(payload, offset)
        self.memory_pages = minimum
        if flags & 1:
            _, offset = read_u32(payload, offset)

    def _read_init_expr(self, payload: bytes, offset: int) -> tuple[bytes, int]:
        start = offset
        while payload[offset] != 0x0B:
            opcode = payload[offset]
            offset += 1
            if opcode == 0x41:
                _, offset = read_i32(payload, offset)
            elif opcode == 0x23:
                _, offset = read_u32(payload, offset)
            else:
                raise ValueError("unsupported init expr opcode")
        return payload[start : offset + 1], offset + 1

    def _parse_global_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for _ in range(count):
            value_type = payload[offset]
            mutable = payload[offset + 1]
            offset += 2
            expr, offset = self._read_init_expr(payload, offset)
            self.globals_meta.append((value_type, mutable, expr))

    def _parse_export_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for _ in range(count):
            name, offset = read_name(payload, offset)
            kind = payload[offset]
            offset += 1
            index, offset = read_u32(payload, offset)
            self.exports[name] = (kind, index)

    def _parse_code_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for i in range(count):
            body_size, offset = read_u32(payload, offset)
            body_end = offset + body_size
            locals_count, offset = read_u32(payload, offset)
            locals_types: list[int] = []
            for _ in range(locals_count):
                count_local, offset = read_u32(payload, offset)
                value_type = payload[offset]
                offset += 1
                locals_types.extend([value_type] * count_local)
            code = payload[offset:body_end]
            offset = body_end
            self.functions.append(WasmFunction(self.function_type_indices[i], locals_types, code))

    def _parse_data_section(self, payload: bytes) -> None:
        offset = 0
        count, offset = read_u32(payload, offset)
        for _ in range(count):
            flag, offset = read_u32(payload, offset)
            if flag == 0:
                expr, offset = self._read_init_expr(payload, offset)
                segment_size, offset = read_u32(payload, offset)
                segment = payload[offset : offset + segment_size]
                offset += segment_size
                self.data_segments.append((self._eval_const_expr(expr), segment))
            elif flag == 2:
                _, offset = read_u32(payload, offset)
                expr, offset = self._read_init_expr(payload, offset)
                segment_size, offset = read_u32(payload, offset)
                segment = payload[offset : offset + segment_size]
                offset += segment_size
                self.data_segments.append((self._eval_const_expr(expr), segment))
            else:
                raise ValueError("unsupported data segment kind")

    def _parse(self, wasm: bytes) -> None:
        for section_id, payload in self._iter_sections(wasm):
            if section_id == 1:
                self._parse_type_section(payload)
            elif section_id == 3:
                self._parse_function_section(payload)
            elif section_id == 5:
                self._parse_memory_section(payload)
            elif section_id == 6:
                self._parse_global_section(payload)
            elif section_id == 7:
                self._parse_export_section(payload)
            elif section_id == 8:
                self.start_function, _ = read_u32(payload, 0)
            elif section_id == 10:
                self._parse_code_section(payload)
            elif section_id == 11:
                self._parse_data_section(payload)

    def _instantiate(self) -> None:
        self.memory = bytearray(self.memory_pages * PAGE_SIZE)
        self.global_values = []
        for _, _, expr in self.globals_meta:
            self.global_values.append(to_u32(self._eval_const_expr(expr)))
        for offset, data in self.data_segments:
            end = offset + len(data)
            if end > len(self.memory):
                raise ValueError("data segment out of bounds")
            self.memory[offset:end] = data
        if self.start_function is not None:
            self.execute_function(self.start_function, [])

    def _eval_const_expr(self, expr: bytes) -> int:
        offset = 0
        stack: list[int] = []
        while True:
            opcode = expr[offset]
            offset += 1
            if opcode == 0x41:
                value, offset = read_i32(expr, offset)
                stack.append(to_u32(value))
            elif opcode == 0x23:
                index, offset = read_u32(expr, offset)
                stack.append(self.global_values[index])
            elif opcode == 0x0B:
                return to_i32(stack.pop() if stack else 0)
            else:
                raise ValueError("unsupported const expr opcode")

    def execute_function(self, func_index: int, args: list[int]) -> int:
        func = self.functions[func_index]
        params, results = self.types[func.type_index]
        locals_values = [to_u32(arg) for arg in args]
        locals_values.extend(0 for _ in func.locals_types)
        stack: list[int] = []
        code = func.code
        offset = 0
        while offset < len(code):
            opcode = code[offset]
            offset += 1
            if opcode == 0x0B:
                break
            if opcode == 0x0F:
                break
            if opcode == 0x10:
                callee, offset = read_u32(code, offset)
                param_types, callee_results = self.types[self.functions[callee].type_index]
                call_args = [stack.pop() for _ in range(len(param_types))]
                call_args.reverse()
                result = self.execute_function(callee, call_args)
                if callee_results:
                    stack.append(to_u32(result))
            elif opcode == 0x20:
                local_index, offset = read_u32(code, offset)
                stack.append(locals_values[local_index])
            elif opcode == 0x21:
                local_index, offset = read_u32(code, offset)
                locals_values[local_index] = stack.pop()
            elif opcode == 0x22:
                local_index, offset = read_u32(code, offset)
                value = stack[-1]
                locals_values[local_index] = value
            elif opcode == 0x23:
                global_index, offset = read_u32(code, offset)
                stack.append(self.global_values[global_index])
            elif opcode == 0x24:
                global_index, offset = read_u32(code, offset)
                self.global_values[global_index] = to_u32(stack.pop())
            elif opcode == 0x28:
                align, offset = read_u32(code, offset)
                mem_offset, offset = read_u32(code, offset)
                _ = align
                addr = to_u32(stack.pop()) + mem_offset
                stack.append(int.from_bytes(self.memory[addr : addr + 4], "little"))
            elif opcode == 0x2D:
                align, offset = read_u32(code, offset)
                mem_offset, offset = read_u32(code, offset)
                _ = align
                addr = to_u32(stack.pop()) + mem_offset
                stack.append(self.memory[addr])
            elif opcode == 0x36:
                align, offset = read_u32(code, offset)
                mem_offset, offset = read_u32(code, offset)
                _ = align
                value = to_u32(stack.pop())
                addr = to_u32(stack.pop()) + mem_offset
                self.memory[addr : addr + 4] = value.to_bytes(4, "little")
            elif opcode == 0x3A:
                align, offset = read_u32(code, offset)
                mem_offset, offset = read_u32(code, offset)
                _ = align
                value = stack.pop() & 0xFF
                addr = to_u32(stack.pop()) + mem_offset
                self.memory[addr] = value
            elif opcode == 0x41:
                value, offset = read_i32(code, offset)
                stack.append(to_u32(value))
            elif opcode == 0x45:
                stack.append(1 if to_u32(stack.pop()) == 0 else 0)
            elif opcode == 0x6A:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a + b))
            elif opcode == 0x6B:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a - b))
            elif opcode == 0x6C:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a * b))
            elif opcode == 0x71:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a & b))
            elif opcode == 0x72:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a | b))
            elif opcode == 0x73:
                b = stack.pop()
                a = stack.pop()
                stack.append(to_u32(a ^ b))
            elif opcode == 0x74:
                b = stack.pop() & 31
                a = stack.pop()
                stack.append(to_u32(a << b))
            elif opcode == 0x75:
                b = stack.pop() & 31
                a = to_i32(stack.pop())
                stack.append(to_u32(a >> b))
            elif opcode == 0x76:
                b = stack.pop() & 31
                a = to_u32(stack.pop())
                stack.append(to_u32(a >> b))
            else:
                raise ValueError(f"unsupported opcode: 0x{opcode:02x}")
        if results:
            return to_i32(stack.pop() if stack else 0)
        return 0


def main() -> None:
    module = WasmModule(Path("/app/module.wasm").read_bytes())
    export_kind, produce_index = module.exports["produce"]
    if export_kind != 0:
        raise ValueError("produce export is not a function")
    memory_export = module.exports.get("memory")
    if memory_export is None or memory_export[0] != 2:
        raise ValueError("memory export not found")

    ptr = module.execute_function(produce_index, [])
    if ptr < 0 or ptr + BYTE_COUNT > len(module.memory):
        raise ValueError("produce returned out-of-bounds pointer")
    data = bytes(module.memory[ptr : ptr + BYTE_COUNT])

    lib = ctypes.CDLL("/app/libcompute.so")
    fold_bytes = lib.fold_bytes
    fold_bytes.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
    fold_bytes.restype = ctypes.c_int32
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    result = int(fold_bytes(buf))
    Path("/app/output.txt").write_text(str(result))


if __name__ == "__main__":
    main()
EOF

chmod +x /app/run_pipeline.sh /app/run_pipeline.py
/app/run_pipeline.sh
