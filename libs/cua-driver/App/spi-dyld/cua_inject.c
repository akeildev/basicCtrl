/*
 * cua_inject.c — Minimal dylib for DYLD injection into Electron renderers.
 *
 * Per RESEARCH.md §"DYLD Injection + arm64e Signing (SPI-06)" L92-131:
 * - arm64e-compiled dylib injected via DYLD_INSERT_LIBRARIES
 * - Ad-hoc signed with PAC-aware entitlements
 * - Tested on macOS 26 Tahoe, M-series Apple Silicon
 *
 * SPIKE OUTCOME (Wave 3, 06-07): GREEN
 * Per 06-07-SPIKE-OUTCOME.md: injection proven feasible and reliable.
 *
 * Stub implementation: exports identification symbols for testing.
 * Future: interception logic (e.g., hooking Slack IPC) is out of scope for Phase 6.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Identification markers for dylib presence detection */
const char *cua_inject_marker = "CUA_DYLD_INJECT_MARKER_v1";
const char *cua_inject_version = "1.0.0";

/* Constructor: fires when dylib loads into target process */
__attribute__((constructor))
static void cua_inject_init(void) {
    fprintf(stderr, "[cua-maximalist] dylib loaded (pid=%d)\n", getpid());
    fflush(stderr);
}

/* Destructor: fires when dylib unloads */
__attribute__((destructor))
static void cua_inject_fini(void) {
    fprintf(stderr, "[cua-maximalist] dylib unloading (pid=%d)\n", getpid());
    fflush(stderr);
}

/* Exported callback for testing (dlsym-able) */
void cua_inject_on_load(void) {
    fprintf(stderr, "[cua-maximalist] cua_inject_on_load callback fired\n");
    fflush(stderr);
}
