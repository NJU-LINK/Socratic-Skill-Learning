;; SAMPLE ONLY (tests generate their own wasm and contract).
;; Writes 16 bytes at offset 4096, returns 4096 through a renamed export.
(module
  (memory (export "heap") 1)
  (data (i32.const 4096) "manifest-guides!")
  (func (export "emit") (result i32)
    i32.const 4096))
