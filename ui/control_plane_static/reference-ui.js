(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const node = $(id); if (node) node.textContent = value == null || value === "" ? "—" : String(value); };
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const fmtNumber = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  const fmtPercent = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : "—";
  const fmtDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ko-KR", { hour12: false });
  };
  const statusLabel = (value) => ({ queued: "대기 중", running: "실행 중", cancelling: "취소 중", completed: "완료", failed: "실패", blocked: "안전 중단", cancelled: "취소됨", interrupted: "중단" }[value] || value || "—");
  const scenarioDescriptions = {
    "Pod Failure": "Pod 비정상 종료",
    "CPU Saturation": "CPU 과부하",
    "Memory Saturation": "Memory 과부하",
    "Network Delay": "네트워크 지연",
  };
  const RESULT_QUERY_MAP = {
    period: "history-period",
    scenario: "history-scenario",
    controller: "history-controller",
    mode: "history-mode",
    status: "history-status",
    q: "history-search",
  };
  const aiopslabState = { jobs: [], tab: "evaluation", historyPage: 1, historyPageSize: 8, historyStatus: "all", historyQuery: "", loading: false, error: "" };
  const resultState = { page: 1, pageSize: 10, syncing: false, searchTimer: null };

  function requestJson(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(async (response) => {
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail || `요청 실패 (${response.status})`);
      return payload;
    });
  }

  function selectedScenarioLabel() {
    const selected = document.querySelector('#scenario-list button[aria-pressed="true"] strong');
    return selected ? selected.textContent.trim() : ($('global-scenario')?.textContent.trim() || "—");
  }

  function selectedControllerLabel() {
    const selected = document.querySelector('#controller-options button[aria-pressed="true"] strong');
    return selected ? selected.textContent.trim() : ($('global-controller')?.textContent.trim() || "—");
  }

  function selectedModeLabel() {
    const selected = document.querySelector('#mode-control button[aria-pressed="true"] strong');
    if (selected) return selected.textContent.trim();
    const fallback = $('overview-mode-select');
    return fallback && fallback.selectedOptions.length ? fallback.selectedOptions[0].textContent.trim() : "—";
  }

  function syncReferenceSummary() {
    const scenario = selectedScenarioLabel();
    const controller = selectedControllerLabel();
    const mode = selectedModeLabel();
    text('overview-current-scenario', scenario);
    text('overview-current-controller', controller);
    text('overview-current-mode', mode);
    text('recovery-header-controller', controller === 'Deterministic Mutual Supervision' ? 'Deterministic' : controller);
    text('selected-summary-scenario', scenario);
    text('selected-summary-scenario-desc', scenarioDescriptions[scenario] || '등록된 장애 시나리오');
    text('selected-summary-controller', controller);
    text('selected-summary-controller-note', mode);
    text('selected-summary-mode', mode);
  }

  function bindRecoveryHeaderRun() {
    const button = $('recovery-header-run');
    if (!button || button.dataset.bound === 'true') return;
    button.dataset.bound = 'true';
    button.addEventListener('click', () => $('run-experiment')?.click());
  }

  function benchmarkOptionSummary(option) {
    const raw = option?.textContent?.trim() || '등록된 Benchmark';
    const parts = raw.split('·').map((part) => part.trim()).filter(Boolean);
    return { title: parts[0] || raw, detail: parts.slice(1).join(' · ') || 'AIOpsLab Benchmark' };
  }

  function benchmarkLabel(benchmarkId) {
    const select = $('aiopslab-benchmark-select');
    const option = select ? Array.from(select.options).find((item) => item.value === benchmarkId) : null;
    return option ? benchmarkOptionSummary(option).title : (benchmarkId || "—");
  }

  function renderBenchmarkScenarioCards() {
    const select = $('aiopslab-benchmark-select');
    const list = $('aiopslab-scenario-list');
    if (!select || !list) return;
    const options = Array.from(select.options).filter((option) => option.value && !/불러오는 중/.test(option.textContent || ''));
    if (!options.length) {
      list.innerHTML = '<p class="empty-state">등록된 Benchmark 시나리오가 없습니다.</p>';
      text('aiopslab-selected-title', '데이터 없음');
      return;
    }
    const cards = options.map((option, index) => {
      const summary = benchmarkOptionSummary(option);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `benchmark-scenario-card${option.selected ? ' active' : ''}`;
      button.setAttribute("aria-pressed", String(option.selected));
      const icon = document.createElement('span');
      icon.className = 'icon';
      icon.textContent = index % 3 === 0 ? '▦' : index % 3 === 1 ? '◆' : '▣';
      const body = document.createElement('span');
      body.innerHTML = `<strong>${escapeHtml(summary.title)}</strong><small>${escapeHtml(summary.detail)}</small>`;
      button.append(icon, body);
      button.addEventListener('click', () => {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        renderBenchmarkScenarioCards();
      });
      return button;
    });
    list.replaceChildren(...cards);
    const current = select.selectedOptions[0] || options[0];
    text('aiopslab-selected-title', benchmarkOptionSummary(current).title);
  }

  function detectorLabel(job) {
    return job?.detector_label || job?.result?.detector_label || "AI-MCMP Four-Agent";
  }

  function detectorId(job) {
    return job?.detector_id || job?.result?.detector_id || "ai-mcmp-four-agent";
  }

  function ensureAIOpsLabTabs() {
    const panel = document.querySelector('[data-view-panel="aiopslab"]');
    if (!panel || $('aiopslab-functional-tabs')) return;
    const heading = panel.querySelector('.page-heading, .aiopslab-header, h2')?.closest('.page-heading, .aiopslab-header') || panel.firstElementChild;
    const nav = document.createElement('nav');
    nav.id = 'aiopslab-functional-tabs';
    nav.className = 'aiopslab-functional-tabs';
    nav.setAttribute('role', 'tablist');
    const labels = { evaluation: '벤치마크 평가', comparison: '모델 성능 비교', history: '실행 이력' };
    Object.entries(labels).forEach(([key, label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.aiopslabTab = key;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-selected', String(key === 'evaluation'));
      button.textContent = label;
      button.addEventListener('click', () => selectAIOpsLabTab(key));
      nav.append(button);
    });
    if (heading?.nextSibling) panel.insertBefore(nav, heading.nextSibling); else panel.append(nav);

    const evaluation = document.createElement('div');
    evaluation.dataset.aiopslabPanel = 'evaluation';
    evaluation.id = 'aiopslab-evaluation-panel';
    const movable = Array.from(panel.children).filter((child) => child !== heading && child !== nav);
    movable.forEach((child) => evaluation.append(child));
    panel.append(evaluation);

    const comparison = document.createElement('section');
    comparison.dataset.aiopslabPanel = 'comparison';
    comparison.id = 'aiopslab-comparison-panel';
    comparison.hidden = true;
    comparison.innerHTML = `
      <div class="surface aiopslab-tool-panel">
        <div class="section-heading"><div><h3>모델 · Detector 성능 비교</h3><p>저장된 실제 Benchmark Job 결과만 집계합니다.</p></div><button type="button" id="aiopslab-comparison-refresh" class="secondary-action">새로고침</button></div>
        <div id="aiopslab-comparison-status" class="inline-status" aria-live="polite">결과를 불러오는 중입니다.</div>
        <div id="aiopslab-comparison-cards" class="detector-comparison-cards"></div>
        <div class="table-wrap"><table><thead><tr><th>Detector</th><th>실행 수</th><th>Accuracy</th><th>Avg TTD</th><th>Avg Steps</th><th>Avg Reward</th></tr></thead><tbody id="aiopslab-comparison-body"></tbody></table></div>
      </div>`;
    panel.append(comparison);

    const history = document.createElement('section');
    history.dataset.aiopslabPanel = 'history';
    history.id = 'aiopslab-history-panel';
    history.hidden = true;
    history.innerHTML = `
      <div class="surface aiopslab-tool-panel">
        <div class="section-heading"><div><h3>AIOpsLab 실행 이력</h3><p>SQLite에 저장된 Benchmark Job을 조회합니다.</p></div><button type="button" id="aiopslab-history-refresh" class="secondary-action">새로고침</button></div>
        <div class="aiopslab-history-filters">
          <label>상태<select id="aiopslab-history-status"><option value="all">전체</option><option value="completed">완료</option><option value="running">실행 중</option><option value="failed">실패</option><option value="blocked">안전 중단</option><option value="cancelled">취소</option></select></label>
          <label>검색<input id="aiopslab-history-query" type="search" placeholder="Job ID 또는 시나리오" /></label>
          <label>페이지 크기<select id="aiopslab-history-page-size"><option value="5">5</option><option value="8" selected>8</option><option value="15">15</option></select></label>
        </div>
        <div id="aiopslab-history-status-line" class="inline-status" aria-live="polite"></div>
        <div class="table-wrap"><table><thead><tr><th>Job ID</th><th>시나리오</th><th>Detector</th><th>반복</th><th>상태</th><th>시작 시간</th><th>Accuracy</th><th>Avg TTD</th><th>상세</th></tr></thead><tbody id="aiopslab-history-body"></tbody></table></div>
        <div class="pagination-row"><button type="button" id="aiopslab-history-prev" class="secondary-action">이전</button><span id="aiopslab-history-page-info">1 / 1</span><button type="button" id="aiopslab-history-next" class="secondary-action">다음</button></div>
        <div id="aiopslab-job-detail" class="aiopslab-job-detail" hidden></div>
      </div>`;
    panel.append(history);

    $('aiopslab-comparison-refresh')?.addEventListener('click', loadAIOpsLabJobs);
    $('aiopslab-history-refresh')?.addEventListener('click', loadAIOpsLabJobs);
    $('aiopslab-history-status')?.addEventListener('change', (event) => { aiopslabState.historyStatus = event.target.value; aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-query')?.addEventListener('input', (event) => { aiopslabState.historyQuery = event.target.value.trim().toLowerCase(); aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-page-size')?.addEventListener('change', (event) => { aiopslabState.historyPageSize = Number(event.target.value) || 8; aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-prev')?.addEventListener('click', () => { aiopslabState.historyPage = Math.max(1, aiopslabState.historyPage - 1); renderAIOpsLabHistory(); });
    $('aiopslab-history-next')?.addEventListener('click', () => { aiopslabState.historyPage += 1; renderAIOpsLabHistory(); });

    const requested = new URLSearchParams(window.location.search).get('aiopslab_tab');
    selectAIOpsLabTab(['evaluation', 'comparison', 'history'].includes(requested) ? requested : 'evaluation', false);
  }

  function selectAIOpsLabTab(tab, updateUrl = true) {
    const resolved = ['evaluation', 'comparison', 'history'].includes(tab) ? tab : 'evaluation';
    aiopslabState.tab = resolved;
    document.querySelectorAll('[data-aiopslab-tab]').forEach((button) => button.setAttribute('aria-selected', String(button.dataset.aiopslabTab === resolved)));
    document.querySelectorAll('[data-aiopslab-panel]').forEach((panel) => { panel.hidden = panel.dataset.aiopslabPanel !== resolved; });
    if (updateUrl) {
      const url = new URL(window.location.href);
      if (resolved === 'evaluation') url.searchParams.delete('aiopslab_tab'); else url.searchParams.set('aiopslab_tab', resolved);
      history.replaceState(null, '', `${url.pathname}${url.search}${window.location.hash || '#aiopslab'}`);
    }
    if (resolved !== 'evaluation') loadAIOpsLabJobs();
  }

  async function loadAIOpsLabJobs() {
    if (aiopslabState.loading) return;
    aiopslabState.loading = true;
    aiopslabState.error = '';
    const status = $('aiopslab-comparison-status');
    if (status) status.textContent = '저장된 Benchmark 결과를 불러오는 중입니다.';
    try {
      const payload = await requestJson('/api/benchmarks/aiopslab/jobs?limit=100');
      aiopslabState.jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
    } catch (error) {
      aiopslabState.error = error instanceof Error ? error.message : String(error);
    } finally {
      aiopslabState.loading = false;
      renderAIOpsLabComparison();
      renderAIOpsLabHistory();
    }
  }

  function actualMetricValues(jobs, key) {
    return jobs.map((job) => Number(job?.result?.[key])).filter((value) => Number.isFinite(value));
  }

  function mean(values) {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  function renderAIOpsLabComparison() {
    const body = $('aiopslab-comparison-body');
    const cards = $('aiopslab-comparison-cards');
    const status = $('aiopslab-comparison-status');
    if (!body || !cards || !status) return;
    if (aiopslabState.error) {
      status.textContent = `결과를 불러오지 못했습니다: ${aiopslabState.error}`;
      body.innerHTML = '<tr><td colspan="6" class="empty-cell">데이터를 불러올 수 없습니다.</td></tr>';
      cards.replaceChildren();
      return;
    }
    const completed = aiopslabState.jobs.filter((job) => job.status === 'completed' && job.result);
    const groups = new Map();
    completed.forEach((job) => {
      const id = detectorId(job);
      if (!groups.has(id)) groups.set(id, { label: detectorLabel(job), jobs: [] });
      groups.get(id).jobs.push(job);
    });
    if (!groups.size) {
      status.textContent = '비교할 실제 Benchmark 결과가 없습니다.';
      body.innerHTML = '<tr><td colspan="6" class="empty-cell">Benchmark를 실행하면 실제 결과가 여기에 표시됩니다.</td></tr>';
      cards.replaceChildren();
      return;
    }
    status.textContent = groups.size === 1 ? '비교 가능한 Detector가 1개입니다.' : `${groups.size}개 Detector의 실제 결과를 비교합니다.`;
    const rows = [];
    const cardNodes = [];
    groups.forEach((group) => {
      const accuracy = mean(actualMetricValues(group.jobs, 'accuracy'));
      const ttd = mean(actualMetricValues(group.jobs, 'average_ttd'));
      const steps = mean(actualMetricValues(group.jobs, 'average_steps'));
      const reward = mean(actualMetricValues(group.jobs, 'average_final_reward'));
      rows.push(`<tr><td><strong>${escapeHtml(group.label)}</strong></td><td>${group.jobs.length}</td><td>${accuracy == null ? '—' : fmtPercent(accuracy)}</td><td>${ttd == null ? '—' : `${fmtNumber(ttd)}s`}</td><td>${steps == null ? '—' : fmtNumber(steps, 2)}</td><td>${reward == null ? '—' : fmtNumber(reward)}</td></tr>`);
      const card = document.createElement('article');
      card.className = 'detector-card';
      card.innerHTML = `<span>Detector</span><strong>${escapeHtml(group.label)}</strong><small>${group.jobs.length}개 완료 Job</small><dl><div><dt>Accuracy</dt><dd>${accuracy == null ? '—' : fmtPercent(accuracy)}</dd></div><div><dt>Avg TTD</dt><dd>${ttd == null ? '—' : `${fmtNumber(ttd)}s`}</dd></div><div><dt>Avg Steps</dt><dd>${steps == null ? '—' : fmtNumber(steps, 2)}</dd></div><div><dt>Avg Reward</dt><dd>${reward == null ? '—' : fmtNumber(reward)}</dd></div></dl>`;
      cardNodes.push(card);
    });
    body.innerHTML = rows.join('');
    cards.replaceChildren(...cardNodes);
  }

  function filteredAIOpsLabJobs() {
    return aiopslabState.jobs.filter((job) => {
      if (aiopslabState.historyStatus !== 'all' && job.status !== aiopslabState.historyStatus) return false;
      if (!aiopslabState.historyQuery) return true;
      const haystack = `${job.job_id || ''} ${job.request?.benchmark_id || ''} ${benchmarkLabel(job.request?.benchmark_id)} ${detectorLabel(job)}`.toLowerCase();
      return haystack.includes(aiopslabState.historyQuery);
    });
  }

  function renderAIOpsLabHistory() {
    const body = $('aiopslab-history-body');
    const line = $('aiopslab-history-status-line');
    if (!body || !line) return;
    if (aiopslabState.error) {
      line.textContent = `실행 이력을 불러오지 못했습니다: ${aiopslabState.error}`;
      body.innerHTML = '<tr><td colspan="9" class="empty-cell">재시도 버튼을 눌러 다시 조회하세요.</td></tr>';
      return;
    }
    const jobs = filteredAIOpsLabJobs();
    const totalPages = Math.max(1, Math.ceil(jobs.length / aiopslabState.historyPageSize));
    aiopslabState.historyPage = Math.min(aiopslabState.historyPage, totalPages);
    const start = (aiopslabState.historyPage - 1) * aiopslabState.historyPageSize;
    const pageJobs = jobs.slice(start, start + aiopslabState.historyPageSize);
    line.textContent = jobs.length ? `총 ${jobs.length}개 Benchmark Job` : '조건에 맞는 Benchmark 실행 이력이 없습니다.';
    text('aiopslab-history-page-info', `${aiopslabState.historyPage} / ${totalPages}`);
    if ($('aiopslab-history-prev')) $('aiopslab-history-prev').disabled = aiopslabState.historyPage <= 1;
    if ($('aiopslab-history-next')) $('aiopslab-history-next').disabled = aiopslabState.historyPage >= totalPages;
    if (!pageJobs.length) {
      body.innerHTML = '<tr><td colspan="9" class="empty-cell">실행 이력이 없습니다.</td></tr>';
      return;
    }
    body.innerHTML = pageJobs.map((job) => {
      const result = job.result || {};
      return `<tr><td><code>${escapeHtml(job.job_id || '—')}</code></td><td>${escapeHtml(benchmarkLabel(job.request?.benchmark_id))}</td><td>${escapeHtml(detectorLabel(job))}</td><td>${job.request?.repetitions ?? '—'}</td><td>${escapeHtml(statusLabel(job.status))}</td><td>${escapeHtml(fmtDate(job.started_at || job.created_at))}</td><td>${result.accuracy == null ? '—' : fmtPercent(result.accuracy)}</td><td>${result.average_ttd == null ? '—' : `${fmtNumber(result.average_ttd)}s`}</td><td><button type="button" class="table-action" data-aiopslab-job-detail="${escapeHtml(job.job_id)}">보기</button></td></tr>`;
    }).join('');
    body.querySelectorAll('[data-aiopslab-job-detail]').forEach((button) => button.addEventListener('click', () => showAIOpsLabJobDetail(button.dataset.aiopslabJobDetail)));
  }

  async function showAIOpsLabJobDetail(jobId) {
    const detail = $('aiopslab-job-detail');
    if (!detail) return;
    detail.hidden = false;
    detail.innerHTML = '<p class="inline-status">상세 데이터를 불러오는 중입니다.</p>';
    try {
      const job = await requestJson(`/api/benchmarks/aiopslab/jobs/${encodeURIComponent(jobId)}`);
      const result = job.result || {};
      const artifactEntries = Object.entries(job.artifact_urls || {});
      const events = Array.isArray(job.events) ? job.events : [];
      detail.innerHTML = `<div class="section-heading"><div><h4>${escapeHtml(job.job_id)}</h4><p>${escapeHtml(benchmarkLabel(job.request?.benchmark_id))} · ${escapeHtml(detectorLabel(job))}</p></div><button type="button" id="aiopslab-job-detail-close" class="secondary-action">닫기</button></div>
        <div class="detail-metric-row"><span>Status <strong>${escapeHtml(statusLabel(job.status))}</strong></span><span>Accuracy <strong>${result.accuracy == null ? '—' : fmtPercent(result.accuracy)}</strong></span><span>Avg TTD <strong>${result.average_ttd == null ? '—' : `${fmtNumber(result.average_ttd)}s`}</strong></span><span>Avg Reward <strong>${result.average_final_reward == null ? '—' : fmtNumber(result.average_final_reward)}</strong></span></div>
        <div class="artifact-links">${artifactEntries.length ? artifactEntries.map(([name, href]) => `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(name)}</a>`).join('') : '<span>다운로드 가능한 Artifact가 없습니다.</span>'}</div>
        <details><summary>실행 이벤트 ${events.length}개</summary><ol>${events.length ? events.map((event) => `<li><time>${escapeHtml(fmtDate(event.created_at))}</time> <strong>${escapeHtml(event.stage || '—')}</strong> ${escapeHtml(event.message || '')}</li>`).join('') : '<li>이벤트가 없습니다.</li>'}</ol></details>`;
      $('aiopslab-job-detail-close')?.addEventListener('click', () => { detail.hidden = true; });
    } catch (error) {
      detail.innerHTML = `<p class="inline-error">상세 데이터를 불러오지 못했습니다: ${escapeHtml(error instanceof Error ? error.message : String(error))}</p>`;
    }
  }

  function updateDashboardDonut() {
    const donut = $('dashboard-donut');
    const totalNode = $('dashboard-total');
    const successNode = $('dashboard-success-rate');
    if (!donut || !totalNode || !successNode) return;
    const total = Number(totalNode.textContent.trim());
    const successRate = Number((successNode.textContent || '').replace('%', ''));
    if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(successRate)) {
      donut.style.background = 'conic-gradient(#e7edf5 0 100%)';
      donut.innerHTML = '<span>데이터 없음</span>';
      return;
    }
    const clamped = Math.max(0, Math.min(100, successRate));
    donut.style.background = `conic-gradient(#0bb46c 0 ${clamped}%, #ef4b4f ${clamped}% 100%)`;
    donut.innerHTML = `<span>${clamped.toFixed(1)}%</span>`;
  }

  function ensureExperimentResultControls() {
    const body = $('experiment-history-body');
    if (!body) return;
    const card = body.closest('.history-table-card, .surface');
    const filterBar = document.querySelector('[data-result-panel="history"] .filter-bar');
    if (filterBar && !$('result-filter-reset')) {
      const reset = document.createElement('button');
      reset.type = 'button';
      reset.id = 'result-filter-reset';
      reset.className = 'secondary-action';
      reset.textContent = '필터 초기화';
      reset.addEventListener('click', resetResultFilters);
      filterBar.append(reset);
    }
    if (card && !$('result-pagination')) {
      const pager = document.createElement('div');
      pager.id = 'result-pagination';
      pager.className = 'pagination-row result-pagination';
      pager.innerHTML = `<span id="result-loaded-boundary" class="helper-text"></span><label>페이지 크기<select id="result-page-size"><option value="5">5</option><option value="10" selected>10</option><option value="20">20</option></select></label><button type="button" id="result-pagination-prev" class="secondary-action">이전</button><span id="result-pagination-info">1 / 1</span><button type="button" id="result-pagination-next" class="secondary-action">다음</button>`;
      card.append(pager);
      $('result-page-size')?.addEventListener('change', (event) => { resultState.pageSize = Number(event.target.value) || 10; resultState.page = 1; syncResultFiltersToUrl(); applyExperimentPagination(); });
      $('result-pagination-prev')?.addEventListener('click', () => { resultState.page = Math.max(1, resultState.page - 1); syncResultFiltersToUrl(); applyExperimentPagination(); });
      $('result-pagination-next')?.addEventListener('click', () => { resultState.page += 1; syncResultFiltersToUrl(); applyExperimentPagination(); });
    }
    bindResultFilterUrlSync();
    syncResultFiltersFromUrl();
    applyExperimentPagination();
  }

  function bindResultFilterUrlSync() {
    Object.entries(RESULT_QUERY_MAP).forEach(([key, id]) => {
      const control = $(id);
      if (!control || control.dataset.urlBound === 'true') return;
      control.dataset.urlBound = 'true';
      const eventName = key === 'q' ? 'input' : 'change';
      control.addEventListener(eventName, () => {
        if (resultState.syncing) return;
        resultState.page = 1;
        if (key === 'q') {
          window.clearTimeout(resultState.searchTimer);
          resultState.searchTimer = window.setTimeout(() => { syncResultFiltersToUrl(); applyExperimentPagination(); }, 300);
        } else {
          syncResultFiltersToUrl();
          window.setTimeout(applyExperimentPagination, 0);
        }
      });
    });
  }

  function syncResultFiltersFromUrl() {
    if (resultState.syncing) return;
    resultState.syncing = true;
    const params = new URLSearchParams(window.location.search);
    Object.entries(RESULT_QUERY_MAP).forEach(([key, id]) => {
      const control = $(id);
      const value = params.get(key);
      if (!control || value == null || value === '') return;
      if (control.tagName === 'SELECT' && !Array.from(control.options).some((option) => option.value === value)) return;
      control.value = value;
      control.dispatchEvent(new Event(key === 'q' ? 'input' : 'change', { bubbles: true }));
    });
    resultState.page = Math.max(1, Number(params.get('page')) || 1);
    resultState.pageSize = [5, 10, 20].includes(Number(params.get('page_size'))) ? Number(params.get('page_size')) : 10;
    if ($('result-page-size')) $('result-page-size').value = String(resultState.pageSize);
    resultState.syncing = false;
    window.setTimeout(applyExperimentPagination, 0);
  }

  function syncResultFiltersToUrl() {
    if (resultState.syncing) return;
    const url = new URL(window.location.href);
    Object.entries(RESULT_QUERY_MAP).forEach(([key, id]) => {
      const control = $(id);
      if (!control) return;
      const value = control.value.trim();
      if (!value || value === 'all') url.searchParams.delete(key); else url.searchParams.set(key, value);
    });
    if (resultState.page > 1) url.searchParams.set('page', String(resultState.page)); else url.searchParams.delete('page');
    if (resultState.pageSize !== 10) url.searchParams.set('page_size', String(resultState.pageSize)); else url.searchParams.delete('page_size');
    history.replaceState(null, '', `${url.pathname}${url.search}${window.location.hash || '#analysis'}`);
  }

  function resetResultFilters() {
    resultState.syncing = true;
    Object.values(RESULT_QUERY_MAP).forEach((id) => {
      const control = $(id);
      if (!control) return;
      control.value = control.tagName === 'SELECT' ? 'all' : '';
      control.dispatchEvent(new Event(control.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    });
    resultState.page = 1;
    resultState.pageSize = 10;
    if ($('result-page-size')) $('result-page-size').value = '10';
    resultState.syncing = false;
    const url = new URL(window.location.href);
    [...Object.keys(RESULT_QUERY_MAP), 'page', 'page_size'].forEach((key) => url.searchParams.delete(key));
    history.replaceState(null, '', `${url.pathname}${url.search}${window.location.hash || '#analysis'}`);
    window.setTimeout(applyExperimentPagination, 0);
  }

  function applyExperimentPagination() {
    const body = $('experiment-history-body');
    if (!body) return;
    const rows = Array.from(body.querySelectorAll('tr'));
    const dataRows = rows.filter((row) => !row.querySelector('.empty-cell') && row.children.length > 1);
    if (!dataRows.length) {
      text('result-pagination-info', '1 / 1');
      if ($('result-pagination-prev')) $('result-pagination-prev').disabled = true;
      if ($('result-pagination-next')) $('result-pagination-next').disabled = true;
      text('result-loaded-boundary', '조건에 맞는 실험 결과가 없습니다.');
      return;
    }
    const totalPages = Math.max(1, Math.ceil(dataRows.length / resultState.pageSize));
    resultState.page = Math.min(resultState.page, totalPages);
    const start = (resultState.page - 1) * resultState.pageSize;
    dataRows.forEach((row, index) => { row.style.display = index >= start && index < start + resultState.pageSize ? '' : 'none'; });
    text('result-pagination-info', `${resultState.page} / ${totalPages} · 총 ${dataRows.length}건`);
    text('result-loaded-boundary', dataRows.length >= 100 ? '현재 불러온 최대 100개 결과 범위에서 필터·페이지네이션합니다.' : '현재 조회된 전체 결과를 페이지네이션합니다.');
    if ($('result-pagination-prev')) $('result-pagination-prev').disabled = resultState.page <= 1;
    if ($('result-pagination-next')) $('result-pagination-next').disabled = resultState.page >= totalPages;
  }

  function currentExperimentId() {
    const subtitle = $('detail-experiment-subtitle')?.textContent?.trim() || '';
    const first = subtitle.split(' · ')[0]?.trim();
    if (first && /^exp-/.test(first)) return first;
    const global = $('global-experiment-id')?.textContent?.trim();
    return global && /^exp-/.test(global) ? global : '';
  }

  async function copyExperimentId() {
    const id = currentExperimentId();
    if (!id) return;
    const button = $('detail-copy-button');
    try {
      await navigator.clipboard.writeText(id);
      if (button) { button.textContent = '복사됨'; window.setTimeout(() => { button.textContent = 'ID 복사'; }, 1200); }
    } catch (_error) {
      if (button) button.textContent = '복사 실패';
    }
  }

  function prefillRerun() {
    const subtitle = $('detail-experiment-subtitle')?.textContent?.trim() || '';
    const parts = subtitle.split(' · ').map((part) => part.trim());
    const scenarioText = parts[1] || '';
    const modeText = parts.find((part) => ['Mock', 'Dry-run', 'Real'].includes(part)) || '';
    const controllerText = parts.find((part) => part.includes('Deterministic') || part.includes('AutoGen')) || '';
    const scenarioSelect = $('overview-scenario-select');
    if (scenarioSelect && scenarioText) {
      const option = Array.from(scenarioSelect.options).find((item) => item.textContent.trim() === scenarioText);
      if (option) { scenarioSelect.value = option.value; scenarioSelect.dispatchEvent(new Event('change', { bubbles: true })); }
    }
    const modeSelect = $('overview-mode-select');
    if (modeSelect && modeText) {
      const modeValue = modeText === 'Dry-run' ? 'dry-run' : modeText.toLowerCase();
      modeSelect.value = modeValue;
      modeSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    const controllerSelect = $('overview-controller-select');
    if (controllerSelect && controllerText) {
      controllerSelect.value = controllerText.includes('AutoGen') ? 'autogen' : 'deterministic';
      controllerSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    window.location.hash = 'experiment';
  }

  function ensureDetailActions() {
    const detailPanel = document.querySelector('[data-view-panel="history"]');
    if (!detailPanel) return;
    const heading = detailPanel.querySelector('.page-heading');
    if (heading && !$('detail-copy-button')) {
      let actions = heading.querySelector('.detail-header-actions');
      if (!actions) {
        actions = document.createElement('div');
        actions.className = 'detail-header-actions';
        heading.append(actions);
      }
      const copy = document.createElement('button');
      copy.id = 'detail-copy-button';
      copy.type = 'button';
      copy.className = 'secondary-action';
      copy.textContent = 'ID 복사';
      copy.addEventListener('click', copyExperimentId);
      actions.prepend(copy);
      const existingDownload = $('detail-download-button');
      const existingRerun = $('detail-rerun-button');
      if (existingDownload && existingDownload.parentElement !== actions) actions.append(existingDownload);
      if (existingRerun && existingRerun.parentElement !== actions) actions.append(existingRerun);
    }
    bindDetailActions();
    ensureDetailLogControls();
    ensureDetailEventPayloads();
    bindDetailTabUrlSync();
    syncDetailTabFromUrl();
  }

  function bindDetailActions() {
    const download = $('detail-download-button');
    if (download && download.dataset.bound !== 'complete') {
      download.dataset.bound = 'complete';
      download.addEventListener('click', (event) => {
        event.preventDefault();
        toggleArtifactMenu(download);
      });
    }
    const rerun = $('detail-rerun-button');
    if (rerun && rerun.dataset.bound !== 'complete') {
      rerun.dataset.bound = 'complete';
      rerun.addEventListener('click', (event) => { event.preventDefault(); prefillRerun(); });
    }
  }

  function toggleArtifactMenu(anchor) {
    let menu = $('detail-artifact-menu');
    if (!menu) {
      menu = document.createElement('div');
      menu.id = 'detail-artifact-menu';
      menu.className = 'artifact-popover';
      anchor.parentElement?.append(menu);
    }
    const links = Array.from(document.querySelectorAll('#experiment-artifacts a'));
    if (!links.length) {
      menu.innerHTML = '<span>다운로드 가능한 결과 파일이 없습니다.</span>';
    } else {
      menu.replaceChildren(...links.map((source) => {
        const link = document.createElement('a');
        link.href = source.href;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = source.textContent || '결과 파일';
        return link;
      }));
    }
    menu.hidden = !menu.hidden && menu.childElementCount > 0;
    if (menu.hidden) menu.hidden = false;
  }

  function bindDetailTabUrlSync() {
    document.querySelectorAll('[data-detail-tab]').forEach((button) => {
      if (button.dataset.urlBound === 'true') return;
      button.dataset.urlBound = 'true';
      button.addEventListener('click', () => syncDetailTabToUrl(button.dataset.detailTab));
    });
  }

  function syncDetailTabToUrl(tab) {
    const url = new URL(window.location.href);
    if (!tab || tab === 'summary') url.searchParams.delete('detail_tab'); else url.searchParams.set('detail_tab', tab);
    history.replaceState(null, '', `${url.pathname}${url.search}${window.location.hash || '#history'}`);
  }

  function syncDetailTabFromUrl() {
    const tab = new URLSearchParams(window.location.search).get('detail_tab') || 'summary';
    const button = document.querySelector(`[data-detail-tab="${CSS.escape(tab)}"]`);
    if (button && button.getAttribute('aria-pressed') !== 'true') button.click();
  }

  function ensureDetailLogControls() {
    const pre = $('detail-logs');
    if (!pre || $('detail-log-search')) return;
    const controls = document.createElement('div');
    controls.className = 'detail-log-controls';
    controls.innerHTML = `<label>Level<select id="detail-log-level"><option value="all">전체</option><option value="error">Error</option><option value="warning">Warning</option><option value="info">Info</option></select></label><label>검색<input id="detail-log-search" type="search" placeholder="로그 검색" /></label><label class="checkbox-label"><input id="detail-log-autoscroll" type="checkbox" checked /> 자동 스크롤</label><button type="button" id="detail-log-download" class="secondary-action">로그 다운로드</button>`;
    pre.parentElement?.insertBefore(controls, pre);
    pre.dataset.rawLog = pre.textContent || '';
    const refresh = () => filterDetailLogs();
    $('detail-log-level')?.addEventListener('change', refresh);
    $('detail-log-search')?.addEventListener('input', refresh);
    $('detail-log-download')?.addEventListener('click', downloadDetailLogs);
    new MutationObserver(() => {
      if (pre.dataset.filtering === 'true') return;
      pre.dataset.rawLog = pre.textContent || '';
      filterDetailLogs();
    }).observe(pre, { childList: true, characterData: true, subtree: true });
  }

  function filterDetailLogs() {
    const pre = $('detail-logs');
    if (!pre) return;
    const raw = pre.dataset.rawLog || pre.textContent || '';
    const level = $('detail-log-level')?.value || 'all';
    const query = ($('detail-log-search')?.value || '').trim().toLowerCase();
    let lines = raw.split(/\r?\n/).slice(-100);
    if (level !== 'all') lines = lines.filter((line) => line.toLowerCase().includes(level));
    if (query) lines = lines.filter((line) => line.toLowerCase().includes(query));
    pre.dataset.filtering = 'true';
    pre.textContent = lines.join('\n') || '조건에 맞는 로그가 없습니다.';
    pre.dataset.filtering = 'false';
    if ($('detail-log-autoscroll')?.checked) pre.scrollTop = pre.scrollHeight;
  }

  function downloadDetailLogs() {
    const raw = $('detail-logs')?.dataset.rawLog || '';
    if (!raw || /로그 데이터가 없습니다/.test(raw)) return;
    const blob = new Blob([raw], { type: 'text/plain;charset=utf-8' });
    const href = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = href;
    link.download = `${currentExperimentId() || 'experiment'}-logs.txt`;
    link.click();
    URL.revokeObjectURL(href);
  }

  function ensureDetailEventPayloads() {
    const events = $('detail-events');
    if (!events || $('detail-event-payloads')) return;
    const container = document.createElement('div');
    container.id = 'detail-event-payloads';
    container.className = 'detail-event-payloads';
    events.parentElement?.append(container);
    const subtitle = $('detail-experiment-subtitle');
    if (subtitle) new MutationObserver(loadDetailEventPayloads).observe(subtitle, { childList: true, characterData: true, subtree: true });
    loadDetailEventPayloads();
  }

  async function loadDetailEventPayloads() {
    const id = currentExperimentId();
    const container = $('detail-event-payloads');
    if (!id || !container) return;
    try {
      const job = await requestJson(`/api/experiments/${encodeURIComponent(id)}`);
      const events = Array.isArray(job.events) ? job.events.slice(-100) : [];
      container.innerHTML = events.length ? events.map((event) => `<details><summary><time>${escapeHtml(fmtDate(event.created_at))}</time> · ${escapeHtml(event.stage || '—')} · ${escapeHtml(event.message || '')}</summary><pre>${escapeHtml(JSON.stringify(event.payload || {}, null, 2))}</pre></details>`).join('') : '<p class="empty-state">이벤트 Payload가 없습니다.</p>';
    } catch (_error) {
      container.innerHTML = '<p class="empty-state">이벤트 상세를 불러올 수 없습니다.</p>';
    }
  }

  function syncDetailReference() {
    const finalAction = $('overview-final-action')?.textContent.trim();
    if (finalAction) text('detail-final-action', finalAction);
    const subtitle = $('detail-experiment-subtitle')?.textContent.trim();
    if (subtitle) text('detail-info-block', subtitle);
    const agreement = $('overview-consensus-status')?.textContent.trim();
    if (agreement) text('detail-agreement-block', agreement);
    const evidence = $('detail-evidence-summary')?.textContent.trim() || $('overview-evidence-change')?.textContent.trim();
    if (evidence) text('detail-evidence-preview', evidence);
  }

  function injectCompletionStyles() {
    if ($('complete-research-console-styles')) return;
    const style = document.createElement('style');
    style.id = 'complete-research-console-styles';
    style.textContent = `
      .aiopslab-functional-tabs{display:flex;gap:28px;border-bottom:1px solid #dbe3ef;margin:0 0 22px;padding:0 20px}.aiopslab-functional-tabs button{padding:13px 2px;border:0;border-bottom:3px solid transparent;background:transparent;color:#6a7891;font-weight:700}.aiopslab-functional-tabs button[aria-selected="true"]{color:#075eea;border-bottom-color:#075eea}.aiopslab-tool-panel{padding:20px}.aiopslab-tool-panel .section-heading p{margin-top:5px;color:#66758f}.detector-comparison-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:16px 0}.detector-card{border:1px solid #d9e2ef;border-radius:10px;padding:16px;background:#fff}.detector-card>span,.detector-card>small{display:block;color:#6b7890}.detector-card>strong{display:block;margin:5px 0 13px;color:#0b1f45}.detector-card dl{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:0}.detector-card dl div{padding:9px;background:#f7f9fc;border-radius:7px}.detector-card dt{color:#718099;font-size:12px}.detector-card dd{margin:3px 0 0;font-weight:800}.aiopslab-history-filters{display:grid;grid-template-columns:180px minmax(240px,1fr) 130px;gap:12px;margin:14px 0}.pagination-row{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:14px}.result-pagination{border-top:1px solid #e1e7f0;padding-top:14px;flex-wrap:wrap}.result-pagination>span:first-child{margin-right:auto}.result-pagination label{display:flex;align-items:center;gap:7px}.result-pagination select{width:auto;min-width:74px}.aiopslab-job-detail{margin-top:18px;border-top:1px solid #dce4ee;padding-top:18px}.detail-metric-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.detail-metric-row span{padding:10px;background:#f7f9fc;border-radius:7px}.detail-metric-row strong{display:block;margin-top:4px}.artifact-links{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.artifact-links a,.artifact-popover a{display:block;padding:8px 10px;border:1px solid #cfdaea;border-radius:6px;background:#fff;color:#075eea;text-decoration:none}.detail-header-actions{display:flex;align-items:center;gap:8px;margin-left:auto;position:relative}.artifact-popover{position:absolute;z-index:50;right:0;top:44px;min-width:230px;padding:9px;border:1px solid #d2dcea;border-radius:8px;background:#fff;box-shadow:0 10px 30px rgba(8,35,70,.16)}.artifact-popover span{display:block;padding:8px;color:#66758f}.detail-log-controls{display:grid;grid-template-columns:150px minmax(220px,1fr) auto auto;gap:10px;align-items:end;margin-bottom:12px}.checkbox-label{display:flex!important;align-items:center;gap:6px;padding-bottom:9px}.checkbox-label input{width:auto;min-height:0}.detail-event-payloads{display:grid;gap:8px;margin-top:14px}.detail-event-payloads details{border:1px solid #dce4ee;border-radius:7px;padding:9px}.detail-event-payloads pre{max-height:280px;overflow:auto;background:#f7f9fc;padding:10px;border-radius:6px}.inline-status{padding:10px 12px;border-radius:7px;background:#f5f8fc;color:#53627b;margin:10px 0}.inline-error{color:#b23643}.table-wrap{overflow:auto}@media(max-width:900px){.aiopslab-history-filters,.detail-log-controls{grid-template-columns:1fr 1fr}.detail-metric-row{grid-template-columns:1fr 1fr}}@media(max-width:760px){.aiopslab-functional-tabs{gap:12px;overflow:auto}.aiopslab-history-filters,.detail-log-controls,.detail-metric-row{grid-template-columns:1fr}.pagination-row{justify-content:center}.result-pagination>span:first-child{width:100%;margin:0;text-align:center}}
    `;
    document.head.append(style);
  }

  function syncAll() {
    syncReferenceSummary();
    renderBenchmarkScenarioCards();
    updateDashboardDonut();
    syncDetailReference();
    ensureExperimentResultControls();
    ensureDetailActions();
  }

  document.addEventListener('DOMContentLoaded', () => {
    injectCompletionStyles();
    bindRecoveryHeaderRun();
    ensureAIOpsLabTabs();
    ensureExperimentResultControls();
    ensureDetailActions();
    syncAll();
    loadAIOpsLabJobs();

    const historyBody = $('experiment-history-body');
    if (historyBody) new MutationObserver(() => applyExperimentPagination()).observe(historyBody, { childList: true, subtree: true });

    const observer = new MutationObserver(() => syncAll());
    const targets = [
      $('scenario-list'), $('controller-options'), $('mode-control'), $('aiopslab-benchmark-select'),
      $('dashboard-total'), $('dashboard-success-rate'), $('overview-final-action'),
      $('overview-consensus-status'), $('detail-experiment-subtitle'), $('detail-evidence-summary'),
    ].filter(Boolean);
    targets.forEach((target) => observer.observe(target, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['aria-pressed'] }));
  });
})();
