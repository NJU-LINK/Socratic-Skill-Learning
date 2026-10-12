#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define RC4_KEYLEN 16

__attribute__((used))
static const unsigned char encrypted_secret[] = {
    0x9b, 0x52, 0xd7, 0x4f, 0x51, 0xbd, 0x1a, 0x6a, 0x5f, 0xe8, 0x6d, 0xe2,
    0x80, 0x1e, 0x6c, 0x94, 0x84, 0x3a, 0xc0, 0x59, 0xd8, 0xc4, 0x48, 0x65,
    0x82, 0x48, 0x14, 0x02, 0xf2, 0xc5, 0xba, 0x63
};

__attribute__((used))
static const unsigned char rc4_key[RC4_KEYLEN] = {
    0x73, 0x33, 0x63, 0x72, 0x33, 0x74, 0x5f, 0x73,
    0x74, 0x72, 0x33, 0x34, 0x6d, 0x5f, 0x6b, 0x33
};

typedef struct {
    char buffer[248];
    void (*handler)(void);
} __attribute__((packed)) item_t;

static void safe_handler(void) {
    printf("Processing complete.\n");
}

static void rc4_init(unsigned char *S, const unsigned char *key, int keylen) {
    int i, j = 0;
    for (i = 0; i < 256; i++)
        S[i] = i;
    for (i = 0; i < 256; i++) {
        j = (j + S[i] + key[i % keylen]) % 256;
        unsigned char tmp = S[i];
        S[i] = S[j];
        S[j] = tmp;
    }
}

static void rc4_crypt(unsigned char *S, unsigned char *data, int len, unsigned char *out) {
    int i = 0, j = 0, k;
    for (k = 0; k < len; k++) {
        i = (i + 1) % 256;
        j = (j + S[i]) % 256;
        unsigned char tmp = S[i];
        S[i] = S[j];
        S[j] = tmp;
        out[k] = data[k] ^ S[(S[i] + S[j]) % 256];
    }
}

__attribute__((noinline))
static int opaque_check(int x) {
    volatile int y = x;
    if (y * y >= 0) {
        volatile int z = y;
        if (z + 1 > z) {
            return 1;
        }
    }
    return 0;
}

__attribute__((used))
static void secret_handler(void) {
    volatile int gate = 7;
    if (opaque_check(gate)) {
        unsigned char S[256];
        unsigned char decrypted[64];
        int secret_len = sizeof(encrypted_secret);

        rc4_init(S, rc4_key, RC4_KEYLEN);
        rc4_crypt(S, (unsigned char*)encrypted_secret, secret_len, decrypted);
        decrypted[secret_len] = '\0';

        printf("Access granted! Secret: %s\n", decrypted);
    } else {
        printf("Integrity check failed.\n");
        exit(1);
    }
}

int main(void) {
    unsigned int count;
    volatile int init_gate = 42;

    if (opaque_check(init_gate)) {
        printf("Welcome to the Data Processing System!\n");
        printf("Enter number of records to process: ");
        fflush(stdout);

        if (scanf("%u", &count) != 1) {
            printf("Invalid input.\n");
            return 1;
        }

        volatile int count_gate = 1;
        if (opaque_check(count_gate)) {
            if (count > 0) {
                size_t alloc_size = count * 256u;
                item_t *items = (item_t*)malloc(alloc_size);

                if (items == NULL) {
                    printf("Memory allocation failed.\n");
                    return 1;
                }

                items[0].handler = safe_handler;

                printf("Enter data: ");
                fflush(stdout);

                volatile int read_gate = 0;
                if (opaque_check(read_gate)) {
                    fread(items[0].buffer, 1, count, stdin);
                } else {
                    free(items);
                    return 1;
                }

                volatile int call_gate = 5;
                if (opaque_check(call_gate)) {
                    items[0].handler();
                } else {
                    free(items);
                    return 1;
                }

                free(items);
            } else {
                printf("Count must be positive.\n");
            }
        }
    } else {
        printf("Initialization failed.\n");
        return 1;
    }

    return 0;
}
