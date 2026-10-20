#!/usr/bin/env python3
"""Run genuine tokenizer, generation, cancellation and cleanup tests on an emulator."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


def run(*args, capture=False, timeout=300):
    result = subprocess.run([str(item) for item in args], check=False, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout or "Command failed: " + " ".join(str(item) for item in args))
    return result.stdout if capture else None


def newest(paths):
    return max(paths, key=lambda item: tuple(int(part) for part in re.findall(r"\d+", str(item))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--ort-aar", type=Path, required=True)
    parser.add_argument("--aar", type=Path, default=Path(__file__).resolve().parent / "build/outputs/aar/onnxruntime-genai.aar")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.serial.startswith("emulator-"):
        raise ValueError("This verification script only accepts Android emulator serials")
    adb = args.sdk / "platform-tools/adb"
    if run(adb, "-s", args.serial, "shell", "getprop", "ro.kernel.qemu", capture=True).strip() != "1":
        raise ValueError("The selected target is not an Android emulator")
    abi = run(adb, "-s", args.serial, "shell", "getprop", "ro.product.cpu.abi", capture=True).strip()
    if abi not in ("arm64-v8a", "x86_64"):
        raise ValueError("Unsupported emulator ABI")
    manifest_path = args.model / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    variant = manifest["modelId"]
    if variant not in ("lite", "advanced"):
        raise ValueError("Unexpected model variant")
    for item in manifest["files"]:
        path = args.model / item["path"]
        if path.stat().st_size != item["size"]:
            raise ValueError(f"Incorrect size: {path}")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != item["sha256"]:
            raise ValueError(f"Incorrect checksum: {path}")
    work = args.output.parent / ("android-smoke-" + variant)
    work.mkdir(parents=True, exist_ok=True)
    runtime = work / "runtime"
    with zipfile.ZipFile(args.aar) as package:
        package.extractall(runtime)
    with zipfile.ZipFile(args.ort_aar) as package:
        ort_library = work / "libonnxruntime.so"
        ort_library.write_bytes(package.read(f"jni/{abi}/libonnxruntime.so"))
    android_jar = newest(args.sdk.glob("platforms/*/android.jar"))
    d8 = newest(args.sdk.glob("build-tools/*/d8"))
    javac = Path(os.environ["JAVA_HOME"]) / "bin/javac" if "JAVA_HOME" in os.environ else "javac"
    classes = work / "classes"
    classes.mkdir(exist_ok=True)
    run(javac, "--release", "8", "-cp", str(android_jar) + os.pathsep + str(runtime / "classes.jar"),
        "-d", classes, Path(__file__).resolve().parent / "tests/AndroidRuntimeSmoke.java")
    harness = work / "harness.jar"
    with zipfile.ZipFile(harness, "w", zipfile.ZIP_DEFLATED) as package:
        for path in classes.rglob("*.class"):
            package.write(path, path.relative_to(classes))
    dex = work / "dex"
    dex.mkdir(exist_ok=True)
    run(d8, "--min-api", "24", "--lib", android_jar, "--output", dex, runtime / "classes.jar", harness)
    remote = "/data/local/tmp/onnxruntime-genai-verification"
    run(adb, "-s", args.serial, "shell", "mkdir", "-p", remote + "/lib")
    run(adb, "-s", args.serial, "push", dex / "classes.dex", remote + "/classes.dex")
    for path in (runtime / f"jni/{abi}").glob("*.so"):
        run(adb, "-s", args.serial, "push", path, remote + "/lib/" + path.name)
    run(adb, "-s", args.serial, "push", ort_library, remote + "/lib/libonnxruntime.so")
    run(adb, "-s", args.serial, "shell", "rm", "-rf", remote + "/" + variant)
    run(adb, "-s", args.serial, "push", args.model, remote + "/" + variant)
    output = run(adb, "-s", args.serial, "shell", "env", "CLASSPATH=" + remote + "/classes.dex",
                 "LD_LIBRARY_PATH=" + remote + "/lib", "app_process", "/system/bin",
                 "ai.onnxruntime.genai.tests.AndroidRuntimeSmoke", remote + "/" + variant,
                 remote + "/lib", capture=True)
    marker = "IMAGETOOLBOX_ASSISTANT_SMOKE="
    line = next(item for item in output.splitlines() if item.startswith(marker))
    report = json.loads(line[len(marker):])
    report.update({
        "modelId": variant, "serial": args.serial,
        "pageSize": int(run(adb, "-s", args.serial, "shell", "getconf", "PAGE_SIZE", capture=True)),
        "modelManifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "runtimeAarSha256": hashlib.sha256(args.aar.read_bytes()).hexdigest(),
    })
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
