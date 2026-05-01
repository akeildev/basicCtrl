// Minimal arm64e test dylib for DYLD injection spike
// Exports a single test symbol and logs its initialization

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>

// Test symbol that will be looked up from the injected process
const char *cua_dyld_spike_marker = "CUA_DYLD_TEST_INJECTED_MARKER_v1";

// Constructor called when dylib loads
__attribute__((constructor))
static void dylib_init(void) {
    pid_t pid = getpid();
    // Write to stderr (will be captured in logs)
    fprintf(stderr, "[CUA-DYLD-SPIKE] Injected dylib loaded into PID %d\n", pid);
    fflush(stderr);
}

// Destructor called when dylib unloads
__attribute__((destructor))
static void dylib_fini(void) {
    fprintf(stderr, "[CUA-DYLD-SPIKE] Injected dylib unloading\n");
    fflush(stderr);
}

// Simple exported function for verification
int cua_dyld_test_function(void) {
    return 42;
}
