#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/ptrace.h>

static struct {
    unsigned char encrypted_key[38];
    char allowed[63];
} data = {
    .encrypted_key = {
        0x04, 0x0e, 0x03, 0x05, 0x39, 0x20, 0x76, 0x24, 0x24, 0x71, 0x30, 0x1d,
        0x72, 0x34, 0x71, 0x30, 0x24, 0x2e, 0x72, 0x35, 0x1d, 0x2f, 0x76, 0x31,
        0x36, 0x71, 0x30, 0x1d, 0x29, 0x71, 0x3b, 0x1d, 0x70, 0x72, 0x70, 0x76,
        0x3f, 0x42
    },
    .allowed = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
};

const int allowed_size = sizeof(data.allowed) - 1;

int is_being_debugged() {
    if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) {
        return 1;
    }
    ptrace(PTRACE_DETACH, 0, 0, 0);
    return 0;
}

int main() {
    if (is_being_debugged()) {
        return 1;
    }

    printf("Safe Key Viewer v1.0\n");
    printf("Enter index (0-%d) to view character, or -1 to quit:\n", allowed_size - 1);
    fflush(stdout);

    int index;
    while (1) {
        printf("> ");
        fflush(stdout);
        if (scanf("%d", &index) != 1) break;
        if (index == -1) break;

        if (index < allowed_size) {
            printf("%c\n", data.allowed[index]);
        } else {
            printf("Index out of bounds!\n");
        }
        fflush(stdout);
    }

    return 0;
}
