plugins {
    base
    `maven-publish`
}

group = "com.github.T8RIN"
version = providers.environmentVariable("VERSION").getOrElse("0.17.0-it1")

val sdkPath = providers.gradleProperty("androidSdkPath")
    .orElse(providers.environmentVariable("ANDROID_HOME"))
    .orElse(providers.environmentVariable("ANDROID_SDK_ROOT"))
val ndkPath = providers.gradleProperty("androidNdkPath")
    .orElse(sdkPath.map { "$it/ndk/28.2.13676358" })
val cmakePath = providers.gradleProperty("cmakePath")
    .orElse(sdkPath.map { "$it/cmake/3.31.6/bin/cmake" })
val runtimeWork = providers.gradleProperty("runtimeWorkDirectory")
    .getOrElse(layout.buildDirectory.dir("native").get().asFile.absolutePath)
val outputDirectory = layout.buildDirectory.dir("outputs/aar")
val runtimeAar = outputDirectory.map { it.file("onnxruntime-genai.aar") }

val prepareRuntime by tasks.registering(Exec::class) {
    inputs.files("prepare_runtime.py", "runtime_options.cpp")
    outputs.dir(outputDirectory)
    doFirst {
        check(ndkPath.isPresent && cmakePath.isPresent) {
            "Set ANDROID_HOME or -PandroidSdkPath to an Android SDK with NDK 28.2.13676358 and CMake 3.31.6"
        }
        commandLine(
            "python3", "prepare_runtime.py", "--ndk", ndkPath.get(),
            "--cmake", cmakePath.get(), "--work", runtimeWork,
            "--output", outputDirectory.get().asFile.absolutePath,
            "--jobs", providers.gradleProperty("nativeJobs").getOrElse("4")
        )
    }
}

val sourcesJar by tasks.registering(Jar::class) {
    dependsOn(prepareRuntime)
    archiveClassifier.set("sources")
    from("$runtimeWork/source/src/java/src/main/java")
    from("runtime_options.cpp", "prepare_runtime.py", "UPSTREAM-LICENSE", "UPSTREAM-NOTICES")
}

tasks.assemble {
    dependsOn(prepareRuntime, sourcesJar)
}

publishing {
    publications {
        create<MavenPublication>("runtime") {
            artifactId = rootProject.name
            artifact(runtimeAar) {
                builtBy(prepareRuntime)
                extension = "aar"
            }
            artifact(sourcesJar)
            pom {
                name.set("ONNX Runtime GenAI Android")
                description.set("GenAI 0.17.0 for Android, without telemetry, with native cancellation and 16-KB page support")
                url.set("https://github.com/T8RIN/OnnxRuntimeGenAIAndroid")
                licenses {
                    license {
                        name.set("Apache License, Version 2.0 (integration)")
                        url.set("https://www.apache.org/licenses/LICENSE-2.0")
                    }
                    license {
                        name.set("MIT License (ONNX Runtime GenAI)")
                        url.set("https://opensource.org/license/mit")
                    }
                }
                scm {
                    url.set("https://github.com/T8RIN/OnnxRuntimeGenAIAndroid")
                }
                withXml {
                    asNode().appendNode("dependencies").appendNode("dependency").apply {
                        appendNode("groupId", "com.microsoft.onnxruntime")
                        appendNode("artifactId", "onnxruntime-android")
                        appendNode("version", "1.31.0")
                        appendNode("scope", "compile")
                    }
                }
            }
        }
    }
    repositories {
        maven {
            name = "verification"
            url = uri(providers.gradleProperty("verificationRepository")
                .getOrElse(layout.buildDirectory.dir("repository").get().asFile.absolutePath))
        }
    }
}
