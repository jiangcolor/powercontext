from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sync_paper_store import SyncPaperStore
from database import PaperRelation, get_all_relations, save_relation
from vector_store import query_by_embedding
from pathlib import Path

# Initialize paper store
_paper_store = SyncPaperStore(Path(__file__).parent / "data" / "papers_powercontext.db")
_paper_store.init_db()


@dataclass
class GraphNodeContent:
    """Wrapper to provide .content interface compatible with Paper Artifact templates."""
    title: str
    year: int | None
    cluster: str
    contributions: str
    authors: list[str]


@dataclass
class GraphNode:
    id: str
    title: str
    year: int | None
    cluster: str
    contributions: str
    authors: list[str]
    content: GraphNodeContent = field(init=False, repr=False)

    def __post_init__(self):
        self.content = GraphNodeContent(
            title=self.title,
            year=self.year,
            cluster=self.cluster,
            contributions=self.contributions,
            authors=self.authors,
        )


@dataclass
class GraphEdge:
    source: str
    target: str
    relation_type: str
    weight: float
    label: str


def build_full_graph() -> tuple[list[GraphNode], list[GraphEdge]]:
    papers = _paper_store.list_papers()
    relations = get_all_relations()

    nodes = []
    for p in papers:
        nodes.append(GraphNode(
            id=p.artifact_id,
            title=p.content.title,
            year=p.content.year,
            cluster=p.content.topic_cluster or "",
            contributions=p.content.contributions or "",
            authors=p.content.authors,
        ))

    edges = []
    seen = set()
    for r in relations:
        key = (r.source_id, r.target_id, r.relation_type)
        if key not in seen:
            seen.add(key)
            edges.append(GraphEdge(
                source=r.source_id,
                target=r.target_id,
                relation_type=r.relation_type,
                weight=r.weight,
                label=r.relation_type,
            ))

    return nodes, edges


def build_subgraph(paper_ids: list[str]) -> tuple[list[GraphNode], list[GraphEdge]]:
    all_nodes, all_edges = build_full_graph()
    id_set = set(paper_ids)

    nodes = [n for n in all_nodes if n.id in id_set]
    edges = [e for e in all_edges if e.source in id_set and e.target in id_set]
    return nodes, edges


def build_cluster_graph(cluster: str) -> tuple[list[GraphNode], list[GraphEdge]]:
    papers = _paper_store.list_papers()
    cluster_ids = [p.artifact_id for p in papers if p.content.topic_cluster == cluster]
    return build_subgraph(cluster_ids)


def discover_semantic_links(paper_id: str, top_k: int = 5) -> list[PaperRelation]:
    similar = query_by_embedding(paper_id, n_results=top_k)
    paper = _paper_store.get_paper(paper_id)
    if not paper:
        return []

    existing_refs = set(paper.content.references)
    new_relations = []

    for s in similar:
        target_id = s["paper_id"]
        if target_id in existing_refs or target_id == paper_id:
            continue

        score = 1.0 - (s.get("distance", 1.0) / 2.0)
        if score < 0.3:
            continue

        rel = PaperRelation(
            source_id=paper_id,
            target_id=target_id,
            relation_type="semantic_similar",
            weight=round(score, 3),
        )
        save_relation(rel)
        new_relations.append(rel)

    return new_relations


def build_citation_relations(paper_id: str, ref_titles: list[str]) -> list[PaperRelation]:
    papers = _paper_store.list_papers()
    title_to_id = {p.content.title.lower().strip(): p.artifact_id for p in papers}

    new_relations = []
    for ref_title in ref_titles:
        ref_lower = ref_title.lower().strip()
        matched_id = None
        for t, pid in title_to_id.items():
            if ref_lower in t or t in ref_lower:
                matched_id = pid
                break

        if matched_id:
            rel = PaperRelation(
                source_id=paper_id,
                target_id=matched_id,
                relation_type="citation",
                weight=1.0,
            )
            save_relation(rel)
            new_relations.append(rel)

    return new_relations


def build_author_relations(paper_id: str) -> list[PaperRelation]:
    paper = _paper_store.get_paper(paper_id)
    if not paper or not paper.content.authors:
        return []

    papers = _paper_store.list_papers()
    new_relations = []

    for other in papers:
        if other.artifact_id == paper_id:
            continue
        shared = set(paper.content.authors) & set(other.content.authors)
        if shared:
            rel = PaperRelation(
                source_id=paper_id,
                target_id=other.artifact_id,
                relation_type="same_author",
                weight=len(shared) * 0.5,
            )
            save_relation(rel)
            new_relations.append(rel)

    return new_relations


def get_paper_timeline() -> list[GraphNode]:
    papers = _paper_store.list_papers()
    sorted_papers = sorted(papers, key=lambda p: p.content.year or 9999)
    return [
        GraphNode(
            id=p.artifact_id,
            title=p.content.title,
            year=p.content.year,
            cluster=p.content.topic_cluster or "",
            contributions=p.content.contributions or "",
            authors=p.content.authors,
        )
        for p in sorted_papers
        if p.content.year
    ]


def get_cluster_summary() -> dict[str, list[GraphNode]]:
    papers = _paper_store.list_papers()
    clusters: dict[str, list[GraphNode]] = {}
    for p in papers:
        c = p.content.topic_cluster or "未分类"
        if c not in clusters:
            clusters[c] = []
        clusters[c].append(GraphNode(
            id=p.artifact_id,
            title=p.content.title,
            year=p.content.year,
            cluster=c,
            contributions=p.content.contributions or "",
            authors=p.content.authors,
        ))
    for c in clusters:
        clusters[c].sort(key=lambda n: n.year or 9999)
    return clusters
