#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

wasm2c /app/module.wasm -n pipeline -o "$workdir/pipeline.c"

cat > "$workdir/main.c" <<'C_EOF'
#include <dlfcn.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "pipeline.h"
#include "wasm-rt.h"

typedef int64_t (*crunch_fn)(const uint8_t* data);

int main(void) {
    wasm_rt_init();

    w2c_pipeline instance;
    wasm2c_pipeline_instantiate(&instance);

    uint32_t base = w2c_pipeline_get_base(&instance);
    uint32_t delta = w2c_pipeline_get_delta(&instance);
    uint32_t offset = base ^ delta;

    wasm_rt_memory_t* heap = w2c_pipeline_heap(&instance);
    if ((uint64_t)offset + 16 > heap->size) {
        fprintf(stderr, "buffer out of bounds\n");
        wasm2c_pipeline_free(&instance);
        wasm_rt_free();
        return 1;
    }

    void* handle = dlopen("/app/libcompute.so", RTLD_NOW);
    if (handle == NULL) {
        fprintf(stderr, "%s\n", dlerror());
        wasm2c_pipeline_free(&instance);
        wasm_rt_free();
        return 1;
    }

    crunch_fn crunch = (crunch_fn)dlsym(handle, "crunch");
    if (crunch == NULL) {
        fprintf(stderr, "%s\n", dlerror());
        dlclose(handle);
        wasm2c_pipeline_free(&instance);
        wasm_rt_free();
        return 1;
    }

    int64_t result = crunch(&heap->data[offset]);

    FILE* output = fopen("/app/output.txt", "w");
    if (output == NULL) {
        perror("fopen");
        dlclose(handle);
        wasm2c_pipeline_free(&instance);
        wasm_rt_free();
        return 1;
    }

    fprintf(output, "%" PRId64 "\n", result);
    fclose(output);

    dlclose(handle);
    wasm2c_pipeline_free(&instance);
    wasm_rt_free();
    return 0;
}
C_EOF

gcc -O2 \
    -I"$workdir" \
    -I/usr/include \
    -o "$workdir/run_pipeline" \
    "$workdir/main.c" \
    "$workdir/pipeline.c" \
    /usr/share/wabt/wasm2c/wasm-rt-impl.c \
    -ldl -lm

"$workdir/run_pipeline"
EOF

chmod +x /app/run_pipeline.sh
/app/run_pipeline.sh
