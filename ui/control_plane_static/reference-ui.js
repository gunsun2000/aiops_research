(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const node = $(id); if (node) node.textContent = value == null || value === "" ? "—" : String(value); };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const num = (value, digits = 3) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  const pct = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : "—";
  const dateText = (value) => { if (!value) return "—"; const d = new Date(value); return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ko-KR", { hour12: false }); };
  const statusText = (value) => ({ queued: "대기 중", running: "실행 중", cancelling: "취소 중", completed: "완료", failed: "실패", blocked: "안전 중단", cancelled: "취소됨", interrupted: "중단" }[value] || value || "—");
  const scenarioDescriptions = { "Pod Failure": "Pod 비정상 종료", "CPU Saturation": "CPU 과부하", "Memory Saturation": "Memory 과부하", "Network Delay": "네트워크 지연" };
  const RESULT_QUERY_MAP = { period: "history-period", scenario: "history-scenario", controller: "history-controller", mode: "history-mode", status: "history-status", q: "history-search" };
  const aiopslabState = { jobs: [], tab: "evaluation", historyPage: 1, historyPageSize: 8, historyStatus: "all", historyQuery: "", loading: false, error: "" };
  const resultState = { page: 1, pageSize: 10, syncing: false, searchTimer: null };

  async function requestJson(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.detail || `요청 실패 (${response.status})`);
    return payload;
  }

  function selectedScenarioLabel() {
    return document.querySelector('#scenario-list button[aria-pressed="true"] strong')?.textContent.trim() || $('global-scenario')?.textContent.trim() || "—";
  }
  function selectedControllerLabel() {
    return document.querySelector('#controller-options button[aria-pressed="true"] strong')?.textContent.trim() || $('global-controller')?.textContent.trim() || "—";
  }
  function selectedModeLabel() {
    const selected = document.querySelector('#mode-control button[aria-pressed="true"] strong');
    if (selected) return selected.textContent.trim();
    return $('overview-mode-select')?.selectedOptions?.[0]?.textContent.trim() || "—";
  }
  function syncReferenceSummary() {
    const scenario = selectedScenarioLabel(), controller = selectedControllerLabel(), mode = selectedModeLabel();
    text('overview-current-scenario', scenario); text('overview-current-controller', controller); text('overview-current-mode', mode);
    text('recovery-header-controller', controller === 'Deterministic Mutual Supervision' ? 'Deterministic' : controller);
    text('selected-summary-scenario', scenario); text('selected-summary-scenario-desc', scenarioDescriptions[scenario] || '등록된 장애 시나리오');
    text('selected-summary-controller', controller); text('selected-summary-controller-note', mode); text('selected-summary-mode', mode);
  }
  function bindRecoveryHeaderRun() {
    const button = $('recovery-header-run'); if (!button || button.dataset.bound === 'true') return;
    button.dataset.bound = 'true'; button.addEventListener('click', () => $('run-experiment')?.click());
  }

  function benchmarkOptionSummary(option) {
    const raw = option?.textContent?.trim() || '등록된 Benchmark';
    const parts = raw.split('·').map((part) => part.trim()).filter(Boolean);
    return { title: parts[0] || raw, detail: parts.slice(1).join(' · ') || 'AIOpsLab Benchmark' };
  }
  function benchmarkLabel(id) {
    const option = $('aiopslab-benchmark-select') ? Array.from($('aiopslab-benchmark-select').options).find((item) => item.value === id) : null;
    return option ? benchmarkOptionSummary(option).title : (id || "—");
  }
  function renderBenchmarkScenarioCards() {
    const select = $('aiopslab-benchmark-select'), list = $('aiopslab-scenario-list'); if (!select || !list) return;
    const options = Array.from(select.options).filter((option) => option.value && !/불러오는 중/.test(option.textContent || ''));
    if (!options.length) { list.innerHTML = '<p class="empty-state">등록된 Benchmark 시나리오가 없습니다.</p>'; text('aiopslab-selected-title', '데이터 없음'); return; }
    list.replaceChildren(...options.map((option, index) => {
      const summary = benchmarkOptionSummary(option), button = document.createElement('button');
      button.type = 'button'; button.className = `benchmark-scenario-card${option.selected ? ' active' : ''}`; button.setAttribute('aria-pressed', String(option.selected));
      button.innerHTML = `<span class="icon">${index % 3 === 0 ? '▦' : index % 3 === 1 ? '◆' : '▣'}</span><span><strong>${esc(summary.title)}</strong><small>${esc(summary.detail)}</small></span>`;
      button.addEventListener('click', () => { select.value = option.value; select.dispatchEvent(new Event('change', { bubbles: true })); renderBenchmarkScenarioCards(); });
      return button;
    }));
    text('aiopslab-selected-title', benchmarkOptionSummary(select.selectedOptions[0] || options[0]).title);
  }

  function detectorLabel(job) { return job?.detector_label || job?.result?.detector_label || "AI-MCMP Four-Agent"; }
  function detectorId(job) { return job?.detector_id || job?.result?.detector_id || "ai-mcmp-four-agent"; }

  function findExistingAIOpsLabTabButtons(panel, labels) {
    const wanted = Object.values(labels);
    return Array.from(panel.querySelectorAll('button')).filter((button) => wanted.includes(button.textContent.trim()));
  }

  function ensureAIOpsLabTabs() {
    const panel = document.querySelector('[data-view-panel="aiopslab"]'); if (!panel || $('aiopslab-functional-tabs')) return;
    const labels = { evaluation: '벤치마크 평가', comparison: '모델 성능 비교', history: '실행 이력' };
    const existing = findExistingAIOpsLabTabButtons(panel, labels);
    let nav;
    if (existing.length === 3 && existing.every((button) => button.parentElement === existing[0].parentElement)) {
      nav = existing[0].parentElement;
      nav.id = 'aiopslab-functional-tabs'; nav.classList.add('aiopslab-functional-tabs'); nav.setAttribute('role', 'tablist');
      existing.forEach((button) => {
        const entry = Object.entries(labels).find(([, label]) => label === button.textContent.trim());
        if (!entry) return;
        button.type = 'button'; button.dataset.aiopslabTab = entry[0]; button.setAttribute('role', 'tab');
      });
    } else {
      nav = document.createElement('nav'); nav.id = 'aiopslab-functional-tabs'; nav.className = 'aiopslab-functional-tabs'; nav.setAttribute('role', 'tablist');
      Object.entries(labels).forEach(([key, label]) => { const button = document.createElement('button'); button.type = 'button'; button.dataset.aiopslabTab = key; button.setAttribute('role', 'tab'); button.textContent = label; nav.append(button); });
      const heading = panel.querySelector('.page-heading, .aiopslab-header') || panel.firstElementChild; heading?.after(nav);
    }
    nav.querySelectorAll('[data-aiopslab-tab]').forEach((button) => button.addEventListener('click', () => selectAIOpsLabTab(button.dataset.aiopslabTab)));

    const evaluation = document.createElement('div'); evaluation.dataset.aiopslabPanel = 'evaluation'; evaluation.id = 'aiopslab-evaluation-panel';
    Array.from(panel.children).filter((child) => child !== nav && !child.matches('.page-heading,.aiopslab-header') && !child.hasAttribute('data-aiopslab-panel')).forEach((child) => evaluation.append(child));
    panel.append(evaluation);

    const comparison = document.createElement('section'); comparison.dataset.aiopslabPanel = 'comparison'; comparison.id = 'aiopslab-comparison-panel'; comparison.hidden = true;
    comparison.innerHTML = `<div class="surface aiopslab-tool-panel"><div class="section-heading"><div><h3>모델 · Detector 성능 비교</h3><p>저장된 실제 Benchmark Job 결과만 집계합니다.</p></div><button type="button" id="aiopslab-comparison-refresh" class="secondary-action">새로고침</button></div><div id="aiopslab-comparison-status" class="inline-status" aria-live="polite">결과를 불러오는 중입니다.</div><div id="aiopslab-comparison-cards" class="detector-comparison-cards"></div><div class="table-wrap"><table><thead><tr><th>Detector</th><th>실행 수</th><th>Accuracy</th><th>Avg TTD</th><th>Avg Steps</th><th>Avg Reward</th></tr></thead><tbody id="aiopslab-comparison-body"></tbody></table></div></div>`;
    panel.append(comparison);

    const historyPanel = document.createElement('section'); historyPanel.dataset.aiopslabPanel = 'history'; historyPanel.id = 'aiopslab-history-panel'; historyPanel.hidden = true;
    historyPanel.innerHTML = `<div class="surface aiopslab-tool-panel"><div class="section-heading"><div><h3>AIOpsLab 실행 이력</h3><p>SQLite에 저장된 Benchmark Job을 조회합니다.</p></div><button type="button" id="aiopslab-history-refresh" class="secondary-action">새로고침</button></div><div class="aiopslab-history-filters"><label>상태<select id="aiopslab-history-status"><option value="all">전체</option><option value="completed">완료</option><option value="running">실행 중</option><option value="failed">실패</option><option value="blocked">안전 중단</option><option value="cancelled">취소</option></select></label><label>검색<input id="aiopslab-history-query" type="search" placeholder="Job ID 또는 시나리오" /></label><label>페이지 크기<select id="aiopslab-history-page-size"><option value="5">5</option><option value="8" selected>8</option><option value="15">15</option></select></label></div><div id="aiopslab-history-status-line" class="inline-status" aria-live="polite"></div><div class="table-wrap"><table><thead><tr><th>Job ID</th><th>시나리오</th><th>Detector</th><th>반복</th><th>상태</th><th>시작 시간</th><th>Accuracy</th><th>Avg TTD</th><th>상세</th></tr></thead><tbody id="aiopslab-history-body"></tbody></table></div><div class="pagination-row"><button type="button" id="aiopslab-history-prev" class="secondary-action">이전</button><span id="aiopslab-history-page-info">1 / 1</span><button type="button" id="aiopslab-history-next" class="secondary-action">다음</button></div><div id="aiopslab-job-detail" class="aiopslab-job-detail" hidden></div></div>`;
    panel.append(historyPanel);

    $('aiopslab-comparison-refresh')?.addEventListener('click', loadAIOpsLabJobs); $('aiopslab-history-refresh')?.addEventListener('click', loadAIOpsLabJobs);
    $('aiopslab-history-status')?.addEventListener('change', (e) => { aiopslabState.historyStatus = e.target.value; aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-query')?.addEventListener('input', (e) => { aiopslabState.historyQuery = e.target.value.trim().toLowerCase(); aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-page-size')?.addEventListener('change', (e) => { aiopslabState.historyPageSize = Number(e.target.value) || 8; aiopslabState.historyPage = 1; renderAIOpsLabHistory(); });
    $('aiopslab-history-prev')?.addEventListener('click', () => { aiopslabState.historyPage = Math.max(1, aiopslabState.historyPage - 1); renderAIOpsLabHistory(); });
    $('aiopslab-history-next')?.addEventListener('click', () => { aiopslabState.historyPage += 1; renderAIOpsLabHistory(); });
    const requested = new URLSearchParams(window.location.search).get('aiopslab_tab'); selectAIOpsLabTab(['evaluation','comparison','history'].includes(requested) ? requested : 'evaluation', false);
  }

  function selectAIOpsLabTab(tab, updateUrl = true) {
    const resolved = ['evaluation','comparison','history'].includes(tab) ? tab : 'evaluation'; aiopslabState.tab = resolved;
    document.querySelectorAll('[data-aiopslab-tab]').forEach((button) => { const selected = button.dataset.aiopslabTab === resolved; button.setAttribute('aria-selected', String(selected)); button.setAttribute('aria-pressed', String(selected)); });
    document.querySelectorAll('[data-aiopslab-panel]').forEach((panel) => { panel.hidden = panel.dataset.aiopslabPanel !== resolved; });
    if (updateUrl) { const url = new URL(window.location.href); if (resolved === 'evaluation') url.searchParams.delete('aiopslab_tab'); else url.searchParams.set('aiopslab_tab', resolved); history.replaceState(null, '', `${url.pathname}${url.search}${window.location.hash || '#aiopslab'}`); }
    if (resolved !== 'evaluation') loadAIOpsLabJobs();
  }

  async function loadAIOpsLabJobs() {
    if (aiopslabState.loading) return; aiopslabState.loading = true; aiopslabState.error = '';
    text('aiopslab-comparison-status', '저장된 Benchmark 결과를 불러오는 중입니다.');
    try { const payload = await requestJson('/api/benchmarks/aiopslab/jobs?limit=100'); aiopslabState.jobs = Array.isArray(payload.jobs) ? payload.jobs : []; }
    catch (error) { aiopslabState.error = error instanceof Error ? error.message : String(error); }
    finally { aiopslabState.loading = false; renderAIOpsLabComparison(); renderAIOpsLabHistory(); }
  }
  function mean(values) { return values.length ? values.reduce((a,b) => a+b,0) / values.length : null; }
  function values(jobs, key) { return jobs.map((job) => Number(job?.result?.[key])).filter(Number.isFinite); }
  function renderAIOpsLabComparison() {
    const body = $('aiopslab-comparison-body'), cards = $('aiopslab-comparison-cards'), status = $('aiopslab-comparison-status'); if (!body || !cards || !status) return;
    if (aiopslabState.error) { status.textContent = `결과를 불러오지 못했습니다: ${aiopslabState.error}`; body.innerHTML = '<tr><td colspan="6" class="empty-cell">데이터를 불러올 수 없습니다.</td></tr>'; cards.replaceChildren(); return; }
    const groups = new Map(); aiopslabState.jobs.filter((job) => job.status === 'completed' && job.result).forEach((job) => { const id = detectorId(job); if (!groups.has(id)) groups.set(id, { label: detectorLabel(job), jobs: [] }); groups.get(id).jobs.push(job); });
    if (!groups.size) { status.textContent = '비교할 실제 Benchmark 결과가 없습니다.'; body.innerHTML = '<tr><td colspan="6" class="empty-cell">Benchmark를 실행하면 실제 결과가 여기에 표시됩니다.</td></tr>'; cards.replaceChildren(); return; }
    status.textContent = groups.size === 1 ? '비교 가능한 Detector가 1개입니다.' : `${groups.size}개 Detector의 실제 결과를 비교합니다.`;
    const rows = [], nodes = [];
    groups.forEach((group) => { const accuracy = mean(values(group.jobs,'accuracy')), ttd = mean(values(group.jobs,'average_ttd')), steps = mean(values(group.jobs,'average_steps')), reward = mean(values(group.jobs,'average_final_reward'));
      rows.push(`<tr><td><strong>${esc(group.label)}</strong></td><td>${group.jobs.length}</td><td>${accuracy == null ? '—' : pct(accuracy)}</td><td>${ttd == null ? '—' : `${num(ttd)}s`}</td><td>${steps == null ? '—' : num(steps,2)}</td><td>${reward == null ? '—' : num(reward)}</td></tr>`);
      const card = document.createElement('article'); card.className = 'detector-card'; card.innerHTML = `<span>Detector</span><strong>${esc(group.label)}</strong><small>${group.jobs.length}개 완료 Job</small><dl><div><dt>Accuracy</dt><dd>${accuracy == null ? '—' : pct(accuracy)}</dd></div><div><dt>Avg TTD</dt><dd>${ttd == null ? '—' : `${num(ttd)}s`}</dd></div><div><dt>Avg Steps</dt><dd>${steps == null ? '—' : num(steps,2)}</dd></div><div><dt>Avg Reward</dt><dd>${reward == null ? '—' : num(reward)}</dd></div></dl>`; nodes.push(card);
    }); body.innerHTML = rows.join(''); cards.replaceChildren(...nodes);
  }
  function filteredAIOpsLabJobs() { return aiopslabState.jobs.filter((job) => { if (aiopslabState.historyStatus !== 'all' && job.status !== aiopslabState.historyStatus) return false; if (!aiopslabState.historyQuery) return true; return `${job.job_id||''} ${job.request?.benchmark_id||''} ${benchmarkLabel(job.request?.benchmark_id)} ${detectorLabel(job)}`.toLowerCase().includes(aiopslabState.historyQuery); }); }
  function renderAIOpsLabHistory() {
    const body = $('aiopslab-history-body'), line = $('aiopslab-history-status-line'); if (!body || !line) return;
    if (aiopslabState.error) { line.textContent = `실행 이력을 불러오지 못했습니다: ${aiopslabState.error}`; body.innerHTML = '<tr><td colspan="9" class="empty-cell">재시도 버튼을 눌러 다시 조회하세요.</td></tr>'; return; }
    const jobs = filteredAIOpsLabJobs(), pages = Math.max(1, Math.ceil(jobs.length / aiopslabState.historyPageSize)); aiopslabState.historyPage = Math.min(aiopslabState.historyPage,pages); const start=(aiopslabState.historyPage-1)*aiopslabState.historyPageSize, pageJobs=jobs.slice(start,start+aiopslabState.historyPageSize);
    line.textContent = jobs.length ? `총 ${jobs.length}개 Benchmark Job` : '조건에 맞는 Benchmark 실행 이력이 없습니다.'; text('aiopslab-history-page-info',`${aiopslabState.historyPage} / ${pages}`); $('aiopslab-history-prev').disabled=aiopslabState.historyPage<=1; $('aiopslab-history-next').disabled=aiopslabState.historyPage>=pages;
    if (!pageJobs.length) { body.innerHTML='<tr><td colspan="9" class="empty-cell">실행 이력이 없습니다.</td></tr>'; return; }
    body.innerHTML = pageJobs.map((job) => { const result=job.result||{}; return `<tr><td><code>${esc(job.job_id||'—')}</code></td><td>${esc(benchmarkLabel(job.request?.benchmark_id))}</td><td>${esc(detectorLabel(job))}</td><td>${job.request?.repetitions??'—'}</td><td>${esc(statusText(job.status))}</td><td>${esc(dateText(job.started_at||job.created_at))}</td><td>${result.accuracy==null?'—':pct(result.accuracy)}</td><td>${result.average_ttd==null?'—':`${num(result.average_ttd)}s`}</td><td><button type="button" class="table-action" data-aiopslab-job-detail="${esc(job.job_id)}">보기</button></td></tr>`; }).join('');
    body.querySelectorAll('[data-aiopslab-job-detail]').forEach((button)=>button.addEventListener('click',()=>showAIOpsLabJobDetail(button.dataset.aiopslabJobDetail)));
  }
  async function showAIOpsLabJobDetail(jobId) {
    const detail=$('aiopslab-job-detail'); if(!detail)return; detail.hidden=false; detail.innerHTML='<p class="inline-status">상세 데이터를 불러오는 중입니다.</p>';
    try { const job=await requestJson(`/api/benchmarks/aiopslab/jobs/${encodeURIComponent(jobId)}`), result=job.result||{}, artifacts=Object.entries(job.artifact_urls||{}), events=Array.isArray(job.events)?job.events:[];
      detail.innerHTML=`<div class="section-heading"><div><h4>${esc(job.job_id)}</h4><p>${esc(benchmarkLabel(job.request?.benchmark_id))} · ${esc(detectorLabel(job))}</p></div><button type="button" id="aiopslab-job-detail-close" class="secondary-action">닫기</button></div><div class="detail-metric-row"><span>Status<strong>${esc(statusText(job.status))}</strong></span><span>Accuracy<strong>${result.accuracy==null?'—':pct(result.accuracy)}</strong></span><span>Avg TTD<strong>${result.average_ttd==null?'—':`${num(result.average_ttd)}s`}</strong></span><span>Avg Reward<strong>${result.average_final_reward==null?'—':num(result.average_final_reward)}</strong></span></div><div class="artifact-links">${artifacts.length?artifacts.map(([name,href])=>`<a href="${esc(href)}" target="_blank" rel="noreferrer">${esc(name)}</a>`).join(''):'<span>다운로드 가능한 Artifact가 없습니다.</span>'}</div><details><summary>실행 이벤트 ${events.length}개</summary><ol>${events.length?events.map((event)=>`<li><time>${esc(dateText(event.created_at))}</time> <strong>${esc(event.stage||'—')}</strong> ${esc(event.message||'')}</li>`).join(''):'<li>이벤트가 없습니다.</li>'}</ol></details>`; $('aiopslab-job-detail-close')?.addEventListener('click',()=>{detail.hidden=true;});
    } catch(error) { detail.innerHTML=`<p class="inline-error">상세 데이터를 불러오지 못했습니다: ${esc(error instanceof Error?error.message:String(error))}</p>`; }
  }

  function updateDashboardDonut() {
    const donut=$('dashboard-donut'), totalNode=$('dashboard-total'), successNode=$('dashboard-success-rate'); if(!donut||!totalNode||!successNode)return; const total=Number(totalNode.textContent.trim()), rate=Number((successNode.textContent||'').replace('%',''));
    if(!Number.isFinite(total)||total<=0||!Number.isFinite(rate)){donut.style.background='conic-gradient(#e7edf5 0 100%)';donut.innerHTML='<span>데이터 없음</span>';return;} const value=Math.max(0,Math.min(100,rate));donut.style.background=`conic-gradient(#0bb46c 0 ${value}%, #ef4b4f ${value}% 100%)`;donut.innerHTML=`<span>${value.toFixed(1)}%</span>`;
  }

  function ensureExperimentResultControls() {
    const body=$('experiment-history-body'); if(!body)return; const card=body.closest('.history-table-card,.surface'), filterBar=document.querySelector('[data-result-panel="history"] .filter-bar');
    if(filterBar&&!$('result-filter-reset')){const reset=document.createElement('button');reset.type='button';reset.id='result-filter-reset';reset.className='secondary-action';reset.textContent='필터 초기화';reset.addEventListener('click',resetResultFilters);filterBar.append(reset);}
    if(card&&!$('result-pagination')){const pager=document.createElement('div');pager.id='result-pagination';pager.className='pagination-row result-pagination';pager.innerHTML=`<span id="result-loaded-boundary" class="helper-text"></span><label>페이지 크기<select id="result-page-size"><option value="5">5</option><option value="10" selected>10</option><option value="20">20</option></select></label><button type="button" id="result-pagination-prev" class="secondary-action">이전</button><span id="result-pagination-info">1 / 1</span><button type="button" id="result-pagination-next" class="secondary-action">다음</button>`;card.append(pager);$('result-page-size').addEventListener('change',(e)=>{resultState.pageSize=Number(e.target.value)||10;resultState.page=1;syncResultFiltersToUrl();applyExperimentPagination();});$('result-pagination-prev').addEventListener('click',()=>{resultState.page=Math.max(1,resultState.page-1);syncResultFiltersToUrl();applyExperimentPagination();});$('result-pagination-next').addEventListener('click',()=>{resultState.page+=1;syncResultFiltersToUrl();applyExperimentPagination();});}
    bindResultFilterUrlSync();syncResultFiltersFromUrl();applyExperimentPagination();
  }
  function bindResultFilterUrlSync(){Object.entries(RESULT_QUERY_MAP).forEach(([key,id])=>{const c=$(id);if(!c||c.dataset.urlBound==='true')return;c.dataset.urlBound='true';c.addEventListener(key==='q'?'input':'change',()=>{if(resultState.syncing)return;resultState.page=1;if(key==='q'){clearTimeout(resultState.searchTimer);resultState.searchTimer=setTimeout(()=>{syncResultFiltersToUrl();applyExperimentPagination();},300);}else{syncResultFiltersToUrl();setTimeout(applyExperimentPagination,0);}});});}
  function syncResultFiltersFromUrl(){if(resultState.syncing)return;resultState.syncing=true;const params=new URLSearchParams(window.location.search);Object.entries(RESULT_QUERY_MAP).forEach(([key,id])=>{const c=$(id),v=params.get(key);if(!c||v==null||v==='')return;if(c.tagName==='SELECT'&&!Array.from(c.options).some((o)=>o.value===v))return;c.value=v;c.dispatchEvent(new Event(key==='q'?'input':'change',{bubbles:true}));});resultState.page=Math.max(1,Number(params.get('page'))||1);resultState.pageSize=[5,10,20].includes(Number(params.get('page_size')))?Number(params.get('page_size')):10;if($('result-page-size'))$('result-page-size').value=String(resultState.pageSize);resultState.syncing=false;setTimeout(applyExperimentPagination,0);}
  function syncResultFiltersToUrl(){if(resultState.syncing)return;const url=new URL(window.location.href);Object.entries(RESULT_QUERY_MAP).forEach(([key,id])=>{const c=$(id);if(!c)return;const v=c.value.trim();if(!v||v==='all')url.searchParams.delete(key);else url.searchParams.set(key,v);});if(resultState.page>1)url.searchParams.set('page',String(resultState.page));else url.searchParams.delete('page');if(resultState.pageSize!==10)url.searchParams.set('page_size',String(resultState.pageSize));else url.searchParams.delete('page_size');history.replaceState(null,'',`${url.pathname}${url.search}${window.location.hash||'#analysis'}`);}
  function resetResultFilters(){resultState.syncing=true;Object.values(RESULT_QUERY_MAP).forEach((id)=>{const c=$(id);if(!c)return;c.value=c.tagName==='SELECT'?'all':'';c.dispatchEvent(new Event(c.tagName==='SELECT'?'change':'input',{bubbles:true}));});resultState.page=1;resultState.pageSize=10;if($('result-page-size'))$('result-page-size').value='10';resultState.syncing=false;const url=new URL(window.location.href);[...Object.keys(RESULT_QUERY_MAP),'page','page_size'].forEach((key)=>url.searchParams.delete(key));history.replaceState(null,'',`${url.pathname}${url.search}${window.location.hash||'#analysis'}`);setTimeout(applyExperimentPagination,0);}
  function applyExperimentPagination(){const body=$('experiment-history-body');if(!body)return;const rows=Array.from(body.querySelectorAll('tr')).filter((row)=>!row.querySelector('.empty-cell')&&row.children.length>1);if(!rows.length){text('result-pagination-info','1 / 1');if($('result-pagination-prev'))$('result-pagination-prev').disabled=true;if($('result-pagination-next'))$('result-pagination-next').disabled=true;text('result-loaded-boundary','조건에 맞는 실험 결과가 없습니다.');return;}const pages=Math.max(1,Math.ceil(rows.length/resultState.pageSize));resultState.page=Math.min(resultState.page,pages);const start=(resultState.page-1)*resultState.pageSize;rows.forEach((row,i)=>{row.style.display=i>=start&&i<start+resultState.pageSize?'':'none';});text('result-pagination-info',`${resultState.page} / ${pages} · 총 ${rows.length}건`);text('result-loaded-boundary',rows.length>=100?'현재 불러온 최대 100개 결과 범위에서 필터·페이지네이션합니다.':'현재 조회된 전체 결과를 페이지네이션합니다.');$('result-pagination-prev').disabled=resultState.page<=1;$('result-pagination-next').disabled=resultState.page>=pages;}

  function currentExperimentId(){const subtitle=$('detail-experiment-subtitle')?.textContent?.trim()||'', first=subtitle.split(' · ')[0]?.trim();if(first&&/^exp-/.test(first))return first;const global=$('global-experiment-id')?.textContent?.trim();return global&&/^exp-/.test(global)?global:'';}
  async function copyExperimentId(){const id=currentExperimentId();if(!id)return;const button=$('detail-copy-button');try{await navigator.clipboard.writeText(id);if(button){button.textContent='복사됨';setTimeout(()=>{button.textContent='ID 복사';},1200);}}catch(_error){if(button)button.textContent='복사 실패';}}
  function prefillRerun(){const subtitle=$('detail-experiment-subtitle')?.textContent?.trim()||'',parts=subtitle.split(' · ').map((p)=>p.trim()),scenarioText=parts[1]||'',modeText=parts.find((p)=>['Mock','Dry-run','Real'].includes(p))||'',controllerText=parts.find((p)=>p.includes('Deterministic')||p.includes('AutoGen'))||'';const scenario=$('overview-scenario-select');if(scenario&&scenarioText){const option=Array.from(scenario.options).find((o)=>o.textContent.trim()===scenarioText);if(option){scenario.value=option.value;scenario.dispatchEvent(new Event('change',{bubbles:true}));}}const mode=$('overview-mode-select');if(mode&&modeText){mode.value=modeText==='Dry-run'?'dry-run':modeText.toLowerCase();mode.dispatchEvent(new Event('change',{bubbles:true}));}const controller=$('overview-controller-select');if(controller&&controllerText){controller.value=controllerText.includes('AutoGen')?'autogen':'deterministic';controller.dispatchEvent(new Event('change',{bubbles:true}));}window.location.hash='experiment';}
  function ensureDetailActions(){const panel=document.querySelector('[data-view-panel="history"]');if(!panel)return;const heading=panel.querySelector('.page-heading');if(heading&&!$('detail-copy-button')){let actions=heading.querySelector('.detail-header-actions');if(!actions){actions=document.createElement('div');actions.className='detail-header-actions';heading.append(actions);}const copy=document.createElement('button');copy.id='detail-copy-button';copy.type='button';copy.className='secondary-action';copy.textContent='ID 복사';copy.addEventListener('click',copyExperimentId);actions.prepend(copy);[$('detail-download-button'),$('detail-rerun-button')].filter(Boolean).forEach((button)=>{if(button.parentElement!==actions)actions.append(button);});}bindDetailActions();ensureDetailLogControls();ensureDetailEventPayloads();bindDetailTabUrlSync();syncDetailTabFromUrl();}
  function bindDetailActions(){const download=$('detail-download-button');if(download&&download.dataset.bound!=='complete'){download.dataset.bound='complete';download.addEventListener('click',(e)=>{e.preventDefault();toggleArtifactMenu(download);});}const rerun=$('detail-rerun-button');if(rerun&&rerun.dataset.bound!=='complete'){rerun.dataset.bound='complete';rerun.addEventListener('click',(e)=>{e.preventDefault();prefillRerun();});}}
  function toggleArtifactMenu(anchor){let menu=$('detail-artifact-menu');if(!menu){menu=document.createElement('div');menu.id='detail-artifact-menu';menu.className='artifact-popover';anchor.parentElement?.append(menu);}const links=Array.from(document.querySelectorAll('#experiment-artifacts a'));if(!links.length)menu.innerHTML='<span>다운로드 가능한 결과 파일이 없습니다.</span>';else menu.replaceChildren(...links.map((source)=>{const a=document.createElement('a');a.href=source.href;a.target='_blank';a.rel='noreferrer';a.textContent=source.textContent||'결과 파일';return a;}));menu.hidden=false;}
  function bindDetailTabUrlSync(){document.querySelectorAll('[data-detail-tab]').forEach((button)=>{if(button.dataset.urlBound==='true')return;button.dataset.urlBound='true';button.addEventListener('click',()=>syncDetailTabToUrl(button.dataset.detailTab));});}
  function syncDetailTabToUrl(tab){const url=new URL(window.location.href);if(!tab||tab==='summary')url.searchParams.delete('detail_tab');else url.searchParams.set('detail_tab',tab);history.replaceState(null,'',`${url.pathname}${url.search}${window.location.hash||'#history'}`);}
  function syncDetailTabFromUrl(){const tab=new URLSearchParams(window.location.search).get('detail_tab')||'summary',button=document.querySelector(`[data-detail-tab="${CSS.escape(tab)}"]`);if(button&&button.getAttribute('aria-pressed')!=='true')button.click();}
  function ensureDetailLogControls(){const pre=$('detail-logs');if(!pre||$('detail-log-search'))return;const controls=document.createElement('div');controls.className='detail-log-controls';controls.innerHTML=`<label>Level<select id="detail-log-level"><option value="all">전체</option><option value="error">Error</option><option value="warning">Warning</option><option value="info">Info</option></select></label><label>검색<input id="detail-log-search" type="search" placeholder="로그 검색" /></label><label class="checkbox-label"><input id="detail-log-autoscroll" type="checkbox" checked /> 자동 스크롤</label><button type="button" id="detail-log-download" class="secondary-action">로그 다운로드</button>`;pre.parentElement?.insertBefore(controls,pre);pre.dataset.rawLog=pre.textContent||'';$('detail-log-level').addEventListener('change',filterDetailLogs);$('detail-log-search').addEventListener('input',filterDetailLogs);$('detail-log-download').addEventListener('click',downloadDetailLogs);new MutationObserver(()=>{if(pre.dataset.filtering==='true')return;pre.dataset.rawLog=pre.textContent||'';filterDetailLogs();}).observe(pre,{childList:true,characterData:true,subtree:true});}
  function filterDetailLogs(){const pre=$('detail-logs');if(!pre)return;const raw=pre.dataset.rawLog||pre.textContent||'',level=$('detail-log-level')?.value||'all',query=($('detail-log-search')?.value||'').trim().toLowerCase();let lines=raw.split(/\r?\n/).slice(-100);if(level!=='all')lines=lines.filter((line)=>line.toLowerCase().includes(level));if(query)lines=lines.filter((line)=>line.toLowerCase().includes(query));pre.dataset.filtering='true';pre.textContent=lines.join('\n')||'조건에 맞는 로그가 없습니다.';pre.dataset.filtering='false';if($('detail-log-autoscroll')?.checked)pre.scrollTop=pre.scrollHeight;}
  function downloadDetailLogs(){const raw=$('detail-logs')?.dataset.rawLog||'';if(!raw||/로그 데이터가 없습니다/.test(raw))return;const blob=new Blob([raw],{type:'text/plain;charset=utf-8'}),href=URL.createObjectURL(blob),a=document.createElement('a');a.href=href;a.download=`${currentExperimentId()||'experiment'}-logs.txt`;a.click();URL.revokeObjectURL(href);}
  function ensureDetailEventPayloads(){const events=$('detail-events');if(!events||$('detail-event-payloads'))return;const container=document.createElement('div');container.id='detail-event-payloads';container.className='detail-event-payloads';events.parentElement?.append(container);const subtitle=$('detail-experiment-subtitle');if(subtitle)new MutationObserver(loadDetailEventPayloads).observe(subtitle,{childList:true,characterData:true,subtree:true});loadDetailEventPayloads();}
  async function loadDetailEventPayloads(){const id=currentExperimentId(),container=$('detail-event-payloads');if(!id||!container)return;try{const job=await requestJson(`/api/experiments/${encodeURIComponent(id)}`),events=Array.isArray(job.events)?job.events.slice(-100):[];container.innerHTML=events.length?events.map((event)=>`<details><summary><time>${esc(dateText(event.created_at))}</time> · ${esc(event.stage||'—')} · ${esc(event.message||'')}</summary><pre>${esc(JSON.stringify(event.payload||{},null,2))}</pre></details>`).join(''):'<p class="empty-state">이벤트 Payload가 없습니다.</p>';}catch(_error){container.innerHTML='<p class="empty-state">이벤트 상세를 불러올 수 없습니다.</p>';}}
  function syncDetailReference(){const action=$('overview-final-action')?.textContent.trim();if(action)text('detail-final-action',action);const subtitle=$('detail-experiment-subtitle')?.textContent.trim();if(subtitle)text('detail-info-block',subtitle);const agreement=$('overview-consensus-status')?.textContent.trim();if(agreement)text('detail-agreement-block',agreement);const evidence=$('detail-evidence-summary')?.textContent.trim()||$('overview-evidence-change')?.textContent.trim();if(evidence)text('detail-evidence-preview',evidence);}

  function injectCompletionStyles(){if($('complete-research-console-styles'))return;const style=document.createElement('style');style.id='complete-research-console-styles';style.textContent=`.aiopslab-functional-tabs{display:flex;gap:28px;border-bottom:1px solid #dbe3ef;margin:0 0 22px;padding:0 20px}.aiopslab-functional-tabs button{padding:13px 2px;border:0;border-bottom:3px solid transparent;background:transparent;color:#6a7891;font-weight:700}.aiopslab-functional-tabs button[aria-selected="true"]{color:#075eea;border-bottom-color:#075eea}.aiopslab-tool-panel{padding:20px}.aiopslab-tool-panel .section-heading p{margin-top:5px;color:#66758f}.detector-comparison-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:16px 0}.detector-card{border:1px solid #d9e2ef;border-radius:10px;padding:16px;background:#fff}.detector-card>span,.detector-card>small{display:block;color:#6b7890}.detector-card>strong{display:block;margin:5px 0 13px;color:#0b1f45}.detector-card dl{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:0}.detector-card dl div{padding:9px;background:#f7f9fc;border-radius:7px}.detector-card dt{color:#718099;font-size:12px}.detector-card dd{margin:3px 0 0;font-weight:800}.aiopslab-history-filters{display:grid;grid-template-columns:180px minmax(240px,1fr) 130px;gap:12px;margin:14px 0}.pagination-row{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:14px}.result-pagination{border-top:1px solid #e1e7f0;padding-top:14px;flex-wrap:wrap}.result-pagination>span:first-child{margin-right:auto}.result-pagination label{display:flex;align-items:center;gap:7px}.result-pagination select{width:auto;min-width:74px}.aiopslab-job-detail{margin-top:18px;border-top:1px solid #dce4ee;padding-top:18px}.detail-metric-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.detail-metric-row span{padding:10px;background:#f7f9fc;border-radius:7px}.detail-metric-row strong{display:block;margin-top:4px}.artifact-links{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.artifact-links a,.artifact-popover a{display:block;padding:8px 10px;border:1px solid #cfdaea;border-radius:6px;background:#fff;color:#075eea;text-decoration:none}.detail-header-actions{display:flex;align-items:center;gap:8px;margin-left:auto;position:relative}.artifact-popover{position:absolute;z-index:50;right:0;top:44px;min-width:230px;padding:9px;border:1px solid #d2dcea;border-radius:8px;background:#fff;box-shadow:0 10px 30px rgba(8,35,70,.16)}.artifact-popover span{display:block;padding:8px;color:#66758f}.detail-log-controls{display:grid;grid-template-columns:150px minmax(220px,1fr) auto auto;gap:10px;align-items:end;margin-bottom:12px}.checkbox-label{display:flex!important;align-items:center;gap:6px;padding-bottom:9px}.checkbox-label input{width:auto;min-height:0}.detail-event-payloads{display:grid;gap:8px;margin-top:14px}.detail-event-payloads details{border:1px solid #dce4ee;border-radius:7px;padding:9px}.detail-event-payloads pre{max-height:280px;overflow:auto;background:#f7f9fc;padding:10px;border-radius:6px}.inline-status{padding:10px 12px;border-radius:7px;background:#f5f8fc;color:#53627b;margin:10px 0}.inline-error{color:#b23643}.table-wrap{overflow:auto}@media(max-width:900px){.aiopslab-history-filters,.detail-log-controls{grid-template-columns:1fr 1fr}.detail-metric-row{grid-template-columns:1fr 1fr}}@media(max-width:760px){.aiopslab-functional-tabs{gap:12px;overflow:auto}.aiopslab-history-filters,.detail-log-controls,.detail-metric-row{grid-template-columns:1fr}.pagination-row{justify-content:center}.result-pagination>span:first-child{width:100%;margin:0;text-align:center}}`;document.head.append(style);}
  function syncAll(){syncReferenceSummary();renderBenchmarkScenarioCards();updateDashboardDonut();syncDetailReference();ensureExperimentResultControls();ensureDetailActions();}
  document.addEventListener('DOMContentLoaded',()=>{injectCompletionStyles();bindRecoveryHeaderRun();ensureAIOpsLabTabs();ensureExperimentResultControls();ensureDetailActions();syncAll();loadAIOpsLabJobs();const historyBody=$('experiment-history-body');if(historyBody)new MutationObserver(applyExperimentPagination).observe(historyBody,{childList:true,subtree:true});const observer=new MutationObserver(syncAll);[$('scenario-list'),$('controller-options'),$('mode-control'),$('aiopslab-benchmark-select'),$('dashboard-total'),$('dashboard-success-rate'),$('overview-final-action'),$('overview-consensus-status'),$('detail-experiment-subtitle'),$('detail-evidence-summary')].filter(Boolean).forEach((target)=>observer.observe(target,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['aria-pressed']}));});
})();
