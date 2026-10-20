// Copyright (c) 2026 T8RIN. Licensed under the Apache License, Version 2.0.
#include <jni.h>
#include "ort_genai_c.h"
#include "utils.h"

extern "C" JNIEXPORT void JNICALL
Java_ai_onnxruntime_genai_Generator_setRuntimeOptionNative(
    JNIEnv* env, jobject, jlong handle, jstring key, jstring value) {
    Helpers::CString name{env, key};
    Helpers::CString option{env, value};
    Helpers::ThrowIfError(env, OgaGenerator_SetRuntimeOption(
        reinterpret_cast<OgaGenerator*>(handle), name, option));
}
