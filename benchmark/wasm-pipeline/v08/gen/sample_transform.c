#include <stddef.h>
#include <stdint.h>

int64_t transform(const uint8_t *data, size_t len)
{
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < len; ++i)
    {
        h ^= (uint64_t)data[i];
        h *= 1099511628211ULL;
    }
    return (int64_t)h;
}
