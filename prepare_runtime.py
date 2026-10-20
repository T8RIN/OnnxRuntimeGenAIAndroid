#!/usr/bin/env python3
"""Build the Android GenAI artifact without telemetry or a second copy of ORT."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import urllib.request
import zipfile


VERSION = "0.17.0-it1"
COMMIT = "1d67be30e5b1ed0c264f6f41c598f85157e8288b"
ORT_VERSION = "1.31.0"
GENAI_SHA256 = "b5d54161336ee4fb3050574949b2d6980d32864a0e727601980f3b7d9d232324"
ORT_SHA256 = "72683787a80d0608a3121b967d8e1239aef48286826661c953211626690540a7"
ABIS = ("arm64-v8a", "x86_64")


def run(*args, cwd=None):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def fetch(url, path, expected_sha256):
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".download")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"Source archive checksum mismatch: {path}")


def verify_alignment(path):
    data = path.read_bytes()
    if data[:5] != b"\x7fELF\x02":
        raise ValueError(f"Expected a 64-bit ELF library: {path}")
    endian = "<" if data[5] == 1 else ">"
    offset = struct.unpack_from(endian + "Q", data, 32)[0]
    size, count = struct.unpack_from(endian + "HH", data, 54)
    for index in range(count):
        entry = struct.unpack_from(endian + "IIQQQQQQ", data, offset + index * size)
        if entry[0] == 1:
            if entry[-1] < 16384 or entry[2] % 16384 != entry[3] % 16384:
                raise ValueError(f"Library is not aligned for 16-KB pages: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--cmake", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("/tmp/imagetoolbox-assistant-runtime"))
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "build/outputs/aar")
    args = parser.parse_args()
    ndk_properties = (args.ndk / "source.properties").read_text()
    if "Pkg.Revision = 28.2.13676358" not in ndk_properties:
        raise ValueError("This build requires Android NDK 28.2.13676358")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source"
    archive = work / "genai.tar.gz"
    fetch(f"https://api.github.com/repos/microsoft/onnxruntime-genai/tarball/{COMMIT}", archive, GENAI_SHA256)
    if not source.is_dir():
        source.mkdir()
        with tarfile.open(archive) as package:
            for member in package:
                parts = Path(member.name).parts[1:]
                if parts:
                    output = source.joinpath(*parts)
                    if source.resolve() not in output.resolve().parents:
                        raise ValueError("Unsafe source archive path")
                    if member.isdir():
                        output.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with package.extractfile(member) as data, output.open("wb") as target:
                            shutil.copyfileobj(data, target)
                        output.chmod(member.mode & 0o777)
                    else:
                        raise ValueError("Links are not accepted in the source archive")

    # ORT 1.31 moved the optional model-package API out of the experimental table.
    # ImageToolbox loads ordinary GenAI directories and does not use that API.
    api_header = source / "src/models/onnxruntime_api.h"
    original_api = api_header.read_text()
    patched_api = original_api.replace(
        "ORT_API_VERSION >= 28 && ORT_GENAI_HAS_EXPERIMENTAL_C_API",
        "ORT_API_VERSION >= 28 && ORT_API_VERSION < 31 && ORT_GENAI_HAS_EXPERIMENTAL_C_API",
    )
    if patched_api != original_api:
        api_header.write_text(patched_api)

    ort_archive = work / f"onnxruntime-android-{ORT_VERSION}.aar"
    fetch(
        "https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/"
        f"onnxruntime-android/{ORT_VERSION}/onnxruntime-android-{ORT_VERSION}.aar",
        ort_archive, ORT_SHA256,
    )
    ort = work / "ort"
    if not ort.is_dir():
        with zipfile.ZipFile(ort_archive) as package:
            package.extractall(ort)

    java_home = os.environ.get("JAVA_HOME")
    javac = Path(java_home) / "bin/javac" if java_home else Path(shutil.which("javac"))
    headers = work / "headers"
    classes = work / "classes"
    headers.mkdir(exist_ok=True)
    classes.mkdir(exist_ok=True)
    generator_java = source / "src/java/src/main/java/ai/onnxruntime/genai/Generator.java"
    java = generator_java.read_text()
    if "public void setRuntimeOption(" not in java:
        java = java.replace("  /** Closes the Generator and releases any associated resources. */", """  /** Update a native runtime option, including terminate_session for cancelling a run. */
  public void setRuntimeOption(String key, String value) throws GenAIException {
    if (nativeHandle == 0) throw new IllegalStateException("Generator is closed");
    setRuntimeOptionNative(nativeHandle, key, value);
  }

  private native void setRuntimeOptionNative(long handle, String key, String value) throws GenAIException;

  /** Closes the Generator and releases any associated resources. */""")
        generator_java.write_text(java)
    java_sources = sorted((source / "src/java/src/main/java").rglob("*.java"))
    run(javac, "--release", "8", "-h", headers, "-d", classes, *java_sources)
    classes_jar = work / "classes.jar"
    with zipfile.ZipFile(classes_jar, "w", zipfile.ZIP_DEFLATED) as package:
        for path in sorted(classes.rglob("*.class")):
            package.write(path, path.relative_to(classes))

    native_project = work / "jni"
    native_project.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__).resolve().parent / "runtime_options.cpp", native_project / "runtime_options.cpp")
    (native_project / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.26)
project(ImageToolboxGenAI LANGUAGES CXX)
file(GLOB JNI_SOURCES "${GENAI_SOURCE}/src/java/src/main/native/*.cpp")
add_library(onnxruntime-genai SHARED IMPORTED)
set_target_properties(onnxruntime-genai PROPERTIES IMPORTED_LOCATION "${GENAI_LIBRARY}")
add_library(onnxruntime-genai-jni SHARED ${JNI_SOURCES} runtime_options.cpp)
target_compile_features(onnxruntime-genai-jni PRIVATE cxx_std_17)
target_include_directories(onnxruntime-genai-jni PRIVATE "${GENAI_SOURCE}/src" "${GENAI_SOURCE}/src/java/src/main/native" "${JAVA_HEADERS}")
target_link_options(onnxruntime-genai-jni PRIVATE "-Wl,-z,max-page-size=16384")
target_link_libraries(onnxruntime-genai-jni PRIVATE onnxruntime-genai)
''')
    jni = work / "package/jni"
    for abi in ABIS:
        build = work / f"build-{abi}"
        common = [
            f"-DCMAKE_TOOLCHAIN_FILE={args.ndk / 'build/cmake/android.toolchain.cmake'}",
            f"-DANDROID_ABI={abi}", "-DANDROID_PLATFORM=android-24",
            f"-DCMAKE_MAKE_PROGRAM={args.cmake.parent / 'ninja'}",
            "-DCMAKE_BUILD_TYPE=Release", "-DANDROID_STL=c++_static",
            "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384",
        ]
        run(args.cmake, "-S", source, "-B", build, "-G", "Ninja", *common,
            f"-DORT_HOME={ort}", "-DENABLE_TELEMETRY=OFF", "-DENABLE_PYTHON=OFF",
            "-DENABLE_JAVA=OFF", "-DENABLE_TESTS=OFF", "-DUSE_CUDA=OFF",
            "-DENABLE_MODEL_BENCHMARK=OFF", "-DUSE_GUIDANCE=OFF")
        run(args.cmake, "--build", build, "--target", "onnxruntime-genai", "-j", args.jobs)
        library = next(build.rglob("libonnxruntime-genai.so"))
        bridge_build = work / f"jni-{abi}"
        run(args.cmake, "-S", native_project, "-B", bridge_build, "-G", "Ninja", *common,
            f"-DGENAI_SOURCE={source}", f"-DJAVA_HEADERS={headers}", f"-DGENAI_LIBRARY={library}")
        run(args.cmake, "--build", bridge_build, "-j", args.jobs)
        target = jni / abi
        target.mkdir(parents=True, exist_ok=True)
        for path in (library, bridge_build / "libonnxruntime-genai-jni.so"):
            verify_alignment(path)
            shutil.copy2(path, target / path.name)

    artifact = args.output.resolve()
    artifact.mkdir(parents=True, exist_ok=True)
    name = "onnxruntime-genai"
    with zipfile.ZipFile(artifact / f"{name}.aar", "w", zipfile.ZIP_DEFLATED) as package:
        package.write(classes_jar, "classes.jar")
        package.writestr("AndroidManifest.xml", '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ai.onnxruntime.genai"><uses-sdk android:minSdkVersion="24" /></manifest>\n')
        package.writestr("proguard.txt", "-keep class ai.onnxruntime.genai.** { *; }\n")
        package.write(source / "LICENSE", "META-INF/LICENSE-GenAI")
        package.write(source / "ThirdPartyNotices.txt", "META-INF/NOTICE-GenAI")
        for path in sorted(jni.rglob("*.so")):
            package.write(path, Path("jni") / path.relative_to(jni))
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifact.iterdir() if p.suffix == ".aar"}
    (artifact / "build.json").write_text(json.dumps({
        "version": VERSION, "genaiCommit": COMMIT, "onnxruntime": ORT_VERSION,
        "abis": ABIS, "minSdk": 24, "telemetry": False, "pageSize": 16384,
        "ndk": (args.ndk / "source.properties").read_text(), "sha256": checksums,
    }, indent=2) + "\n")
    print(artifact)


if __name__ == "__main__":
    main()
