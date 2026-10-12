;; SAMPLE ONLY (tests generate their own wasm).
;; Returns a packed i64: low 32 bits are the offset, high 32 bits are the length.
(module
  (memory (export "mem0") 1)
  (data (i32.const 4096) "packed-pointer-demo")
  (func (export "produce_packed") (result i64)
    i64.const 81604382720))
