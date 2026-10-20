# ONNX Runtime GenAI for Android

Source build and JitPack publication of ONNX Runtime GenAI **0.17.0**, with
telemetry disabled, Android 16-KB ELF alignment, and native generation
cancellation exposed to Java/Kotlin. No compiled AAR, native libraries, or model
weights are stored in this repository.

The implementation uses Microsoft's MIT-licensed GenAI source at commit
`1d67be30e5b1ed0c264f6f41c598f85157e8288b`. The integration code is Apache-2.0.
`UPSTREAM-LICENSE` and `UPSTREAM-NOTICES` retain upstream attribution.

## Dependency

After publishing this repository and the `0.17.0-it1` tag:

```kotlin
repositories {
    maven("https://jitpack.io")
}

dependencies {
    implementation("com.github.T8RIN:OnnxRuntimeGenAIAndroid:0.17.0-it1")
}
```

The POM declares `com.microsoft.onnxruntime:onnxruntime-android:1.31.0`.
Gradle resolves the existing ORT dependency once; the generated GenAI AAR does
not contain another ORT binary. Both `arm64-v8a` and `x86_64` are included,
with minimum Android API 24. Applications targeting 32-bit ARM should keep
their non-LLM features available and check the running process ABI before
initializing GenAI.

The Java package remains `ai.onnxruntime.genai`. Initialize the existing ORT
environment before opening a GenAI model:

```kotlin
OrtEnvironment.getEnvironment().setTelemetry(false)
GenAI.setTelemetry(false)

Model(modelDirectory).use { model ->
    Tokenizer(model).use { tokenizer ->
        tokenizer.encode(formattedPrompt).use { tokens ->
            GeneratorParams(model).use { parameters ->
                parameters.setSearchOption("max_length", 4096.0)
                parameters.setSearchOption("do_sample", false)
                Generator(model, parameters).use { generator ->
                    tokenizer.createStream().use { stream ->
                        generator.appendTokenSequences(tokens)
                        var emitted = tokens.getSequence(0).size
                        while (!generator.isDone) {
                            generator.generateNextToken()
                            val sequence = generator.getSequence(0)
                            for (index in emitted until sequence.size) {
                                val token = sequence[index]
                                if (token !in tokenizer.eosTokenIds) {
                                    onText(stream.decode(token))
                                }
                            }
                            emitted = sequence.size
                        }
                    }
                }
            }
        }
    }
}
```

Run model loading and generation on a worker thread. Supply a prompt formatted
for the selected model and an appropriate context/token limit. Emit sequence
changes: on an EOS step no new token may be appended, so repeatedly reading
`getLastTokenInSequence()` can duplicate the preceding fragment. Models are
ordinary GenAI directories containing `genai_config.json`, ONNX weights,
external tensor data where required, and tokenizer files.

## Native cancellation

This build adds `Generator.setRuntimeOption(String key, String value)` to the
upstream Java/JNI binding. A cancellation thread can call:

```kotlin
generator.setRuntimeOption("terminate_session", "1")
```

This calls the existing `OgaGenerator_SetRuntimeOption` C API and interrupts
an in-flight ORT run. The worker can receive a native generation exception
after cancellation; distinguish this using your own cancellation state. Wait
for the worker to finish before closing the generator. Synchronize the
cancellation handle with disposal, close tokenizer streams/sequences/parameters,
and then close the tokenizer and model. Never close a generator concurrently
with a native run.

## Build and publish

Use JDK 21 or later, Python 3.9 or later, Git, Android NDK **28.2.13676358**,
and Android SDK CMake **3.31.6**. The SDK CMake distribution supplies Ninja.
The Gradle wrapper is pinned to 9.8.1. JitPack installs the two pinned Android
SDK packages through `jitpack.yml` and runs `publishToMavenLocal`.

```sh
export ANDROID_HOME=/path/to/Android/sdk
./gradlew assemble
./gradlew publishToMavenLocal
```

Override SDK paths with `-PandroidSdkPath`, `-PandroidNdkPath`, or `-PcmakePath`.
`-PnativeJobs=2` limits build concurrency. `VERSION` selects the publication
version, as provided by JitPack. For an isolated local publication:

```sh
./gradlew publishRuntimePublicationToVerificationRepository \
  -PverificationRepository=/tmp/onnx-genai-verification-maven
```

`prepare_runtime.py` downloads pinned upstream sources and ORT headers,
compiles GenAI without Python/Java Gradle builds or telemetry, compiles Java
bindings with `javac --release 8`, builds JNI, and verifies every native ELF
LOAD segment for 16-KB alignment. It then packages:

- `build/outputs/aar/onnxruntime-genai.aar`
- `build/outputs/aar/build.json`, with source/toolchain identity and actual SHA-256

The source and ORT downloads are checked against fixed SHA-256 values:

| Archive | SHA-256 |
| --- | --- |
| GenAI commit source archive | `b5d54161336ee4fb3050574949b2d6980d32864a0e727601980f3b7d9d232324` |
| ONNX Runtime Android 1.31.0 | `72683787a80d0608a3121b967d8e1239aef48286826661c953211626690540a7` |

The upstream dependency commits and archive hashes remain fixed by GenAI's
dependency manifest. Build outputs and downloaded sources stay under `build/`.
Do not commit those outputs or local Maven publications.

The upstream Android AAR includes a telemetry initializer and a
4-KB-aligned `libmat.so`. This source build excludes both. It also disables
GenAI 0.17.0's unused experimental model-package wrappers when compiling with
ORT 1.31 headers, where that optional API has been stabilized. Ordinary GenAI
model-directory loading remains supported.

## Android verification

`verify_android.py` validates a prepared model package manifest and SHA-256
values, compiles the included Java smoke harness with D8, and runs it through
`app_process` on an Android emulator. It refuses physical-device serials.
Model weights are copied to the emulator's temporary directory, outside any
APK. Verification requires Python 3.11 or later and the Android SDK.

```sh
python3 verify_android.py \
  --serial emulator-5554 \
  --sdk "$ANDROID_HOME" \
  --model /path/to/lite-or-advanced-package \
  --ort-aar /path/to/onnxruntime-android-1.31.0.aar \
  --output /tmp/android-generation-report.json
```

The harness checks Russian tokenizer round-trip, real Russian/English
generation, equality of streaming text and full sequence decoding, native
cancellation, generation after cancellation, and memory
before/after explicitly closing resources. The report records the exact
model manifest and runtime AAR SHA-256 values.

Current verified scope:

| Check | Status |
| --- | --- |
| ARM64 and x86_64 native compilation against ORT 1.31.0 | Passed |
| Both ABIs, every GenAI ELF LOAD segment aligned to 16 KB | Passed |
| Gradle AAR and sources publication to isolated Maven repository | Passed |
| ARM64 Android API 36, 4-KB pages, Qwen3-0.6B INT4 | Russian/English, tokenizer, streaming equality, cancellation and cleanup passed |
| ARM64 Android API 36, 4-KB pages, Qwen3-1.7B INT4 | Russian/English, tokenizer, streaming equality, cancellation and cleanup passed |
| x86_64 Android inference | Not yet tested |
| Android running with 16-KB pages | Not yet tested |
| JitPack remote build | Requires repository/tag publication |

For ARM64 Android emulators, the tested model configuration includes
`"mlas.disable_kleidiai": "1"` under `model.decoder.session_options`.
Without it, ORT 1.31 can select an SME instruction unsupported by the emulator
and fail with SIGILL during model initialization. The prepared ImageToolbox
model packages include this configuration.

PSS can remain above its initial value after close because the platform and
ORT retain allocator/library pages. The report gives measured values; it
does not assert that process memory returns to zero.

Upstream references: [GenAI source](https://github.com/microsoft/onnxruntime-genai),
[Android build instructions](https://github.com/microsoft/onnxruntime-genai/blob/main/src/java/AndroidBuild.md),
[Java API](https://onnxruntime.ai/docs/genai/api/java.html).
