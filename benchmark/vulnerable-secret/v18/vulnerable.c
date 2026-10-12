#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/ptrace.h>
#include <openssl/sha.h>

// XOR-encrypted seed value (key 0x5A)
unsigned char enc_seed[] = {
    0x3e, 0x69, 0x6e, 0x3e, 0x38, 0x69, 0x69, 0x3c, 0x05, 0x32,
    0x69, 0x6e, 0x2a, 0x05, 0x37, 0x6e, 0x29, 0x2e, 0x69, 0x28,
    0x05, 0x68, 0x6a, 0x68, 0x6c, 0x5A
};

struct auth_data {
    int authenticated;
    char reserved[60];
};

int is_being_debugged() {
    if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) {
        return 1;
    }
    ptrace(PTRACE_DETACH, 0, 0, 0);
    return 0;
}

void compute_and_print_secret() {
    if (is_being_debugged()) {
        printf("Debugging detected! Access denied.\n");
        exit(1);
    }

    unsigned char hash[SHA256_DIGEST_LENGTH];
    char input[128];
    char secret[64];
    char seed[64];
    int i = 0;

    while (enc_seed[i] != 0x5A) {
        seed[i] = enc_seed[i] ^ 0x5A;
        i++;
    }
    seed[i] = '\0';

    snprintf(input, sizeof(input), "secret_salt_%s", seed);
    SHA256((unsigned char *)input, strlen(input), hash);

    snprintf(secret, sizeof(secret), "FLAG{");
    for (i = 0; i < 16; i++) {
        snprintf(secret + 5 + (i * 2), 3, "%02x", hash[i]);
    }
    secret[37] = '}';
    secret[38] = '\0';

    printf("Access granted! Secret: %s\n", secret);
}

void vulnerable_function() {
    struct auth_data *auth = NULL;
    char *buffer = NULL;

    auth = (struct auth_data *)malloc(sizeof(struct auth_data));
    if (!auth) {
        printf("Memory allocation failed!\n");
        return;
    }
    memset(auth, 0, sizeof(struct auth_data));

    free(auth);

    buffer = (char *)malloc(sizeof(struct auth_data));
    if (!buffer) {
        printf("Memory allocation failed!\n");
        return;
    }

    printf("Enter your input: ");
    fflush(stdout);

    read(STDIN_FILENO, buffer, sizeof(struct auth_data));

    if (auth->authenticated == 1) {
        printf("Authentication bypassed!\n");
        compute_and_print_secret();
    } else {
        printf("Input processed successfully.\n");
    }

    free(buffer);
}

int main() {
    printf("Welcome to the Security Challenge!\n");
    printf("This program processes user input.\n");
    printf("Find a way to extract the hidden information.\n");

    vulnerable_function();

    return 0;
}
