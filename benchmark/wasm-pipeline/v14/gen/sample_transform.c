#include <stdint.h>

int64_t crunch(const uint8_t *data)
{
    uint64_t len = 16;
    return (int64_t)data[len - 1];
}
