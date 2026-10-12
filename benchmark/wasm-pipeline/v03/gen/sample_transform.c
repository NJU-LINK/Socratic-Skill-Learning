#include <stdint.h>

int64_t score_bytes(const uint8_t *data, uint32_t len)
{
    uint64_t h = 1469598103934665603ULL;
    for (uint32_t i = 0; i < len; ++i)
    {
        h ^= (uint64_t)data[i];
        h *= 1099511628211ULL;
    }

    __int128 t = ((__int128)((int64_t)h) * ((__int128)31337)) + ((__int128)2718281);
    int64_t y = (int64_t)t;
    return y ^ (int64_t)424242;
}
