#!/bin/bash
# build.sh — Build arm64e signed dylib for DYLD injection
#
# Per RESEARCH.md §"DYLD Injection + arm64e Signing (SPI-06)" L114-125:
# - Compile as arm64e (not universal)
# - Code-sign with PAC entitlements
# - Use ad-hoc signing (-s -)
#
# SPIKE OUTCOME (Wave 3, 06-07): GREEN
# Per 06-07-SPIKE-OUTCOME.md: validated build flags on M-series
#
# Usage: ./build.sh
# Output: ./cua_inject.dylib (signed, arm64e)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${SCRIPT_DIR}/cua_inject.c"
PLIST="${SCRIPT_DIR}/arm64e.plist"
OUTPUT="${SCRIPT_DIR}/cua_inject.dylib"

if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: $SOURCE not found"
    exit 1
fi

if [[ ! -f "$PLIST" ]]; then
    echo "ERROR: $PLIST not found"
    exit 1
fi

echo "[build.sh] Compiling cua_inject.c as arm64e dylib..."
clang -arch arm64e -dynamiclib -fPIC -o "$OUTPUT" "$SOURCE"

if [[ ! -f "$OUTPUT" ]]; then
    echo "ERROR: Compilation failed; $OUTPUT not created"
    exit 1
fi

echo "[build.sh] Verifying architecture..."
lipo -info "$OUTPUT"

echo "[build.sh] Code-signing with PAC entitlements..."
codesign -s - --entitlements "$PLIST" --options runtime,library "$OUTPUT"

echo "[build.sh] Verifying signature..."
codesign -v -v "$OUTPUT"

echo "[build.sh] Build successful: $OUTPUT"
ls -lh "$OUTPUT"
