plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "qing.albatross.app.agent"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        consumerProguardFiles("consumer-rules.pro")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
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
}

dependencies {
    val useSourceModules = gradle.extra.has("albatrossSourceAvailable") &&
            gradle.extra["albatrossSourceAvailable"] as? Boolean == true

    if (useSourceModules) {
        compileOnly(project(":annotation"))
        compileOnly(project(":core"))
        compileOnly(project(":server"))
    } else {
        compileOnly("qing.albatross:annotation-release:1.0@aar")
        compileOnly("qing.albatross:core-release:1.0@aar")
        compileOnly("qing.albatross:server-release:1.0@aar")
        logger.lifecycle("[$name] Using Albatross libraries as AAR files.")
    }
    compileOnly(project(":agent_lib_common"))
}