plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "qing.albatross.agent.common"
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
        implementation(project(":annotation"))
        implementation(project(":core"))
        implementation(project(":server"))
    } else {
        implementation("qing.albatross:annotation-release:1.0@aar")
        implementation("qing.albatross:core-release:1.0@aar")
        implementation("qing.albatross:server-release:1.0@aar")
        logger.lifecycle("[$name] Using Albatross libraries as AAR files.")
    }
}