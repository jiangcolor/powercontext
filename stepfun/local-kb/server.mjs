import path from "node:path";
process.env.SEEKDB_BINDINGS_CACHE_DIR ||= path.resolve(".data/bindings");
import express from "express";
import { createRequire } from "node:module";
import { createServer } from "vite";
import { client, collection, refresh, search, checkVector } from "./db.mjs";
import { mkdir, writeFile } from "node:fs/promises";
const app = express();
const transformerRequire = createRequire(import.meta.resolve("@huggingface/transformers"));
app.use("/ort", express.static(path.dirname(transformerRequire.resolve("onnxruntime-web"))));
app.use(express.json({ limit: "15mb" }));
// Only serve local requests: documents and embeddings never leave this machine.
app.use("/api", (req, res, next) => {
  if (
    req.headers.origin &&
    !/^http:\/\/(localhost|127\.0\.0\.1):5173$/.test(req.headers.origin)
  )
    return res.status(403).json({ error: "仅支持本机页面" });
  next();
});
app.get("/api/health", async (req, res, next) => {
  try {
    await client.execute("SELECT 1");
    res.json({ ok: true, database: "seekdb" });
  } catch (e) {
    next(e);
  }
});
app.post("/api/collection", async (req, res, next) => {
  try {
    const c = await collection(req.body.name);
    res.json({ count: await c.count() });
  } catch (e) {
    next(e);
  }
});
app.post("/api/import", async (req, res, next) => {
  try {
    const { name, documents } = req.body;
    if (
      !Array.isArray(documents) ||
      !documents.length ||
      documents.length > 100
    )
      throw Error("每次写入 1–100 个片段");
    for (const d of documents) {
      checkVector(d.embedding);
      if (
        typeof d.text !== "string" ||
        !d.text.trim() ||
        d.text.length > 6000 ||
        typeof d.id !== "string" ||
        !/^[a-f0-9]{64}$/.test(d.id)
      )
        throw Error("文档格式不正确");
    }
    const c = await collection(name),
      start = performance.now();
    await c.upsert({
      ids: documents.map((d) => d.id),
      documents: documents.map((d) => d.text),
      embeddings: documents.map((d) => d.embedding),
      metadatas: documents.map((d) => ({
        source: String(d.source || "文本"),
        model: String(d.model),
        chunk: Number(d.chunk || 0),
      })),
    });
    const writeMs = performance.now() - start;
    const t = performance.now();
    await refresh(name);
    res.json({
      count: await c.count(),
      writeMs,
      refreshMs: performance.now() - t,
    });
  } catch (e) {
    next(e);
  }
});
app.post("/api/search", async (req, res, next) => {
  try {
    const { name, text, embedding, k = 5 } = req.body;
    if (
      typeof text !== "string" ||
      !text.trim() ||
      text.length > 1000 ||
      !Number.isInteger(k) ||
      k < 1 ||
      k > 20
    )
      throw Error("查询格式不正确");
    const t = performance.now();
    const result = await search(name, text, embedding, k);
    res.json({ result, searchMs: performance.now() - t });
  } catch (e) {
    next(e);
  }
});
app.post("/api/report", async (req, res, next) => {
  try {
    await mkdir("evidence", { recursive: true });
    const file = `benchmark-${Date.now()}.json`;
    await writeFile(`evidence/${file}`, JSON.stringify(req.body, null, 2));
    res.json({ file });
  } catch (e) {
    next(e);
  }
});
app.use("/api", (err, req, res, next) =>
  res.status(400).json({ error: err.message }),
);
app.use(
  (await createServer({ server: { middlewareMode: true }, appType: "spa" }))
    .middlewares,
);
// Initialize the native database before accepting concurrent browser requests.
await client.execute("SELECT 1");
app.listen(5173, "127.0.0.1", () =>
  console.log("本地知识库：http://127.0.0.1:5173"),
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, async () => {
    await client.close();
    process.exit();
  });
