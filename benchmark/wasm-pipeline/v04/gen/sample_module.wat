;; SAMPLE ONLY (tests provide different inputs).
;; produce_region returns a packed i64: high 32 bits = length, low 32 bits = offset.
(module
  (memory (export "memory") 1)
  (data (i32.const 4096) "variable-length-demo")
  (func (export "produce_region") (result i64)
    i64.const 85899350016))
