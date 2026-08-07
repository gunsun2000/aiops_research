(function () {
  "use strict";

  const FLOW_STEPS = [
    { title: "장애 조건 확인", subtitle: "Chaos Mesh", roleClass: "stage-neutral" },
    { title: "Evidence 수집", subtitle: "Metric / K8s / Event", roleClass: "stage-neutral" },
    { title: "HA Agent 진단", subtitle: "Availability", roleClass: "stage-ha" },
    { title: "APP Agent 복구 Action 제안", subtitle: "Application", roleClass: "stage-app" },
    { title: "Infra Agent 검토", subtitle: "Resource Review", roleClass: "stage-infra" },
    { title: "Cost Agent 검토", subtitle: "Cost Review", roleClass: "stage-cost" },
    { title: "안전 명령 검증", subtitle: "Guard: Python + Go", roleClass: "stage-neutral" },
    { title: "복구 실행 · 결과 확인", subtitle: "Kubernetes Action / Recovery Monitor", roleClass: "stage-neutral" },
  ];

  const ROLE_CLASSES = ["stage-neutral", "stage-ha", "stage-app", "stage-infra", "stage-cost"];

  function applyRoleClass(item, roleClass) {
    if (!item) return;
    item.classList.remove(...ROLE_CLASSES);
    item.classList.add(roleClass);
  }

  function renderOverviewFlow() {
    const timeline = document.getElementById("overview-stage-timeline");
    if (!timeline) return;
    const items = Array.from(timeline.querySelectorAll("li"));
    FLOW_STEPS.forEach((step, index) => {
      const item = items[index];
      if (!item) return;
      applyRoleClass(item, step.roleClass);
      const number = item.querySelector("b");
      let text = item.querySelector("span");
      if (!text) {
        text = document.createElement("span");
        item.append(text);
      }
      if (number) number.textContent = String(index + 1).padStart(2, "0");
      text.replaceChildren(document.createTextNode(step.title));
      const small = document.createElement("small");
      small.textContent = step.subtitle;
      text.append(small);
    });
  }

  function renderMiniFlow() {
    const list = document.querySelector(".mini-stage-list");
    if (!list) return;
    const items = Array.from(list.querySelectorAll("li"));
    FLOW_STEPS.forEach((step, index) => {
      const item = items[index];
      if (!item) return;
      applyRoleClass(item, step.roleClass);
      item.textContent = `${index + 1}. ${step.title}`;
    });
  }

  function renderLiveFlow() {
    const timeline = document.getElementById("stage-timeline");
    if (!timeline) return;
    const items = Array.from(timeline.querySelectorAll("li"));
    FLOW_STEPS.forEach((step, index) => {
      const item = items[index];
      if (!item) return;
      applyRoleClass(item, step.roleClass);
      item.textContent = step.title;
    });
  }

  function renderFourAgentFlow() {
    renderOverviewFlow();
    renderMiniFlow();
    renderLiveFlow();
  }

  function bootstrap() {
    renderFourAgentFlow();
    [100, 500, 1200].forEach((delay) => window.setTimeout(renderFourAgentFlow, delay));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
})();
