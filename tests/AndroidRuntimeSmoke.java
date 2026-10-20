/*
 * ImageToolbox is an image editor for android
 * Copyright (c) 2026 T8RIN (Malik Mukhametzyanov)
 * Licensed under the Apache License, Version 2.0
 */
package ai.onnxruntime.genai.tests;

import ai.onnxruntime.genai.GenAI;
import ai.onnxruntime.genai.Generator;
import ai.onnxruntime.genai.GeneratorParams;
import ai.onnxruntime.genai.Model;
import ai.onnxruntime.genai.Sequences;
import ai.onnxruntime.genai.Tokenizer;
import ai.onnxruntime.genai.TokenizerStream;
import android.os.Build;
import android.os.Debug;
import org.json.JSONObject;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public final class AndroidRuntimeSmoke {
    private static String prompt(String text) {
        return "<|im_start|>system\nYou are a concise assistant.<|im_end|>\n"
            + "<|im_start|>user\n" + text + "<|im_end|>\n"
            + "<|im_start|>assistant\n<think>\n\n</think>\n\n";
    }

    private static String generate(Model model, Tokenizer tokenizer, String input) throws Exception {
        StringBuilder text = new StringBuilder();
        try (Sequences tokens = tokenizer.encode(prompt(input));
             GeneratorParams params = new GeneratorParams(model);
             TokenizerStream stream = tokenizer.createStream()) {
            params.setSearchOption("max_length", tokens.getSequence(0).length + 64.0);
            params.setSearchOption("do_sample", false);
            try (Generator generator = new Generator(model, params)) {
                generator.appendTokenSequences(tokens);
                int emitted = tokens.getSequence(0).length;
                while (!generator.isDone()) {
                    generator.generateNextToken();
                    int[] current = generator.getSequence(0);
                    for (int index = emitted; index < current.length; index++) {
                        int token = current[index];
                        boolean eos = false;
                        for (int stop : tokenizer.getEosTokenIds()) eos |= stop == token;
                        if (!eos) text.append(stream.decode(token));
                    }
                    emitted = current.length;
                }
                int[] sequence = generator.getSequence(0);
                int[] generated = java.util.Arrays.copyOfRange(sequence, tokens.getSequence(0).length, sequence.length);
                String decoded = tokenizer.decode(generated);
                if (!text.toString().equals(decoded)) {
                    throw new AssertionError("Streamed output differs from sequence: " + text + " != " + decoded);
                }
            }
        }
        if (text.toString().trim().isEmpty()) throw new AssertionError("Empty generation");
        return text.toString();
    }

    public static void main(String[] args) {
        try {
            verify(args);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
    }

    private static void verify(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("modelDirectory nativeDirectory");
        System.load(args[1] + "/libonnxruntime.so");
        GenAI.setTelemetry(false);
        JSONObject result = new JSONObject();
        result.put("androidApi", Build.VERSION.SDK_INT);
        result.put("abi", Build.SUPPORTED_ABIS[0]);
        result.put("pssBeforeKb", Debug.getPss());
        result.put("nativeHeapBefore", Debug.getNativeHeapAllocatedSize());
        try (Model model = new Model(args[0]); Tokenizer tokenizer = new Tokenizer(model)) {
            result.put("pssLoadedKb", Debug.getPss());
            String roundTrip = "Привет, ImageToolbox!";
            try (Sequences encoded = tokenizer.encode(roundTrip)) {
                if (!tokenizer.decode(encoded.getSequence(0)).equals(roundTrip)) {
                    throw new AssertionError("Russian tokenizer round-trip failed");
                }
            }
            result.put("tokenizerRoundTrip", true);
            result.put("streamMatchesSequence", true);
            result.put("russian", generate(model, tokenizer, "Сколько будет два плюс два? Ответь по-русски одним словом."));
            result.put("english", generate(model, tokenizer, "Say hello in English in one short sentence."));
            AtomicBoolean cancelled = new AtomicBoolean(false);
            AtomicReference<Throwable> failure = new AtomicReference<>();
            try (Sequences encoded = tokenizer.encode(prompt("Write a long detailed guide to image editing."));
                 GeneratorParams params = new GeneratorParams(model)) {
                params.setSearchOption("max_length", 2048.0);
                params.setSearchOption("do_sample", false);
                try (Generator generator = new Generator(model, params)) {
                    Thread worker = new Thread(() -> {
                        try {
                            generator.appendTokenSequences(encoded);
                            while (!cancelled.get() && !generator.isDone()) {
                                generator.generateNextToken();
                            }
                        } catch (Throwable error) {
                            if (!cancelled.get()) failure.set(error);
                        }
                    });
                    worker.start();
                    Thread.sleep(200);
                    long start = System.nanoTime();
                    cancelled.set(true);
                    generator.setRuntimeOption("terminate_session", "1");
                    worker.join(10000);
                    if (worker.isAlive()) throw new AssertionError("Native cancellation timed out");
                    if (failure.get() != null) throw new RuntimeException(failure.get());
                    result.put("cancelMilliseconds", (System.nanoTime() - start) / 1000000.0);
                    result.put("cancellation", true);
                }
            }
            result.put("afterCancel", generate(model, tokenizer, "Reply with the word ready."));
            result.put("nativeHeapLoaded", Debug.getNativeHeapAllocatedSize());
        }
        System.gc();
        Thread.sleep(100);
        result.put("nativeHeapAfterClose", Debug.getNativeHeapAllocatedSize());
        result.put("pssAfterCloseKb", Debug.getPss());
        result.put("resourcesClosed", true);
        System.out.println("IMAGETOOLBOX_ASSISTANT_SMOKE=" + result);
    }
}
