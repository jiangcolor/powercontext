import { corpus, queries } from "./dataset.js";
const $ = (id) => document.getElementById(id),
  worker = new Worker(new URL("./embed-worker.js", import.meta.url), {
    type: "module",
  });
let sequence = 0,
  pending = new Map(),
  active = "personal",
  loaded = null,
  busy = false;
worker.onmessage = ({ data: m }) => {
  const p = pending.get(m.id);
  if (!p) return;
  if (m.error) {
    pending.delete(m.id);
    p.reject(Error(m.error));
  } else if (m.result) {
    pending.delete(m.id);
    p.resolve(m.result);
  } else if (m.progress) {
    const x = m.progress;
    $("status").textContent =
      `加载模型：${x.file || x.status} ${Math.round(x.progress || 0)}%`;
    $("progress").value = x.progress || 0;
  } else if (m.total) {
    $("progress").value = (100 * m.completed) / m.total;
    $("status").textContent =
      `${loaded?.backend?.toUpperCase() || ""} · ${loaded?.dtype?.toUpperCase() || ""} · 本地向量化 ${m.completed}/${m.total}`;
  }
};
const call = (type, args = {}) =>
  new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, type, ...args });
  });
async function api(endpoint, data) {
  const r = await fetch("/api/" + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const j = await r.json();
  if (!r.ok) throw Error(j.error || r.statusText);
  return j;
}
async function load(device = $("backend").value, dtype = "q8") {
  loaded = await call("load", { device, dtype });
  $("status").textContent =
    `当前后端：${loaded.backend.toUpperCase()} · ${loaded.dtype === "q8" ? "INT8" : loaded.dtype.toUpperCase()} · ${loaded.reason || "本机 GPU 推理"} · 加载 ${Math.round(loaded.loadMs)} ms`;
  $("progress").value = 100;
  return loaded;
}
async function embed(texts, batchSize = 1) {
  if (!loaded) await load();
  return call("embed", { texts, batchSize });
}
async function idFor(text) {
  return [
    ...new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)),
    ),
  ]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}
function chunks(text) {
  const clean = text.replace(/\r\n/g, "\n").trim();
  const a = [];
  for (let i = 0; i < clean.length; i += 700) a.push(clean.slice(i, i + 800));
  return a;
}
async function open() {
  const r = await api("collection", { name: $("name").value });
  active = $("name").value;
  localStorage.setItem("stepfun-collection", active);
  $("collection").textContent = `当前知识库：${active} · ${r.count} 个片段`;
}
async function ingest(entries, name = active, batchSize = 1, writeSize = 100) {
  const t = performance.now();
  const e = await embed(
    entries.map((d) => d.text),
    batchSize,
  );
  const docs = await Promise.all(
    entries.map(async (d, i) => ({
      ...d,
      id: await idFor(d.text + "|" + d.source + "|" + d.chunk),
      embedding: e.embeddings[i],
      model: e.model,
    })),
  );
  let writeMs = 0,
    refreshMs = 0,
    count = 0;
  for (let i = 0; i < docs.length; i += writeSize) {
    const r = await api("import", {
      name,
      documents: docs.slice(i, i + writeSize),
    });
    writeMs += r.writeMs;
    refreshMs += r.refreshMs;
    count = r.count;
  }
  $("importStats").textContent =
    `${name}：共 ${count} 片段；本地向量化 ${e.ms.toFixed(0)} ms，写入 ${writeMs.toFixed(0)} ms，索引刷新 ${refreshMs.toFixed(0)} ms`;
  if (name === active)
    $("collection").textContent = `当前知识库：${active} · ${count} 个片段`;
  $("status").textContent =
    `当前后端：${loaded.backend.toUpperCase()} · ${loaded.dtype.toUpperCase()} · ${loaded.reason || "本机推理"}`;
  return {
    embedMs: e.ms,
    writeMs,
    refreshMs,
    totalMs: performance.now() - t,
    count,
  };
}
async function query(text, name = active) {
  const start = performance.now(),
    e = await embed([text]);
  const r = await api("search", {
    name,
    text,
    embedding: e.embeddings[0],
    k: 3,
  });
  return { ...r, queryEmbedMs: e.ms, endToEndMs: performance.now() - start };
}
function show(r) {
  $("results").replaceChildren();
  const x = r.result;
  for (let i = 0; i < (x.ids?.[0]?.length || 0); i++) {
    const el = document.createElement("article"),
      meta = document.createElement("small"),
      body = document.createElement("p");
    meta.textContent = `#${i + 1} · ${x.metadatas?.[0]?.[i]?.source || x.ids[0][i]}`;
    body.textContent = x.documents?.[0]?.[i] || "";
    el.append(meta, body);
    $("results").append(el);
  }
  $("queryStats").textContent =
    `查询向量 ${r.queryEmbedMs.toFixed(0)} ms · seekdb ${r.searchMs.toFixed(0)} ms · 端到端 ${r.endToEndMs.toFixed(0)} ms`;
}
const median = (a) => [...a].sort((a, b) => a - b)[Math.floor(a.length / 2)];
async function benchmark() {
  const report = {
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    model: "Xenova/all-MiniLM-L6-v2",
    corpusSize: corpus.length,
    queryCount: queries.length,
    repeats: 3,
    runs: [],
  };
  const variants = [
    { device: "wasm", dtype: "fp32", batchSize: 1, writeSize: 1 },
    { device: "wasm", dtype: "q8", batchSize: 1, writeSize: 1 },
    { device: "wasm", dtype: "q8", batchSize: 1, writeSize: 100 },
    { device: "auto", dtype: "q8", batchSize: 1, writeSize: 100 },
  ];
  for (const [index, v] of variants.entries()) {
    $("report").textContent =
      `配置 ${index + 1}/${variants.length}：${JSON.stringify(v)}\n首次加载或预热中…`;
    const config = await load(v.device, v.dtype);
    await embed(["warm up"]);
    const name = `bench_${Date.now()}_${index}`;
    const imports = [];
    const entries = corpus.map(([source, text]) => ({
      source,
      text,
      chunk: 0,
    }));
    for (let rep = 0; rep < 3; rep++)
      imports.push(await ingest(entries, name, v.batchSize, v.writeSize));
    const measurements = [];
    for (let rep = 0; rep < 3; rep++)
      for (const [text, relevant] of queries) {
        const r = await query(text, name),
          sources = r.result.metadatas?.[0]?.map((m) => m.source) || [];
        const rank = sources.indexOf(relevant);
        measurements.push({
          rep,
          text,
          relevant,
          sources,
          recallAt3: rank >= 0 ? 1 : 0,
          ndcgAt3: rank >= 0 ? 1 / Math.log2(rank + 2) : 0,
          queryEmbedMs: r.queryEmbedMs,
          searchMs: r.searchMs,
          endToEndMs: r.endToEndMs,
        });
      }
    report.runs.push({
      ...v,
      config,
      collection: name,
      imports,
      measurements,
      median: {
        importTotalMs: median(imports.map((r) => r.totalMs)),
        documentEmbedMs: median(imports.map((r) => r.embedMs)),
        writeMs: median(imports.map((r) => r.writeMs)),
        refreshMs: median(imports.map((r) => r.refreshMs)),
        searchMs: median(measurements.map((r) => r.searchMs)),
        endToEndMs: median(measurements.map((r) => r.endToEndMs)),
      },
      recallAt3:
        measurements.reduce((s, r) => s + r.recallAt3, 0) / measurements.length,
      ndcgAt3:
        measurements.reduce((s, r) => s + r.ndcgAt3, 0) / measurements.length,
    });
    $("report").textContent = JSON.stringify(
      report.runs.map(({ measurements, imports, ...r }) => r),
      null,
      2,
    );
  }
  await api("report", report);
  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: "application/json",
  });
  $("download").href = URL.createObjectURL(blob);
  $("download").download = "stepfun-benchmark.json";
  $("download").hidden = false;
  await load();
  return report;
}
function task(fn) {
  return async () => {
    if (busy) return;
    busy = true;
    document
      .querySelectorAll("button,select")
      .forEach((b) => (b.disabled = true));
    try {
      await fn();
    } catch (e) {
      $("status").textContent = "操作失败：" + e.message;
      console.error(e);
    } finally {
      busy = false;
      document
        .querySelectorAll("button,select")
        .forEach((b) => (b.disabled = false));
    }
  };
}
$("switch").onclick = task(open);
$("load").onclick = task(() => load());
$("sample").onclick = task(() =>
  ingest(corpus.map(([source, text]) => ({ source, text, chunk: 0 }))),
);
$("import").onclick = task(async () => {
  const entries = [];
  if ($("text").value.trim())
    chunks($("text").value).forEach((text, chunk) =>
      entries.push({ source: "粘贴文本", text, chunk }),
    );
  for (const file of $("files").files) {
    if (file.size > 2e6) throw Error("单文件最多 2 MB");
    chunks(await file.text()).forEach((text, chunk) =>
      entries.push({ source: file.name, text, chunk }),
    );
  }
  if (!entries.length) throw Error("请先选择文件或粘贴文本");
  await ingest(entries);
});
$("search").onclick = task(async () => {
  if (!$("query").value.trim()) throw Error("请输入查询");
  show(await query($("query").value));
});
$("benchmark").onclick = task(benchmark);
$("name").value = localStorage.getItem("stepfun-collection") || "personal";
open().catch((e) => ($("collection").textContent = e.message));
