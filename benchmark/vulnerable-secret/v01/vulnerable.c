#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <unistd.h>

#define AUTH_MAGIC 0x51A7C0DEu

static const unsigned char encrypted_secret[] = {
    0x04, 0x0e, 0x03, 0x05, 0x39, 0x31, 0x36, 0x23,
    0x21, 0x29, 0x1d, 0x25, 0x23, 0x36, 0x27, 0x1d,
    0x30, 0x37, 0x2c, 0x36, 0x2b, 0x2f, 0x27, 0x1d,
    0x31, 0x27, 0x21, 0x30, 0x27, 0x36, 0x3f, 0x42
};

struct access_record {
    char input[64];
    uint32_t authenticated;
} __attribute__((packed));

static int is_being_debugged(void) {
    if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) {
        return 1;
    }
    return 0;
}

static void reveal_secret(void) {
    char secret[sizeof(encrypted_secret)];
    size_t i;

    if (is_being_debugged()) {
        puts("Tracing detected; access denied.");
        exit(1);
    }

    for (i = 0; i + 1 < sizeof(encrypted_secret); i++) {
        secret[i] = (char)(encrypted_secret[i] ^ 0x42);
    }
    secret[i] = '\0';
    printf("Access granted! Secret: %s\n", secret);
}

int main(void) {
    volatile struct access_record record;
    ssize_t received;

    memset((void *)&record, 0, sizeof(record));
    puts("Local Access Utility");
    printf("Input: ");
    fflush(stdout);

    received = read(STDIN_FILENO, (void *)record.input, sizeof(record));
    if (received < 0) {
        perror("read");
        return 1;
    }

    if (record.authenticated == AUTH_MAGIC) {
        puts("Authentication bypassed.");
        reveal_secret();
    } else {
        puts("Input accepted; authorization unchanged.");
    }
    return 0;
}
