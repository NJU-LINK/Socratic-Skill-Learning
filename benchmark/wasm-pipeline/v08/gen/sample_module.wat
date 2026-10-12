;; SAMPLE ONLY (tests generate their own wasm).
;; Exposes descriptor() -> ptr to four little-endian i32 values: ptr1,len1,ptr2,len2.
(module
  (memory (export "memory") 1)
  (data (i32.const 2048) "segment")
  (data (i32.const 3072) "edbuffer1")
  (data (i32.const 1024)
    "\00\08\00\00"
    "\07\00\00\00"
    "\00\0c\00\00"
    "\09\00\00\00")
  (func (export "descriptor") (result i32)
    i32.const 1024))
