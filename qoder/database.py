from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from config import DB_PATH


@dataclass
class Paper:
    paper_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    abstract: str = ""
    methods: str = ""
    contributions: str = ""
    conclusions: str = ""
    references: list[str] = field(default_factory=list)
    pdf_path: str = ""
    topic_cluster: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.paper_id:
            self.paper_id = uuid.uuid4().hex[:12]


@dataclass
class UserProfile:
    profile_id: str = "default"
    name: str = ""
    research_interests: list[str] = field(default_factory=list)
    focus_keywords: list[str] = field(default_factory=list)
    read_papers: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self):
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class PaperRelation:
    source_id: str
    target_id: str
    relation_type: str  # 'citation' | 'semantic_similar' | 'same_author'
    weight: float = 1.0
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT DEFAULT '[]',
                year INTEGER,
                venue TEXT DEFAULT '',
                abstract TEXT DEFAULT '',
                methods TEXT DEFAULT '',
                contributions TEXT DEFAULT '',
                conclusions TEXT DEFAULT '',
                "references" TEXT DEFAULT '[]',
                pdf_path TEXT DEFAULT '',
                topic_cluster TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                research_interests TEXT DEFAULT '[]',
                focus_keywords TEXT DEFAULT '[]',
                read_papers TEXT DEFAULT '[]',
                created_at REAL DEFAULT 0,
                updated_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS paper_relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at REAL DEFAULT 0,
                PRIMARY KEY (source_id, target_id, relation_type)
            );

            CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
            CREATE INDEX IF NOT EXISTS idx_papers_cluster ON papers(topic_cluster);
            CREATE INDEX IF NOT EXISTS idx_relations_source ON paper_relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON paper_relations(target_id);
        """)


def _row_to_paper(row: sqlite3.Row) -> Paper:
    return Paper(
        paper_id=row["paper_id"],
        title=row["title"],
        authors=json.loads(row["authors"]),
        year=row["year"],
        venue=row["venue"],
        abstract=row["abstract"],
        methods=row["methods"],
        contributions=row["contributions"],
        conclusions=row["conclusions"],
        references=json.loads(row["references"]),
        pdf_path=row["pdf_path"],
        topic_cluster=row["topic_cluster"],
        created_at=row["created_at"],
    )


def save_paper(paper: Paper):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO papers
               (paper_id, title, authors, year, venue, abstract, methods,
                contributions, conclusions, "references", pdf_path, topic_cluster, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper.paper_id, paper.title, json.dumps(paper.authors),
                paper.year, paper.venue, paper.abstract, paper.methods,
                paper.contributions, paper.conclusions, json.dumps(paper.references),
                paper.pdf_path, paper.topic_cluster, paper.created_at,
            ),
        )


def update_paper_cluster(paper_id: str, cluster: str):
    """更新论文的主题聚类"""
    with get_conn() as conn:
        conn.execute("UPDATE papers SET topic_cluster = ? WHERE paper_id = ?", (cluster, paper_id))


def batch_update_clusters(cluster_map: dict[str, str]):
    """批量更新论文的主题聚类"""
    with get_conn() as conn:
        for paper_id, cluster in cluster_map.items():
            conn.execute("UPDATE papers SET topic_cluster = ? WHERE paper_id = ?", (cluster, paper_id))


def get_paper(paper_id: str) -> Paper | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    return _row_to_paper(row) if row else None


def list_papers() -> list[Paper]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
    return [_row_to_paper(r) for r in rows]


def delete_paper(paper_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM paper_relations WHERE source_id = ? OR target_id = ?", (paper_id, paper_id))


def search_papers(keyword: str) -> list[Paper]:
    pattern = f"%{keyword}%"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM papers WHERE title LIKE ? OR abstract LIKE ? OR methods LIKE ? ORDER BY year DESC",
            (pattern, pattern, pattern),
        ).fetchall()
    return [_row_to_paper(r) for r in rows]


def find_duplicate(title: str) -> Paper | None:
    """基于论文题目检测重复，返回匹配的已有论文或 None"""
    title_clean = _normalize_title(title)
    if not title_clean:
        return None

    with get_conn() as conn:
        rows = conn.execute("SELECT paper_id, title FROM papers").fetchall()
        for row in rows:
            existing_clean = _normalize_title(row["title"])
            if not existing_clean:
                continue

            # 1. 完全匹配
            if title_clean == existing_clean:
                full_row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (row["paper_id"],)).fetchone()
                return _row_to_paper(full_row) if full_row else None

            # 2. 包含关系（短标题被长标题包含）
            shorter = min(title_clean, existing_clean, key=len)
            longer = max(title_clean, existing_clean, key=len)
            if shorter in longer and len(shorter) >= 10:
                full_row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (row["paper_id"],)).fetchone()
                return _row_to_paper(full_row) if full_row else None

    return None


def _normalize_title(title: str) -> str:
    """标准化论文题目：转小写、去除多余空格和标点"""
    import re
    if not title:
        return ""
    title = title.lower().strip()
    title = re.sub(r'[\s\-_]+', ' ', title)
    title = re.sub(r'[^\w\s]', '', title)
    return title.strip()


def is_paper_relevant(paper: Paper, interests: list[str], keywords: list[str]) -> bool:
    """检查论文是否与用户研究方向相关"""
    if not interests and not keywords:
        return False

    text = f"{paper.title} {paper.abstract} {paper.methods} {paper.topic_cluster}".lower()

    # 检查兴趣方向
    for interest in interests:
        if interest.lower() in text:
            return True

    # 检查关键词
    for keyword in keywords:
        if keyword.lower() in text:
            return True

    return False


def save_relation(rel: PaperRelation):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO paper_relations (source_id, target_id, relation_type, weight, created_at) VALUES (?, ?, ?, ?, ?)",
            (rel.source_id, rel.target_id, rel.relation_type, rel.weight, rel.created_at),
        )


def get_relations(paper_id: str | None = None) -> list[PaperRelation]:
    with get_conn() as conn:
        if paper_id:
            rows = conn.execute(
                "SELECT * FROM paper_relations WHERE source_id = ? OR target_id = ?",
                (paper_id, paper_id),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM paper_relations").fetchall()
    return [
        PaperRelation(
            source_id=r["source_id"], target_id=r["target_id"],
            relation_type=r["relation_type"], weight=r["weight"] or 1.0,
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_all_relations() -> list[PaperRelation]:
    return get_relations()


def save_profile(profile: UserProfile):
    profile.updated_at = time.time()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO user_profiles
               (profile_id, name, research_interests, focus_keywords, read_papers, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                profile.profile_id, profile.name,
                json.dumps(profile.research_interests),
                json.dumps(profile.focus_keywords),
                json.dumps(profile.read_papers),
                profile.created_at, profile.updated_at,
            ),
        )


def get_profile(profile_id: str = "default") -> UserProfile:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
    if row:
        return UserProfile(
            profile_id=row["profile_id"],
            name=row["name"],
            research_interests=json.loads(row["research_interests"]),
            focus_keywords=json.loads(row["focus_keywords"]),
            read_papers=json.loads(row["read_papers"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    return UserProfile(profile_id=profile_id)


def mark_paper_read(paper_id: str, status: str = "read"):
    profile = get_profile()
    if paper_id not in profile.read_papers:
        profile.read_papers.append(paper_id)
        save_profile(profile)


def get_paper_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM papers").fetchone()
    return row["cnt"]


def get_clusters() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic_cluster FROM papers WHERE topic_cluster != '' ORDER BY topic_cluster"
        ).fetchall()
    return [r["topic_cluster"] for r in rows]
