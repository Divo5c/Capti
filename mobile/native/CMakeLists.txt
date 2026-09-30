# Capti Native-Bridge: whisper.cpp-Anbindung für dart:ffi.
#
# Mit whisper.cpp-Quellen (native/third_party/whisper.cpp, via
# tools/fetch_native.sh):
#   cmake -B build -DCAPTI_WITH_WHISPER=ON ...
# Ohne Quellen wird die Bridge im Fallback-Modus gebaut:
# capti_whisper_create() liefert NULL -> die App zeigt explizit den
# "Engine nicht verfügbar"-Zustand (keine Fake-Ergebnisse).

cmake_minimum_required(VERSION 3.14)
project(capti_whisper_bridge LANGUAGES C CXX)

set(CAPTI_WITH_WHISPER OFF CACHE BOOL "Link against whisper.cpp")
# Root der statischen Media-Archive (siehe tools/build_media_android.sh):
#   $MEDIA_PREBUILT_ROOT/<abi>/lib*.a
set(MEDIA_PREBUILT_ROOT "" CACHE PATH "Static ffmpeg/libass archives root")

add_library(whisper_bridge SHARED whisper_bridge.c)

if(CAPTI_WITH_WHISPER)
  target_compile_definitions(whisper_bridge PRIVATE CAPTI_WITH_WHISPER=1)
  target_include_directories(whisper_bridge PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/third_party/whisper.cpp/include)

  # Schlanke Bibliotheks-Builds für Mobile: keine Beispiele/Tests/Server,
  # kein OpenMP (Android-NDK liefert libomp nicht garantiert mit),
  # statisch in die Bridge gelinkt.
  set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
  set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
  set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
  set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)

  add_subdirectory(third_party/whisper.cpp EXCLUDE_FROM_ALL)
  target_link_libraries(whisper_bridge PRIVATE whisper)
else()
  target_compile_definitions(whisper_bridge PRIVATE CAPTI_WITH_WHISPER=0)
endif()

target_compile_options(whisper_bridge PRIVATE -O2)

# ---------------------------------------------------------------------
# Media-Bridge: FFmpeg + libass (statisch vorgebaut, siehe
# tools/fetch_media.sh + tools/build_media_android.sh).
# Fehlen die Archive für die aktuelle ABI, wird die Bridge trotzdem
# gebaut und liefert zur Laufzeit saubere Fehlercodes statt zu crashen
# -> Dart zeigt den ehrlichen "Media-Engine nicht verfügbar"-Zustand.
# ---------------------------------------------------------------------
if(MEDIA_PREBUILT_ROOT)
  set(_media_dir "${MEDIA_PREBUILT_ROOT}/${ANDROID_ABI}")
  if(EXISTS "${_media_dir}/libavcodec.a")
    add_library(media_bridge SHARED media_bridge.c)
    target_include_directories(media_bridge PRIVATE "${_media_dir}/include")
    find_library(ANDROID_LOG_LIB log REQUIRED)
    target_link_libraries(media_bridge PRIVATE
      -Wl,--start-group
      "${_media_dir}/libavfilter.a"
      "${_media_dir}/libswscale.a"
      "${_media_dir}/libavformat.a"
      "${_media_dir}/libavcodec.a"
      "${_media_dir}/libswresample.a"
      "${_media_dir}/libavutil.a"
      "${_media_dir}/libass.a"
      "${_media_dir}/libharfbuzz.a"
      "${_media_dir}/libfreetype.a"
      "${_media_dir}/libfribidi.a"
      "${_media_dir}/libx264.a"
      "${_media_dir}/libz.a"
      -Wl,--end-group
      -Wl,--exclude-libs,ALL
      -lm ${ANDROID_LOG_LIB})
    target_compile_options(media_bridge PRIVATE -O2 -fvisibility=hidden)
    # Debug-Symbole raus (APK-Größe!); API-Symbole bleiben erhalten.
    add_custom_command(TARGET media_bridge POST_BUILD
        COMMAND ${CMAKE_STRIP} --strip-unneeded $<TARGET_FILE:media_bridge>
        COMMENT "Stripping libmedia_bridge.so")
  else()
    message(STATUS "Capti media: keine Archive für ${ANDROID_ABI} – "
                   "media_bridge wird übersprungen")
  endif()
endif()
