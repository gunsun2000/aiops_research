(function () {
  "use strict";

  const TERMINAL = new Set(["completed", "failed", "blocked", "cancelled", "interrupted"]);
  const $ = (id) => document.getElementById(id);

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.detail || `요청 실패 (${response.status})`);
    return payload;
  }

  function setStatus(message, kind = "neutral") {
    const node = $("bulk-delete-status");
    if (!node) return;
    node.textContent = message;
    node.dataset.kind = kind;
  }

  async function refreshDeleteButtonState() {
    const button = $("delete-all-experiments");
    if (!button || button.dataset.busy === "1") return;
    try {
      const payload = await api("/api/experiments?limit=100");
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      const terminalCount = jobs.filter((job) => TERMINAL.has(job.status)).length;
      button.disabled = terminalCount === 0;
      button.title = terminalCount
        ? `삭제 가능한 완료 상태 실험 ${terminalCount}개 이상`
        : "삭제 가능한 완료 상태 실험이 없습니다.";
    } catch (_error) {
      button.disabled = true;
      button.title = "실험 결과 상태를 확인하지 못했습니다.";
    }
  }

  async function deleteAllExperimentResults() {
    const button = $("delete-all-experiments");
    if (!button || button.dataset.busy === "1") return;

    const confirmed = window.confirm(
      "완료/실패/안전 중단/취소/중단된 실험 결과를 전부 영구 삭제합니다.\n\n" +
      "각 실험의 Job, 이벤트, 생성된 결과 파일도 함께 삭제됩니다.\n" +
      "실행 중인 실험은 삭제하지 않습니다.\n\n" +
      "계속하시겠습니까?"
    );
    if (!confirmed) return;

    button.dataset.busy = "1";
    button.disabled = true;
    button.textContent = "전체 삭제 중...";
    setStatus("서버에서 완료된 실험 결과를 일괄 삭제하고 있습니다.", "warning");

    try {
      const response = await fetch("/api/experiments", {
        method: "DELETE",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        let detail = `요청 실패 (${response.status})`;
        try {
          const payload = await response.json();
          if (payload?.detail) detail = payload.detail;
        } catch (_error) {
          // Keep the HTTP status fallback when an error body cannot be parsed.
        }
        throw new Error(detail);
      }

      sessionStorage.setItem(
        "aiops-bulk-delete-message",
        "전체 삭제가 완료되었습니다. 실행 중인 실험은 보호되었습니다."
      );
      const url = new URL(location.href);
      url.searchParams.delete("page");
      url.hash = "analysis";
      history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
      location.reload();
    } catch (error) {
      setStatus(`전체 삭제 실패: ${error instanceof Error ? error.message : String(error)}`, "danger");
      button.dataset.busy = "0";
      button.textContent = "전체 삭제";
      await refreshDeleteButtonState();
    }
  }

  function ensureBulkDeleteControl() {
    if ($("delete-all-experiments")) return;
    const analysisPanel = document.querySelector('[data-view-panel="analysis"]');
    const heading = analysisPanel?.querySelector(".page-heading");
    if (!analysisPanel || !heading) return;

    let actions = heading.querySelector(".bulk-delete-actions");
    if (!actions) {
      actions = document.createElement("div");
      actions.className = "bulk-delete-actions";
      heading.append(actions);
    }

    const status = document.createElement("span");
    status.id = "bulk-delete-status";
    status.className = "bulk-delete-status";
    status.setAttribute("aria-live", "polite");

    const button = document.createElement("button");
    button.id = "delete-all-experiments";
    button.type = "button";
    button.className = "danger-action bulk-delete-button";
    button.textContent = "전체 삭제";
    button.addEventListener("click", deleteAllExperimentResults);

    actions.append(status, button);

    const saved = sessionStorage.getItem("aiops-bulk-delete-message");
    if (saved) {
      sessionStorage.removeItem("aiops-bulk-delete-message");
      setStatus(saved, "success");
    }
    refreshDeleteButtonState();
  }

  function injectBulkDeleteStyles() {
    if ($("bulk-delete-ui-styles")) return;
    const style = document.createElement("style");
    style.id = "bulk-delete-ui-styles";
    style.textContent = `
      .bulk-delete-actions{margin-left:auto;display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end}
      .bulk-delete-status{font-size:12px;color:#64748b;max-width:520px;text-align:right}
      .bulk-delete-status[data-kind="success"]{color:#087a46}.bulk-delete-status[data-kind="danger"]{color:#b42318}.bulk-delete-status[data-kind="warning"]{color:#9a6700}
      .danger-action.bulk-delete-button{border:1px solid #dc2626;background:#fff;color:#b91c1c;border-radius:8px;padding:10px 15px;font-weight:700;cursor:pointer}
      .danger-action.bulk-delete-button:hover:not(:disabled){background:#fff1f2}.danger-action.bulk-delete-button:disabled{opacity:.45;cursor:not-allowed}
      @media(max-width:760px){.bulk-delete-actions{width:100%;justify-content:flex-start}.bulk-delete-status{text-align:left}}
    `;
    document.head.append(style);
  }

  function ensurePolishScript() {
    if (document.querySelector('script[data-research-console-polish]')) return;
    const script = document.createElement("script");
    script.src = "/static/research-console-polish.js?v=2";
    script.defer = true;
    script.dataset.researchConsolePolish = "1";
    document.head.append(script);
  }

  function ensureStageFlowScript() {
    if (document.querySelector('script[data-stage-flow-ui]')) return;
    const script = document.createElement("script");
    script.src = "/static/stage-flow-ui.js?v=1";
    script.defer = true;
    script.dataset.stageFlowUi = "1";
    document.head.append(script);
  }

  function bootstrap() {
    injectBulkDeleteStyles();
    ensureBulkDeleteControl();
    ensurePolishScript();
    ensureStageFlowScript();
    document.querySelector('[data-view="analysis"]')?.addEventListener("click", () => setTimeout(refreshDeleteButtonState, 0));
    window.addEventListener("aiops:history-updated", () => setTimeout(refreshDeleteButtonState, 0));
  }

  document.addEventListener("DOMContentLoaded", bootstrap);
})();
