#!/usr/bin/env bash
# Gemeinsame Umgebung für den Android-Media-Cross-Build (WSL-freundlich).
# Alle Host-Tools stammen aus offiziellen Ubuntu-Archiv-Paketen, extrahiert
# ohne Root nach /tmp/opencode/hosttools (siehe tools/fetch_host_tools.sh).
set -euo pipefail

export NDK="${ANDROID_NDK:-$HOME/opt/android-sdk/ndk/28.2.13676358}"
export SDK_CMAKE="$HOME/opt/android-sdk/cmake/3.22.1/bin"
export HOSTTOOLS=/tmp/opencode/hosttools/root/usr/bin
export HOSTLIB=/tmp/opencode/hosttools/root/usr/lib/x86_64-linux-gnu

export PATH="$HOSTTOOLS:$SDK_CMAKE:/tmp/opencode/capti-py-venv/bin:$PATH"
export LD_LIBRARY_PATH="$HOSTLIB:${LD_LIBRARY_PATH:-}"

export MEDIA_ROOT="${MEDIA_ROOT:-/tmp/opencode/media-build}"
export SRC="$MEDIA_ROOT/srcs"
export BUILD="$MEDIA_ROOT/build"
export PREFIX="$MEDIA_ROOT/prefix"

export API=24            # entspricht minSdk der App
export HOST_TAG=linux-x86_64
export TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/$HOST_TAG"

mkdir -p "$SRC" "$BUILD" "$PREFIX"

case "${1:-}" in
  env) for abi in arm64-v8a x86_64; do :; done ;;
esac

if [ -n "${1:-}" ]; then
  ABI="$1"
  case "$ABI" in
    arm64-v8a) TRIPLE=aarch64-linux-android; ARCH=aarch64; CPU=armv8-a ;;
    x86_64)    TRIPLE=x86_64-linux-android;  ARCH=x86_64;  CPU=x86-64 ;;
    *) echo "Unbekannte ABI: $ABI" >&2; exit 1 ;;
  esac
  export ABI TRIPLE ARCH CPU
  export SYSROOT="$TOOLCHAIN/sysroot"
  export CC="$TOOLCHAIN/bin/${TRIPLE}${API}-clang"
  export CXX="$TOOLCHAIN/bin/${TRIPLE}${API}-clang++"
  export AR="$TOOLCHAIN/bin/llvm-ar"
  export RANLIB="$TOOLCHAIN/bin/llvm-ranlib"
  export STRIP="$TOOLCHAIN/bin/llvm-strip"
  export LD="$TOOLCHAIN/bin/ld.lld"  # wird von configure meist ignoriert, schadet nicht
  export CPPFLAGS="--sysroot=$SYSROOT -DANDROID -fPIC"
  export CFLAGS="--sysroot=$SYSROOT -DANDROID -fPIC -O2 -ffunction-sections -fdata-sections"
  export CXXFLAGS="$CFLAGS"
  export LDFLAGS="--sysroot=$SYSROOT -fPIC -Wl,--gc-sections"
  export PKG_CONFIG="pkgconf"
  export PKG_CONFIG_PATH="$PREFIX/$ABI/lib/pkgconfig"
  export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"   # niemals Host-.pc leaken
fi
