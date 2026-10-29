import { pipeline, env } from "@huggingface/transformers";
env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = "/models/";
env.useBrowserCache = true;
env.backends.onnx.wasm.wasmPaths = "/ort/";
let model, config;
self.onmessage = async ({
  data: { id, type, texts, device = "auto", dtype = "q8", batchSize = 1 },
}) => {
  try {
    if (type === "load") {
      if (model) await model.dispose();
      model = null;
      let backend = "wasm",
        reason = "",
        actualDtype = dtype;
      if (device === "auto") {
        try {
          const adapter =
            navigator.gpu && (await navigator.gpu.requestAdapter());
          if (adapter && adapter.features.has("shader-f16")) {
            backend = "webgpu";
            actualDtype = dtype === "fp32" ? "fp32" : "fp16";
          } else reason = "WebGPU / FP16 不可用，自动使用 WASM";
        } catch {
          reason = "WebGPU 检测失败，自动使用 WASM";
        }
      } else reason = "手动验证 WASM 路径";
      performance.clearResourceTimings();
      const start = performance.now();
      const options = {
        device: backend,
        dtype: actualDtype,
        revision: "751bff37182d3f1213fa05d7196b954e230abad9",
        progress_callback: (p) => self.postMessage({ id, progress: p }),
      };
      try {
        model = await pipeline(
          "feature-extraction",
          "Xenova/all-MiniLM-L6-v2",
          options,
        );
      } catch (e) {
        if (backend !== "webgpu") throw e;
        backend = "wasm";
        actualDtype = dtype;
        reason = "WebGPU 初始化失败，已降级 WASM";
        model = await pipeline(
          "feature-extraction",
          "Xenova/all-MiniLM-L6-v2",
          { ...options, device: "wasm", dtype: actualDtype },
        );
      }
      config = {
        backend,
        dtype: actualDtype,
        reason,
        revision: "751bff37182d3f1213fa05d7196b954e230abad9",
        model: "Xenova/all-MiniLM-L6-v2",
        loadMs: performance.now() - start,
        resources: performance
          .getEntriesByType("resource")
          .map((r) => ({
            url: r.name,
            durationMs: r.duration,
            transferBytes: r.transferSize,
            decodedBytes: r.decodedBodySize,
          })),
      };
      self.postMessage({ id, result: config });
    } else if (type === "embed") {
      if (!model) throw Error("请先加载模型");
      const start = performance.now(),
        embeddings = [];
      for (let i = 0; i < texts.length; i += batchSize) {
        const output = await model(texts.slice(i, i + batchSize), {
          pooling: "mean",
          normalize: true,
        });
        embeddings.push(...output.tolist());
        self.postMessage({
          id,
          completed: Math.min(i + batchSize, texts.length),
          total: texts.length,
        });
      }
      self.postMessage({
        id,
        result: { embeddings, ms: performance.now() - start, ...config },
      });
    }
  } catch (e) {
    self.postMessage({ id, error: e.message });
  }
};
