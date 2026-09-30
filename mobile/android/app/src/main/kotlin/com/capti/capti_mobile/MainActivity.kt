package com.capti.capti_mobile

import android.content.ContentValues
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    private val channelName = "capti/media"
    private val galleryTag = "CaptiGallery"
    private var lastSavedUri: Uri? = null
    private var lastSavedPath: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    // SAF-Absicherung: content://-URIs sind für native
                    // FFmpeg (POSIX fopen) unlesbar. Wir kopieren den
                    // Inhalt einmalig in den App-Cache und liefern einen
                    // echten Dateipfad zurück.
                    "resolveInputPath" -> {
                        val raw = call.argument<String>("path") ?: ""
                        if (!raw.startsWith("content://")) {
                            result.success(raw)
                        } else {
                            try {
                                val uri = Uri.parse(raw)
                                val name = queryDisplayName(uri)
                                    ?: ("capti_input_${System.currentTimeMillis()}")
                                val safeName = name.replace(Regex("[^A-Za-z0-9._-]"), "_")
                                val dir = File(cacheDir, "capti_inputs").apply { mkdirs() }
                                val outFile = File(dir, "${System.currentTimeMillis()}_$safeName")
                                contentResolver.openInputStream(uri)?.use { input ->
                                    outFile.outputStream().use { output ->
                                        input.copyTo(output, 1 shl 16)
                                    }
                                } ?: throw IllegalStateException("openInputStream null")
                                result.success(outFile.absolutePath)
                            } catch (e: Exception) {
                                Log.e(galleryTag, "CAPTI_GALLERY_ERROR resolveInputPath: ${e::class.java.simpleName}: ${e.message}", e)
                                result.error("COPY_FAILED", e.message, null)
                            }
                        }
                    }
                    "saveToGallery" -> {
                        val sourcePath = call.argument<String>("sourcePath") ?: ""
                        var displayName = call.argument<String>("displayName") ?: "Capti_${System.currentTimeMillis()}.mp4"
                        displayName = displayName.replace(Regex("[/\\\\]"), "_")
                        if (!displayName.lowercase().endsWith(".mp4")) displayName += ".mp4"
                        if (!displayName.startsWith("Capti_")) displayName = "Capti_$displayName"
                        Log.i(galleryTag, "CAPTI_GALLERY_START displayName=$displayName sourcePath=$sourcePath")
                        var pendingUri: Uri? = null
                        try {
                            val sourceFile = File(sourcePath)
                            Log.i(galleryTag, "CAPTI_GALLERY_SOURCE exists=${sourceFile.exists()} readable=${sourceFile.canRead()} size=${if (sourceFile.exists()) sourceFile.length() else -1} path=$sourcePath")
                            if (!sourceFile.exists()) throw IllegalStateException("Quelle nicht gefunden: $sourcePath")
                            if (!sourceFile.canRead()) throw IllegalStateException("Quelle nicht lesbar: $sourcePath")
                            val fileSize = sourceFile.length()
                            Log.i(galleryTag, "CAPTI_GALLERY_SOURCE size=$fileSize mime=video/mp4")
                            if (fileSize < 1024) throw IllegalStateException("Quelle zu klein ($fileSize Bytes), vermutlich unvollständig")
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                Log.i(galleryTag, "CAPTI_GALLERY_INSERT Q+ RELATIVE_PATH=Movies/Capti DISPLAY_NAME=$displayName")
                                val values = ContentValues().apply {
                                    put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
                                    put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                                    put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/Capti")
                                    put(MediaStore.Video.Media.IS_PENDING, 1)
                                }
                                val collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                                val uri = contentResolver.insert(collection, values)
                                if (uri == null) {
                                    Log.e(galleryTag, "CAPTI_GALLERY_ERROR insert returned null")
                                    throw IllegalStateException("MediaStore insert fehlgeschlagen (null Uri)")
                                }
                                pendingUri = uri
                                Log.i(galleryTag, "CAPTI_GALLERY_URI $uri")
                                Log.i(galleryTag, "CAPTI_GALLERY_STREAM openOutputStream for $uri")
                                val outStream = contentResolver.openOutputStream(uri)
                                if (outStream == null) {
                                    Log.e(galleryTag, "CAPTI_GALLERY_ERROR openOutputStream null for $uri")
                                    try { contentResolver.delete(uri, null, null) } catch (_: Exception) {}
                                    throw IllegalStateException("openOutputStream null für $uri")
                                }
                                Log.i(galleryTag, "CAPTI_GALLERY_COPY start fileSize=$fileSize")
                                var copied: Long = 0
                                outStream.use { out ->
                                    sourceFile.inputStream().use { inp ->
                                        val buf = ByteArray(1 shl 16)
                                        var n: Int
                                        while (inp.read(buf).also { n = it } != -1) {
                                            out.write(buf, 0, n)
                                            copied += n
                                        }
                                        out.flush()
                                    }
                                }
                                Log.i(galleryTag, "CAPTI_GALLERY_COPY done copied=$copied")
                                if (copied < 1024) {
                                    Log.e(galleryTag, "CAPTI_GALLERY_ERROR copied too small: $copied")
                                    try { contentResolver.delete(uri, null, null) } catch (_: Exception) {}
                                    throw IllegalStateException("Kopierte Datei zu klein ($copied Bytes)")
                                }
                                Log.i(galleryTag, "CAPTI_GALLERY_COMPLETE clear IS_PENDING for $uri")
                                val updValues = ContentValues().apply {
                                    put(MediaStore.Video.Media.IS_PENDING, 0)
                                }
                                val updated = contentResolver.update(uri, updValues, null, null)
                                Log.i(galleryTag, "CAPTI_GALLERY_COMPLETE updated=$updated uri=$uri")
                                lastSavedUri = uri
                                lastSavedPath = null
                                result.success(uri.toString())
                            } else {
                                Log.i(galleryTag, "CAPTI_GALLERY_INSERT pre-Q Movies/Capti")
                                val moviesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
                                val captiDir = File(moviesDir, "Capti").apply { mkdirs() }
                                Log.i(galleryTag, "CAPTI_GALLERY_SOURCE captiDir=$captiDir exists=${captiDir.exists()} mkdirs=${captiDir.mkdirs()} canWrite=${captiDir.canWrite()}")
                                if (!captiDir.exists() && !captiDir.mkdirs()) {
                                    Log.e(galleryTag, "CAPTI_GALLERY_ERROR could not create $captiDir")
                                    throw IllegalStateException("Konnte Verzeichnis nicht erstellen: $captiDir")
                                }
                                var dest = File(captiDir, displayName)
                                var counter = 1
                                while (dest.exists()) {
                                    val base = displayName.removeSuffix(".mp4")
                                    dest = File(captiDir, "${base}_$counter.mp4")
                                    counter++
                                }
                                Log.i(galleryTag, "CAPTI_GALLERY_COPY pre-Q source=$sourcePath dest=${dest.absolutePath}")
                                sourceFile.copyTo(dest, overwrite = false)
                                Log.i(galleryTag, "CAPTI_GALLERY_COPY done size=${dest.length()}")
                                MediaScannerConnection.scanFile(this, arrayOf(dest.absolutePath), arrayOf("video/mp4"), null)
                                Log.i(galleryTag, "CAPTI_GALLERY_COMPLETE scanFile done ${dest.absolutePath}")
                                lastSavedUri = null
                                lastSavedPath = dest.absolutePath
                                result.success(dest.absolutePath)
                            }
                        } catch (e: Exception) {
                            Log.e(galleryTag, "CAPTI_GALLERY_ERROR ${e::class.java.simpleName}: ${e.message}", e)
                            // Pending Eintrag aufräumen
                            if (pendingUri != null) {
                                try {
                                    Log.i(galleryTag, "CAPTI_GALLERY_ERROR delete pending $pendingUri")
                                    contentResolver.delete(pendingUri!!, null, null)
                                } catch (delEx: Exception) {
                                    Log.e(galleryTag, "CAPTI_GALLERY_ERROR delete failed: ${delEx.message}", delEx)
                                }
                            }
                            result.error("SAVE_FAILED", "${e::class.java.simpleName}: ${e.message}", e.stackTraceToString())
                        }
                    }
                    "testGalleryExport" -> {
                        // Unabhängiger Test: kleine Dummy-MP4 in Cache erzeugen und via gleichen Pfad exportieren
                        Log.i(galleryTag, "CAPTI_GALLERY_START testGalleryExport")
                        try {
                            val testFile = File(cacheDir, "capti_test_dummy_${System.currentTimeMillis()}.mp4")
                            // Minimaler MP4-Header (nicht abspielbar, aber fuer MediaStore-Test reicht Kopier-Logik)
                            // Wir schreiben 2KB Dummy-Daten, um IS_PENDING-Flow zu testen
                            testFile.writeBytes(ByteArray(2048) { 0x00 })
                            Log.i(galleryTag, "CAPTI_GALLERY_SOURCE testFile=${testFile.absolutePath} size=${testFile.length()}")
                            // Wiederverwendung des gleichen Codes wie saveToGallery, aber mit testFile
                            val displayName = "Capti_TestDummy_${System.currentTimeMillis()}.mp4"
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                                val values = ContentValues().apply {
                                    put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
                                    put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                                    put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/Capti")
                                    put(MediaStore.Video.Media.IS_PENDING, 1)
                                }
                                val collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
                                val uri = contentResolver.insert(collection, values) ?: throw IllegalStateException("insert null")
                                Log.i(galleryTag, "CAPTI_GALLERY_URI test $uri")
                                contentResolver.openOutputStream(uri)?.use { out ->
                                    testFile.inputStream().use { inp -> inp.copyTo(out) }
                                } ?: throw IllegalStateException("openOutputStream null")
                                val upd = ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }
                                contentResolver.update(uri, upd, null, null)
                                Log.i(galleryTag, "CAPTI_GALLERY_COMPLETE test $uri")
                                result.success(uri.toString())
                            } else {
                                val moviesDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES)
                                val captiDir = File(moviesDir, "Capti").apply { mkdirs() }
                                val dest = File(captiDir, displayName)
                                testFile.copyTo(dest, overwrite = true)
                                MediaScannerConnection.scanFile(this, arrayOf(dest.absolutePath), arrayOf("video/mp4"), null)
                                Log.i(galleryTag, "CAPTI_GALLERY_COMPLETE test pre-Q ${dest.absolutePath}")
                                result.success(dest.absolutePath)
                            }
                        } catch (e: Exception) {
                            Log.e(galleryTag, "CAPTI_GALLERY_ERROR testGalleryExport ${e::class.java.simpleName}: ${e.message}", e)
                            result.error("TEST_FAILED", "${e::class.java.simpleName}: ${e.message}", e.stackTraceToString())
                        }
                    }
                    "openGallery" -> {
                        try {
                            val uri = lastSavedUri
                            if (uri != null) {
                                val view = Intent(Intent.ACTION_VIEW).apply {
                                    setDataAndType(uri, "video/*")
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                startActivity(Intent.createChooser(view, "Video öffnen"))
                            } else if (lastSavedPath != null) {
                                val f = File(lastSavedPath!!)
                                val fileUri = Uri.fromFile(f)
                                val view = Intent(Intent.ACTION_VIEW).apply {
                                    setDataAndType(fileUri, "video/*")
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                startActivity(Intent.createChooser(view, "Video öffnen"))
                            } else {
                                val intent = Intent(Intent.ACTION_VIEW).apply {
                                    setDataAndType(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, "video/*")
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                try {
                                    startActivity(intent)
                                } catch (_: Exception) {
                                    val fallback = Intent(Intent.ACTION_VIEW).apply {
                                        type = "video/*"
                                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    }
                                    startActivity(Intent.createChooser(fallback, "Galerie öffnen"))
                                }
                            }
                            result.success(true)
                        } catch (e: Exception) {
                            Log.e(galleryTag, "CAPTI_GALLERY_ERROR openGallery ${e::class.java.simpleName}: ${e.message}", e)
                            result.error("OPEN_FAILED", e.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun queryDisplayName(uri: Uri): String? {
        return try {
            contentResolver.query(
                uri,
                arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),
                null, null, null
            )?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        } catch (_: Exception) {
            null
        }
    }
}
