(function () {
  "use strict";

  // Data-first visual polish only. No broad MutationObserver is used here because
  // the console must remain responsive while other scripts update the DOM.
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const fmtDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ko-KR", { hour12: false });
  };
  const fmtNumber = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  const fmtPercent = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : "—";
  const statusLabel = (value) => ({
    queued: "대기 중", running: "실행 중", cancelling: "취소 중", completed: "완료",
    failed: "실패", blocked: "안전 중단", cancelled: "취소됨", interrupted: "중단",
  })[value] || value || "—";
  const supportedAIOpsLabMetrics = ["Accuracy", "Average TTD", "Average Steps", "Average Reward"];
  let benchmarkCatalog = [];

  async function requestJson(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.detail || `요청 실패 (${response.status})`);
    return payload;
  }

  function injectPolishStyles() {
    if ($("research-console-polish-styles")) return;
    const style = document.createElement("style");
    style.id = "research-console-polish-styles";
    style.textContent = `
      :root{--reference-green:#0aa85f;--reference-soft:#f7f9fc;--reference-line:#dce4ef}
      body{background:#f8fafc}
      .platform-shell{grid-template-columns:248px minmax(0,1fr)}
      .platform-sidebar{padding-left:18px;padding-right:18px;background:linear-gradient(180deg,#022a58 0%,#032d60 52%,#02254e 100%)}
      .platform-brand{height:88px}.platform-nav button{min-height:74px}.view-container{padding:24px 30px 42px}
      .view-panel{max-width:1500px;margin:0 auto}.page-heading{margin-bottom:22px}.page-heading h2,.recovery-header h2{font-size:27px;letter-spacing:-.02em}
      .surface{border-color:var(--reference-line);box-shadow:0 1px 3px rgba(15,35,68,.04)}
      .overview-status-strip{min-height:72px}.overview-flow-card{padding-top:18px;padding-bottom:18px}.reference-flow b{transition:.18s ease}
      .reference-flow li.done b{background:var(--reference-green);border-color:var(--reference-green);color:#fff}.reference-flow li.done:not(:last-child)::after{color:var(--reference-green)}
      .reference-flow li.active b{background:#eaf2ff;border:2px solid #075eea;color:#075eea;box-shadow:0 0 0 4px rgba(7,94,234,.08)}
      .reference-flow li.failed b{background:#fff0f1;border-color:#ef4b4f;color:#c62f3a}
      .agent-summary-grid article{min-height:126px}.agent-summary-grid p{color:#56657d}.overview-result,.overview-agents,.overview-current,.overview-quick{min-height:250px}
      .scenario-list button::before{content:"◇"}.scenario-list button[data-scenario="pod-kill"]::before{content:"⬡"}.scenario-list button[data-scenario="cpu-stress"]::before{content:"▦"}.scenario-list button[data-scenario="memory-stress"]::before{content:"▤"}.scenario-list button[data-scenario="network-delay"]::before{content:"⌁"}
      .scenario-list button[data-scenario="pod-kill"]::before{color:#e34d59}.scenario-list button[data-scenario="cpu-stress"]::before{color:#f39a1d}.scenario-list button[data-scenario="memory-stress"]::before{color:#744be8}.scenario-list button[data-scenario="network-delay"]::before{color:#075eea}
      .selected-summary{position:sticky;top:24px;height:max-content}.mode-guide article{align-items:flex-start}
      .reference-tabs,.result-tabs,.detail-tabs{gap:26px}.reference-tabs button,.result-tabs button,.detail-tabs button{padding-left:4px;padding-right:4px}
      .benchmark-scenario-card{position:relative;min-height:82px;text-align:left}.benchmark-scenario-card.active{border-color:#1769e8;background:#f7fbff;box-shadow:0 0 0 2px rgba(23,105,232,.08)}
      .benchmark-scenario-card .icon{width:40px;height:40px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;background:#0b63e5;color:#fff;font-size:19px;flex:0 0 auto}.benchmark-scenario-card>span:nth-child(2){min-width:0}.benchmark-scenario-card small{display:block;margin-top:4px;color:#728097}.benchmark-selected-badge{margin-left:auto;padding:4px 8px;border-radius:999px;background:#eaf2ff;color:#075eea;font-size:11px;font-weight:750}
      .benchmark-selected{align-items:flex-start}.benchmark-selected .benchmark-icon{width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:#0b63e5;color:#fff;font-size:21px}.benchmark-selected-title-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.benchmark-tag{display:inline-flex;padding:3px 7px;border-radius:999px;background:#edf4ff;color:#075eea;font-size:10px;font-weight:750}.benchmark-selected small{display:block;margin-top:4px;color:#718099}.benchmark-meta-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0 4px}.benchmark-meta-grid div{padding:9px 10px;border:1px solid #e0e7f0;border-radius:7px;background:#f8fafc;min-width:0}.benchmark-meta-grid span{display:block;color:#758299;font-size:10px}.benchmark-meta-grid strong{display:block;margin-top:4px;font-size:11px;overflow-wrap:anywhere}
      .recent-benchmark{margin-top:18px;padding:0;overflow:hidden}.recent-benchmark>.section-heading{padding:18px 20px;border-bottom:1px solid var(--reference-line)}
      .recent-benchmark-table-wrap{overflow:auto}.recent-benchmark-table{width:100%;border-collapse:collapse;font-size:12px}.recent-benchmark-table th,.recent-benchmark-table td{padding:13px 16px;border-bottom:1px solid #edf1f6;text-align:left;white-space:nowrap}.recent-benchmark-table th{background:#fbfcfe;color:#5d6b82;font-weight:750}.recent-benchmark-table td strong{font-weight:750}.recent-benchmark-empty{padding:34px 20px;text-align:center;color:#6b7890}.recent-benchmark-note{padding:10px 20px 16px;color:#77849a;font-size:11px}
      .result-search-shell{display:flex;align-items:center;gap:10px;margin:0 0 14px;padding:8px 14px;border:1px solid var(--reference-line);border-radius:8px;background:#fff}.result-search-shell::before{content:"⌕";font-size:20px;color:#718099}.result-search-shell label{display:block;flex:1;font-size:0}.result-search-shell input{height:40px;border:0;padding:0;outline:0;font-size:13px}.result-search-shell input:focus{box-shadow:none}.experiment-id-search{font-size:13px}
      [data-result-panel="history"] .filter-bar{grid-template-columns:repeat(5,minmax(120px,1fr)) auto;align-items:end}.bulk-delete-actions{align-self:flex-end}
      .history-table-card table{width:100%}.history-table-card th{background:#fbfcfe}.history-table-card tbody tr:hover{background:#fbfdff}
      .aiopslab-tool-panel table{width:100%;border-collapse:collapse}.aiopslab-tool-panel .table-wrap{margin-top:16px;border:1px solid var(--reference-line);border-radius:8px;overflow:auto}.aiopslab-tool-panel th,.aiopslab-tool-panel td{padding:13px 14px;border-bottom:1px solid #edf1f6;text-align:left;font-size:12px;white-space:nowrap}.aiopslab-tool-panel th{background:#fbfcfe;color:#5d6b82;font-weight:750}.aiopslab-tool-panel tbody tr:last-child td{border-bottom:0}.aiopslab-tool-panel .empty-cell{text-align:center;color:#718099;padding:32px 14px}.aiopslab-tool-panel .inline-status{border-radius:7px}.aiopslab-history-filters{align-items:end}
      .detail-header{display:grid;grid-template-columns:42px auto minmax(0,1fr) auto;gap:12px;align-items:center;margin-bottom:14px}.detail-header>button{width:42px;height:38px;padding:0;border:1px solid #cbd6e5;border-radius:7px;background:#fff;font-size:18px}.detail-header h2{margin:0;font-size:25px}.detail-header>strong{color:#69778f;font-size:12px;font-weight:550;min-width:0}.detail-header>div:not(.detail-header-actions):empty{display:none}.detail-header>.detail-header-actions{grid-column:4;grid-row:1;justify-self:end;display:flex;gap:8px;align-items:center;flex-wrap:nowrap}.detail-header>.detail-header-actions button{white-space:nowrap}.detail-summary{min-height:530px}.success-hero{padding:26px 18px;border-radius:8px;background:#eefaf5;border:1px solid #d5f1e4}.success-hero strong{color:#087a46}
      .aiopslab-tool-panel{min-height:380px}.benchmark-metric-grid>div{min-height:74px}
      @media(max-width:1050px){.platform-shell{grid-template-columns:220px minmax(0,1fr)}.view-container{padding:20px}.aiopslab-reference-grid{grid-template-columns:1fr}.selected-summary{position:static}.reference-recovery-setup{grid-template-columns:1fr}.detail-header{grid-template-columns:42px 1fr}.detail-header>strong{grid-column:2}.detail-header>.detail-header-actions{grid-column:1/-1;grid-row:auto;justify-self:start;flex-wrap:wrap}}
      @media(max-width:760px){.platform-shell{display:block}.platform-sidebar{position:relative;width:100%;height:auto}.platform-nav{grid-template-columns:1fr 1fr}.sidebar-connections{margin-top:18px}.view-container{padding:16px}.result-search-shell{margin-top:8px}[data-result-panel="history"] .filter-bar{grid-template-columns:1fr 1fr}.benchmark-meta-grid{grid-template-columns:1fr}}
    `;
    document.head.append(style);
  }

  function ensureExperimentIdSearch() {
    const input = $("history-search");
    if (!input || input.closest(".result-search-shell")) return;
    input.classList.add("experiment-id-search");
    input.placeholder = "Experiment ID 검색...";
    input.setAttribute("aria-label", "Experiment ID 검색");
    const oldLabel = input.closest("label");
    oldLabel?.classList.remove("visually-hidden");
    const shell = document.createElement("div");
    shell.className = "result-search-shell";
    shell.dataset.dataFirst = "true";
    const historyPanel = document.querySelector('[data-result-panel="history"]');
    const filterBar = historyPanel?.querySelector(".filter-bar");
    if (oldLabel) shell.append(oldLabel); else shell.append(input);
    filterBar?.after(shell);
  }

  function selectedBenchmarkId() {
    return $("aiopslab-benchmark-select")?.value || benchmarkCatalog[0]?.id || "";
  }

  function benchmarkById(id) {
    return benchmarkCatalog.find((item) => item.id === id) || null;
  }

  function benchmarkDisplayName(id) {
    return benchmarkById(id)?.title || id || "—";
  }

  function renderBenchmarkPresentation() {
    const selectedId = selectedBenchmarkId();
    const selected = benchmarkById(selectedId) || benchmarkCatalog[0];
    if (!selected) return;

    const select = $("aiopslab-benchmark-select");
    const options = select ? Array.from(select.options).filter((option) => option.value && !/불러오는 중/.test(option.textContent || "")) : [];
    const cards = Array.from(document.querySelectorAll("#aiopslab-scenario-list .benchmark-scenario-card"));
    cards.forEach((card, index) => {
      const option = options[index];
      const item = benchmarkById(option?.value) || selected;
      const active = item.id === selectedId;
      card.dataset.benchmarkId = item.id;
      card.classList.toggle("active", active);
      card.setAttribute("aria-pressed", String(active));
      card.innerHTML = `<span class="icon">${esc(item.icon || "▦")}</span><span><strong>${esc(item.title || item.id)}</strong><small>${esc(item.subtitle || item.problem_id || "AIOpsLab Benchmark")}</small></span>${active ? '<span class="benchmark-selected-badge">선택됨</span>' : ""}`;
    });

    setTextSafe("aiopslab-selected-title", selected.title || selected.id);
    setTextSafe("aiopslab-benchmark-description", selected.description || "등록된 설명이 없습니다.");
    const selectedBlock = document.querySelector(".benchmark-selected");
    if (selectedBlock) {
      const icon = selectedBlock.querySelector(".benchmark-icon");
      if (icon) icon.textContent = selected.icon || "▦";
      const textBlock = selectedBlock.querySelector("div");
      if (textBlock) {
        const title = textBlock.querySelector("strong");
        if (title && !$("aiopslab-selected-title-row")) {
          const row = document.createElement("div");
          row.id = "aiopslab-selected-title-row";
          row.className = "benchmark-selected-title-row";
          title.before(row);
          row.append(title);
          const tag = document.createElement("span");
          tag.id = "aiopslab-selected-tag";
          tag.className = "benchmark-tag";
          row.append(tag);
        }
        const tag = $("aiopslab-selected-tag");
        if (tag) tag.textContent = selected.tag || "AIOpsLab";
        const subtitle = textBlock.querySelector("small");
        if (subtitle) subtitle.textContent = selected.subtitle || selected.problem_id || "AIOpsLab Benchmark";
      }
    }

    let meta = $("aiopslab-selected-meta");
    const description = $("aiopslab-benchmark-description");
    if (!meta && description) {
      meta = document.createElement("div");
      meta.id = "aiopslab-selected-meta";
      meta.className = "benchmark-meta-grid";
      description.after(meta);
    }
    if (meta) {
      meta.innerHTML = `<div><span>Namespace</span><strong>${esc(selected.namespace || "—")}</strong></div><div><span>Service</span><strong>${esc(selected.service || "—")}</strong></div><div><span>Problem ID</span><strong>${esc(selected.problem_id || "—")}</strong></div>`;
    }

    const info = document.querySelector(".benchmark-info");
    if (info) {
      const sourceLabel = Array.from(info.querySelectorAll("span")).find((node) => node.textContent.trim() === "데이터 소스");
      const sourceValue = sourceLabel?.nextElementSibling;
      if (sourceValue) sourceValue.textContent = selected.dataset_label || "AIOpsLab Dataset";
    }
  }

  function setTextSafe(id, value) {
    const node = $(id);
    if (node) node.textContent = value == null || value === "" ? "—" : String(value);
  }

  async function loadBenchmarkPresentation() {
    try {
      const payload = await requestJson("/api/benchmarks/aiopslab");
      benchmarkCatalog = Array.isArray(payload.benchmarks) ? payload.benchmarks : [];
      renderBenchmarkPresentation();
    } catch (_error) {
      benchmarkCatalog = [];
    }
  }

  function metricCells(result) {
    return {
      accuracy: result?.accuracy == null ? "—" : fmtPercent(result.accuracy),
      ttd: result?.average_ttd == null ? "—" : `${fmtNumber(result.average_ttd, 3)}s`,
      steps: result?.average_steps == null ? "—" : fmtNumber(result.average_steps, 2),
      reward: result?.average_final_reward == null ? "—" : fmtNumber(result.average_final_reward, 3),
    };
  }

  function recentBenchmarkTable(jobs) {
    const rows = jobs.map((job) => {
      const result = job.result || {};
      const metrics = metricCells(result);
      const benchmark = benchmarkDisplayName(job.request?.benchmark_id);
      return `<tr><td><strong>${esc(benchmark)}</strong></td><td>${esc(statusLabel(job.status))}</td><td>${esc(fmtDate(job.started_at || job.created_at))}</td><td>${metrics.accuracy}</td><td>${metrics.ttd}</td><td>${metrics.steps}</td><td>${metrics.reward}</td></tr>`;
    }).join("");
    return `<div class="recent-benchmark-table-wrap"><table class="recent-benchmark-table"><thead><tr><th>Benchmark</th><th>상태</th><th>실행 시간</th><th>${supportedAIOpsLabMetrics[0]}</th><th>${supportedAIOpsLabMetrics[1]}</th><th>${supportedAIOpsLabMetrics[2]}</th><th>${supportedAIOpsLabMetrics[3]}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  async function renderRecentBenchmarkResults(force = false) {
    const section = document.querySelector(".recent-benchmark");
    if (!section || (!force && section.dataset.dataFirstLoaded === "1")) return;
    section.dataset.dataFirstLoaded = "1";
    let content = section.querySelector(".recent-benchmark-data");
    if (!content) {
      content = document.createElement("div");
      content.className = "recent-benchmark-data";
      const heading = section.querySelector(".section-heading");
      heading?.after(content);
    }
    content.innerHTML = '<div class="recent-benchmark-empty">최근 Benchmark 결과를 불러오는 중입니다.</div>';
    try {
      const payload = await requestJson("/api/benchmarks/aiopslab/jobs?limit=6");
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      content.innerHTML = jobs.length
        ? `${recentBenchmarkTable(jobs)}<div class="recent-benchmark-note">실제 저장된 AIOpsLab Job만 표시합니다. 값이 없는 지표는 — 로 유지합니다.</div>`
        : '<div class="recent-benchmark-empty">저장된 Benchmark 실행 결과가 없습니다.</div>';
    } catch (error) {
      content.innerHTML = `<div class="recent-benchmark-empty">최근 결과를 불러오지 못했습니다: ${esc(error instanceof Error ? error.message : String(error))}</div>`;
      section.dataset.dataFirstLoaded = "0";
    }
  }

  function improveAIOpsLabMetricCopy() {
    const cards = document.querySelectorAll(".benchmark-metric-grid > div");
    const labels = supportedAIOpsLabMetrics;
    cards.forEach((card, index) => {
      const label = card.querySelector("span");
      if (label && labels[index]) label.textContent = labels[index];
    });
  }

  function polishScenarioCards() {
    document.querySelectorAll("#scenario-list button[data-scenario]").forEach((button) => {
      button.dataset.visualPolished = "1";
    });
  }

  function polishResultTable() {
    const body = $("experiment-history-body");
    if (!body) return;
    body.closest(".history-table-card,.surface")?.classList.add("data-first-results");
  }

  function applyFinitePolish() {
    ensureExperimentIdSearch();
    improveAIOpsLabMetricCopy();
    polishScenarioCards();
    polishResultTable();
    renderBenchmarkPresentation();
  }

  async function bootstrap() {
    applyFinitePolish();
    await loadBenchmarkPresentation();
    renderRecentBenchmarkResults(true);
    $("aiopslab-benchmark-select")?.addEventListener("change", () => setTimeout(renderBenchmarkPresentation, 0));
    // app.js finishes some API-backed rendering after DOMContentLoaded. Re-apply a
    // bounded number of times instead of observing the whole document indefinitely.
    [250, 900, 1800].forEach((delay) => setTimeout(() => {
      applyFinitePolish();
      if (delay === 900) renderRecentBenchmarkResults(true);
    }, delay));
    document.querySelector('[data-view="aiopslab"]')?.addEventListener("click", () => setTimeout(() => {
      renderBenchmarkPresentation();
      renderRecentBenchmarkResults(true);
    }, 0));
    window.addEventListener("aiops:history-updated", () => setTimeout(polishResultTable, 0));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootstrap);
  else bootstrap();
})();
