/*
 * capti_whisper_bridge.c – flache C-API zwischen Capti Mobile (dart:ffi)
 * und whisper.cpp.
 *
 * Bewusst einfache Zeiger-/Skalar-Signaturen, damit dart:ffi ohne
 * Struct-Layouts binden kann. Alle Zeiten werden in SEKUNDEN (double)
 * geliefert; whisper.cpp liefert intern Zentisekunden -> /100.
 *
 * Word-Timestamps (Grundlage für das Karaoke-Highlighting) werden über
 * token_timestamps aktiviert und pro Segment als Token-Wörter exportiert;
 * Sonder-Tokens werden gefiltert.
 *
 * Build:
 *   - Mit whisper.cpp: Quellen nach native/third_party/whisper.cpp legen
 *     (tools/fetch_native.sh) und CAPTI_WITH_WHISPER=ON bauen.
 *   - Ohne: kompiliert die Bridge im Fallback-Modus (CAPTI_WITH_WHISPER=OFF);
 *     capti_whisper_create() liefert dann immer NULL -> die App zeigt den
 *     lokalisierten "Engine nicht verfügbar"-Zustand (KEINE Fake-Ergebnisse).
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(CAPTI_WITH_WHISPER) && CAPTI_WITH_WHISPER
#define CAPTI_HAVE_WHISPER 1
#else
#define CAPTI_HAVE_WHISPER 0
#endif

#if CAPTI_HAVE_WHISPER
#include "whisper.h"
#endif

/* ------------------------------------------------------------------ */
/* Minimaler 16-bit-PCM-WAV-Leser (16 kHz mono erwartet, aber tolerant */
/* gegenüber Kanälen/Sample-Rate -> Resampling überspringt Capti: die  */
/* App extrahiert Audio bereits korrekt als 16 kHz Mono).              */
/* ------------------------------------------------------------------ */

static int32_t read_i32(const uint8_t* p) {
    return (int32_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8) |
                     ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24));
}

static int16_t read_i16(const uint8_t* p) {
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

#if CAPTI_HAVE_WHISPER
/* Liest eine WAV-Datei und liefert Mono-float-PCMs. Rückgabe: Samplezahl,
 * bei Fehler -1. Ergebnisbuffer gehört dem Aufrufer (free()). */
static int64_t read_wav_mono_f32(const char* path, float** out_samples,
                                 uint32_t* out_rate) {
    FILE* f = fopen(path, "rb");
    if (!f) return -1;

    uint8_t hdr[12];
    if (fread(hdr, 1, 12, f) != 12 || memcmp(hdr, "RIFF", 4) != 0 ||
        memcmp(hdr + 8, "WAVE", 4) != 0) {
        fclose(f);
        return -1;
    }

    uint16_t channels = 1;
    uint32_t rate = 16000;
    uint16_t bits = 16;
    uint8_t* data = NULL;
    int64_t n_data = 0;

    for (;;) {
        uint8_t ch[8];
        size_t got = fread(ch, 1, 8, f);
        if (got < 8) break;
        const int64_t sz = read_i32(ch + 4);
        if (sz <= 0 || sz > (int64_t)1 << 31) break;

        if (memcmp(ch, "fmt ", 4) == 0) {
            uint8_t fmtbuf[40];
            const int64_t take = sz < 40 ? sz : 40;
            if (fread(fmtbuf, 1, (size_t)take, f) != (size_t)take) break;
            channels = (uint16_t)read_i16(fmtbuf + 2);
            rate = (uint32_t)read_i32(fmtbuf + 4);
            bits = (uint16_t)read_i16(fmtbuf + 14);
            if (sz > take) fseek(f, (long)(sz - take), SEEK_CUR);
        } else if (memcmp(ch, "data", 4) == 0) {
            data = (uint8_t*)malloc((size_t)sz);
            if (!data) break;
            if (fread(data, 1, (size_t)sz, f) != (size_t)sz) {
                free(data);
                data = NULL;
                break;
            }
            n_data = sz;
            break; // erster data-Chunk genügt
        } else {
            fseek(f, (long)((sz + 1) & ~1L), SEEK_CUR);
        }
    }
    fclose(f);

    if (!data || bits != 16 || channels < 1) {
        free(data);
        return -1;
    }

    const int64_t total_s16 = n_data / 2;
    const int64_t frames = total_s16 / channels;
    float* samples = (float*)malloc(sizeof(float) * (size_t)(frames ? frames : 1));
    if (!samples) {
        free(data);
        return -1;
    }
    for (int64_t i = 0; i < frames; i++) {
        int32_t acc = 0;
        for (uint16_t c = 0; c < channels; c++) {
            acc += read_i16(data + (i * channels + c) * 2);
        }
        samples[i] = (float)((double)acc / channels) / 32768.0f;
    }
    free(data);
    *out_samples = samples;
    *out_rate = rate;
    return frames;
}
#endif /* CAPTI_HAVE_WHISPER */

/* ------------------------------------------------------------------ */
/* Öffentliche Bridge-API                                              */
/* ------------------------------------------------------------------ */

#if CAPTI_HAVE_WHISPER
struct capti_ctx {
    struct whisper_context* wctx;
};
#endif

void* capti_whisper_create(const char* model_path) {
#if CAPTI_HAVE_WHISPER
    if (!model_path) return NULL;
    struct whisper_context_params cparams =
        whisper_context_default_params();
    struct whisper_context* wctx =
        whisper_init_from_file_with_params(model_path, cparams);
    if (!wctx) return NULL;
    struct capti_ctx* ctx = (struct capti_ctx*)malloc(sizeof(struct capti_ctx));
    if (!ctx) {
        whisper_free(wctx);
        return NULL;
    }
    ctx->wctx = wctx;
    return ctx;
#else
    (void)model_path;
    return NULL; /* Native-Schicht nicht mitgebaut: explizit unavailable */
#endif
}

int32_t capti_whisper_transcribe_file(void* handle, const char* wav_path,
                                      const char* language) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || !wav_path) return -1;

    float* samples = NULL;
    uint32_t rate = 16000;
    const int64_t n = read_wav_mono_f32(wav_path, &samples, &rate);
    if (n <= 0) return -2;
    if (rate != 16000) { // Whisper erwartet 16 kHz
        free(samples);
        return -3;
    }

    struct whisper_full_params wparams =
        whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wparams.print_progress = false;
    wparams.print_special = false;
    wparams.print_realtime = false;
    wparams.print_timestamps = false;
    wparams.translate = false;
    wparams.language = language && language[0] ? language : "auto";
    wparams.beam_search.beam_size = 1; // greedy reicht für Mobile-V1
    wparams.n_threads = 4;
    /* Word-Timestamps für Karaoke-Highlighting */
    wparams.token_timestamps = true;
    wparams.split_on_word = true;

    const int rc = whisper_full(ctx->wctx, wparams, samples, (int)n);
    free(samples);
    if (rc != 0) return -4;

    return (int32_t)whisper_full_n_segments(ctx->wctx);
#else
    (void)handle;
    (void)wav_path;
    (void)language;
    return -100; /* Native-Schicht nicht mitgebaut */
#endif
}

int32_t capti_whisper_segment_count(void* handle) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx) return 0;
    return (int32_t)whisper_full_n_segments(ctx->wctx);
#else
    (void)handle;
    return 0;
#endif
}

const char* capti_whisper_segment_text(void* handle, int32_t index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || index < 0) return "";
    return whisper_full_get_segment_text(ctx->wctx, (int)index);
#else
    (void)handle;
    (void)index;
    return "";
#endif
}

double capti_whisper_segment_t0(void* handle, int32_t index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || index < 0) return 0.0;
    /* whisper.cpp: Zentisekunden */
    return (double)whisper_full_get_segment_t0(ctx->wctx, (int)index) / 100.0;
#else
    (void)handle;
    (void)index;
    return 0.0;
#endif
}

double capti_whisper_segment_t1(void* handle, int32_t index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || index < 0) return 0.0;
    return (double)whisper_full_get_segment_t1(ctx->wctx, (int)index) / 100.0;
#else
    (void)handle;
    (void)index;
    return 0.0;
#endif
}

/* ------------------------- Word-Ebene ------------------------------ */

int32_t capti_whisper_word_count(void* handle, int32_t segment_index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || segment_index < 0) return 0;
    const int n_tokens =
        whisper_full_n_tokens(ctx->wctx, (int)segment_index);
    int32_t words = 0;
    for (int t = 0; t < n_tokens; t++) {
        const char* txt =
            whisper_full_get_token_text(ctx->wctx, (int)segment_index, t);
        if (!txt) continue;
        if (txt[0] == '[') continue;      // Sonder-/Zeit-Token auslassen
        if (txt[0] == '<' || txt[0] == '>') continue;
        if (txt[0] == '\0') continue;
        words++;
    }
    return words;
#else
    (void)handle;
    (void)segment_index;
    return 0;
#endif
}

const char* capti_whisper_word_text(void* handle, int32_t segment_index,
                                    int32_t token_index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || segment_index < 0 || token_index < 0) return "";
    return whisper_full_get_token_text(ctx->wctx, (int)segment_index,
                                       (int)token_index);
#else
    (void)handle;
    (void)segment_index;
    (void)token_index;
    return "";
#endif
}

double capti_whisper_word_t0(void* handle, int32_t segment_index,
                             int32_t token_index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || segment_index < 0 || token_index < 0) return 0.0;
    const whisper_token_data tok = whisper_full_get_token_data(
        ctx->wctx, (int)segment_index, (int)token_index);
    return (double)tok.t0 / 100.0;
#else
    (void)handle;
    (void)segment_index;
    (void)token_index;
    return 0.0;
#endif
}

double capti_whisper_word_t1(void* handle, int32_t segment_index,
                             int32_t token_index) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx || segment_index < 0 || token_index < 0) return 0.0;
    const whisper_token_data tok = whisper_full_get_token_data(
        ctx->wctx, (int)segment_index, (int)token_index);
    return (double)tok.t1 / 100.0;
#else
    (void)handle;
    (void)segment_index;
    (void)token_index;
    return 0.0;
#endif
}

void capti_whisper_free(void* handle) {
#if CAPTI_HAVE_WHISPER
    struct capti_ctx* ctx = (struct capti_ctx*)handle;
    if (!ctx) return;
    whisper_free(ctx->wctx);
    free(ctx);
#else
    (void)handle;
#endif
}
