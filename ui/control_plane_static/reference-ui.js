(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const node = $(id); if (node) node.textContent = value || "—"; };
  const scenarioDescriptions = {
    "Pod Failure": "Pod 비정상 종료",
    "CPU Saturation": "CPU 과부하",
    "Memory Saturation": "Memory 과부하",
    "Network Delay": "네트워크 지연",
  };

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

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
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

  function bindDetailActions() {
    const download = $('detail-download-button');
    if (download && download.dataset.bound !== 'true') {
      download.dataset.bound = 'true';
      download.addEventListener('click', () => {
        const firstArtifact = document.querySelector('#experiment-artifacts a');
        if (firstArtifact) firstArtifact.click();
      });
    }
    const rerun = $('detail-rerun-button');
    if (rerun && rerun.dataset.bound !== 'true') {
      rerun.dataset.bound = 'true';
      rerun.addEventListener('click', () => {
        window.location.hash = 'experiment';
      });
    }
  }

  function syncAll() {
    syncReferenceSummary();
    renderBenchmarkScenarioCards();
    updateDashboardDonut();
    syncDetailReference();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindRecoveryHeaderRun();
    bindDetailActions();
    syncAll();
    const observer = new MutationObserver(() => syncAll());
    const targets = [
      $('scenario-list'), $('controller-options'), $('mode-control'), $('aiopslab-benchmark-select'),
      $('dashboard-total'), $('dashboard-success-rate'), $('overview-final-action'),
      $('overview-consensus-status'), $('detail-experiment-subtitle'), $('detail-evidence-summary'),
    ].filter(Boolean);
    targets.forEach((target) => observer.observe(target, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['aria-pressed'] }));
  });
})();
