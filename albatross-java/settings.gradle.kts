pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        val aarDirectory = File(rootDir.parentFile, "resource/jar")
        if (aarDirectory.exists() && aarDirectory.isDirectory) {
            flatDir {
                dirs(aarDirectory)
            }
        } else {
            logger.warn("AAR directory not found or is not a directory: ${aarDirectory.absolutePath}.")
        }
    }
}


rootProject.name = "AlbatrossAgent"


fun getLocalProperty(propertyName: String): String? {
    val localProperties = java.util.Properties()
    val localPropertiesFile = File(rootDir, "local.properties")
    if (localPropertiesFile.exists()) {
        localPropertiesFile.inputStream().use { localProperties.load(it) }
    }
    return localProperties.getProperty(propertyName)
}


val albatrossDirPath = getLocalProperty("project.albatross.dir")
var areAlbatrossModulesIncluded = false // 标记模块是否被包含

if (!albatrossDirPath.isNullOrBlank()) {
    val albatrossDir = File(albatrossDirPath)

    val annotationDir = File(albatrossDir, "annotation")
    val coreDir = File(albatrossDir, "core")
    val serverDir = File(albatrossDir, "server")

    if (albatrossDir.exists() && albatrossDir.isDirectory &&
        annotationDir.exists() && annotationDir.isDirectory &&
        coreDir.exists() && coreDir.isDirectory &&
        serverDir.exists() && serverDir.isDirectory) {

        include(":annotation", ":core", ":server")

        project(":annotation").projectDir = annotationDir
        project(":core").projectDir = coreDir
        project(":server").projectDir = serverDir

        areAlbatrossModulesIncluded = true // 更新标记
        logger.lifecycle("Albatross modules included from source: $albatrossDirPath")
    } else {
        logger.warn("The path specified by 'project.albatross.dir' ($albatrossDirPath) or its required subdirectories (annotation, core, server) are not valid. Will attempt to use AAR dependencies.")
    }
} else {
    logger.lifecycle("Property 'project.albatross.dir' not found or empty. Will attempt to use AAR dependencies.")
}

gradle.extra.set("albatrossSourceAvailable",areAlbatrossModulesIncluded)
include(":app_agent")
include(":agent_lib_common")
include(":app_agent_lib")
include(":plugin_demo")
include(":system_agent")







