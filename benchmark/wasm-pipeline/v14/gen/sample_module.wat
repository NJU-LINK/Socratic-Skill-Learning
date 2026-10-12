;; SAMPLE ONLY (tests generate their own wasm).
;; The real pointer is get_base() xor get_delta().
(module
  (memory (export "heap") 1)
  (data (i32.const 4352) "0123456789abcdef")
  (func (export "get_base") (result i32)
    i32.const 23040)
  (func (export "get_delta") (result i32)
    i32.const 19200))
