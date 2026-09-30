/// Capti Media Bridge – echte Medienverarbeitung über FFmpeg + libass.
///
/// Flache C-API für dart:ffi (analog whisper_bridge.c):
///
///   CAPTI_API int32_t capti_media_probe(const char* video, int32_t* w, int32_t* h,
///                             int64_t* duration_ms);
///   CAPTI_API int32_t capti_media_extract_audio(const char* video, const char* wav_out,
///                                     char* err, int32_t err_len);
///   CAPTI_API int32_t capti_media_burn_ass(const char* video, const char* ass,
///                                const char* out, const char* fonts_dir,
///                                void (*progress)(double),
///                                char* err, int32_t err_len);
///   void    capti_media_request_cancel(void);
///
/// Rückgabecodes (stabil, Dart mappt sie auf lokalisierte Exceptions):
///   0 OK, 1 OPEN_INPUT, 2 STREAM_INFO, 3 NO_STREAMS, 4 EXTRACT_AUDIO,
///   5 ASS, 6 FILTER_GRAPH, 7 OPEN_OUTPUT, 8 ENCODE, 9 CANCELLED, 10 INTERNAL
///
/// Keine Fake-Pfade: Fehler enthalten Kontexttext, Fortschritt stammt aus
/// echtem Dekodierfortschritt (pts / duration).

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavfilter/avfilter.h>
#include <libavfilter/buffersink.h>
#include <libavfilter/buffersrc.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libavutil/pixdesc.h>
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
#include <math.h>
// Forward declare av_display_rotation_get to avoid needing display.h
extern double av_display_rotation_get(const int32_t *matrix);

#if defined(__ANDROID__)
#include <android/log.h>
#define CAPTI_LOGI(...) __android_log_print(ANDROID_LOG_INFO, "CaptiMedia", __VA_ARGS__)
#define CAPTI_LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "CaptiMedia", __VA_ARGS__)
#else
#include <stdarg.h>
static void CAPTI_LOGI(const char *fmt, ...) { (void)fmt; }
static void CAPTI_LOGE(const char *fmt, ...) { (void)fmt; }
#endif

/* FFmpeg-internes Logging nach Logcat spiegeln – unverzichtbar für die
 * Runtime-Diagnose auf dem Gerät (adb logcat -s CaptiMedia). */
static void capti_av_log_cb(void *avl, int level, const char *fmt, va_list vl)
{
    (void)avl;
    char line[1024];
    int n = vsnprintf(line, sizeof(line), fmt, vl);
    if (n > 0 && line[n - 1] == '\n') line[n - 1] = '\0';
#if defined(__ANDROID__)
    __android_log_print(level <= AV_LOG_ERROR ? ANDROID_LOG_ERROR
                                              : ANDROID_LOG_INFO,
                        "CaptiMedia", "[ffmpeg] %s", line);
#else
    (void)line;
#endif
}

/* Fataler Native-Crash: Signum + Adresse nach logcat, dann Standard-
 * Behandlung wiederherstellen (Android erzeugt Tombstone). Ziel: Der
 * Crash ist in adb logcat eindeutig der Media-Bridge zuzuordnen. */
#include <signal.h>
static void capti_crash_handler(int sig, siginfo_t *info, void *uctx)
{
    (void)uctx;
    CAPTI_LOGE("FATAL signal %d at addr %p (CaptiMedia native crash)",
               sig, info ? info->si_addr : NULL);
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = SIG_DFL;
    sigaction(sig, &sa, NULL);
}

__attribute__((constructor)) static void capti_media_init(void)
{
    av_log_set_callback(capti_av_log_cb);
#ifdef __ANDROID__
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = capti_crash_handler;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGABRT, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
#endif
    CAPTI_LOGI("media_bridge loaded");
}

#if defined(__GNUC__)
#define CAPTI_API __attribute__((visibility("default")))
#else
#define CAPTI_API
#endif

enum {
    MEDIA_OK = 0,
    MEDIA_ERR_OPEN_INPUT = 1,
    MEDIA_ERR_STREAM_INFO = 2,
    MEDIA_ERR_NO_STREAMS = 3,
    MEDIA_ERR_EXTRACT_AUDIO = 4,
    MEDIA_ERR_ASS = 5,
    MEDIA_ERR_FILTER_GRAPH = 6,
    MEDIA_ERR_OPEN_OUTPUT = 7,
    MEDIA_ERR_ENCODE = 8,
    MEDIA_ERR_CANCELLED = 9,
    MEDIA_ERR_INTERNAL = 10,
};

static volatile int g_cancel_requested = 0;

CAPTI_API void capti_media_request_cancel(void) { g_cancel_requested = 1; }

static void set_err(char *err, int err_len, const char *msg)
{
    if (err && err_len > 0) snprintf(err, (size_t)err_len, "%s", msg);
}

static int cancelled_by_user(void (*progress_cb)(double), double p)
{
    if (progress_cb) progress_cb(p);
    return g_cancel_requested;
}


/* Rotation als CCW-Winkel (0,90,180,270) – EINHEITLICHE Konvention.
 *
 * BEGRUENDUNG (kein Raten, offizielle FFmpeg-Doku):
 * - av_display_rotation_get() liefert "angle by which the transformation
 *   rotates the frame counterclockwise" (libavutil/display.h, Doxygen).
 * - transpose clock = 90 CW, transpose cclock = 90 CCW (ffmpeg filters doc).
 * - MP4-Tag "rotate" ist dagegen CLOCKWISE (ffmpeg cmdutils: get_rotation =
 *   -round(av_display_rotation_get())).
 * Darum: Tag (CW) wird nach CCW konvertiert (ccw = (360-cw)%360), Matrix
 * direkt via offizieller API (CCW). Mapping: CCW 90 -> cclock,
 * CCW 270 -> clock, CCW 180 -> clock+clock. 90/270 vertauscht gegenueber
 * der alten Implementierung – das war der KOPFUEBER-Bug (180 Grad Fehler,
 * gleiche Dimensionen, falsche Vertikale).
 */
static int get_rotation_ccw(AVStream *st) {
    // 1) Tag "rotate" (MP4, CLOCKWISE) -> nach CCW konvertieren
    AVDictionaryEntry *tag = av_dict_get(st->metadata, "rotate", NULL, 0);
    if (tag && tag->value) {
        int cw = atoi(tag->value) % 360;
        if (cw < 0) cw += 360;
        if (cw % 90 == 0) {
            int ccw = (360 - cw) % 360;
            CAPTI_LOGI("get_rotation tag rotate=%s (cw %d) -> ccw %d", tag->value, cw, ccw);
            return ccw;
        } else {
            CAPTI_LOGI("get_rotation tag rotate=%s not a multiple of 90 -> 0", tag->value);
        }
    } else {
        CAPTI_LOGI("get_rotation no rotate tag");
    }
    // 2) Display-Matrix side data – offizielle FFmpeg API (CCW)
    uint8_t *sd = av_stream_get_side_data(st, AV_PKT_DATA_DISPLAYMATRIX, NULL);
    if (sd) {
        int32_t *matrix = (int32_t*)sd;
        CAPTI_LOGI("get_rotation displaymatrix [%d,%d,%d; %d,%d,%d; %d,%d,%d]",
            matrix[0], matrix[1], matrix[2],
            matrix[3], matrix[4], matrix[5],
            matrix[6], matrix[7], matrix[8]);
        double rot = av_display_rotation_get(matrix);
        int ccw = (int) lrint(rot) % 360;
        if (ccw < 0) ccw += 360;
        CAPTI_LOGI("get_rotation av_display_rotation_get=%.2f -> ccw %d", rot, ccw);
        if (ccw % 90 == 0) return ccw;
        CAPTI_LOGE("get_rotation matrix angle not multiple of 90 -> 0");
    } else {
        CAPTI_LOGI("get_rotation no displaymatrix");
    }
    return 0;
}
// Historischer Name -> neue CCW-Semantik (alle Caller nutzen CCW).
static int get_rotation(AVStream *st) { return get_rotation_ccw(st); }

/* Defensive Eingabeprüfung: existiert, lesbar, Größe > 0.
 * Fängt z. B. fehlgeschlagene SAF-Cache-Kopien (0 Byte) sauber ab,
 * BEVOR FFmpeg den Kontext öffnet – jeder Pfad endet im Cleanup. */
static int input_file_ok(const char *path, char *err, int err_len)
{
    if (!path || !path[0]) { set_err(err, err_len, "input path empty"); return 0; }
    FILE *f = fopen(path, "rb");
    if (!f) { set_err(err, err_len, "input not readable"); return 0; }
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); set_err(err, err_len, "seek failed"); return 0; }
    long sz = ftell(f);
    fclose(f);
    if (sz <= 0) { set_err(err, err_len, "input file empty"); return 0; }
    return 1;
}

// ---------------------------------------------------------------------
// probe
// ---------------------------------------------------------------------

CAPTI_API int32_t capti_media_probe(const char *video, int32_t *w, int32_t *h,
                          int64_t *duration_ms)
{
    AVFormatContext *fmt = NULL;
    char errbuf[128];
    if (!input_file_ok(video, errbuf, sizeof(errbuf)))
        return MEDIA_ERR_OPEN_INPUT;
    if (avformat_open_input(&fmt, video, NULL, NULL) < 0)
        return MEDIA_ERR_OPEN_INPUT;
    if (avformat_find_stream_info(fmt, NULL) < 0) {
        avformat_close_input(&fmt);
        return MEDIA_ERR_STREAM_INFO;
    }
    if (w && h) {
        *w = 0; *h = 0;
        for (unsigned i = 0; i < fmt->nb_streams; i++) {
            if (fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
                AVCodecParameters *par = fmt->streams[i]->codecpar;
                int ww = par->width;
                int hh = par->height;
                AVRational sar = par->sample_aspect_ratio.num ? par->sample_aspect_ratio : (AVRational){1,1};
                double dar = sar.den && hh ? (double)ww * sar.num / sar.den / hh : 0.0;
                AVDictionaryEntry *rtag = av_dict_get(fmt->streams[i]->metadata, "rotate", NULL, 0);
                uint8_t *sd = av_stream_get_side_data(fmt->streams[i], AV_PKT_DATA_DISPLAYMATRIX, NULL);
                CAPTI_LOGI("probe coded=%dx%d sar=%d/%d dar=%.3f rotate_tag=%s displaymatrix=%s",
                    ww, hh, sar.num, sar.den, dar,
                    rtag ? rtag->value : "(none)", sd ? "present" : "absent");
                int rot = get_rotation_ccw(fmt->streams[i]);
                if (rot == 90 || rot == 270) {
                    int tmp = ww; ww = hh; hh = tmp;
                    CAPTI_LOGI("probe rotation_ccw %d -> swapped display %dx%d", rot, ww, hh);
                } else {
                    CAPTI_LOGI("probe rotation_ccw %d (no swap)", rot);
                }
                *w = ww;
                *h = hh;
                break;
            }
        }
        CAPTI_LOGI("probe result display %dx%d", *w, *h);
    }
    if (duration_ms)
        *duration_ms = fmt->duration > 0 ? fmt->duration / (AV_TIME_BASE / 1000)
                                         : -1;
    avformat_close_input(&fmt);
    return MEDIA_OK;
}

// ---------------------------------------------------------------------
// extract_audio: Video -> 16 kHz Mono S16-WAV (Whisper-Eingang)
// ---------------------------------------------------------------------

CAPTI_API int32_t capti_media_extract_audio(const char *video, const char *wav_out,
                                  char *err, int32_t err_len)
{
    int32_t rc = MEDIA_ERR_INTERNAL;
    CAPTI_LOGI("extract_audio ENTER video=%s wav=%s",
               video ? video : "(null)", wav_out ? wav_out : "(null)");
    if (!video || !wav_out || !err || err_len <= 0) {
        CAPTI_LOGE("extract_audio invalid args");
        return MEDIA_ERR_INTERNAL;
    }
    {
        char eb[128];
        if (!input_file_ok(video, eb, sizeof(eb))) {
            CAPTI_LOGE("extract_audio input_file_ok failed");
            set_err(err, err_len, eb);
            return MEDIA_ERR_OPEN_INPUT;
        }
    }
    AVFormatContext *fmt = NULL;
    const AVCodec *dec = NULL;
    AVCodecContext *dec_ctx = NULL;
    SwrContext *swr = NULL;
    FILE *out = NULL;
    AVPacket *pkt = NULL;
    AVFrame *frame = NULL;
    AVFrame *dst = NULL;
    uint8_t wav_header[44];
    uint32_t byte_rate = 16000 * 2;
    int audio_stream = -1;
    int64_t total_samples = 0;

    if (avformat_open_input(&fmt, video, NULL, NULL) < 0) {
        CAPTI_LOGE("extract_audio open_input FAILED");
        set_err(err, err_len, "open_input failed");
        return MEDIA_ERR_OPEN_INPUT;
    }
    if (avformat_find_stream_info(fmt, NULL) < 0) {
        CAPTI_LOGE("extract_audio find_stream_info FAILED");
        set_err(err, err_len, "find_stream_info failed");
        rc = MEDIA_ERR_STREAM_INFO; goto done;
    }
    audio_stream = av_find_best_stream(fmt, AVMEDIA_TYPE_AUDIO, -1, -1, &dec, 0);
    CAPTI_LOGI("extract_audio audio_stream=%d codec=%s",
               audio_stream, dec ? dec->name : "?");
    if (audio_stream < 0 || !dec) {
        set_err(err, err_len, "no audio stream");
        rc = MEDIA_ERR_NO_STREAMS; goto done;
    }
    dec_ctx = avcodec_alloc_context3(dec);
    if (!dec_ctx ||
        avcodec_parameters_to_context(dec_ctx,
                                      fmt->streams[audio_stream]->codecpar) < 0 ||
        avcodec_open2(dec_ctx, dec, NULL) < 0) {
        set_err(err, err_len, "audio decoder open failed");
        rc = MEDIA_ERR_EXTRACT_AUDIO; goto done;
    }
    CAPTI_LOGI("extract_audio decoder sr=%d fmt=%s ch=%d",
               dec_ctx->sample_rate,
               av_get_sample_fmt_name(dec_ctx->sample_fmt)
                   ? av_get_sample_fmt_name(dec_ctx->sample_fmt)
                   : "?",
               dec_ctx->ch_layout.nb_channels);

    {
        AVChannelLayout mono = AV_CHANNEL_LAYOUT_MONO;
        if (swr_alloc_set_opts2(&swr,
                                &mono, AV_SAMPLE_FMT_S16, 16000,
                                &dec_ctx->ch_layout, dec_ctx->sample_fmt,
                                dec_ctx->sample_rate, 0, NULL) < 0 ||
            !swr || swr_init(swr) < 0) {
            set_err(err, err_len, "swr init failed");
            rc = MEDIA_ERR_EXTRACT_AUDIO; goto done;
        }
    }

    out = fopen(wav_out, "wb");
    if (!out) { set_err(err, err_len, "cannot write wav"); rc = MEDIA_ERR_EXTRACT_AUDIO; goto done; }

    memset(wav_header, 0, sizeof(wav_header));
    memcpy(wav_header + 0, "RIFF", 4);
    memcpy(wav_header + 8, "WAVE", 4);
    memcpy(wav_header + 12, "fmt ", 4);
    memcpy(wav_header + 16, &(uint32_t){16}, 4);
    memcpy(wav_header + 20, &(uint16_t){1}, 2);       /* PCM */
    memcpy(wav_header + 22, &(uint16_t){1}, 2);       /* mono */
    memcpy(wav_header + 24, &(uint32_t){16000}, 4);
    memcpy(wav_header + 28, &byte_rate, 4);
    memcpy(wav_header + 32, &(uint16_t){2}, 2);       /* block align */
    memcpy(wav_header + 34, &(uint16_t){16}, 2);      /* bits */
    memcpy(wav_header + 36, "data", 4);
    fwrite(wav_header, 1, sizeof(wav_header), out);

    pkt = av_packet_alloc();
    frame = av_frame_alloc();
    dst = av_frame_alloc();

    while (!g_cancel_requested && av_read_frame(fmt, pkt) >= 0) {
        if (pkt->stream_index != audio_stream) { av_packet_unref(pkt); continue; }
        if (avcodec_send_packet(dec_ctx, pkt) < 0) { av_packet_unref(pkt); continue; }
        while (avcodec_receive_frame(dec_ctx, frame) >= 0) {
            dst->format = AV_SAMPLE_FMT_S16;
            dst->sample_rate = 16000;
            av_channel_layout_uninit(&dst->ch_layout);
            av_channel_layout_copy(&dst->ch_layout,
                                   &(AVChannelLayout)AV_CHANNEL_LAYOUT_MONO);
            dst->nb_samples = (int)av_rescale_rnd(
                swr_get_delay(swr, frame->sample_rate) + frame->nb_samples,
                16000, frame->sample_rate, AV_ROUND_UP);
            if (av_frame_get_buffer(dst, 0) == 0 &&
                swr_convert_frame(swr, dst, frame) >= 0 && dst->nb_samples > 0) {
                fwrite(dst->data[0], 1, (size_t)dst->nb_samples * 2, out);
                total_samples += dst->nb_samples;
            }
            av_frame_unref(frame);
            av_frame_unref(dst);
        }
        av_packet_unref(pkt);
    }
    /* Decoder flushen */
    avcodec_send_packet(dec_ctx, NULL);
    while (avcodec_receive_frame(dec_ctx, frame) >= 0) av_frame_unref(frame);

    if (g_cancel_requested) { rc = MEDIA_ERR_CANCELLED; goto done; }

    {
        uint32_t data_len = (uint32_t)(total_samples * 2);
        uint32_t riff_len = 36 + data_len;
        fseek(out, 4, SEEK_SET); fwrite(&riff_len, 4, 1, out);
        fseek(out, 40, SEEK_SET); fwrite(&data_len, 4, 1, out);
    }
    rc = total_samples > 0 ? MEDIA_OK : MEDIA_ERR_NO_STREAMS;

done:
    CAPTI_LOGI("extract_audio EXIT rc=%d samples=%lld", rc,
               (long long)total_samples);
    /* Cleanup in Einzelschritten geloggt: zeigt im nächsten Gerätelauf
     * exakt, welche Freigabe (falls doch eine) den Abort auslöst. */
    CAPTI_LOGI("cleanup: wav");
    if (out) { fclose(out); out = NULL; }
    CAPTI_LOGI("cleanup: buffers");
    CAPTI_LOGI("cleanup: swr");
    swr_free(&swr);
    CAPTI_LOGI("cleanup: frame");
    av_frame_free(&dst);
    av_frame_free(&frame);
    CAPTI_LOGI("cleanup: packet");
    av_packet_free(&pkt);
    CAPTI_LOGI("cleanup: codec");
    avcodec_free_context(&dec_ctx);
    CAPTI_LOGI("cleanup: format");
    avformat_close_input(&fmt);
    CAPTI_LOGI("cleanup: return rc=%d", rc);
    return rc;
}

// ---------------------------------------------------------------------
// burn_ass: Video + ASS -> Output (H.264/AAC MP4), echter Fortschritt
// ---------------------------------------------------------------------

static int open_decoder(AVFormatContext *fmt, int idx, AVCodecContext **out)
{
    const AVCodec *c = avcodec_find_decoder(fmt->streams[idx]->codecpar->codec_id);
    AVCodecContext *ctx;
    if (!c) return -1;
    ctx = avcodec_alloc_context3(c);
    if (!ctx) return -1;
    if (avcodec_parameters_to_context(ctx, fmt->streams[idx]->codecpar) < 0) {
        avcodec_free_context(&ctx); return -1;
    }
    ctx->time_base = fmt->streams[idx]->time_base;
    if (avcodec_open2(ctx, c, NULL) < 0) {
        avcodec_free_context(&ctx); return -1;
    }
    *out = ctx;
    return 0;
}

/* Ein dekodiertes Frame durch den ASS-Filter schicken und das Ergebnis
 * direkt in den Video-Encoder speisen; Encoder-Pakete werden gemuxt. */
static int pump_video(AVCodecContext *v_dec, AVFilterContext *bufsrc,
                      AVFilterContext *bufsink, AVCodecContext *v_enc,
                      AVFormatContext *out_fmt, double duration_s,
                      void (*progress_cb)(double),
                      AVPacket *opkt, AVFrame *fframe,
                      char *err, int err_len)
{
    /* Dekodiertes Frame rein */
    /* (Aufrufer hat es bereits via av_buffersrc_add_frame geschickt.) */

    while (av_buffersink_get_frame(bufsink, fframe) >= 0) {
        fframe->pict_type = AV_PICTURE_TYPE_NONE;
        if (avcodec_send_frame(v_enc, fframe) < 0) {
            set_err(err, err_len, "video send_frame failed");
            return MEDIA_ERR_ENCODE;
        }
        av_frame_unref(fframe);
        while (avcodec_receive_packet(v_enc, opkt) >= 0) {
            av_packet_rescale_ts(opkt, v_enc->time_base,
                                 out_fmt->streams[0]->time_base);
            opkt->stream_index = 0;
            if (av_interleaved_write_frame(out_fmt, opkt) < 0) {
                set_err(err, err_len, "mux write failed");
                return MEDIA_ERR_ENCODE;
            }
            av_packet_unref(opkt);
        }
    }
    (void)duration_s; (void)progress_cb;
    return MEDIA_OK;
}

CAPTI_API int32_t capti_media_burn_ass(const char *video, const char *ass_path,
                             const char *out_path, const char *fonts_dir,
                             void (*progress_cb)(double),
                             char *err, int32_t err_len)
{
    int32_t rc = MEDIA_ERR_INTERNAL;
    CAPTI_LOGI("burn_ass ENTER video=%s ass=%s out=%s fonts=%s",
               video ? video : "(null)", ass_path ? ass_path : "(null)",
               out_path ? out_path : "(null)",
               fonts_dir ? fonts_dir : "(null)");
    if (!video || !ass_path || !out_path || !err || err_len <= 0) {
        CAPTI_LOGE("burn_ass invalid args");
        return MEDIA_ERR_INTERNAL;
    }
    // Diagnose: Eingabedateien vor FFmpeg pruefen
    {
        FILE *vf = fopen(video, "rb");
        long vsize = -1;
        if (vf) { fseek(vf, 0, SEEK_END); vsize = ftell(vf); fclose(vf); }
        FILE *af = fopen(ass_path, "rb");
        long asize = -1;
        if (af) { fseek(af, 0, SEEK_END); asize = ftell(af); fclose(af); }
        CAPTI_LOGI("burn_ass INPUT video size=%ld ass size=%ld", vsize, asize);
        if (asize >= 0 && asize < 10) {
            CAPTI_LOGE("burn_ass ASS file too small: %ld", asize);
        }
        // Fonts Verzeichnis pruefen
        if (fonts_dir && fonts_dir[0]) {
            FILE *ff = fopen(fonts_dir, "rb");
            if (ff) fclose(ff);
            CAPTI_LOGI("burn_ass fonts_dir=%s", fonts_dir);
        }
    }
    {
        char eb[128];
        if (!input_file_ok(video, eb, sizeof(eb))) {
            CAPTI_LOGE("burn_ass input_file_ok failed: %s", eb);
            set_err(err, err_len, eb);
            return MEDIA_ERR_OPEN_INPUT;
        }
    }
    // ASS separat pruefen (nicht via input_file_ok, da Textdatei)
    {
        FILE *af = fopen(ass_path, "rb");
        if (!af) {
            CAPTI_LOGE("burn_ass ASS not readable: %s", ass_path);
            set_err(err, err_len, "ASS not readable");
            return MEDIA_ERR_ASS;
        }
        fseek(af, 0, SEEK_END);
        long asz = ftell(af);
        fclose(af);
        if (asz < 10) {
            CAPTI_LOGE("burn_ass ASS empty/too small: %ld", asz);
            set_err(err, err_len, "ASS empty");
            return MEDIA_ERR_ASS;
        }
        CAPTI_LOGI("burn_ass ASS validated size=%ld", asz);
        // Zaehle Dialogue-Zeilen fuer Diagnose (sichtbare Untertitel?)
        {
            FILE *af2 = fopen(ass_path, "r");
            if (af2) {
                char line[4096];
                int dialogue_count = 0;
                char first_dialogue[1024] = "";
                while (fgets(line, sizeof(line), af2)) {
                    if (strncmp(line, "Dialogue:", 9) == 0) {
                        dialogue_count++;
                        if (first_dialogue[0] == '\0') {
                            strncpy(first_dialogue, line, sizeof(first_dialogue)-1);
                            char *nl = strchr(first_dialogue, '\n');
                            if (nl) *nl = '\0';
                            // Kuerzen fuer Log
                            if (strlen(first_dialogue) > 200) first_dialogue[200] = '\0';
                        }
                    }
                }
                fclose(af2);
                CAPTI_LOGI("burn_ass ASS dialogueCount=%d firstDialogue=%s", dialogue_count, first_dialogue[0] ? first_dialogue : "(none)");
                if (dialogue_count == 0) {
                    CAPTI_LOGE("burn_ass ASS has no Dialogue – no subtitles will be visible");
                }
            } else {
                CAPTI_LOGE("burn_ass could not open ASS for dialogue count");
            }
        }
    }
    AVFormatContext *in_fmt = NULL, *out_fmt = NULL;
    AVCodecContext *v_dec = NULL, *a_dec = NULL, *v_enc = NULL, *a_enc = NULL;
    AVFilterGraph *graph = NULL;
    AVFilterContext *bufsrc = NULL, *bufsink = NULL;
    AVPacket *ipkt = NULL, *opkt = NULL;
    AVFrame *dframe = NULL, *fframe = NULL, *swr_frame = NULL;
    SwrContext *swr = NULL;
    int v_idx = -1, a_idx = -1;
    int out_audio_idx = -1;
    double duration_s = 0;
    int64_t audio_pts_samples = 0;
    int eof_in = 0, v_sink_eof = 0, a_done = 0;
    int decoded_frames = 0, filtered_frames = 0, encoded_packets = 0;
    int use_audio_copy = 0;
    int audio_packets_read = 0, audio_packets_written = 0;

    g_cancel_requested = 0;

    if (avformat_open_input(&in_fmt, video, NULL, NULL) < 0) {
        set_err(err, err_len, "open_input failed"); return MEDIA_ERR_OPEN_INPUT;
    }
    if (avformat_find_stream_info(in_fmt, NULL) < 0) {
        set_err(err, err_len, "find_stream_info failed");
        rc = MEDIA_ERR_STREAM_INFO; goto done;
    }
    v_idx = av_find_best_stream(in_fmt, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
    if (v_idx < 0) { set_err(err, err_len, "no video stream"); rc = MEDIA_ERR_NO_STREAMS; goto done; }
    a_idx = av_find_best_stream(in_fmt, AVMEDIA_TYPE_AUDIO, -1, -1, NULL, 0);
    CAPTI_LOGI("burn_ass streams nb_streams=%d v_idx=%d a_idx=%d", in_fmt->nb_streams, v_idx, a_idx);
    if (v_idx >= 0) {
        AVCodecParameters *par = in_fmt->streams[v_idx]->codecpar;
        CAPTI_LOGI("burn_ass video stream %d codec=%d (%s) %dx%d", v_idx, par->codec_id, avcodec_get_name(par->codec_id), par->width, par->height);
    }
    if (a_idx >= 0) {
        AVCodecParameters *par = in_fmt->streams[a_idx]->codecpar;
        const char *cname = avcodec_get_name(par->codec_id);
        CAPTI_LOGI("burn_ass audio stream %d codec=%d (%s) sr=%d ch=%d", a_idx, par->codec_id, cname ? cname : "?", par->sample_rate, par->ch_layout.nb_channels);
    } else {
        CAPTI_LOGI("burn_ass no audio stream found");
    }
    if (in_fmt->duration > 0) duration_s = (double)in_fmt->duration / AV_TIME_BASE;
    CAPTI_LOGI("burn_ass duration_s=%.2f", duration_s);
    // Rotation/Orientation – CCW-Konvention (siehe get_rotation_ccw Kommentar).
    // Kein Transpose bei 0. 90 CCW -> cclock, 270 CCW (=90 CW) -> clock, 180 -> clock+clock.
    // Vorher war 90->clock / 270->cclock (invertiert) -> KOPFUEBER (180 Grad Fehler).
    int rotation = 0; // CCW
    int need_transpose = 0;
    int transpose_dir = 0; // 1=cclock (90 CCW), 2=clock (90 CW / 270 CCW), 0=180 (clock+clock)
    if (v_idx >= 0) {
        AVCodecParameters *vpar = in_fmt->streams[v_idx]->codecpar;
        AVRational vsar = vpar->sample_aspect_ratio.num ? vpar->sample_aspect_ratio : (AVRational){1,1};
        AVDictionaryEntry *vtag = av_dict_get(in_fmt->streams[v_idx]->metadata, "rotate", NULL, 0);
        uint8_t *vsd = av_stream_get_side_data(in_fmt->streams[v_idx], AV_PKT_DATA_DISPLAYMATRIX, NULL);
        CAPTI_LOGI("burn_ass input coded=%dx%d sar=%d/%d rotate_tag=%s displaymatrix=%s",
            vpar->width, vpar->height, vsar.num, vsar.den,
            vtag ? vtag->value : "(none)", vsd ? "present" : "absent");
        rotation = get_rotation_ccw(in_fmt->streams[v_idx]);
        CAPTI_LOGI("burn_ass rotation_ccw=%d", rotation);
        if (rotation == 90) { need_transpose = 1; transpose_dir = 1; }
        else if (rotation == 270) { need_transpose = 1; transpose_dir = 2; }
        else if (rotation == 180) { need_transpose = 1; transpose_dir = 0; } // 180 via transpose+transpose
        if (need_transpose) {
            CAPTI_LOGI("burn_ass need_transpose ccw=%d dir=%d (%s)", rotation, transpose_dir,
                transpose_dir == 1 ? "cclock" : (transpose_dir == 2 ? "clock" : "clock+clock"));
        } else {
            CAPTI_LOGI("burn_ass no transpose needed (ccw=0)");
        }
    }

    if (open_decoder(in_fmt, v_idx, &v_dec) < 0) {
        set_err(err, err_len, "video decoder failed"); rc = MEDIA_ERR_ENCODE; goto done;
    }
    if (a_idx >= 0 && open_decoder(in_fmt, a_idx, &a_dec) < 0) a_idx = -1;

    // ---------------- Filtergraph ----------------
    // Rotation: bei 90/270/180 wird vor ASS transponiert, damit Untertitel korrekt liegen
    // und Ausgabe physisch rotiert (keine Display-Matrix, kein Stretch/Crop, nur transpose)
    graph = avfilter_graph_alloc();
    {
        const AVFilter *src_f = avfilter_get_by_name("buffer");
        const AVFilter *sink_f = avfilter_get_by_name("buffersink");
        const AVFilter *ass_f = avfilter_get_by_name("ass");
        const AVFilter *transpose_f = need_transpose ? avfilter_get_by_name("transpose") : NULL;
        AVRational fr = av_guess_frame_rate(in_fmt, in_fmt->streams[v_idx], NULL);
        char args[512], ass_args[1200];
        AVFilterContext *ass_filter = NULL;
        AVFilterContext *transpose1 = NULL, *transpose2 = NULL;

        if (!src_f || !sink_f || !ass_f) {
            set_err(err, err_len, "required filters not compiled in");
            rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        if (need_transpose && !transpose_f) {
            CAPTI_LOGE("burn_ass transpose filter not available");
            set_err(err, err_len, "transpose filter not compiled in"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        snprintf(args, sizeof(args),
                 "video_size=%dx%d:pix_fmt=%s:time_base=%d/%d:"
                 "pixel_aspect=%d/%d:frame_rate=%d/%d",
                 v_dec->width, v_dec->height,
                 av_get_pix_fmt_name(v_dec->pix_fmt),
                 v_dec->time_base.num, v_dec->time_base.den,
                 v_dec->sample_aspect_ratio.num ? v_dec->sample_aspect_ratio.num : 1,
                 v_dec->sample_aspect_ratio.den ? v_dec->sample_aspect_ratio.den : 1,
                 fr.num > 0 ? fr.num : 30, fr.den > 0 ? fr.den : 1);
        CAPTI_LOGI("burn_ass buffer args=%s rotation=%d need_transpose=%d", args, rotation, need_transpose);
        if (avfilter_graph_create_filter(&bufsrc, src_f, "src", args, NULL, graph) < 0) {
            CAPTI_LOGE("burn_ass buffer src failed args=%s", args);
            set_err(err, err_len, "buffer src failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        AVFilterContext *prev = bufsrc;
        // Transpose vor ASS, damit Untertitel auf rotiertem Bild liegen.
        // CCW 90 -> cclock (90 CCW), CCW 270 (=90 CW) -> clock. Vertauscht man
        // dies, sind die Dimensionen gleich, aber das Bild steht KOPF (180 Fehler).
        if (need_transpose) {
            const char *t_args = NULL;
            if (rotation == 90) t_args = "dir=cclock";
            else if (rotation == 270) t_args = "dir=clock";
            else if (rotation == 180) t_args = "dir=clock"; // erste von zwei
            if (avfilter_graph_create_filter(&transpose1, transpose_f, "transp1", t_args, NULL, graph) < 0) {
                CAPTI_LOGE("burn_ass transpose1 failed t_args=%s", t_args);
                set_err(err, err_len, "transpose failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
            }
            CAPTI_LOGI("burn_ass transpose1 %s", t_args);
            if (avfilter_link(prev, 0, transpose1, 0) < 0) { set_err(err, err_len, "link src->transpose"); rc = MEDIA_ERR_FILTER_GRAPH; goto done; }
            prev = transpose1;
            if (rotation == 180) {
                // 180 braucht zwei mal 90
                if (avfilter_graph_create_filter(&transpose2, transpose_f, "transp2", "dir=clock", NULL, graph) < 0) {
                    CAPTI_LOGE("burn_ass transpose2 failed");
                    set_err(err, err_len, "transpose2 failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
                }
                if (avfilter_link(prev, 0, transpose2, 0) < 0) { set_err(err, err_len, "link transp1->transp2"); rc = MEDIA_ERR_FILTER_GRAPH; goto done; }
                prev = transpose2;
                CAPTI_LOGI("burn_ass transpose2 for 180");
            }
        }
        if (fonts_dir && fonts_dir[0])
            snprintf(ass_args, sizeof(ass_args), "filename=%s:fontsdir=%s",
                     ass_path, fonts_dir);
        else
            snprintf(ass_args, sizeof(ass_args), "filename=%s", ass_path);
        CAPTI_LOGI("burn_ass ass_args=%s", ass_args);
        if (avfilter_graph_create_filter(&ass_filter, ass_f, "ass", ass_args,
                                         NULL, graph) < 0) {
            CAPTI_LOGE("burn_ass ass filter failed ass_args=%s", ass_args);
            set_err(err, err_len, "ass load failed (Datei/Fonts?)");
            rc = MEDIA_ERR_ASS; goto done;
        }
        CAPTI_LOGI("burn_ass ass filter ok%s", need_transpose ? " (after transpose)" : "");
        if (avfilter_link(prev, 0, ass_filter, 0) < 0) {
            set_err(err, err_len, "link prev->ass"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        if (avfilter_graph_create_filter(&bufsink, sink_f, "sink", NULL, NULL, graph) < 0) {
            set_err(err, err_len, "buffersink failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        enum AVPixelFormat fmts[2] = { AV_PIX_FMT_YUV420P, AV_PIX_FMT_NONE };
        if (av_opt_set_int_list(bufsink, "pix_fmts", fmts, AV_PIX_FMT_NONE,
                                AV_OPT_SEARCH_CHILDREN) < 0) {
            set_err(err, err_len, "pix_fmts failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        if (avfilter_link(ass_filter, 0, bufsink, 0) < 0) {
            set_err(err, err_len, "link ass->sink"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        if (avfilter_graph_config(graph, NULL) < 0) {
            CAPTI_LOGE("burn_ass graph config failed (rotation %d)", rotation);
            set_err(err, err_len, "graph config failed"); rc = MEDIA_ERR_FILTER_GRAPH; goto done;
        }
        CAPTI_LOGI("burn_ass graph config ok rotation=%d", rotation);
    }

    // ---------------- Encoder ----------------
    {
        const AVCodec *enc = avcodec_find_encoder_by_name("libx264");
        if (!enc) { set_err(err, err_len, "libx264 not available"); rc = MEDIA_ERR_ENCODE; goto done; }
        v_enc = avcodec_alloc_context3(enc);
        // Rotation: bei 90/270 CCW Ausgabe vertauscht, sonst original.
        // Physisch rotiert -> Output traegt KEINE rotate/displaymatrix (rotation=0 by design).
        if (need_transpose && (rotation == 90 || rotation == 270)) {
            v_enc->width = v_dec->height;
            v_enc->height = v_dec->width;
            CAPTI_LOGI("burn_ass encoder swapped for rotation %d: %dx%d -> %dx%d", rotation, v_dec->width, v_dec->height, v_enc->width, v_enc->height);
        } else {
            v_enc->width = v_dec->width; v_enc->height = v_dec->height;
        }
        v_enc->pix_fmt = AV_PIX_FMT_YUV420P;
        v_enc->time_base = v_dec->time_base.num > 0 && v_dec->time_base.den > 0
                               ? v_dec->time_base
                               : (AVRational){1, 30};
        v_enc->framerate = av_inv_q(v_enc->time_base);
        v_enc->bit_rate = 4000000; v_enc->gop_size = 120;
        v_enc->max_b_frames = 2;
        av_opt_set(v_enc->priv_data, "preset", "veryfast", 0);
        av_opt_set(v_enc->priv_data, "crf", "22", 0);
        if (avcodec_open2(v_enc, enc, NULL) < 0) {
            set_err(err, err_len, "x264 open failed"); rc = MEDIA_ERR_ENCODE; goto done;
        }
    }
    // Audio: bevorzuge Stream-Copy (kein Re-Encode) fuer Original-Audio
    if (a_idx >= 0) {
        // Behalte Decoder fuer Validierung, aber fuer Output nutzen wir Copy
        // Pruefe ob Audio-Codec fuer MP4 Copy geeignet (fuer jetzt immer Copy versuchen)
        use_audio_copy = 1;
        CAPTI_LOGI("burn_ass audio copy enabled for idx %d", a_idx);
        // Kein a_enc/srs noetig fuer Copy – trotzdem Decoder behalten fuer read
        // Fallback zu Re-Encode waere hier, aber Copy ist bevorzugt
    }
    // Falls Copy aktiv, kein a_enc noetig
    if (a_idx >= 0 && !use_audio_copy) {
        const AVCodec *enc = avcodec_find_encoder(AV_CODEC_ID_AAC);
        if (enc) {
            a_enc = avcodec_alloc_context3(enc);
            a_enc->sample_rate = a_dec->sample_rate == 48000 ? 48000 : 44100;
            av_channel_layout_default(&a_enc->ch_layout,
                                      a_dec->ch_layout.nb_channels);
            a_enc->sample_fmt = AV_SAMPLE_FMT_FLTP;
            a_enc->bit_rate = 128000;
            a_enc->time_base = (AVRational){1, a_enc->sample_rate};
            if (avcodec_open2(a_enc, enc, NULL) < 0) { avcodec_free_context(&a_enc); }
        }
        if (!a_enc) { a_idx = -1; use_audio_copy = 0; }
        else {
            AVChannelLayout target = a_enc->ch_layout;
            if (swr_alloc_set_opts2(&swr, &target, AV_SAMPLE_FMT_FLTP,
                                    a_enc->sample_rate,
                                    &a_dec->ch_layout, a_dec->sample_fmt,
                                    a_dec->sample_rate, 0, NULL) < 0 || !swr ||
                swr_init(swr) < 0) { a_idx = -1; swr_free(&swr); swr = NULL; use_audio_copy = 0; }
        }
    }

    // ---------------- Ausgabe ----------------
    CAPTI_LOGI("burn_ass OUTPUT alloc out_path=%s", out_path);
    if (avformat_alloc_output_context2(&out_fmt, NULL, NULL, out_path) < 0 ||
        !out_fmt) {
        CAPTI_LOGE("burn_ass output alloc failed");
        set_err(err, err_len, "output alloc failed"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done;
    }
    {
        AVStream *vs = avformat_new_stream(out_fmt, NULL);
        if (!vs) { CAPTI_LOGE("burn_ass new vstream failed"); set_err(err, err_len, "new vstream"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done; }
        avcodec_parameters_from_context(vs->codecpar, v_enc);
        vs->time_base = v_enc->time_base;
        {
            AVRational sar = vs->codecpar->sample_aspect_ratio.num ? vs->codecpar->sample_aspect_ratio : (AVRational){1,1};
            double dar = sar.den && vs->codecpar->height ? (double)vs->codecpar->width * sar.num / sar.den / vs->codecpar->height : 0.0;
            CAPTI_LOGI("burn_ass OUTPUT video %dx%d sar=%d/%d dar=%.3f time_base=%d/%d rotation=0 (physically rotated, no displaymatrix)",
                vs->codecpar->width, vs->codecpar->height, sar.num, sar.den, dar, vs->time_base.num, vs->time_base.den);
        }
        if (use_audio_copy && a_idx >= 0) {
            AVStream *as = avformat_new_stream(out_fmt, NULL);
            if (!as) { CAPTI_LOGE("burn_ass new astream copy failed"); set_err(err, err_len, "new astream"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done; }
            if (avcodec_parameters_copy(as->codecpar, in_fmt->streams[a_idx]->codecpar) < 0) {
                CAPTI_LOGE("burn_ass copy audio par failed");
                set_err(err, err_len, "copy audio par failed"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done;
            }
            as->time_base = in_fmt->streams[a_idx]->time_base;
            out_audio_idx = as->index;
            CAPTI_LOGI("burn_ass OUTPUT audio copy stream %d codec=%d time_base=%d/%d", as->index, as->codecpar->codec_id, as->time_base.num, as->time_base.den);
        } else if (a_enc) {
            AVStream *as = avformat_new_stream(out_fmt, NULL);
            avcodec_parameters_from_context(as->codecpar, a_enc);
            as->time_base = (AVRational){1, a_enc->sample_rate};
            out_audio_idx = as->index;
            CAPTI_LOGI("burn_ass OUTPUT astream re-encode stream %d sample_rate=%d", as->index, a_enc->sample_rate);
        }
        if (!(out_fmt->oformat->flags & AVFMT_NOFILE) &&
            avio_open(&out_fmt->pb, out_path, AVIO_FLAG_WRITE) < 0) {
            CAPTI_LOGE("burn_ass avio_open failed for %s", out_path);
            set_err(err, err_len, "cannot open output"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done;
        }
        CAPTI_LOGI("burn_ass avio_open ok for %s", out_path);
        CAPTI_LOGI("burn_ass output streams nb_streams=%d", out_fmt->nb_streams);
        for (unsigned _i=0; _i<out_fmt->nb_streams; _i++) {
            AVStream *st = out_fmt->streams[_i];
            uint8_t *osd = av_stream_get_side_data(st, AV_PKT_DATA_DISPLAYMATRIX, NULL);
            AVDictionaryEntry *ort = av_dict_get(st->metadata, "rotate", NULL, 0);
            CAPTI_LOGI("burn_ass output stream %d codec=%d time_base=%d/%d rotate_tag=%s displaymatrix=%s", _i, st->codecpar->codec_id, st->time_base.num, st->time_base.den, ort ? ort->value : "(none)", osd ? "present" : "absent");
        }
        if (avformat_write_header(out_fmt, NULL) < 0) {
            CAPTI_LOGE("burn_ass write_header failed");
            set_err(err, err_len, "write_header failed"); rc = MEDIA_ERR_OPEN_OUTPUT; goto done;
        }
        CAPTI_LOGI("burn_ass write_header ok");
    }

    ipkt = av_packet_alloc(); opkt = av_packet_alloc();
    dframe = av_frame_alloc(); fframe = av_frame_alloc();
    if (a_idx >= 0) swr_frame = av_frame_alloc();

    // ---------------- Hauptschleife ----------------
    while (!(v_sink_eof && a_done)) {
        double prog = 0;

        /* Eingabe lesen & in Decoder schieben */
        if (!eof_in) {
            int r = av_read_frame(in_fmt, ipkt);
            if (r < 0) {
                eof_in = 1;
                avcodec_send_packet(v_dec, NULL);
                if (!use_audio_copy && a_dec) avcodec_send_packet(a_dec, NULL);
                CAPTI_LOGI("burn_ass read EOF r=%d", r);
            } else if (ipkt->stream_index == v_idx) {
                avcodec_send_packet(v_dec, ipkt);
                av_packet_unref(ipkt);
            } else if (a_idx >= 0 && ipkt->stream_index == a_idx) {
                if (use_audio_copy) {
                    audio_packets_read++;
                    AVStream *in_st = in_fmt->streams[a_idx];
                    AVStream *out_st = out_fmt->streams[out_audio_idx];
                    // Rescale und direkt muxen (Stream Copy)
                    av_packet_rescale_ts(ipkt, in_st->time_base, out_st->time_base);
                    ipkt->stream_index = out_audio_idx;
                    CAPTI_LOGI("burn_ass audio copy read packet %d pts=%ld dts=%ld", audio_packets_read, (long)ipkt->pts, (long)ipkt->dts);
                    if (av_interleaved_write_frame(out_fmt, ipkt) < 0) {
                        CAPTI_LOGE("burn_ass audio copy write failed");
                        set_err(err, err_len, "audio copy write failed");
                        rc = MEDIA_ERR_ENCODE; goto done;
                    }
                    audio_packets_written++;
                    av_packet_unref(ipkt);
                } else {
                    audio_packets_read++;
                    avcodec_send_packet(a_dec, ipkt);
                    av_packet_unref(ipkt);
                }
            } else {
                av_packet_unref(ipkt); /* fremde Spur verwerfen */
            }
        }

        /* ---------- Video: decode -> ass -> encode ---------- */
        while (!v_sink_eof) {
            int drc = avcodec_receive_frame(v_dec, dframe);
            if (drc == 0) {
                decoded_frames++;
                if (decoded_frames == 1) {
                    CAPTI_LOGI("burn_ass first decoded frame %dx%d format=%s sar=%d/%d", dframe->width, dframe->height, av_get_pix_fmt_name(dframe->format) ? av_get_pix_fmt_name(dframe->format) : "?", dframe->sample_aspect_ratio.num, dframe->sample_aspect_ratio.den);
                }
                prog = duration_s > 0 && dframe->pts != AV_NOPTS_VALUE
                           ? dframe->pts * av_q2d(v_dec->time_base) / duration_s
                           : 0;
                if (cancelled_by_user(progress_cb, prog)) { rc = MEDIA_ERR_CANCELLED; goto done; }
                if (av_buffersrc_add_frame_flags(bufsrc, dframe, AV_BUFFERSRC_FLAG_KEEP_REF) < 0) {
                    CAPTI_LOGE("burn_ass av_buffersrc_add_frame failed");
                    set_err(err, err_len, "buffer src add failed");
                    rc = MEDIA_ERR_FILTER_GRAPH; goto done;
                }
                av_frame_unref(dframe);
                CAPTI_LOGI("burn_ass decoded frame %d pts=%ld", decoded_frames, (long)dframe->pts);
            } else if (drc == AVERROR(EAGAIN)) {
                // Benoetigt mehr Pakete – Schleife verlassen, mehr Input lesen
                break;
            } else if (drc == AVERROR_EOF) {
                CAPTI_LOGI("burn_ass decoder EOF, decoded=%d", decoded_frames);
                if (!v_sink_eof) {
                    if (av_buffersrc_add_frame_flags(bufsrc, NULL, 0) < 0) {
                        CAPTI_LOGE("burn_ass av_buffersrc_add_frame NULL failed");
                    } else {
                        CAPTI_LOGI("burn_ass sent NULL to filter (EOF)");
                    }
                }
            } else {
                CAPTI_LOGE("burn_ass avcodec_receive_frame error %d", drc);
                set_err(err, err_len, "video decode failed");
                rc = MEDIA_ERR_ENCODE; goto done;
            }

            // Alle verfuegbaren gefilterten Frames drainen und encodieren
            int filtered_this = 0;
            while (av_buffersink_get_frame(bufsink, fframe) >= 0) {
                filtered_this++;
                filtered_frames++;
                if (filtered_frames == 1) {
                    CAPTI_LOGI("burn_ass first filtered frame %dx%d format=%s (filter output)", fframe->width, fframe->height, av_get_pix_fmt_name(fframe->format) ? av_get_pix_fmt_name(fframe->format) : "?");
                } else {
                    CAPTI_LOGI("burn_ass filtered frame %d", filtered_frames);
                }
                fframe->pict_type = AV_PICTURE_TYPE_NONE;
                if (avcodec_send_frame(v_enc, fframe) < 0) {
                    CAPTI_LOGE("burn_ass avcodec_send_frame failed");
                    set_err(err, err_len, "video send_frame failed");
                    rc = MEDIA_ERR_ENCODE; goto done;
                }
                av_frame_unref(fframe);
                while (avcodec_receive_packet(v_enc, opkt) >= 0) {
                    encoded_packets++;
                    CAPTI_LOGI("burn_ass encoded packet %d pts=%ld", encoded_packets, (long)opkt->pts);
                    av_packet_rescale_ts(opkt, v_enc->time_base, out_fmt->streams[0]->time_base);
                    opkt->stream_index = 0;
                    if (av_interleaved_write_frame(out_fmt, opkt) < 0) {
                        CAPTI_LOGE("burn_ass av_interleaved_write_frame failed");
                        set_err(err, err_len, "mux write failed");
                        rc = MEDIA_ERR_ENCODE; goto done;
                    }
                    av_packet_unref(opkt);
                }
            }
            if (filtered_this == 0) {
                CAPTI_LOGI("burn_ass no filtered frames this iter drc=%d", drc);
            }
            if (drc == AVERROR_EOF) {
                // Filter drain bereits oben, jetzt Encoder flushen
                CAPTI_LOGI("burn_ass flushing encoder, filtered_total=%d", filtered_frames);
                if (avcodec_send_frame(v_enc, NULL) < 0) {
                    CAPTI_LOGE("burn_ass avcodec_send_frame flush failed");
                }
                while (avcodec_receive_packet(v_enc, opkt) >= 0) {
                    encoded_packets++;
                    av_packet_rescale_ts(opkt, v_enc->time_base, out_fmt->streams[0]->time_base);
                    opkt->stream_index = 0;
                    if (av_interleaved_write_frame(out_fmt, opkt) < 0) {
                        CAPTI_LOGE("burn_ass flush write failed");
                        set_err(err, err_len, "mux write failed (flush)");
                        rc = MEDIA_ERR_ENCODE; goto done;
                    }
                    av_packet_unref(opkt);
                }
                CAPTI_LOGI("burn_ass encoder flush done encoded_total=%d", encoded_packets);
                if (encoded_packets == 0) {
                    CAPTI_LOGE("burn_ass no packets encoded at all – check input/filter/encoder");
                    set_err(err, err_len, "no packets encoded – check input/filter/encoder");
                    rc = MEDIA_ERR_ENCODE; goto done;
                }
                v_sink_eof = 1;
                break;
            }
            // Falls keine gefilterten Frames und EAGAIN, mehr Input holen
            if (filtered_this == 0 && drc == AVERROR(EAGAIN)) {
                break;
            }
        }

        /* ---------- Audio ---------- */
        if (a_idx < 0) {
            a_done = 1;
        } else if (use_audio_copy) {
            if (eof_in) {
                if (!a_done) {
                    CAPTI_LOGI("burn_ass audio copy done read=%d written=%d", audio_packets_read, audio_packets_written);
                    if (audio_packets_read > 0 && audio_packets_written == 0) {
                        CAPTI_LOGE("burn_ass audio copy no packets written despite %d read", audio_packets_read);
                        set_err(err, err_len, "audio copy no packets written");
                        rc = MEDIA_ERR_ENCODE; goto done;
                    }
                    if (audio_packets_read == 0) {
                        CAPTI_LOGI("burn_ass audio copy no packets read – maybe no audio?");
                    }
                }
                a_done = 1;
            }
        } else if (!a_done) {
            int arc = avcodec_receive_frame(a_dec, dframe);
            if (arc == 0) {
                audio_packets_read++;
                swr_frame->format = a_enc->sample_fmt;
                av_channel_layout_uninit(&swr_frame->ch_layout);
                av_channel_layout_copy(&swr_frame->ch_layout, &a_enc->ch_layout);
                swr_frame->sample_rate = a_enc->sample_rate;
                swr_frame->nb_samples = (int)av_rescale_rnd(
                    swr_get_delay(swr, a_dec->sample_rate) + dframe->nb_samples,
                    a_enc->sample_rate, a_dec->sample_rate, AV_ROUND_UP);
                if (av_frame_get_buffer(swr_frame, 0) == 0 &&
                    swr_convert_frame(swr, swr_frame, dframe) >= 0 &&
                    swr_frame->nb_samples > 0) {
                    swr_frame->pts = audio_pts_samples;
                    audio_pts_samples += swr_frame->nb_samples;
                    if (avcodec_send_frame(a_enc, swr_frame) == 0) {
                        // Drain encoder
                        while (avcodec_receive_packet(a_enc, opkt) >= 0) {
                            audio_packets_written++;
                            av_packet_rescale_ts(opkt, a_enc->time_base, out_fmt->streams[out_audio_idx]->time_base);
                            opkt->stream_index = out_audio_idx;
                            if (av_interleaved_write_frame(out_fmt, opkt) < 0) {
                                CAPTI_LOGE("burn_ass audio re-encode write failed");
                                set_err(err, err_len, "audio mux write failed");
                                rc = MEDIA_ERR_ENCODE; goto done;
                            }
                            av_packet_unref(opkt);
                        }
                    }
                }
                av_frame_unref(dframe);
                av_frame_unref(swr_frame);
            } else if (arc == AVERROR_EOF) {
                avcodec_send_frame(a_enc, NULL);
                while (avcodec_receive_packet(a_enc, opkt) >= 0) {
                    audio_packets_written++;
                    av_packet_rescale_ts(opkt, a_enc->time_base,
                                         out_fmt->streams[out_audio_idx]->time_base);
                    opkt->stream_index = out_audio_idx;
                    if (av_interleaved_write_frame(out_fmt, opkt) < 0) {
                        CAPTI_LOGE("burn_ass audio flush write failed");
                    }
                    av_packet_unref(opkt);
                }
                CAPTI_LOGI("burn_ass audio re-encode done read=%d written=%d", audio_packets_read, audio_packets_written);
                a_done = 1;
            } else if (arc != AVERROR(EAGAIN)) {
                CAPTI_LOGE("burn_ass audio decode error %d", arc);
            }
        }

        if (cancelled_by_user(progress_cb, prog)) { rc = MEDIA_ERR_CANCELLED; goto done; }
    }

    if (av_write_trailer(out_fmt) < 0) {
        CAPTI_LOGE("burn_ass write_trailer failed");
        set_err(err, err_len, "write_trailer failed");
        rc = MEDIA_ERR_ENCODE; goto done;
    }
    CAPTI_LOGI("burn_ass write_trailer ok");
    // Validierung: Output muss >1KB sein – 859-Byte-Bug abfangen
    {
        FILE *of = fopen(out_path, "rb");
        long osize = -1;
        if (of) { fseek(of, 0, SEEK_END); osize = ftell(of); fclose(of); }
        CAPTI_LOGI("burn_ass OUTPUT size=%ld path=%s", osize, out_path ? out_path : "(null)");
        if (osize >= 0 && osize < 1024) {
            CAPTI_LOGE("burn_ass OUTPUT too small (%ld) – encode produced only header, treating as error", osize);
            set_err(err, err_len, "output too small – encode failed (no packets, check input/ASS/codec)");
            // Kaputte Ausgabe loeschen, damit Dart/ Gallery nicht 859-Byte feiert
            remove(out_path);
            rc = MEDIA_ERR_ENCODE;
            goto done;
        }
        if (osize < 0) {
            CAPTI_LOGE("burn_ass OUTPUT not found after trailer");
            set_err(err, err_len, "output not found after encode");
            rc = MEDIA_ERR_ENCODE;
            goto done;
        }
    }
    rc = cancelled_by_user(progress_cb, 1.0) ? MEDIA_ERR_CANCELLED : MEDIA_OK;

    CAPTI_LOGI("burn_ass AUDIO read=%d written=%d use_copy=%d out_audio_idx=%d", audio_packets_read, audio_packets_written, use_audio_copy, out_audio_idx);
done:
    CAPTI_LOGI("burn_ass EXIT rc=%d", rc);
    CAPTI_LOGI("cleanup: frames");
    av_frame_free(&swr_frame);
    av_frame_free(&fframe);
    av_frame_free(&dframe);
    CAPTI_LOGI("cleanup: packets");
    av_packet_free(&opkt);
    av_packet_free(&ipkt);
    CAPTI_LOGI("cleanup: swr");
    swr_free(&swr);
    CAPTI_LOGI("cleanup: graph");
    avfilter_graph_free(&graph);
    CAPTI_LOGI("cleanup: codecs");
    avcodec_free_context(&v_enc);
    avcodec_free_context(&a_enc);
    avcodec_free_context(&v_dec);
    avcodec_free_context(&a_dec);
    if (out_fmt && !(out_fmt->oformat->flags & AVFMT_NOFILE) && out_fmt->pb)
        avio_closep(&out_fmt->pb);
    avformat_free_context(out_fmt);
    avformat_close_input(&in_fmt);
    return rc;
}
