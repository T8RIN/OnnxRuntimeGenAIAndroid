# ONNX Runtime GenAI Android

Android source build of ONNX Runtime GenAI 0.17.0 with JSON Schema guidance,
native cancellation, and telemetry disabled. Supports `arm64-v8a` and `x86_64`,
Android API 24+, and 16-KB pages. The AAR depends on ONNX Runtime Android 1.31.0;
it does not bundle another ORT library or model weights.

```kotlin
repositories { maven("https://jitpack.io") }

dependencies {
    implementation("com.github.T8RIN:OnnxRuntimeGenAIAndroid:0.17.0")
}
```

Check that the application runs in a supported 64-bit process before loading
GenAI. Initialize `OrtEnvironment.getEnvironment().setTelemetry(false)` and
`GenAI.setTelemetry(false)` before opening a model directory.

The upstream `ai.onnxruntime.genai` API is unchanged except for two additions:

```kotlin
// Before constructing Generator; accepts json_schema, regex, or lark_grammar.
parameters.setGuidance("json_schema", schema, true)

// From a cancellation thread; interrupts an in-flight native run.
generator.setRuntimeOption("terminate_session", "1")
```

With fast forwarding enabled, one generation step can append multiple tokens.
Emit all new tokens from `generator.getSequence(0)` after each step. Reading
only the last token can lose tokens or repeat text at EOS. Run inference on a
worker thread. On cancellation, allow the worker to stop before closing the
generator, parameters, tokenizer stream, sequences, tokenizer, and model.

Build with JDK 21+, Python 3.9+, Android NDK 28.2.13676358, SDK CMake 3.31.6,
and Rust 1.94.1:

```sh
export ANDROID_HOME=/path/to/Android/sdk
rustup toolchain install 1.94.1 --profile minimal
rustup target add --toolchain 1.94.1 aarch64-linux-android x86_64-linux-android
./gradlew assemble
./gradlew publishToMavenLocal
```

`jitpack.yml` installs these pinned tools and publishes the source tag using
`VERSION`. Build files, downloads, and native binaries stay under `build/`.
`build/outputs/aar/build.json` records source identity and the generated AAR hash.

`prepare_runtime.py` verifies the pinned GenAI source and ORT archive SHA-256,
builds both ABIs, and checks every ELF LOAD segment for 16-KB alignment. It
excludes the upstream Android telemetry initializer and `libmat.so`. The unused
experimental model-package wrappers are disabled for ORT 1.31 compatibility;
ordinary GenAI model directories are supported.

The source uses GenAI commit `1d67be30e5b1ed0c264f6f41c598f85157e8288b`,
llguidance commit `94fa39128ef184ffeda33845f6d333f332a34b4d`, and
Corrosion commit `b1fab721655c5c4b1b08a083d3cd29f163af75d0`.
`guidance-Cargo.lock` pins Rust dependencies; Cargo builds with `--locked`.

The integration is Apache-2.0; GenAI is MIT licensed. Upstream notices are
retained in this repository. The build collects license texts for all reachable
Rust dependencies and includes GenAI, integration, and Rust notices in the AAR
under `assets/onnxruntime-genai/` and in the sources artifact.
