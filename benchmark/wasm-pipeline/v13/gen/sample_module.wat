;; SAMPLE ONLY (tests generate their own wasm).
;; The target bytes are written only after calling the exported seed_state function.
(module
  (memory (export "memory") 1)
  (data (i32.const 4096) "................")
  (func (export "seed_state")
    i32.const 4096
    i32.const 115
    i32.store8
    i32.const 4097
    i32.const 116
    i32.store8
    i32.const 4098
    i32.const 97
    i32.store8
    i32.const 4099
    i32.const 116
    i32.store8
    i32.const 4100
    i32.const 101
    i32.store8
    i32.const 4101
    i32.const 102
    i32.store8
    i32.const 4102
    i32.const 117
    i32.store8
    i32.const 4103
    i32.const 108
    i32.store8
    i32.const 4104
    i32.const 45
    i32.store8
    i32.const 4105
    i32.const 111
    i32.store8
    i32.const 4106
    i32.const 117
    i32.store8
    i32.const 4107
    i32.const 116
    i32.store8
    i32.const 4108
    i32.const 112
    i32.store8
    i32.const 4109
    i32.const 117
    i32.store8
    i32.const 4110
    i32.const 116
    i32.store8
    i32.const 4111
    i32.const 33
    i32.store8)
  (func (export "produce") (result i32)
    i32.const 4096))
