from __future__ import annotations

import json

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return _client


def _chat(system: str, user: str, temperature: float = 0.3) -> str:
    client = _get_client()
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def extract_paper_structure(full_text: str, title_guess: str, abstract: str) -> dict:
    truncated = full_text[:8000]
    system = """你是一个学术论文分析助手。从论文文本中提取结构化信息，输出 JSON 格式。
字段：
- title: 论文标题
- authors: 作者列表（字符串数组）
- year: 发表年份（整数，找不到为 null）
- venue: 发表会议/期刊
- methods: 核心方法描述（2-3句话）
- contributions: 一句话贡献总结（强调相比前人的改进）
- conclusions: 主要结论（1-2句话）
- topic_cluster: 研究主题分类（3-5个词的英文短语）
只输出 JSON，不要其他内容。"""

    user = f"""论文标题猜测: {title_guess}
论文摘要: {abstract or '(未找到)'}

论文文本（前8000字符）:
{truncated}

请提取结构化信息，输出 JSON:"""

    result = _chat(system, user)
    try:
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        return {
            "title": title_guess,
            "authors": [],
            "year": None,
            "venue": "",
            "methods": "",
            "contributions": "",
            "conclusions": "",
            "topic_cluster": "",
        }


def parse_references_batch(references_raw: list[str]) -> list[dict]:
    if not references_raw:
        return []

    refs_text = "\n".join(f"[{i+1}] {r}" for i, r in enumerate(references_raw[:50]))
    system = """你是参考文献解析器。从每条参考文献中提取结构化信息，输出 JSON 数组。
每个元素：{"title": "...", "authors": "...", "year": 数字或null, "venue": "..."}
只输出 JSON 数组，不要其他内容。"""

    user = f"解析以下参考文献:\n{refs_text}"
    result = _chat(system, user)

    try:
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        return [{"title": r[:100], "authors": "", "year": None, "venue": ""} for r in references_raw[:50]]


def generate_contribution_summary(title: str, abstract: str, methods: str) -> str:
    system = "你是学术写作助手。用一句中文（30-60字）概括论文的核心贡献，强调相比前人工作的改进点。只输出这句话。"
    user = f"标题: {title}\n摘要: {abstract[:500]}\n方法: {methods[:300]}"
    return _chat(system, user).strip()


def generate_related_work_outline(papers: list[dict], user_interests: list[str]) -> str:
    paper_list = "\n".join(
        f"- [{p.get('title', '')}] ({p.get('year', '?')}): {p.get('contributions', p.get('abstract', '')[:100])}"
        for p in papers[:30]
    )
    interests = ", ".join(user_interests) if user_interests else "通用"

    system = """你是学术写作助手。根据提供的论文列表，按主题聚类生成 Related Work 章节大纲。
要求：
1. 按研究主题分组（每组2-5篇）
2. 每组写一段综述性描述（指出发展脉络）
3. 标注论文间的引用和改进关系
4. 输出 Markdown 格式
5. 用中文输出"""

    user = f"用户研究方向: {interests}\n\n论文列表:\n{paper_list}\n\n请生成 Related Work 大纲:"
    return _chat(system, user, temperature=0.5)


def find_semantic_connections(paper_title: str, paper_methods: str, existing_papers: list[dict]) -> list[dict]:
    if not existing_papers:
        return []

    existing_list = "\n".join(
        f"[{p['paper_id']}] {p['title']} - {p.get('methods', '')[:80]}"
        for p in existing_papers[:20]
    )

    system = """你是学术关联分析器。判断新论文与已有论文之间是否存在方法上的关联（相似方法、改进关系、应用到新场景等）。
输出 JSON 数组，每个元素：{"paper_id": "...", "relation": "改进|应用|相似|扩展", "reason": "一句话理由"}
只输出有关联的论文，没有关联则输出空数组 []。"""

    user = f"新论文: {paper_title}\n方法: {paper_methods[:300]}\n\n已有论文:\n{existing_list}\n\n输出 JSON 数组:"
    result = _chat(system, user)

    try:
        result = result.strip()
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        return []
