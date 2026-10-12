#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <openssl/sha.h>
#include <fcntl.h>

/* Placeholder — patched by fix_checksum.py with SHA-256 of text segment */
static const unsigned char g_expected_text_hash[32] = {
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
    0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF,
    0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7,
    0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF
};

/* XOR string decryption */
static void xdec(unsigned char *dst, const unsigned char *src, int len, unsigned char key) {
    int i;
    for (i = 0; i < len; i++) dst[i] = src[i] ^ key;
    dst[len] = 0;
}

/* Encrypted strings (XOR key = 0x5A) */
static const unsigned char enc_seed[] = {
    0x33, 0x34, 0x30, 0x3f, 0x39, 0x2e, 0x05, 0x2e,
    0x32, 0x69, 0x05, 0x29, 0x69, 0x69, 0x3e, 0x05,
    0x68, 0x35, 0x68, 0x6f, 0x05, 0x39, 0x32, 0x6e,
    0x6b, 0x34, 0x05, 0x32, 0x6e, 0x29, 0x32, 0x05,
    0x3d, 0x69, 0x34, 0x5a
};
static const unsigned char enc_pass[] = {
    0x29, 0x69, 0x39, 0x2f, 0x28, 0x69, 0x05, 0x2a,
    0x6e, 0x29, 0x29, 0x05, 0x68, 0x6a, 0x68, 0x6f,
    0x05, 0x36, 0x35, 0x3d, 0x33, 0x34, 0x05, 0x31,
    0x69, 0x23, 0x5a
};
static const unsigned char enc_query[] = {
    0x37, 0x6e, 0x3d, 0x6b, 0x39, 0x05, 0x2b, 0x2f,
    0x69, 0x28, 0x23, 0x05, 0x2e, 0x6a, 0x31, 0x69,
    0x34, 0x05, 0x28, 0x69, 0x2a, 0x36, 0x05, 0x32,
    0x6e, 0x39, 0x31, 0x5a
};
static const unsigned char enc_admin[] = {
    0x6e, 0x3e, 0x37, 0x6b, 0x34, 0x05, 0x39, 0x6a,
    0x3e, 0x69, 0x05, 0x38, 0x28, 0x69, 0x6e, 0x31,
    0x05, 0x68, 0x6a, 0x68, 0x6f, 0x05, 0x28, 0x69,
    0x2a, 0x36, 0x5a
};

/* Read a 16-bit little-endian value from a buffer */
static unsigned short read_u16_le(const unsigned char *p) {
    return (unsigned short)p[0] | ((unsigned short)p[1] << 8);
}

/* Read a 64-bit little-endian value from a buffer */
static unsigned long long read_u64_le(const unsigned char *p) {
    return (unsigned long long)p[0]
        | ((unsigned long long)p[1] << 8)
        | ((unsigned long long)p[2] << 16)
        | ((unsigned long long)p[3] << 24)
        | ((unsigned long long)p[4] << 32)
        | ((unsigned long long)p[5] << 40)
        | ((unsigned long long)p[6] << 48)
        | ((unsigned long long)p[7] << 56);
}

#define PT_LOAD     1
#define PF_X        1

/* Parse /proc/self/exe ELF headers to find the first executable LOAD segment
 * and compute its SHA-256 directly from the file (not from memory mapping).
 * This matches what fix_checksum.py does at build time. */
static int verify_text_integrity(void) {
    unsigned char hdr[64];
    unsigned char buf[4096];
    unsigned char computed[SHA256_DIGEST_LENGTH];
    SHA256_CTX ctx;
    int fd, i, n;
    unsigned long long phoff, phsize, poff, pfsz;
    unsigned short phnum, phentsize;
    unsigned int ptype, pflags;
    long long remaining;

    fd = open("/proc/self/exe", O_RDONLY);
    if (fd < 0) return 0;

    /* Read ELF header */
    if (read(fd, hdr, 64) != 64) { close(fd); return 0; }
    if (hdr[0] != 0x7f || hdr[1] != 'E' || hdr[2] != 'L' || hdr[3] != 'F')
        { close(fd); return 0; }

    /* ELF64: program header offset at 0x20, phentsize at 0x36, phnum at 0x38 */
    phoff     = read_u64_le(hdr + 0x20);
    phentsize = read_u16_le(hdr + 0x36);
    phnum     = read_u16_le(hdr + 0x38);
    phsize    = (unsigned long long)phentsize * phnum;

    if (phoff == 0 || phnum == 0 || phentsize < 56) { close(fd); return 0; }

    /* Read program headers */
    {
        unsigned char *phdrs = (unsigned char *)malloc((size_t)phsize);
        if (!phdrs) { close(fd); return 0; }
        if (lseek(fd, (off_t)phoff, SEEK_SET) < 0) { free(phdrs); close(fd); return 0; }
        if (read(fd, phdrs, (size_t)phsize) != (ssize_t)phsize) { free(phdrs); close(fd); return 0; }

        /* Find first executable PT_LOAD */
        poff = 0;
        pfsz = 0;
        for (i = 0; i < phnum; i++) {
            ptype  = *(unsigned int *)(phdrs + i * phentsize);
            pflags = *(unsigned int *)(phdrs + i * phentsize + 4);
            if (ptype == PT_LOAD && (pflags & PF_X)) {
                poff = read_u64_le(phdrs + i * phentsize + 8);
                pfsz = read_u64_le(phdrs + i * phentsize + 32);
                break;
            }
        }
        free(phdrs);

        if (poff == 0 || pfsz == 0) { close(fd); return 0; }
    }

    /* Seek to the segment's file offset and hash p_filesz bytes */
    if (lseek(fd, (off_t)poff, SEEK_SET) < 0) { close(fd); return 0; }

    SHA256_Init(&ctx);
    remaining = (long long)pfsz;
    while (remaining > 0) {
        n = (int)(remaining > (long long)sizeof(buf) ? (long long)sizeof(buf) : remaining);
        if (read(fd, buf, n) != n) { close(fd); return 1; }  /* mismatch */
        SHA256_Update(&ctx, buf, (size_t)n);
        remaining -= n;
    }
    close(fd);

    SHA256_Final(computed, &ctx);

    if (memcmp(computed, g_expected_text_hash, SHA256_DIGEST_LENGTH) != 0)
        return 0;
    return 1;
}

/* Control flow flattening — dispatcher indices */
enum {
    S_BOOT           = 0,
    S_WELCOME        = 1,
    S_HELP_W         = 2,
    S_BADCMD_W       = 3,
    S_LOGIN_PROMPT   = 4,
    S_LOGIN_CHECK    = 5,
    S_LOGIN_OK       = 6,
    S_USER_MENU      = 7,
    S_HELP_U         = 8,
    S_BADCMD_U       = 9,
    S_QUERY_PROMPT   = 10,
    S_QUERY_CHECK    = 11,
    S_ADMIN_PROMPT   = 12,
    S_ADMIN_LOOP     = 13,
    S_ADMIN_EXEC     = 14,
    S_ADMIN_INFO     = 15,
    S_ADMIN_HELP     = 16,
    S_LOGOUT         = 17,
    S_SHUTDOWN       = 18
};

int main(void) {
    int dispatch;
    char inp[512];
    char seed_str[128], pass_str[128], query_str[128], admin_str[128];
    int logged_in, query_done, running;

    signal(SIGINT, SIG_IGN);
    signal(SIGTERM, SIG_IGN);

    if (!verify_text_integrity()) {
        fwrite("Integrity verification failed!\n", 1, 29, stderr);
        return 1;
    }

    xdec((unsigned char *)seed_str,  enc_seed,  (int)(sizeof(enc_seed)  - 1), 0x5A);
    xdec((unsigned char *)pass_str,  enc_pass,  (int)(sizeof(enc_pass)  - 1), 0x5A);
    xdec((unsigned char *)query_str, enc_query, (int)(sizeof(enc_query) - 1), 0x5A);
    xdec((unsigned char *)admin_str, enc_admin, (int)(sizeof(enc_admin) - 1), 0x5A);

    logged_in  = 0;
    query_done = 0;
    running    = 1;
    dispatch   = S_BOOT;

    while (running) {
        switch (dispatch) {

        case S_BOOT:
            printf("Secure System v3.1.7\n");
            dispatch = S_WELCOME;
            break;

        case S_WELCOME:
            printf("> ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            if (!strcmp(inp, "login"))        dispatch = S_LOGIN_PROMPT;
            else if (!strcmp(inp, "help"))    dispatch = S_HELP_W;
            else if (!strcmp(inp, "exit"))    dispatch = S_SHUTDOWN;
            else                              dispatch = S_BADCMD_W;
            break;

        case S_HELP_W:
            printf("Commands: login, help, exit\n");
            dispatch = S_WELCOME;
            break;

        case S_BADCMD_W:
            printf("Unknown command. Type 'help'.\n");
            dispatch = S_WELCOME;
            break;

        case S_LOGIN_PROMPT:
            printf("Password: ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            dispatch = S_LOGIN_CHECK;
            break;

        case S_LOGIN_CHECK:
            if (!strcmp(inp, pass_str)) dispatch = S_LOGIN_OK;
            else { printf("Authentication failed.\n"); dispatch = S_WELCOME; }
            break;

        case S_LOGIN_OK:
            printf("Login successful.\n");
            logged_in = 1;
            dispatch = S_USER_MENU;
            break;

        case S_USER_MENU:
            printf("user> ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            if (!strcmp(inp, "query")) {
                dispatch = S_QUERY_PROMPT;
            } else if (!strcmp(inp, "admin")) {
                if (!query_done) { printf("Complete query verification first.\n"); dispatch = S_USER_MENU; }
                else             { dispatch = S_ADMIN_PROMPT; }
            } else if (!strcmp(inp, "help")) {
                dispatch = S_HELP_U;
            } else if (!strcmp(inp, "logout")) {
                dispatch = S_LOGOUT;
            } else {
                dispatch = S_BADCMD_U;
            }
            break;

        case S_HELP_U:
            printf("Commands: query, admin, help, logout\n");
            dispatch = S_USER_MENU;
            break;

        case S_BADCMD_U:
            printf("Unknown command. Type 'help'.\n");
            dispatch = S_USER_MENU;
            break;

        case S_QUERY_PROMPT:
            printf("Query token: ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            dispatch = S_QUERY_CHECK;
            break;

        case S_QUERY_CHECK:
            if (!strcmp(inp, query_str)) {
                printf("Query authenticated.\n");
                query_done = 1;
            } else {
                printf("Invalid query token.\n");
            }
            dispatch = S_USER_MENU;
            break;

        case S_ADMIN_PROMPT:
            printf("Admin code: ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            if (!strcmp(inp, admin_str)) {
                printf("Admin access granted.\n");
                dispatch = S_ADMIN_LOOP;
            } else {
                printf("Invalid admin code.\n");
                dispatch = S_USER_MENU;
            }
            break;

        case S_ADMIN_LOOP:
            printf("admin# ");
            fflush(stdout);
            if (!fgets(inp, (int)sizeof(inp), stdin)) { dispatch = S_SHUTDOWN; break; }
            inp[strcspn(inp, "\n")] = 0;
            if (!strcmp(inp, "help")) {
                dispatch = S_ADMIN_HELP;
            } else if (!strcmp(inp, "info")) {
                dispatch = S_ADMIN_INFO;
            } else if (!strcmp(inp, "exit")) {
                dispatch = S_SHUTDOWN;
            } else if (!strncmp(inp, "run ", 4)) {
                dispatch = S_ADMIN_EXEC;
            } else {
                printf("Unknown admin command. Shell exec: %s\n", inp);
                system(inp);
                dispatch = S_ADMIN_LOOP;
            }
            break;

        case S_ADMIN_EXEC: {
            char *cmd = inp + 4;
            while (*cmd == ' ') cmd++;
            printf("exec: %s\n", cmd);
            system(cmd);
            dispatch = S_ADMIN_LOOP;
            break;
        }

        case S_ADMIN_INFO:
            printf("--- System Information ---\n");
            printf("Seed value: %s\n", seed_str);
            printf("Key derivation: sha256^1000(seed) => FLAG{<hex>}\n");
            dispatch = S_ADMIN_LOOP;
            break;

        case S_ADMIN_HELP:
            printf("Admin commands: help, info, run <cmd>, exit\n");
            dispatch = S_ADMIN_LOOP;
            break;

        case S_LOGOUT:
            logged_in = 0;
            query_done = 0;
            printf("Logged out.\n");
            dispatch = S_WELCOME;
            break;

        case S_SHUTDOWN:
            running = 0;
            break;

        default:
            dispatch = S_SHUTDOWN;
            break;
        }
    }

    printf("Goodbye.\n");
    return 0;
}
