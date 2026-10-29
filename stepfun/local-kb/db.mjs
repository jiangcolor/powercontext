import {
  SeekdbClient,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";
import path from "node:path";
export const client = new SeekdbClient(
  process.env.SEEKDB_HOST
    ? {
        host: process.env.SEEKDB_HOST,
        port: Number(process.env.SEEKDB_PORT || 2881),
        user: process.env.SEEKDB_USER || "root",
        password: process.env.SEEKDB_PASSWORD || "",
        database: process.env.SEEKDB_DATABASE || "test",
      }
    : { path: path.resolve(".data/seekdb"), database: "test" },
);
export const validName = (n) =>
  typeof n === "string" && /^[a-z][a-z0-9_]{0,39}$/.test(n);
export function checkVector(v) {
  if (
    !Array.isArray(v) ||
    v.length !== 384 ||
    !v.every(Number.isFinite) ||
    !v.some((x) => x !== 0)
  )
    throw Error("需要浏览器生成的 384 维非零向量");
}
export async function collection(name) {
  if (!validName(name))
    throw Error("知识库名应为小写英文、数字、下划线，且以字母开头");
  return client.getOrCreateCollection({
    name,
    embeddingFunction: null,
    schema: new Schema({
      vectorIndex: new VectorIndexConfig({
        hnsw: { dimension: 384, distance: "cosine" },
        embeddingFunction: null,
      }),
      fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
    }),
  });
}
export async function refresh(name) {
  // Wait for seekdb's asynchronous vector and full-text indexes.
  const c = await collection(name);
  await c.refresh_index();
}
export async function search(name, text, embedding, k = 5) {
  checkVector(embedding);
  const c = await collection(name);
  return c.hybridSearch({
    query: { whereDocument: { $contains: text }, nResults: 20 },
    knn: { queryEmbeddings: [embedding], nResults: 20 },
    rank: { rrf: {} },
    nResults: k,
    include: ["documents", "metadatas", "distances"],
  });
}
