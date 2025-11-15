plugins {
    id("com.android.application")
}

android {
    namespace = "qing.albatross.injector"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "qing.albatross.injector"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        versionCode = libs.versions.versionCode.get().toInt()
        versionName = libs.versions.versionName.get()

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
    compileOnly(project(":app_agent_lib"))
    compileOnly(project(":agent_lib_common"))
}