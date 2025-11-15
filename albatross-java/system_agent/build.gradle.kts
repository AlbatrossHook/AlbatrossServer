plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "qing.albatross.android.system_server"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "qing.albatross.android.system_server"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        versionCode = libs.versions.versionCode.get().toInt()
        versionName = libs.versions.versionName.get()
        ndk {
            abiFilters.addAll(arrayOf("arm64-v8a", "armeabi-v7a", "x86", "x86_64"))
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.valueOf(libs.versions.javaVersion.get())
        targetCompatibility = JavaVersion.valueOf(libs.versions.javaVersion.get())
    }
//    kotlinOptions {
//        jvmTarget = "1.8"
//    }
    buildFeatures {
        buildConfig = true;
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    val useSourceModules = gradle.extra.has("albatrossSourceAvailable") &&
            gradle.extra["albatrossSourceAvailable"] as? Boolean == true

    if (useSourceModules) {
        implementation(project(":annotation"))
        implementation(project(":core"))
        implementation(project(":server"))
    } else {
        implementation("qing.albatross:annotation-release:1.0@aar")
        implementation("qing.albatross:core-release:1.0@aar")
        implementation("qing.albatross:server-release:1.0@aar")
        logger.lifecycle("[$name] Using Albatross libraries as AAR files.")
    }
    implementation(project(":agent_lib_common"))
}