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

extern "C" JNIEXPORT void JNICALL
Java_ai_onnxruntime_genai_GeneratorParams_setGuidanceNative(
    JNIEnv* env, jobject, jlong handle, jstring type, jstring data, jboolean fast_forward) {
    Helpers::CString grammar_type{env, type};
    Helpers::CString grammar_data{env, data};
    Helpers::ThrowIfError(env, OgaGeneratorParamsSetGuidance(
        reinterpret_cast<OgaGeneratorParams*>(handle), grammar_type, grammar_data,
        fast_forward == JNI_TRUE));
}
