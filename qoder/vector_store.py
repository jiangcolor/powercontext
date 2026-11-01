from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import numpy as np

from config import DATA_DIR

VEC_DB_PATH = DATA_DIR / "vectors.db"


@contextmanager
def _get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(VEC_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_vec_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                paper_id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                embedding BLOB
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vec_paper ON vectors(paper_id)")


_init_vec_db()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        dim = max(len(a), len(b))
        if len(a) < dim:
            a = np.pad(a, (0, dim - len(a)))
        if len(b) < dim:
            b = np.pad(b, (0, dim - len(b)))
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    result = float(np.dot(a, b) / (norm_a * norm_b))
    # 处理可能的 NaN 值
    if np.isnan(result):
        return 0.0
    return result


def _build_tfidf_embeddings(texts: list[str], dim: int = 384) -> list[np.ndarray]:
    """
    从文本列表构建 TF-IDF 向量，所有文本共享同一词汇表
    这样相似的文本会在相同维度上有非零值，产生有意义的相似度
    """
    import re
    import math

    # 文本预处理和分词
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "can", "this", "that",
        "these", "those", "it", "its", "we", "our", "they", "their", "which",
        "what", "who", "whom", "how", "when", "where", "why", "if", "then",
        "than", "so", "as", "not", "no", "nor", "yet", "about", "into",
        "through", "during", "before", "after", "above", "below", "between",
        "under", "over", "again", "further", "once", "here", "there", "all",
        "each", "every", "both", "few", "more", "most", "other", "some", "such",
        "only", "own", "same", "also", "very", "up", "down", "out", "off",
        "over", "under", "again", "further", "then", "once", "etc", "et", "al",
        "using", "used", "use", "based", "propose", "proposed", "method",
        "approach", "paper", "show", "shows", "shown", "present", "presents",
        "work", "works", "study", "studies", "research", "new", "novel",
    }

    def tokenize(text: str) -> list[str]:
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        words = [w for w in text.split() if len(w) > 2 and w not in stop_words]
        return words

    # 对所有文本分词
    tokenized = [tokenize(t) for t in texts]

    # 构建词汇表（选择出现频率最高的词）
    doc_freq = {}  # 每个词出现在多少文档中
    term_freq_total = {}  # 每个词的总出现次数

    for words in tokenized:
        unique_words = set(words)
        for w in unique_words:
            doc_freq[w] = doc_freq.get(w, 0) + 1
        for w in words:
            term_freq_total[w] = term_freq_total.get(w, 0) + 1

    # 选择出现至少2次的词作为词汇表
    vocab = [w for w, count in doc_freq.items() if count >= 2]

    # 如果词汇表太小，降低阈值
    if len(vocab) < 20:
        vocab = [w for w, count in doc_freq.items() if count >= 1]

    # 限制词汇表大小
    if len(vocab) > dim:
        # 保留文档频率最高的词
        vocab.sort(key=lambda w: doc_freq[w], reverse=True)
        vocab = vocab[:dim]

    # 如果还是不够，就用所有词
    if len(vocab) < 10:
        all_words = list(doc_freq.keys())
        all_words.sort(key=lambda w: term_freq_total.get(w, 0), reverse=True)
        vocab = all_words[:dim]

    n_docs = len(texts)
    embeddings = []

    for words in tokenized:
        vec = np.zeros(dim, dtype=np.float32)

        # 计算词频
        tf = {}
        for w in words:
            tf[w] = tf.get(w, 0) + 1

        # 构建 TF-IDF 向量
        for i, term in enumerate(vocab):
            if i >= dim:
                break
            if term in tf:
                # TF: 词频归一化
                tf_val = tf[term] / max(len(words), 1)
                # IDF: 逆文档频率
                idf_val = math.log(n_docs / (1 + doc_freq.get(term, 0))) + 1
                # 使用 hash 确保维度映射的确定性（当 vocab 大于 dim 时）
                vec[i] = tf_val * idf_val

        # L2 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        embeddings.append(vec)

    return embeddings


def _text_to_embedding_fallback(text: str, dim: int = 384) -> np.ndarray:
    """单个文本的向量化（向后兼容，但建议用 _build_tfidf_embeddings）"""
    # 这个函数保留用于向后兼容，但单独使用时效果有限
    # 对于聚类任务，应该使用 _build_tfidf_embeddings
    result = _build_tfidf_embeddings([text], dim)
    return result[0] if result else np.zeros(dim)


def _get_embedding(text: str) -> np.ndarray:
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, EMBEDDING_MODEL

    if OPENAI_API_KEY and not OPENAI_API_KEY.startswith("sk-your") and EMBEDDING_MODEL:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            resp = client.embeddings.create(input=text, model=EMBEDDING_MODEL)
            return np.array(resp.data[0].embedding, dtype=np.float32)
        except Exception:
            pass

    return _text_to_embedding_fallback(text)


def add_paper(paper_id: str, text: str, metadata: dict):
    embedding = _get_embedding(text)
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vectors (paper_id, document, metadata, embedding) VALUES (?, ?, ?, ?)",
            (paper_id, text, json.dumps(metadata, ensure_ascii=False), embedding.tobytes()),
        )


def _load_embedding(row) -> np.ndarray | None:
    if row["embedding"]:
        return np.frombuffer(row["embedding"], dtype=np.float32)
    return None


def _load_embedding_by_tuple(row) -> np.ndarray | None:
    """从元组类型的 row 加载 embedding（row 格式：paper_id, document, metadata, embedding）"""
    if row[3]:
        return np.frombuffer(row[3], dtype=np.float32)
    return None


def query_similar(query_text: str, n_results: int = 10, where: dict | None = None) -> list[dict]:
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, EMBEDDING_MODEL
    use_openai = bool(OPENAI_API_KEY and not OPENAI_API_KEY.startswith("sk-your") and EMBEDDING_MODEL)

    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM vectors").fetchall()

    if use_openai:
        query_emb = _get_embedding(query_text)
        scored = []
        for row in rows:
            emb = _load_embedding(row)
            if emb is None:
                continue
            if where:
                meta = json.loads(row["metadata"])
                match = all(meta.get(k) == v for k, v in where.items())
                if not match:
                    continue
            sim = _cosine_similarity(query_emb, emb)
            scored.append({
                "paper_id": row["paper_id"],
                "document": row["document"],
                "metadata": json.loads(row["metadata"]),
                "similarity": sim,
                "distance": 1.0 - sim,
            })
    else:
        # 使用共享词汇表的 TF-IDF
        all_docs = [row["document"] for row in rows]
        all_docs_with_query = [query_text] + all_docs
        all_embeddings = _build_tfidf_embeddings(all_docs_with_query)
        query_emb = all_embeddings[0]
        doc_embeddings = all_embeddings[1:]

        # 更新数据库中的向量
        with _get_conn() as conn:
            for i, row in enumerate(rows):
                conn.execute(
                    "UPDATE vectors SET embedding = ? WHERE paper_id = ?",
                    (doc_embeddings[i].tobytes(), row["paper_id"]),
                )

        scored = []
        for i, row in enumerate(rows):
            if where:
                meta = json.loads(row["metadata"])
                match = all(meta.get(k) == v for k, v in where.items())
                if not match:
                    continue
            sim = _cosine_similarity(query_emb, doc_embeddings[i])
            scored.append({
                "paper_id": row["paper_id"],
                "document": row["document"],
                "metadata": json.loads(row["metadata"]),
                "similarity": sim,
                "distance": 1.0 - sim,
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:n_results]


def query_by_embedding(paper_id: str, n_results: int = 10) -> list[dict]:
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, EMBEDDING_MODEL
    use_openai = bool(OPENAI_API_KEY and not OPENAI_API_KEY.startswith("sk-your") and EMBEDDING_MODEL)

    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        all_rows = conn.execute("SELECT * FROM vectors").fetchall()
        target_row = conn.execute("SELECT * FROM vectors WHERE paper_id = ?", (paper_id,)).fetchone()

    if not target_row:
        return []

    if use_openai:
        target_emb = _load_embedding(target_row)
        if target_emb is None:
            target_emb = _get_embedding(target_row["document"])

        scored = []
        for r in all_rows:
            if r["paper_id"] == paper_id:
                continue
            emb = _load_embedding(r)
            if emb is None:
                continue
            sim = _cosine_similarity(target_emb, emb)
            scored.append({
                "paper_id": r["paper_id"],
                "document": r["document"],
                "metadata": json.loads(r["metadata"]),
                "similarity": sim,
                "distance": 1.0 - sim,
            })
    else:
        # 使用共享词汇表的 TF-IDF
        all_docs = [r["document"] for r in all_rows]
        all_embeddings = _build_tfidf_embeddings(all_docs)

        paper_ids_list = [r["paper_id"] for r in all_rows]
        target_idx = paper_ids_list.index(paper_id)
        target_emb = all_embeddings[target_idx]

        # 更新数据库中的向量
        with _get_conn() as conn:
            for i, r in enumerate(all_rows):
                conn.execute(
                    "UPDATE vectors SET embedding = ? WHERE paper_id = ?",
                    (all_embeddings[i].tobytes(), r["paper_id"]),
                )

        scored = []
        for i, r in enumerate(all_rows):
            if r["paper_id"] == paper_id:
                continue
            sim = _cosine_similarity(target_emb, all_embeddings[i])
            scored.append({
                "paper_id": r["paper_id"],
                "document": r["document"],
                "metadata": json.loads(r["metadata"]),
                "similarity": sim,
                "distance": 1.0 - sim,
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:n_results]


def delete_paper(paper_id: str):
    with _get_conn() as conn:
        conn.execute("DELETE FROM vectors WHERE paper_id = ?", (paper_id,))


def get_all_ids() -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT paper_id FROM vectors").fetchall()
    return [r[0] for r in rows]


def get_paper_embedding_text(paper_id: str) -> str:
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT document FROM vectors WHERE paper_id = ?", (paper_id,)).fetchone()
    return row["document"] if row else ""


class UnionFind:
    """并查集，用于聚类"""
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1


def auto_cluster(similarity_threshold: float = 0.5) -> dict[str, str]:
    """
    基于向量相似度自动聚类论文
    使用共享词汇表的 TF-IDF 重新计算所有论文的向量，确保相似度有意义
    返回 {paper_id: cluster_name} 映射
    """
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT paper_id, document, metadata, embedding FROM vectors").fetchall()

    if len(rows) < 2:
        return {row["paper_id"]: "未分类" for row in rows}

    paper_ids = [row["paper_id"] for row in rows]
    documents = [row["document"] for row in rows]
    metadatas = [json.loads(row["metadata"]) for row in rows]

    # 检查是否有 OpenAI embedding 可用
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, EMBEDDING_MODEL
    use_openai = bool(OPENAI_API_KEY and not OPENAI_API_KEY.startswith("sk-your") and EMBEDDING_MODEL)

    if use_openai:
        # 使用 OpenAI embedding：先尝试加载已有的，缺少的再调 API
        embeddings = []
        need_recompute = False
        for i, row in enumerate(rows):
            emb = _load_embedding_by_tuple(tuple(row))
            if emb is None:
                need_recompute = True
                break
            embeddings.append(emb)

        if need_recompute:
            # 重新计算所有 embedding
            embeddings = []
            for doc in documents:
                emb = _get_embedding(doc)
                embeddings.append(emb)
            # 更新数据库中的向量
            with _get_conn() as conn:
                for i, pid in enumerate(paper_ids):
                    conn.execute(
                        "UPDATE vectors SET embedding = ? WHERE paper_id = ?",
                        (embeddings[i].tobytes(), pid),
                    )
    else:
        # 没有 OpenAI，使用共享词汇表的 TF-IDF
        embeddings = _build_tfidf_embeddings(documents)
        # 更新数据库中的向量
        with _get_conn() as conn:
            for i, pid in enumerate(paper_ids):
                conn.execute(
                    "UPDATE vectors SET embedding = ? WHERE paper_id = ?",
                    (embeddings[i].tobytes(), pid),
                )

    # 使用并查集进行聚类
    uf = UnionFind(len(paper_ids))

    for i in range(len(paper_ids)):
        for j in range(i + 1, len(paper_ids)):
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim >= similarity_threshold:
                uf.union(i, j)

    # 收集每个聚类的成员
    clusters = {}
    for i, pid in enumerate(paper_ids):
        root = uf.find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(pid)

    # 为每个聚类生成标签
    result = {}
    for idx, (root, members) in enumerate(clusters.items()):
        # 从聚类中所有论文的标题和 metadata 提取关键词生成聚类名
        cluster_words = {}
        for pid in members:
            meta_idx = paper_ids.index(pid)
            meta = metadatas[meta_idx]
            title = meta.get("title", "")
            for w in title.split():
                w_lower = w.lower().strip(".,;:!?()[]{}\"'")
                if len(w_lower) > 3:
                    cluster_words[w_lower] = cluster_words.get(w_lower, 0) + 1

        # 优先使用 metadata 中的 cluster 字段
        first_meta = metadatas[paper_ids.index(members[0])]
        cluster_name = first_meta.get("cluster", "")

        if not cluster_name and cluster_words:
            # 取出现频率最高的词作为聚类名
            stop = {"with", "from", "that", "this", "have", "been", "were", "was", "their", "which", "using", "based"}
            meaningful = [(w, c) for w, c in cluster_words.items() if w not in stop and c >= 1]
            meaningful.sort(key=lambda x: x[1], reverse=True)
            if meaningful:
                cluster_name = " ".join(w for w, _ in meaningful[:3])
            else:
                cluster_name = f"聚类 {idx + 1}"
        elif not cluster_name:
            cluster_name = f"聚类 {idx + 1}"

        for pid in members:
            result[pid] = cluster_name

    return result
