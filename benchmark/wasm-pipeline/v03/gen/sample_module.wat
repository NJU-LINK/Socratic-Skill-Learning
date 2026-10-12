;; SAMPLE ONLY (tests generate their own wasm).
;; Writes 19 bytes at offset 4096 and exposes the pointer and length separately.
(module
  (memory (export "mem") 1)
  (data (i32.const 4096) "renamed-export-demo")
  (func (export "emit_ptr") (result i32)
    i32.const 4096)
  (func (export "emit_len") (result i32)
    i32.const 19))
