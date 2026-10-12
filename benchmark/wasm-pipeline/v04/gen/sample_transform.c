#include <stdint.h>

int64_t transform_region(const uint8_t *data, uint32_t len)
{
    int64_t total = (int64_t)len * 100;
    for (uint32_t i = 0; i < len; ++i) {
        total += data[i];
    }
    return total;
}
