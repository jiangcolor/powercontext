const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8080'
  : '';

async function api(path, options = {}) {
  const url = `${API_BASE}/api${path}`;
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    const error = await resp.text();
    throw new Error(`API Error ${resp.status}: ${error}`);
  }
  return resp.json();
}

function showToast(message, type = 'info') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return dateStr;
  }
}

function statusLabel(status) {
  const labels = { success: '成功', failed: '失败', inconclusive: '不确定' };
  return labels[status] || status;
}

function renderExperimentCard(exp, showCheckbox = false) {
  const paramsHtml = Object.entries(exp.parameters || {})
    .map(([k, v]) => `<span>${k}: ${v}</span>`)
    .join('');
  const metricsHtml = Object.entries(exp.metrics || {})
    .map(([k, v]) => `<span>${k}: ${v}</span>`)
    .join('');
  const tagsHtml = (exp.tags || [])
    .map(t => `<span class="tag">${t}</span>`)
    .join('');

  return `
    <div class="experiment-card ${showCheckbox ? 'search-result' : ''}" data-id="${exp.id}">
      ${showCheckbox ? `<input type="checkbox" class="compare-checkbox" value="${exp.id}" title="加入对比">` : ''}
      ${exp.distance != null ? `<span class="relevance">相关度: ${(1 / (1 + exp.distance)).toFixed(2)}</span>` : ''}
      <div class="exp-header">
        <span class="exp-title">${exp.title || '未命名实验'}</span>
        <span class="exp-date">${formatDate(exp.date)}</span>
      </div>
      ${tagsHtml ? `<div class="exp-tags">${tagsHtml}</div>` : ''}
      <span class="status-badge ${exp.status}">${statusLabel(exp.status)}</span>
      ${paramsHtml ? `<div class="exp-params"><strong>参数:</strong> ${paramsHtml}</div>` : ''}
      ${metricsHtml ? `<div class="exp-metrics"><strong>指标:</strong> ${metricsHtml}</div>` : ''}
      ${exp.notes ? `<div class="exp-notes">${exp.notes}</div>` : ''}
      <div class="exp-actions">
        <button class="btn btn-danger btn-sm" onclick="deleteExperiment('${exp.id}')">删除</button>
      </div>
    </div>
  `;
}

async function deleteExperiment(id) {
  if (!confirm('确定要删除这条实验记录吗？')) return;
  try {
    await api(`/experiments/${id}`, { method: 'DELETE' });
    showToast('已删除', 'success');
    if (typeof loadExperiments === 'function') loadExperiments();
    if (typeof performSearch === 'function' && document.querySelector('.search-box input')?.value) {
      performSearch();
    }
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error');
  }
}
