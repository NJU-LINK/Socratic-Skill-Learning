;; SAMPLE ONLY (tests generate their own wasm and seed file).
;; init(seed_ptr) copies 8 seed bytes into scratch space, xors/adds constants,
;; then produce() returns the offset of the derived 16-byte buffer.
(module
  (memory (export "memory") 1)
  (data (i32.const 2048) "................................")
  (data (i32.const 4096) "................")
  (global $ready (mut i32) (i32.const 0))

  (func (export "init") (param $seed_ptr i32)
    (local $i i32)
    (local $b i32)
    (local.set $i (i32.const 0))
    (loop $seed_loop
      (local.set $b
        (i32.load8_u (i32.add (local.get $seed_ptr) (local.get $i))))
      (i32.store8
        (i32.add (i32.const 2048) (local.get $i))
        (local.get $b))
      (i32.store8
        (i32.add (i32.const 4096) (local.get $i))
        (i32.xor (local.get $b) (i32.add (i32.const 16) (local.get $i))))
      (i32.store8
        (i32.add (i32.const 4096) (i32.add (local.get $i) (i32.const 8)))
        (i32.and
          (i32.add (local.get $b) (i32.const 97))
          (i32.const 255)))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br_if $seed_loop (i32.lt_u (local.get $i) (i32.const 8))))
    (global.set $ready (i32.const 1)))

  (func (export "produce") (result i32)
    (if (i32.eqz (global.get $ready))
      (then unreachable))
    (i32.const 4096)))
