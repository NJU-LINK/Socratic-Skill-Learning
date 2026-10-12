#include <stdint.h>

int64_t transform(const uint8_t* data, uint32_t len) {
    uint64_t h = 1469598103934665603ULL;
    for (uint32_t i = 0; i < len; ++i) {
        h ^= (uint64_t)data[i];
        h *= 1099511628211ULL;
    }
    return (int64_t)((h ^ len) % 257ULL);
}
