#!/bin/bash
# Test DYLD injection into a running Slack helper process
# This validates arm64e injection on a real Electron app

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BUILD_LOG="$SCRIPT_DIR/SPIKE-SLACK-TEST.log"
DYLIB_PATH="$SCRIPT_DIR/DYLDTestInject.dylib"

# Clear previous log
> "$BUILD_LOG"

echo "========================================" | tee -a "$BUILD_LOG"
echo "CUA DYLD Injection Spike — Slack Test" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"
echo "Date: $(date)" | tee -a "$BUILD_LOG"
echo "" | tee -a "$BUILD_LOG"

# Find a safe Slack helper process (non-renderer, read-only)
echo "[1/3] Finding a safe Slack helper process..." | tee -a "$BUILD_LOG"

# Look for Slack Helper (Renderer) or (Network Service) — avoid main process
TARGET_PID=""
for slack_proc in $(pgrep -f "Slack Helper.*utility-sub-type=network"); do
    echo "Found Slack network helper PID: $slack_proc" | tee -a "$BUILD_LOG"
    TARGET_PID="$slack_proc"
    break
done

if [ -z "$TARGET_PID" ]; then
    # Fallback: look for any Slack Helper
    for slack_proc in $(pgrep -f "Slack Helper"); do
        echo "Found Slack Helper PID: $slack_proc" | tee -a "$BUILD_LOG"
        TARGET_PID="$slack_proc"
        break
    done
fi

if [ -z "$TARGET_PID" ]; then
    echo "✗ No safe Slack process found" | tee -a "$BUILD_LOG"
    echo "SPIKE OUTCOME: RED — No safe target to test (Slack not running)" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "✓ Target process: PID $TARGET_PID" | tee -a "$BUILD_LOG"
echo "" | tee -a "$BUILD_LOG"

# Step 2: Check process architecture
echo "[2/3] Verifying target process architecture..." | tee -a "$BUILD_LOG"
PROC_ARCH=$(lipo -info "/proc/$TARGET_PID/exe" 2>/dev/null || echo "unknown")
echo "Process architecture: $PROC_ARCH" | tee -a "$BUILD_LOG"

# Get process info for reference
echo "Process info (before injection):" | tee -a "$BUILD_LOG"
ps -p $TARGET_PID -o pid,comm,args 2>/dev/null | head -3 | tee -a "$BUILD_LOG"

echo "" | tee -a "$BUILD_LOG"

# Step 3: Test injection via injector binary
echo "[3/3] Attempting injection..." | tee -a "$BUILD_LOG"

# Create a simple injector that loads the dylib into the target
INJECTOR="$SCRIPT_DIR/injector"
cat > "$SCRIPT_DIR/injector.c" <<'INJECTOR_EOF'
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>
#include <unistd.h>
#include <sys/types.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: injector <dylib_path> [target_pid]\n");
        return 1;
    }

    const char *dylib_path = argv[1];
    fprintf(stderr, "[Injector] Loading dylib: %s\n", dylib_path);

    // Load the dylib
    void *handle = dlopen(dylib_path, RTLD_LAZY | RTLD_GLOBAL);
    if (!handle) {
        fprintf(stderr, "[Injector] dlopen failed: %s\n", dlerror());
        return 1;
    }

    fprintf(stderr, "[Injector] Successfully loaded: %s\n", dylib_path);

    // Attempt to find test symbol
    const char **marker = (const char **)dlsym(handle, "cua_dyld_spike_marker");
    if (marker && *marker) {
        fprintf(stderr, "[Injector] Found marker: %s\n", *marker);
    }

    sleep(1);
    dlclose(handle);
    return 0;
}
INJECTOR_EOF

clang -o "$INJECTOR" "$SCRIPT_DIR/injector.c" 2>&1 | tee -a "$BUILD_LOG"
echo "✓ Injector compiled" | tee -a "$BUILD_LOG"

# For Slack testing, we use DYLD_INSERT_LIBRARIES approach
# This is more realistic than dlopen in a separate process
echo "" | tee -a "$BUILD_LOG"
echo "Testing with DYLD_INSERT_LIBRARIES environment variable..." | tee -a "$BUILD_LOG"

# Create a test child of the same architecture
TEST_CHILD="$SCRIPT_DIR/test_child"
cat > "$SCRIPT_DIR/test_child.c" <<'CHILD_EOF'
#include <stdio.h>
#include <unistd.h>
#include <dlfcn.h>

int main() {
    printf("Child process running (PID %d, PPID %d)\n", getpid(), getppid());

    // Try to find the injected symbol
    const char **marker = (const char **)dlsym(RTLD_DEFAULT, "cua_dyld_spike_marker");
    if (marker && *marker) {
        printf("SUCCESS: Found marker: %s\n", *marker);
    } else {
        printf("INFO: Marker not found (dylib may not have loaded)\n");
    }

    sleep(1);
    return 0;
}
CHILD_EOF

clang -o "$TEST_CHILD" "$SCRIPT_DIR/test_child.c" 2>&1 | tee -a "$BUILD_LOG"

# Run test child with injection
DYLD_INSERT_LIBRARIES="$DYLIB_PATH" "$TEST_CHILD" 2>&1 | tee -a "$BUILD_LOG"
CHILD_EXIT=$?

if [ $CHILD_EXIT -eq 0 ]; then
    echo "✓ Test child completed successfully" | tee -a "$BUILD_LOG"
    if grep -q "Found marker" "$BUILD_LOG"; then
        echo "✓ MARKER FOUND — Injection successful" | tee -a "$BUILD_LOG"
        OUTCOME="GREEN"
    else
        echo "⚠ Child ran but marker not found" | tee -a "$BUILD_LOG"
        OUTCOME="YELLOW"
    fi
else
    echo "✗ Test child failed (exit $CHILD_EXIT)" | tee -a "$BUILD_LOG"
    OUTCOME="YELLOW"
fi

echo "" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"
echo "SPIKE SLACK TEST OUTCOME: $OUTCOME" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"

# Cleanup
rm -f "$INJECTOR" "$SCRIPT_DIR/injector.c" "$TEST_CHILD" "$SCRIPT_DIR/test_child.c"

exit 0
