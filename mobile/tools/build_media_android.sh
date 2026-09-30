#!/usr/bin/env bash
# Cross-kompiliert die komplette Media-Kette für Android (statisch).
#
#   zlib -> freetype -> fribidi -> harfbuzz -> x264 -> libass -> ffmpeg
#
# Ergebnis je ABI: statische Archive unter $PREFIX/<abi>/lib (+ Header).
# Die finale Brücke (media_bridge.c) baut später Gradle/CMake und linkt
# diese Archive in eine einzige libmedia_bridge.so – siehe CMakeLists.
#
# Nutzung:  bash tools/build_media_android.sh [arm64-v8a|x86_64]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1090
source "$here/media_env.sh"

ABI_ARG="${1:-arm64-v8a}"
source_env() { true; }
# shellcheck disable=SC1090
source "$here/media_env.sh" "$ABI_ARG"

LOGS="$BUILD/logs/$ABI"
mkdir -p "$LOGS"
step() { echo "===== [$ABI] $1 ====="; }

# In-Source-Builds (zlib/x264/ffmpeg) dürfen nie Reste anderer ABIs sehen:
# -> je ABI eine frische Kopie der Quellen.
fresh_tree() {
  local name="$1"
  local dst="$BUILD/$ABI/tree/$name"
  rm -rf "$dst"
  mkdir -p "$(dirname "$dst")"
  cp -a "$SRC/$name" "$dst"
  # Kompilierte Reste früherer Läufe (andere ABI!) konsequent entfernen:
  find "$dst" \( -name '*.o' -o -name '*.a' -o -name '*.so' -o -name '*.so.*' \
                 -o -name '*.dylib' \) -type f -delete
  # Alte Configure-Ergebnisse ebenfalls verwerfen (configure schreibt neu):
  rm -f "$dst/ffbuild/config.mak" "$dst/ffbuild/config.h" \
        "$dst/config.h" "$dst/config.mak" "$dst/x264_config.h" 2>/dev/null || true
  echo "$dst"
}

meson_cross_file() {
  cat > "$1" <<EOF
[binaries]
c     = '$CC'
cpp   = '$CXX'
ar    = '$AR'
strip = '$STRIP'
pkg-config = 'pkgconf'

[built-in options]
c_args = ['$([ "${CPU}" = armv8-a ] && echo "-march=armv8-a" || echo "-march=x86-64")', '-DANDROID', '--sysroot=$SYSROOT', '-O2', '-fPIC']
cpp_args = ['-DANDROID', '--sysroot=$SYSROOT', '-O2', '-fPIC']
c_link_args = ['--sysroot=$SYSROOT', '-fPIC']
cpp_link_args = ['--sysroot=$SYSROOT', '-fPIC']
pkg_config_path = '$PKG_CONFIG_PATH'

[host_machine]
system = 'android'
cpu_family = '${ARCH}'
cpu = '${CPU}'
endian = 'little'
EOF
}

build_zlib() {
  step "zlib"
  local b="$BUILD/$ABI/zlib"; mkdir -p "$b"
  ( cd "$(fresh_tree zlib)" \
    && CHOST="$TRIPLE" CC="$CC" AR="$AR" RANLIB="$RANLIB" \
       CFLAGS="--sysroot=$SYSROOT -O2 -fPIC -DANDROID" \
       ./configure --static --prefix="$PREFIX/$ABI" >"$LOGS/zlib.conf" 2>&1 \
    && make -j"$(nproc)" >"$LOGS/zlib.make" 2>&1 \
    && make install >>"$LOGS/zlib.make" 2>&1 )
}

build_freetype() {
  step "freetype (meson)"
  local b="$BUILD/$ABI/freetype"; rm -rf "$b"; mkdir -p "$b"
  meson_cross_file "$b/cross.ini"
  ( cd "$SRC/freetype" \
    && meson setup "$b" --cross-file "$b/cross.ini" --default-library=static \
        --buildtype release --prefix="$PREFIX/$ABI" \
        -Dzlib=enabled -Dpng=disabled -Dbzip2=disabled -Dbrotli=disabled \
        -Dharfbuzz=disabled -Dtests=disabled \
        >"$LOGS/freetype.meson" 2>&1 \
    && ninja -C "$b" install >>"$LOGS/freetype.meson" 2>&1 )
}

build_fribidi() {
  step "fribidi (meson)"
  # Cross-Build-Patch: kein nativer Host-Compiler verfügbar -> das Release-
  # Tarball liefert alle Tabellen vorgeneriert mit; wir kopieren sie statt
  # sie mit gen.tab-Tools (native: true) neu zu erzeugen.
  cat > "$SRC/fribidi/gen.tab/meson.build" <<'MESON'
# PATCHED (tools/build_media_android.sh): shipped pre-generated tables.
shipped = [
  'bidi-type', 'joining-type', 'arabic-shaping',
  'mirroring', 'brackets', 'brackets-type',
]

fribidi_unicode_version_h = configure_file(
  input: files('../lib/fribidi-unicode-version.h'),
  output: 'fribidi-unicode-version.h',
  copy: true,
  install: true,
  install_dir: join_paths(get_option('includedir'), 'fribidi'))

generated_tab_include_files = []
foreach name : shipped
  generated_tab_include_files += custom_target(
    'copy-' + name,
    input: files('../lib/@0@.tab.i'.format(name)),
    output: '@0@.tab.i'.format(name),
    command: ['cp', '@INPUT@', '@OUTPUT@'])
endforeach
MESON
  local b="$BUILD/$ABI/fribidi"; rm -rf "$b"; mkdir -p "$b"
  meson_cross_file "$b/cross.ini"
  ( cd "$SRC/fribidi" \
    && meson setup "$b" --cross-file "$b/cross.ini" --default-library=static \
        --buildtype release --prefix="$PREFIX/$ABI" \
        -Ddocs=false -Dbin=false -Dtests=false \
        >"$LOGS/fribidi.meson" 2>&1 \
    && ninja -C "$b" install >>"$LOGS/fribidi.meson" 2>&1 )
}

build_harfbuzz() {
  step "harfbuzz (meson)"
  local b="$BUILD/$ABI/harfbuzz"; rm -rf "$b"; mkdir -p "$b"
  meson_cross_file "$b/cross.ini"
  ( cd "$SRC/harfbuzz" \
    && meson setup "$b" --cross-file "$b/cross.ini" --default-library=static \
        --buildtype release --prefix="$PREFIX/$ABI" \
        -Dglib=disabled -Dgobject=disabled -Dcairo=disabled -Dicu=disabled \
        -Dchafa=disabled -Dfreetype=disabled -Dtests=disabled \
        -Dintrospection=disabled -Ddocs=disabled -Dutilities=disabled \
        >"$LOGS/harfbuzz.meson" 2>&1 \
    && ninja -C "$b" install >>"$LOGS/harfbuzz.meson" 2>&1 )
}

build_x264() {
  step "x264 (configure)"
  local b="$BUILD/$ABI/x264"; mkdir -p "$b"
  ( cd "$(fresh_tree x264)" \
    && CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" STRIP="$STRIP" \
       ./configure --host="$TRIPLE" --enable-static --enable-pic \
         --disable-cli --disable-opencl --prefix="$PREFIX/$ABI" \
       >"$LOGS/x264.conf" 2>&1 \
    && make -j"$(nproc)" >"$LOGS/x264.make" 2>&1 \
    && make install >>"$LOGS/x264.make" 2>&1 )
}

build_libass() {
  step "libass (meson)"
  local b="$BUILD/$ABI/libass"; rm -rf "$b"; mkdir -p "$b"
  meson_cross_file "$b/cross.ini"
  ( cd "$SRC/libass" \
    && meson setup "$b" --cross-file "$b/cross.ini" --default-library=static \
        --buildtype release --prefix="$PREFIX/$ABI" \
        -Dfontconfig=disabled -Ddirectwrite=disabled -Dcoretext=disabled \
        -Dtest=disabled -Dcompare=disabled -Dprofile=disabled -Dfuzz=disabled \
        -Dcheckasm=disabled -Dasm=enabled \
        -Drequire-system-font-provider=false \
        >"$LOGS/libass.meson" 2>&1 \
    && ninja -C "$b" install >>"$LOGS/libass.meson" 2>&1 )
}

FFMPEG_ENABLE_COMPONENTS=(
  # Demuxer (Eingangsformate Phones: mp4/mov, mkv/webm, avi, flv, ts, ogg)
  --enable-demuxer=mov --enable-demuxer=matroska --enable-demuxer=avi
  --enable-demuxer=flv --enable-demuxer=mpegts --enable-demuxer=ogg
  --enable-demuxer=h264 --enable-demuxer=hevc --enable-demuxer=aac
  --enable-demuxer=mp3 --enable-demuxer=wav
  # Dekoder
  --enable-decoder=h264 --enable-decoder=hevc --enable-decoder=mpeg4
  --enable-decoder=vp8 --enable-decoder=vp9 --enable-decoder=av1
  --enable-decoder=aac --enable-decoder=mp3float --enable-decoder=opus
  --enable-decoder=vorbis --enable-decoder=flac --enable-decoder=pcm_s16le
  # Parser
  --enable-parser=h264 --enable-parser=hevc --enable-parser=aac
  --enable-parser=mpegaudio --enable-parser=vorbis --enable-parser=opus
  # Encoder + Muxer
  --enable-encoder=libx264 --enable-encoder=aac
  --enable-muxer=mp4
  # Filter (ass-Burn-in-Kette)
  --enable-filter=ass --enable-filter=scale --enable-filter=format
  --enable-filter=null --enable-filter=anull
)

build_ffmpeg() {
  step "ffmpeg (configure, statisch, minimal aber vollständig für Burn-in)"
  local b="$BUILD/$ABI/ffmpeg"; mkdir -p "$b"
  ( cd "$(fresh_tree ffmpeg)" \
    && ./configure \
        --prefix="$PREFIX/$ABI" \
        --enable-cross-compile --target-os=linux --arch="$ARCH" --cpu="$CPU" \
        --sysroot="$SYSROOT" \
        --host-cc="${HOSTCC:-/tmp/opencode/hosttools/hostcc}" \
        --cc="$CC" --cxx="$CXX" --ar="$AR" --nm="$TOOLCHAIN/bin/llvm-nm" \
        --ranlib="$RANLIB" --strip="$STRIP" \
        --extra-cflags="-DANDROID -fPIC -O2 -fvisibility=hidden" \
        --extra-cxxflags="-DANDROID -fPIC -O2" \
        --extra-ldflags="-fPIC" \
        --enable-static --disable-shared \
        --enable-pic \
        --disable-programs --disable-doc --disable-debug \
        --disable-avdevice --disable-postproc --disable-network \
        --disable-autodetect --disable-iconv --disable-lzma --disable-bzlib \
        --disable-sdl2 --disable-vaapi --disable-vdpau --disable-vulkan \
        --enable-gpl --enable-version3 \
        --enable-libx264 --enable-libass \
        --enable-protocol=file \
        --enable-swresample --enable-swscale \
        "${FFMPEG_ENABLE_COMPONENTS[@]}" \
        >"$LOGS/ffmpeg.conf" 2>&1 \
    && make -j"$(nproc)" >"$LOGS/ffmpeg.make" 2>&1 \
    && make install >>"$LOGS/ffmpeg.make" 2>&1 )
}

stage_static_archives() {
  step "Statisches Staging nach mobile/native/media_prebuilt/$ABI"
  local dest="$here/../native/media_prebuilt/$ABI"
  mkdir -p "$dest/include"
  cp -r "$PREFIX/$ABI/lib/"*.a "$dest/"
  cp -r "$PREFIX/$ABI/include/." "$dest/include/"
  ls -lh "$dest" | sed 's/^/  /'
}

case "$ABI_ARG" in
  arm64-v8a|arm64) build_zlib; build_freetype; build_fribidi; build_harfbuzz;
                   build_x264; build_libass; build_ffmpeg; stage_static_archives ;;
  x86_64)          build_zlib; build_freetype; build_fribidi; build_harfbuzz;
                   build_x264; build_libass; build_ffmpeg; stage_static_archives ;;
  *) echo "Nutzung: $0 [arm64-v8a|x86_64]" >&2; exit 1 ;;
esac

step "FERTIG für $ABI_ARG"
