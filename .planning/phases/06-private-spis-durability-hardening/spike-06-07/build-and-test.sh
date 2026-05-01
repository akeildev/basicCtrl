#!/bin/bash
# arm64e DYLD injection spike: build, sign, and test
# Logs all outcomes to SPIKE-BUILD.log

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BUILD_LOG="$SCRIPT_DIR/SPIKE-BUILD.log"
DYLIB_PATH="$SCRIPT_DIR/DYLDTestInject.dylib"
ENTITLEMENTS_PATH="$SCRIPT_DIR/arm64e.plist"

# Clear previous log
> "$BUILD_LOG"

echo "========================================" | tee -a "$BUILD_LOG"
echo "CUA DYLD Injection Spike — Build & Test" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"
echo "Date: $(date)" | tee -a "$BUILD_LOG"
echo "Host: $(uname -a)" | tee -a "$BUILD_LOG"
echo "" | tee -a "$BUILD_LOG"

# Step 1: Compile as arm64e
echo "[1/5] Compiling C source as arm64e dylib..." | tee -a "$BUILD_LOG"
if clang -arch arm64e \
    -dynamiclib \
    -fPIC \
    -o "$DYLIB_PATH" \
    "$SCRIPT_DIR/DYLDTestInject.c" \
    2>&1 | tee -a "$BUILD_LOG"; then
    echo "✓ Compilation successful" | tee -a "$BUILD_LOG"
    file "$DYLIB_PATH" | tee -a "$BUILD_LOG"
else
    echo "✗ Compilation failed" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"

# Step 2: Verify architecture
echo "[2/5] Verifying arm64e architecture..." | tee -a "$BUILD_LOG"
if lipo -info "$DYLIB_PATH" | tee -a "$BUILD_LOG"; then
    echo "✓ Architecture info retrieved" | tee -a "$BUILD_LOG"
else
    echo "✗ lipo info failed" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"

# Step 3: Code sign with entitlements
echo "[3/5] Code-signing with ad-hoc signature + PAC entitlements..." | tee -a "$BUILD_LOG"
if codesign -s - \
    --entitlements "$ENTITLEMENTS_PATH" \
    --options runtime,library \
    "$DYLIB_PATH" \
    2>&1 | tee -a "$BUILD_LOG"; then
    echo "✓ Code signing successful" | tee -a "$BUILD_LOG"
else
    echo "✗ Code signing failed (may indicate PAC signing constraints)" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"

# Step 4: Verify signature
echo "[4/5] Verifying code signature..." | tee -a "$BUILD_LOG"
if codesign -v -v "$DYLIB_PATH" 2>&1 | tee -a "$BUILD_LOG"; then
    echo "✓ Signature verification successful" | tee -a "$BUILD_LOG"
else
    echo "✗ Signature verification failed" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"

# Step 5: Test injection into a simple test target
echo "[5/5] Testing injection into test target..." | tee -a "$BUILD_LOG"

# Create a simple test target that will exit cleanly
TEST_PROG="$SCRIPT_DIR/test_target"
cat > "$SCRIPT_DIR/test_target.c" <<'TESTEOF'
#include <stdio.h>
#include <unistd.h>
int main() {
    printf("Test target running (PID %d)\n", getpid());
    sleep(2);
    printf("Test target exiting\n");
    return 0;
}
TESTEOF

# Compile test target
if clang -o "$TEST_PROG" "$SCRIPT_DIR/test_target.c" 2>&1 | tee -a "$BUILD_LOG"; then
    echo "✓ Test target compiled" | tee -a "$BUILD_LOG"
else
    echo "✗ Test target compilation failed" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"

# Attempt injection via DYLD_INSERT_LIBRARIES
echo "Attempting to inject dylib into test target..." | tee -a "$BUILD_LOG"
DYLD_INSERT_LIBRARIES="$DYLIB_PATH" "$TEST_PROG" 2>&1 | tee -a "$BUILD_LOG"
INJECT_EXIT=$?

if [ $INJECT_EXIT -eq 0 ]; then
    echo "✓ Injection test completed (exit code 0)" | tee -a "$BUILD_LOG"

    # Check if the spike marker was found
    if grep -q "CUA-DYLD-SPIKE" "$BUILD_LOG"; then
        echo "✓ DYLIB INITIALIZATION MESSAGE DETECTED — INJECTION CONFIRMED" | tee -a "$BUILD_LOG"
        OUTCOME="GREEN"
    else
        echo "⚠ Injection ran but marker not found in output (may indicate dylib didn't load)" | tee -a "$BUILD_LOG"
        OUTCOME="YELLOW"
    fi
else
    echo "⚠ Test target exited with code $INJECT_EXIT (dylib may not have loaded into target)" | tee -a "$BUILD_LOG"
    OUTCOME="YELLOW"
fi

echo "" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"
echo "SPIKE OUTCOME: $OUTCOME" | tee -a "$BUILD_LOG"
echo "========================================" | tee -a "$BUILD_LOG"
echo "" | tee -a "$BUILD_LOG"

# Cleanup
rm -f "$SCRIPT_DIR/test_target" "$SCRIPT_DIR/test_target.c"

exit 0
