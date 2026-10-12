(module
  (memory (export "memory") 1)
  (data (i32.const 4096) "\61\61\61\61\6e\63")
  (func (export "produce") (result i32)
    i32.const 4096)
  (func (export "produce_len") (result i32)
    i32.const 6))
