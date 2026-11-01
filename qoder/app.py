from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path

from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
from markupsafe import Markup

import config
from paper_artifacts import Paper, PaperContent, PaperQuery
from sync_paper_store import SyncPaperStore
from pdf_parser import extract_pdf
from vector_store import add_paper, auto_cluster, delete_paper as vec_delete, query_similar
from llm_utils import (
    extract_paper_structure,
    find_semantic_connections,
    generate_contribution_summary,
    generate_related_work_outline,
    parse_references_batch,
)
from graph_builder import (
    build_citation_relations,
    build_full_graph,
    build_cluster_graph,
    discover_semantic_links,
    get_cluster_summary,
    get_paper_timeline,
)


def make_paper(**kwargs) -> Paper:
    """Helper to create a Paper artifact with generated ID."""
    paper_id = kwargs.pop("paper_id", "") or str(uuid.uuid4())
    content = PaperContent(**kwargs)
    return Paper(artifact_id=paper_id, revision=1, content=content)


paper_store = SyncPaperStore(Path(config.DATA_DIR) / "papers_powercontext.db")
paper_store.init_db()

app = Flask(__name__)
app.secret_key = "paper-graph-secret-key"

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - 论文脉络图</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f23; color: #e0e0e0; display: flex; min-height: 100vh; }
        .sidebar { width: 220px; background: #1a1a2e; padding: 20px 0; position: fixed; height: 100vh; overflow-y: auto; border-right: 1px solid #333; }
        .sidebar h1 { font-size: 18px; padding: 0 20px 20px; border-bottom: 1px solid #333; color: #e94560; }
        .sidebar nav { padding: 15px 0; }
        .sidebar nav a { display: block; padding: 10px 20px; color: #aaa; text-decoration: none; transition: all 0.2s; font-size: 14px; }
        .sidebar nav a:hover, .sidebar nav a.active { background: #16213e; color: #fff; border-left: 3px solid #e94560; }
        .sidebar .stats { padding: 15px 20px; border-top: 1px solid #333; margin-top: auto; position: absolute; bottom: 0; width: 100%; font-size: 12px; color: #666; }
        .main { margin-left: 220px; padding: 30px; flex: 1; min-height: 100vh; }
        .main h2 { margin-bottom: 20px; color: #fff; font-size: 24px; }
        .card { background: #1a1a2e; border-radius: 8px; padding: 20px; margin-bottom: 20px; border: 1px solid #333; }
        .card h3 { margin-bottom: 12px; color: #e94560; font-size: 16px; }
        .metric-row { display: flex; gap: 20px; margin-bottom: 20px; }
        .metric { background: #16213e; border-radius: 8px; padding: 20px; flex: 1; text-align: center; border: 1px solid #333; }
        .metric .value { font-size: 32px; font-weight: bold; color: #e94560; }
        .metric .label { font-size: 12px; color: #888; margin-top: 5px; }
        .btn { display: inline-block; padding: 8px 16px; border-radius: 5px; border: none; cursor: pointer; font-size: 14px; text-decoration: none; transition: all 0.2s; }
        .btn-primary { background: #e94560; color: #fff; }
        .btn-primary:hover { background: #c73e54; }
        .btn-danger { background: #333; color: #e94560; border: 1px solid #e94560; }
        .btn-danger:hover { background: #e94560; color: #fff; }
        .btn-sm { padding: 4px 10px; font-size: 12px; }
        input[type="text"], input[type="number"], textarea, select {
            width: 100%; padding: 10px; border-radius: 5px; border: 1px solid #333;
            background: #0f0f23; color: #e0e0e0; font-size: 14px; margin-bottom: 10px;
        }
        textarea { resize: vertical; min-height: 80px; font-family: inherit; }
        label { display: block; margin-bottom: 5px; color: #aaa; font-size: 13px; }
        .paper-item { padding: 12px; border-bottom: 1px solid #222; }
        .paper-item:last-child { border-bottom: none; }
        .paper-item .title { font-weight: bold; color: #fff; margin-bottom: 4px; }
        .paper-item .meta { font-size: 12px; color: #888; }
        .paper-item .contrib { font-size: 13px; color: #aaa; margin-top: 4px; }
        .tag { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #16213e; color: #e94560; font-size: 11px; margin-right: 5px; }
        .flash { padding: 10px 15px; border-radius: 5px; margin-bottom: 15px; }
        .flash-success { background: #1a3a2a; border: 1px solid #2ec4b6; color: #2ec4b6; }
        .flash-error { background: #3a1a1a; border: 1px solid #e94560; color: #e94560; }
        .cluster-section { margin-bottom: 15px; }
        .cluster-section h4 { color: #e94560; margin-bottom: 8px; cursor: pointer; }
        .cluster-section .papers { padding-left: 15px; }
        .search-result { padding: 10px; border-bottom: 1px solid #222; }
        .similarity { color: #2ec4b6; font-size: 12px; }
        #graph-container { width: 100%; height: 600px; background: #1a1a2e; border-radius: 8px; border: 1px solid #333; }
        .legend { display: flex; gap: 20px; margin-bottom: 15px; font-size: 13px; }
        .legend-item { display: flex; align-items: center; gap: 5px; }
        .legend-dot { width: 12px; height: 12px; border-radius: 50%; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #222; }
        th { color: #888; font-size: 12px; text-transform: uppercase; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h1>📖 论文脉络图</h1>
        <nav>
            <a href="/" class="{{ 'active' if active == 'dashboard' else '' }}">📊 总览</a>
            <a href="/upload" class="{{ 'active' if active == 'upload' else '' }}">📤 上传论文</a>
            <a href="/library" class="{{ 'active' if active == 'library' else '' }}">📚 文献库</a>
            <a href="/search" class="{{ 'active' if active == 'search' else '' }}">🔍 语义检索</a>
            <a href="/graph" class="{{ 'active' if active == 'graph' else '' }}">🕸️ 脉络图</a>
            <a href="/profile" class="{{ 'active' if active == 'profile' else '' }}">👤 研究画像</a>
            <a href="/writing" class="{{ 'active' if active == 'writing' else '' }}">📝 写作助手</a>
        </nav>
        <div class="stats">文献库: {{ paper_count }} 篇论文</div>
    </div>
    <div class="main">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        {% for category, message in messages %}
        <div class="flash flash-{{ category }}">{{ message }}</div>
        {% endfor %}
        {% endif %}
        {% endwith %}
        {{ content }}
    </div>
</body>
</html>
"""

DASHBOARD_CONTENT = """
<h2>📊 文献库总览</h2>
<div class="metric-row">
    <div class="metric"><div class="value">{{ paper_count }}</div><div class="label">论文总数</div></div>
    <div class="metric"><div class="value">{{ cluster_count }}</div><div class="label">主题聚类</div></div>
    <div class="metric"><div class="value">{{ read_count }}</div><div class="label">已读论文</div></div>
</div>
<div class="card">
    <h3>按主题聚类</h3>
    {% for cluster, papers in clusters.items() %}
    <div class="cluster-section">
        <h4>{{ cluster }} ({{ papers|length }} 篇)</h4>
        <div class="papers">
            {% for p in papers %}
            <div class="paper-item">
                <div class="title">{{ p.content.title }} {% if p.content.year %}({{ p.content.year }}){% endif %}</div>
                {% if p.content.contributions %}<div class="contrib">💡 {{ p.content.contributions }}</div>{% endif %}
            </div>
            {% endfor %}
        </div>
    </div>
    {% endfor %}
    {% if not clusters %}<p style="color:#666">暂无论文</p>{% endif %}
</div>
"""

UPLOAD_CONTENT = """
<h2>📤 上传论文</h2>
<div class="card">
    <h3>批量上传</h3>
    <form method="POST" enctype="multipart/form-data" action="/upload/batch">
        <label>选择 PDF 文件（支持多选）</label>
        <input type="file" name="pdfs" accept=".pdf" multiple required>
        <br><br>
        <button type="submit" class="btn btn-primary">批量上传并解析</button>
    </form>
</div>
{% if papers %}
<div class="card">
    <h3>待确认论文 ({{ papers|length }} 篇)</h3>
    <form method="POST" action="/upload/save_batch">
        {% for paper in papers %}
        <div style="border:1px solid #333;border-radius:5px;padding:15px;margin-bottom:15px;background:#0f0f23">
            <input type="hidden" name="pdf_path_{{ loop.index0 }}" value="{{ paper.content.pdf_path }}">
            <input type="hidden" name="references_json_{{ loop.index0 }}" value="{{ paper.content.references | tojson }}">
            <input type="hidden" name="is_duplicate_{{ loop.index0 }}" value="{{ paper.is_duplicate | default(false) }}">
            <input type="hidden" name="duplicate_id_{{ loop.index0 }}" value="{{ paper.duplicate_id | default('') }}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                <strong style="color:#e94560">论文 {{ loop.index }}</strong>
                <div>
                    {% if paper.is_duplicate %}
                    <span class="tag" style="background:#3a1a1a;color:#e94560">⚠️ 可能重复</span>
                    {% endif %}
                    {% if paper.content.is_relevant %}
                    <span class="tag" style="background:#1a3a2a;color:#2ec4b6"> 与你的研究相关</span>
                    {% endif %}
                </div>
            </div>
            <label>标题</label>
            <input type="text" name="title_{{ loop.index0 }}" value="{{ paper.content.title }}" required>
            <label>作者（逗号分隔）</label>
            <input type="text" name="authors_{{ loop.index0 }}" value="{{ paper.content.authors | join(', ') }}">
            <label>年份</label>
            <input type="number" name="year_{{ loop.index0 }}" value="{{ paper.content.year or 2024 }}">
            <label>会议/期刊</label>
            <input type="text" name="venue_{{ loop.index0 }}" value="{{ paper.content.venue }}">
            <label>摘要</label>
            <textarea name="abstract_{{ loop.index0 }}" rows="3">{{ paper.content.abstract }}</textarea>
            <label>核心方法</label>
            <textarea name="methods_{{ loop.index0 }}" rows="2">{{ paper.content.methods }}</textarea>
            <label>主题分类</label>
            <input type="text" name="topic_cluster_{{ loop.index0 }}" value="{{ paper.content.topic_cluster }}">
            <label>贡献总结</label>
            <textarea name="contributions_{{ loop.index0 }}" rows="2">{{ paper.content.contributions }}</textarea>
        </div>
        {% endfor %}
        <button type="submit" class="btn btn-primary">✅ 批量保存 ({{ papers|length }} 篇)</button>
    </form>
</div>
{% endif %}
{% if duplicates %}
<div class="card">
    <h3>️ 检测到重复论文 ({{ duplicates|length }} 篇)</h3>
    {% for dup in duplicates %}
    <div style="border:1px solid #e94560;border-radius:5px;padding:10px;margin-bottom:10px;background:#3a1a1a">
        <strong>{{ dup.new_title }}</strong>
        <div style="font-size:12px;color:#aaa;margin-top:5px">与已有论文相似: <strong>{{ dup.existing_title }}</strong></div>
        <div style="font-size:12px;color:#888;margin-top:3px">相似度: {{ "%.0f" | format(dup.similarity * 100) }}%</div>
    </div>
    {% endfor %}
</div>
{% endif %}
"""

LIBRARY_CONTENT = """
<h2>📚 文献库</h2>
<div class="card">
    <div style="display:flex;gap:10px;align-items:end">
        <div style="flex:1">
            <label>按聚类筛选</label>
            <form method="GET" action="/library" style="margin:0">
                <select name="cluster" onchange="this.form.submit()">
                    <option value="">全部聚类</option>
                    {% for c in clusters %}
                    <option value="{{ c }}" {{ 'selected' if selected_cluster == c else '' }}>{{ c }}</option>
                    {% endfor %}
                </select>
            </form>
        </div>
        <div style="flex:1">
            <label>按相关性筛选</label>
            <form method="GET" action="/library" style="margin:0">
                <select name="relevant" onchange="this.form.submit()">
                    <option value="">全部论文</option>
                    <option value="yes" {{ 'selected' if selected_relevant == 'yes' else '' }}>与我的研究相关</option>
                    <option value="no" {{ 'selected' if selected_relevant == 'no' else '' }}>与我的研究无关</option>
                </select>
            </form>
        </div>
        <div style="flex:1">
            <label>自动聚类</label>
            <form method="POST" action="/library/cluster" style="display:flex;gap:5px;margin:0">
                <input type="number" name="threshold" value="0.5" min="0.1" max="0.9" step="0.1" style="width:80px;margin:0" title="相似度阈值（越高聚类越细）">
                <button type="submit" class="btn btn-primary" style="margin:0">🔄 重新聚类</button>
            </form>
        </div>
    </div>
    <p style="font-size:12px;color:#666;margin-top:10px">💡 基于论文向量相似度自动聚类，阈值越高聚类越细（0.3=粗聚类，0.7=细聚类）</p>
</div>
{% for p in papers %}
<div class="card" style="{{ 'border-left:3px solid #2ec4b6' if p.content.is_relevant else '' }}">
    <div style="display:flex; justify-content:space-between; align-items:start;">
        <div>
            <h3>{{ p.content.title }} {% if p.content.year %}({{ p.content.year }}){% endif %} {% if p.content.is_relevant %}<span class="tag" style="background:#1a3a2a;color:#2ec4b6">相关</span>{% endif %}</h3>
            {% if p.content.authors %}<div class="meta" style="color:#888;font-size:13px">👤 {{ p.content.authors | join(', ') }}</div>{% endif %}
            {% if p.content.venue %}<div class="meta" style="color:#888;font-size:13px">📍 {{ p.content.venue }}</div>{% endif %}
        </div>
        <div style="display:flex;gap:8px;">
            {% if p.artifact_id in read_set %}
            <span class="tag">✅ 已读</span>
            {% else %}
            <a href="/library/read/{{ p.artifact_id }}" class="btn btn-sm btn-primary">标记已读</a>
            {% endif %}
            <a href="/library/delete/{{ p.artifact_id }}" class="btn btn-sm btn-danger" onclick="return confirm('确定删除?')">删除</a>
        </div>
    </div>
    {% if p.content.contributions %}<div class="contrib" style="margin-top:8px">💡 {{ p.content.contributions }}</div>{% endif %}
    {% if p.content.methods %}<div class="contrib">🔧 {{ p.content.methods }}</div>{% endif %}
    {% if p.content.topic_cluster %}<div style="margin-top:5px"><span class="tag">{{ p.content.topic_cluster }}</span></div>{% endif %}
</div>
{% endfor %}
{% if not papers %}<div class="card"><p style="color:#666">暂无论文</p></div>{% endif %}
"""

SEARCH_CONTENT = """
<h2>🔍 语义检索</h2>
<div class="card">
    <form method="GET" action="/search">
        <label>输入查询（支持自然语言）</label>
        <input type="text" name="q" value="{{ query }}" placeholder="例如: 图神经网络在知识图谱中的应用">
        <label>返回数量</label>
        <input type="number" name="n" value="{{ n }}" min="1" max="50">
        <button type="submit" class="btn btn-primary">搜索</button>
    </form>
</div>
{% if results %}
{% for r in results %}
<div class="card search-result">
    <div style="display:flex;justify-content:space-between">
        <strong>{{ r.metadata.get('title', r.paper_id) }}</strong>
        <span class="similarity">相似度: {{ "%.1f" | format(r.similarity * 100) }}%</span>
    </div>
    {% if r.metadata.get('year') %}<div class="meta">年份: {{ r.metadata.year }}</div>{% endif %}
    <div class="contrib" style="margin-top:5px;font-size:13px;color:#aaa">{{ r.document[:300] }}...</div>
</div>
{% endfor %}
{% elif query %}
<div class="card"><p style="color:#666">未找到相关论文</p></div>
{% endif %}
"""

GRAPH_CONTENT = """
<h2>🕸️ 论文脉络图</h2>
<div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#e94560"></div> 引用关系</div>
    <div class="legend-item"><div class="legend-dot" style="background:#00d2ff"></div> 语义相似</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ff9f1c"></div> 同一作者</div>
</div>
{% if clusters %}
<div class="card" style="padding:10px 20px">
    <form method="GET" action="/graph" style="display:flex;align-items:center;gap:10px;margin:0">
        <label style="margin:0;white-space:nowrap">按聚类筛选:</label>
        <select name="cluster" onchange="this.form.submit()" style="margin:0;width:auto">
            <option value="">全部</option>
            {% for c in clusters %}
            <option value="{{ c }}" {{ 'selected' if selected_cluster == c else '' }}>{{ c }}</option>
            {% endfor %}
        </select>
    </form>
</div>
{% endif %}
<div id="graph-container"></div>
<script>
var chart = echarts.init(document.getElementById('graph-container'));
var data = {{ graph_data | safe }};
var option = {
    backgroundColor: '#1a1a2e',
    tooltip: {
        trigger: 'item',
        formatter: function(p) {
            if (p.dataType === 'node') return '<b>' + p.data.title + '</b><br/>' + (p.data.contrib || '');
            return p.data.source_name + ' → ' + p.data.target_name + '<br/>类型: ' + p.data.relation;
        }
    },
    series: [{
        type: 'graph',
        layout: 'force',
        data: data.nodes,
        links: data.links,
        roam: true,
        draggable: true,
        force: { repulsion: 300, gravity: 0.1, edgeLength: [100, 250] },
        label: { show: true, position: 'right', fontSize: 10, color: '#ccc' },
        edgeLabel: { show: false },
        lineStyle: { curveness: 0.2, opacity: 0.6 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        categories: data.categories
    }]
};
chart.setOption(option);
window.addEventListener('resize', function() { chart.resize(); });
</script>
"""

PROFILE_CONTENT = """
<h2>👤 研究画像</h2>
<div class="card" style="background:#16213e;border:1px solid #2ec4b6">
    <h3 style="color:#2ec4b6">💡 这个功能有什么用？</h3>
    <p style="color:#ccc;line-height:1.6">
        研究画像用于记录你的研究方向和关注关键词，系统会基于此：<br>
        • <strong>上传论文时</strong>：自动标记与你的研究相关的论文<br>
        • <strong>文献库中</strong>：可筛选出与你研究方向相关的论文<br>
        • <strong>写作助手</strong>：优先生成与你研究方向相关的大纲
    </p>
</div>
<div class="card">
    <form method="POST" action="/profile">
        <label>姓名/昵称</label>
        <input type="text" name="name" value="{{ profile.name }}">
        <label>研究方向（每行一个，例如：Graph Neural Networks）</label>
        <textarea name="interests" rows="4" placeholder="Graph Neural Networks&#10;Knowledge Graphs&#10;Node Classification">{{ profile.research_interests | join('\\n') }}</textarea>
        <label>关注关键词（每行一个，例如：attention mechanism, GNN）</label>
        <textarea name="keywords" rows="4" placeholder="attention mechanism&#10;GNN&#10;link prediction">{{ profile.focus_keywords | join('\\n') }}</textarea>
        <br>
        <button type="submit" class="btn btn-primary">💾 保存画像</button>
    </form>
</div>
<div class="card">
    <h3>阅读进度</h3>
    <div style="display:flex;gap:30px">
        <div style="flex:1">
            <h4 style="color:#2ec4b6;margin-bottom:10px">已读 ({{ read_papers|length }})</h4>
            {% for p in read_papers %}
            <div class="paper-item"><div class="title" style="text-decoration:line-through;color:#666">{{ p.content.title }}</div></div>
            {% endfor %}
        </div>
        <div style="flex:1">
            <h4 style="color:#e94560;margin-bottom:10px">未读 ({{ unread_papers|length }})</h4>
            {% for p in unread_papers %}
            <div class="paper-item"><div class="title">{{ p.content.title }}</div></div>
            {% endfor %}
        </div>
    </div>
</div>
"""

WRITING_CONTENT = """
<h2>📝 写作助手</h2>
<div class="card">
    <h3>生成 Related Work 大纲</h3>
    <form method="POST" action="/writing/generate">
        <label>选择主题</label>
        <select name="cluster">
            <option value="">全部主题概览</option>
            {% for c in clusters %}
            <option value="{{ c }}" {{ 'selected' if selected_cluster == c else '' }}>{{ c }}</option>
            {% endfor %}
        </select>
        <br>
        <button type="submit" class="btn btn-primary">🚀 生成大纲</button>
    </form>
    {% if selected_cluster %}
    <p style="margin-top:10px;color:#888;font-size:13px">当前选择: <strong style="color:#2ec4b6">{{ selected_cluster }}</strong></p>
    {% endif %}
</div>
{% if outline %}
<div class="card">
    <h3>📄 生成结果</h3>
    <div style="white-space:pre-wrap;line-height:1.8;color:#ccc;font-family:'Courier New',monospace;font-size:14px;background:#1a1a1a;padding:20px;border-radius:8px;overflow-x:auto">{{ outline }}</div>
</div>
{% endif %}
<div class="card">
    <h3>📚 相关论文 ({{ papers | length }} 篇)</h3>
    {% for p in papers[:10] %}
    <div class="paper-item" style="margin-bottom:15px;padding:10px;background:#1a1a1a;border-radius:5px">
        <div class="title" style="font-size:15px;margin-bottom:5px">{{ p.content.title }} {% if p.content.year %}<span style="color:#888">({{ p.content.year }})</span>{% endif %}</div>
        {% if p.content.topic_cluster %}<div style="color:#2ec4b6;font-size:12px;margin-bottom:5px">主题: {{ p.content.topic_cluster }}</div>{% endif %}
        {% if p.content.contributions %}
        <div class="contrib" style="color:#aaa;font-size:13px">💡 {{ p.content.contributions }}</div>
        {% elif p.content.abstract %}
        <div class="contrib" style="color:#aaa;font-size:13px">📝 {{ p.content.abstract[:150] }}...</div>
        {% endif %}
    </div>
    {% endfor %}
    {% if papers | length > 10 %}
    <p style="color:#666;font-size:13px">...还有 {{ papers | length - 10 }} 篇论文</p>
    {% endif %}
    {% if not papers %}<p style="color:#666">暂无论文，请选择其他主题</p>{% endif %}
</div>
"""


def _render(title, content, active, **kwargs):
    return render_template_string(
        BASE_TEMPLATE,
        title=title,
        content=Markup(render_template_string(content, **kwargs)),
        active=active,
        paper_count=paper_store.get_paper_count(),
    )


@app.route("/")
def dashboard():
    summary = get_cluster_summary()
    profile = paper_store.get_profile()
    return _render(
        "总览", DASHBOARD_CONTENT, "dashboard",
        paper_count=paper_store.get_paper_count(),
        cluster_count=len(summary),
        read_count=len(profile.read_papers),
        clusters=summary,
    )


@app.route("/upload", methods=["GET"])
def upload():
    return _render("上传论文", UPLOAD_CONTENT, "upload", papers=[], duplicates=[])


@app.route("/upload/batch", methods=["POST"])
def upload_batch():
    files = request.files.getlist("pdfs")
    if not files:
        flash("请选择 PDF 文件", "error")
        return redirect(url_for("upload"))

    papers = []
    duplicates = []

    for f in files:
        if not f.filename or not f.filename.endswith(".pdf"):
            continue

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        f.save(tmp.name)
        tmp.close()

        pdf_content = extract_pdf(tmp.name)

        if config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
            extracted = extract_paper_structure(pdf_content.full_text, pdf_content.title_guess, pdf_content.abstract)
        else:
            extracted = {
                "title": pdf_content.title_guess,
                "authors": [],
                "year": None,
                "venue": "",
                "methods": "",
                "contributions": "",
                "conclusions": "",
                "topic_cluster": "",
            }

        paper_content = PaperContent(
            title=extracted.get("title", pdf_content.title_guess),
            authors=extracted.get("authors", []),
            year=extracted.get("year"),
            venue=extracted.get("venue", ""),
            abstract=pdf_content.abstract or extracted.get("abstract", ""),
            methods=extracted.get("methods", ""),
            contributions=extracted.get("contributions", ""),
            conclusions=extracted.get("conclusions", ""),
            topic_cluster=extracted.get("topic_cluster", ""),
            pdf_path=tmp.name,
            references=[],
        )
        paper = Paper(
            artifact_id="",
            revision=1,
            content=paper_content,
        )

        # Check for duplicates
        existing = paper_store.find_duplicate(paper.content.title)
        if existing:
            paper.content.is_duplicate = True
            paper.content.duplicate_id = existing.artifact_id
            duplicates.append({
                "new_title": paper.content.title,
                "existing_title": existing.content.title,
                "similarity": 0.9,
            })
        else:
            paper.content.is_duplicate = False
            paper.content.duplicate_id = ""

        # Check if relevant to user's research
        profile = paper_store.get_profile()
        paper.content.is_relevant = paper_store.is_paper_relevant(paper, profile.research_interests, profile.focus_keywords)

        papers.append(paper)

    if not papers:
        flash("未找到有效的 PDF 文件", "error")
        return redirect(url_for("upload"))

    return _render("上传论文", UPLOAD_CONTENT, "upload", papers=papers, duplicates=duplicates)


@app.route("/upload/save_batch", methods=["POST"])
def upload_save_batch():
    saved_count = 0
    skipped_count = 0

    # Count how many papers were submitted
    idx = 0
    while True:
        title_key = f"title_{idx}"
        if title_key not in request.form:
            break

        is_duplicate = request.form.get(f"is_duplicate_{idx}", "false") == "true"
        duplicate_id = request.form.get(f"duplicate_id_{idx}", "")

        # Skip if marked as duplicate and user didn't override
        if is_duplicate and not request.form.get(f"override_{idx}"):
            skipped_count += 1
            idx += 1
            continue

        paper_content = PaperContent(
            title=request.form[title_key],
            authors=[a.strip() for a in request.form.get(f"authors_{idx}", "").split(",") if a.strip()],
            year=int(request.form[f"year_{idx}"]) if request.form.get(f"year_{idx}") else None,
            venue=request.form.get(f"venue_{idx}", ""),
            abstract=request.form.get(f"abstract_{idx}", ""),
            methods=request.form.get(f"methods_{idx}", ""),
            contributions=request.form.get(f"contributions_{idx}", ""),
            topic_cluster=request.form.get(f"topic_cluster_{idx}", ""),
        )
        paper = Paper(artifact_id=str(uuid.uuid4()), revision=1, content=paper_content)

        pdf_src = request.form.get(f"pdf_path_{idx}", "")
        if pdf_src and Path(pdf_src).exists():
            pdf_dest = config.UPLOAD_DIR / f"{paper.artifact_id}.pdf"
            shutil.copy2(pdf_src, str(pdf_dest))
            paper_content = PaperContent(**{**paper.content.model_dump(), "pdf_path": str(pdf_dest)})
            paper = Paper(artifact_id=paper.artifact_id, revision=1, content=paper_content)
            Path(pdf_src).unlink(missing_ok=True)

        if config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
            contrib = generate_contribution_summary(paper.content.title, paper.content.abstract, paper.content.methods) or paper.content.contributions
            paper_content = PaperContent(**{**paper.content.model_dump(), "contributions": contrib})
            paper = Paper(artifact_id=paper.artifact_id, revision=1, content=paper_content)

        paper_store.save_paper(paper)
        add_paper(paper.artifact_id, f"{paper.content.title}. {paper.content.abstract}. {paper.content.methods}", {
            "title": paper.content.title, "year": paper.content.year, "cluster": paper.content.topic_cluster,
            "authors": ", ".join(paper.content.authors),
        })

        refs_json = request.form.get(f"references_json_{idx}", "[]")
        try:
            refs = json.loads(refs_json)
            if refs:
                paper_content = PaperContent(**{**paper.content.model_dump(), "references": refs})
                paper = Paper(artifact_id=paper.artifact_id, revision=paper.revision + 1, content=paper_content)
                paper_store.save_paper(paper)
                build_citation_relations(paper.artifact_id, refs)
        except json.JSONDecodeError:
            pass

        existing = [{"paper_id": p.artifact_id, "title": p.content.title, "methods": p.content.methods} for p in paper_store.list_papers() if p.artifact_id != paper.artifact_id]
        if existing and config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
            connections = find_semantic_connections(paper.content.title, paper.content.methods, existing)
            for c in connections:
                from database import PaperRelation, save_relation
                save_relation(PaperRelation(source_id=paper.artifact_id, target_id=c["paper_id"], relation_type="semantic_similar", weight=0.8))
            discover_semantic_links(paper.artifact_id)

        saved_count += 1
        idx += 1

    flash(f"已保存 {saved_count} 篇论文" + (f"，跳过 {skipped_count} 篇重复" if skipped_count else ""), "success")
    return redirect(url_for("library"))


@app.route("/upload/save", methods=["POST"])
def upload_save():
    paper_content = PaperContent(
        title=request.form["title"],
        authors=[a.strip() for a in request.form.get("authors", "").split(",") if a.strip()],
        year=int(request.form["year"]) if request.form.get("year") else None,
        venue=request.form.get("venue", ""),
        abstract=request.form.get("abstract", ""),
        methods=request.form.get("methods", ""),
        contributions=request.form.get("contributions", ""),
        topic_cluster=request.form.get("topic_cluster", ""),
    )
    paper = Paper(artifact_id=str(uuid.uuid4()), revision=1, content=paper_content)

    pdf_src = request.form.get("pdf_path", "")
    if pdf_src and Path(pdf_src).exists():
        pdf_dest = config.UPLOAD_DIR / f"{paper.artifact_id}.pdf"
        shutil.copy2(pdf_src, str(pdf_dest))
        paper_content = PaperContent(**{**paper.content.model_dump(), "pdf_path": str(pdf_dest)})
        paper = Paper(artifact_id=paper.artifact_id, revision=1, content=paper_content)
        Path(pdf_src).unlink(missing_ok=True)

    if config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
        contrib = generate_contribution_summary(paper.content.title, paper.content.abstract, paper.content.methods) or paper.content.contributions
        paper_content = PaperContent(**{**paper.content.model_dump(), "contributions": contrib})
        paper = Paper(artifact_id=paper.artifact_id, revision=1, content=paper_content)

    paper_store.save_paper(paper)
    add_paper(paper.artifact_id, f"{paper.content.title}. {paper.content.abstract}. {paper.content.methods}", {
        "title": paper.content.title, "year": paper.content.year, "cluster": paper.content.topic_cluster,
        "authors": ", ".join(paper.content.authors),
    })

    refs_json = request.form.get("references_json", "[]")
    try:
        refs = json.loads(refs_json)
        if refs:
            paper_content = PaperContent(**{**paper.content.model_dump(), "references": refs})
            paper = Paper(artifact_id=paper.artifact_id, revision=paper.revision + 1, content=paper_content)
            paper_store.save_paper(paper)
            build_citation_relations(paper.artifact_id, refs)
    except json.JSONDecodeError:
        pass

    existing = [{"paper_id": p.artifact_id, "title": p.content.title, "methods": p.content.methods} for p in paper_store.list_papers() if p.artifact_id != paper.artifact_id]
    if existing and config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
        connections = find_semantic_connections(paper.content.title, paper.content.methods, existing)
        for c in connections:
            from database import PaperRelation, save_relation
            save_relation(PaperRelation(source_id=paper.artifact_id, target_id=c["paper_id"], relation_type="semantic_similar", weight=0.8))
        discover_semantic_links(paper.artifact_id)

    flash(f"已保存: {paper.content.title}", "success")
    return redirect(url_for("library"))


@app.route("/library/cluster", methods=["POST"])
def library_cluster():
    """自动聚类论文"""
    threshold = float(request.form.get("threshold", "0.5"))
    cluster_map = auto_cluster(similarity_threshold=threshold)
    paper_store.batch_update_clusters(cluster_map)
    flash(f"已完成自动聚类，共 {len(set(cluster_map.values()))} 个主题", "success")
    return redirect(url_for("library"))


@app.route("/library")
def library():
    cluster = request.args.get("cluster", "")
    relevant_filter = request.args.get("relevant", "")
    papers = paper_store.list_papers()
    if cluster:
        papers = [p for p in papers if p.content.topic_cluster == cluster]

    profile = paper_store.get_profile()
    # 标记每篇论文是否与用户研究相关
    for p in papers:
        p.content.is_relevant = paper_store.is_paper_relevant(p, profile.research_interests, profile.focus_keywords)

    # 按相关性筛选
    if relevant_filter == "yes":
        papers = [p for p in papers if p.content.is_relevant]
    elif relevant_filter == "no":
        papers = [p for p in papers if not p.content.is_relevant]

    return _render(
        "文献库", LIBRARY_CONTENT, "library",
        papers=papers,
        clusters=paper_store.get_clusters(),
        selected_cluster=cluster,
        selected_relevant=relevant_filter,
        read_set=set(profile.read_papers),
    )


@app.route("/library/read/<paper_id>")
def library_read(paper_id):
    paper_store.mark_paper_read(paper_id)
    flash("已标记为已读", "success")
    return redirect(url_for("library"))


@app.route("/library/delete/<paper_id>")
def library_delete(paper_id):
    paper_store.delete_paper(paper_id)
    vec_delete(paper_id)
    flash("已删除", "success")
    return redirect(url_for("library"))


@app.route("/search")
def search():
    q = request.args.get("q", "")
    n = int(request.args.get("n", "5"))
    results = []
    if q:
        results = query_similar(q, n_results=n)
    return _render("语义检索", SEARCH_CONTENT, "search", query=q, n=n, results=results)


@app.route("/graph")
def graph():
    cluster = request.args.get("cluster", "")
    if cluster:
        nodes, edges = build_cluster_graph(cluster)
    else:
        nodes, edges = build_full_graph()

    cluster_set = set()
    for n in nodes:
        if n.cluster:
            cluster_set.add(n.cluster)
    cluster_list = sorted(cluster_set)

    cluster_colors = {}
    palette = ["#e94560", "#00d2ff", "#ff9f1c", "#2ec4b6", "#98c1d9", "#3d5a80", "#e71d36", "#533483"]
    for i, c in enumerate(cluster_list):
        cluster_colors[c] = palette[i % len(palette)]

    categories = [{"name": c} for c in cluster_list] if cluster_list else [{"name": "未分类"}]

    edge_colors = {"citation": "#e94560", "semantic_similar": "#00d2ff", "same_author": "#ff9f1c"}

    graph_nodes = []
    for n in nodes:
        c = n.cluster or "未分类"
        degree = len([e for e in edges if e.source == n.id or e.target == n.id])
        graph_nodes.append({
            "id": n.id,
            "name": f"{n.year or ''} {n.title[:25]}".strip(),
            "title": n.title,
            "contrib": n.contributions or "",
            "symbolSize": min(20 + degree * 5, 50),
            "category": cluster_list.index(c) if c in cluster_list else 0,
            "itemStyle": {"color": cluster_colors.get(c, "#666")},
        })

    graph_links = []
    for e in edges:
        src_paper = paper_store.get_paper(e.source)
        tgt_paper = paper_store.get_paper(e.target)
        graph_links.append({
            "source": e.source,
            "target": e.target,
            "source_name": src_paper.content.title if src_paper else e.source,
            "target_name": tgt_paper.content.title if tgt_paper else e.target,
            "relation": e.relation_type,
            "lineStyle": {"color": edge_colors.get(e.relation_type, "#666"), "width": max(1, min((e.weight or 1.0) * 3, 5))},
        })

    graph_data = json.dumps({"nodes": graph_nodes, "links": graph_links, "categories": categories}, ensure_ascii=False)

    return _render(
        "脉络图", GRAPH_CONTENT, "graph",
        graph_data=graph_data,
        clusters=cluster_list,
        selected_cluster=cluster,
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    p = paper_store.get_profile()
    if request.method == "POST":
        p.name = request.form.get("name", "")
        p.research_interests = [l.strip() for l in request.form.get("interests", "").split("\n") if l.strip()]
        p.focus_keywords = [l.strip() for l in request.form.get("keywords", "").split("\n") if l.strip()]
        paper_store.save_profile(p)
        flash("画像已保存", "success")
        return redirect(url_for("profile"))

    papers = paper_store.list_papers()
    read_set = set(p.read_papers)
    return _render(
        "研究画像", PROFILE_CONTENT, "profile",
        profile=p,
        read_papers=[pp for pp in papers if pp.artifact_id in read_set],
        unread_papers=[pp for pp in papers if pp.artifact_id not in read_set],
    )


@app.route("/writing")
def writing():
    return _render(
        "写作助手", WRITING_CONTENT, "writing",
        papers=paper_store.list_papers(),
        clusters=paper_store.get_clusters(),
        outline=None,
    )


@app.route("/writing/generate", methods=["POST"])
def writing_generate():
    cluster = request.form.get("cluster", "")
    papers = paper_store.list_papers()
    if cluster:
        papers = [p for p in papers if p.content.topic_cluster == cluster]

    profile = paper_store.get_profile()
    paper_dicts = [{"title": p.content.title, "year": p.content.year, "contributions": p.content.contributions, "abstract": p.content.abstract} for p in papers]

    outline = ""
    if config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-your"):
        outline = generate_related_work_outline(paper_dicts, profile.research_interests)
    else:
        # 生成 Related Work 风格的内容
        lines = []
        
        if cluster:
            # 用户选择了特定主题，只生成该主题的内容
            lines.append(f"## {cluster}\n")
            lines.append(f"本章节综述了与 **{cluster}** 相关的 {len(papers)} 篇论文。\n")
            
            # 按年份排序
            sorted_papers = sorted(papers, key=lambda p: p.content.year or 0, reverse=True)
            
            # 生成综述内容
            for i, p in enumerate(sorted_papers, 1):
                year_str = f" ({p.content.year})" if p.content.year else ""
                authors_str = ", ".join(p.content.authors[:3]) if p.content.authors else "Unknown"
                if len(p.content.authors) > 3:
                    authors_str += " et al."
                
                lines.append(f"### {i}. {p.content.title}{year_str}\n")
                lines.append(f"**作者**: {authors_str}\n")
                
                # 如果有贡献，优先显示贡献
                if p.content.contributions:
                    lines.append(f"**主要贡献**: {p.content.contributions}\n")
                elif p.content.abstract:
                    # 否则显示摘要的前200字符
                    abstract_preview = p.content.abstract[:200] + "..." if len(p.content.abstract) > 200 else p.content.abstract
                    lines.append(f"**摘要**: {abstract_preview}\n")
                
                # 如果有方法，显示方法
                if p.content.methods:
                    lines.append(f"**方法**: {p.content.methods}\n")
                
                lines.append("")
        else:
            # 用户没有选择主题，按主题分组显示概览
            lines.append("# 研究主题概览\n")
            lines.append(f"共收录 {len(papers)} 篇论文，分布在 {len(set(p.content.topic_cluster for p in papers if p.content.topic_cluster))} 个主题领域。\n")
            
            clusters_map = {}
            for p in papers:
                c = p.content.topic_cluster or "未分类"
                if c not in clusters_map:
                    clusters_map[c] = []
                clusters_map[c].append(p)
            
            for c, ps in sorted(clusters_map.items(), key=lambda x: len(x[1]), reverse=True):
                lines.append(f"## {c} ({len(ps)} 篇)\n")
                # 按年份排序
                sorted_ps = sorted(ps, key=lambda p: p.content.year or 0, reverse=True)
                for p in sorted_ps[:5]:  # 每个主题最多显示5篇
                    year_str = f" ({p.content.year})" if p.content.year else ""
                    contrib = p.content.contributions or (p.content.abstract[:100] + "..." if p.content.abstract else "暂无摘要")
                    lines.append(f"- **{p.content.title}**{year_str}: {contrib}")
                if len(ps) > 5:
                    lines.append(f"- *...还有 {len(ps) - 5} 篇论文*")
                lines.append("")
        
        outline = "\n".join(lines)

    return _render(
        "写作助手", WRITING_CONTENT, "writing",
        papers=papers,
        clusters=paper_store.get_clusters(),
        outline=outline,
        selected_cluster=cluster,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
