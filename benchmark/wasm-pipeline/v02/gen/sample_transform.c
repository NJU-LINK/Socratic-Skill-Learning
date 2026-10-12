#include <stdint.h>

int32_t fold_bytes(const uint8_t *data)
{
    int32_t total = 0;
    for (int i = 0; i < 16; ++i)
    {
        total += (int32_t)data[i];
    }
    return total - 832;
}
