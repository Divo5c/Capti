import java.io.File

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Native whisper.cpp-Bridge: wird nur mitgebaut, wenn die Quellen vorhanden
// sind (mobile/tools/fetch_native.sh). Ohne Quellen baut die App ohne
// Engine und zeigt zur Laufzeit den expliziten "nicht verfügbar"-Zustand.
val whisperSources = File(rootDir.parentFile, "native/third_party/whisper.cpp")
// Statische FFmpeg/libass-Archive (tools/build_media_android.sh). Fehlen sie
// für eine ABI, wird media_bridge für diese ABI schlicht nicht gebaut.
val mediaPrebuiltRoot = File(rootDir.parentFile, "native/media_prebuilt")

android {
    namespace = "com.capti.capti_mobile"
    // file_picker benötigt compileSdk >= 36
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    if (whisperSources.exists()) {
        externalNativeBuild {
            cmake {
                path = file("../../native/CMakeLists.txt")
                version = "3.22.1"
                // WSL/DrvFs: CMake-Staging (.cxx) braucht ein Dateisystem
                // mit chmod-Unterstützung -> über den Build-Symlink auf
                // Linux-ext4 auslagern.
                buildStagingDirectory =
                    file("../../build/cxx-staging")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.capti.capti_mobile"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        if (whisperSources.exists()) {
            externalNativeBuild {
                cmake {
                    arguments += listOf("-DCAPTI_WITH_WHISPER=ON")
                    if (mediaPrebuiltRoot.isDirectory) {
                        arguments += listOf(
                            "-DMEDIA_PREBUILT_ROOT=${mediaPrebuiltRoot.absolutePath}"
                        )
                    }
                    abiFilters += listOf("arm64-v8a", "x86_64")
                }
            }
        }
    }

    buildTypes {
        release {
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
