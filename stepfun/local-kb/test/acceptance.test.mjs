import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
const root = "http://127.0.0.1:5173/api/";
async function post(endpoint, body) {
  const response = await fetch(root + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: response.status, ...(await response.json()) };
}
test("seekdb refresh, increment, duplicate import and collection isolation", async () => {
  const name = "accept_" + Date.now(),
    embedding = [1, ...Array(383).fill(0)];
  const document = (text) => ({
    id: createHash("sha256").update(text).digest("hex"),
    text,
    source: "acceptance",
    embedding,
    model: "synthetic-test-only",
    chunk: 0,
  });
  const first = document("backup archive recovery"),
    second = document("incremental new document");
  assert.equal((await post("collection", { name })).count, 0);
  assert.equal((await post("import", { name, documents: [first] })).count, 1);
  assert.equal((await post("import", { name, documents: [first] })).count, 1);
  assert.equal((await post("import", { name, documents: [second] })).count, 2);
  const r = await post("search", {
    name,
    text: "incremental",
    embedding,
    k: 3,
  });
  assert.equal(r.status, 200);
  assert.ok(r.result.documents[0].includes(second.text));
  const isolated = await post("search", {
    name: name + "_other",
    text: "incremental",
    embedding,
    k: 3,
  });
  assert.deepEqual(isolated.result.ids, [[]]);
  assert.equal(
    (await post("search", { name, text: "backup", embedding: [1], k: 3 }))
      .status,
    400,
  );
  assert.equal(
    (await post("collection", { name: "bad; DROP TABLE x" })).status,
    400,
  );
});
