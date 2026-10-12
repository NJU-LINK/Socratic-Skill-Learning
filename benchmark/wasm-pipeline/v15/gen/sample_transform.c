#include <stdint.h>

int64_t transform(const uint8_t *data)
{
    uint64_t total = 0;
    for (uint64_t i = 0; i < 16; ++i)
    {
        total += data[i];
    }
    return (int64_t)total;
}
