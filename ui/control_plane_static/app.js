(function () {
  const root = document.getElementById("root");

  const ROUTES = [
    { key: "dashboard", hash: "#/dashboard", label: "대시보드", eyebrow: "Research overview" },
    { key: "experiments", hash: "#/experiments", label: "장애 실험", eyebrow: "Fault laboratory" },
    { key: "decision", hash: "#/decision", label: "4-Agent 판단", eyebrow: "Decision workspace" },
    { key: "safety", hash: "#/safety", label: "안전 검증", eyebrow: "Safety boundary" },
    { key: "evidence", hash: "#/evidence", label: "실험 결과", eyebrow: "Evidence archive" },
    { key: "documents", hash: "#/documents", label: "연구 문서", eyebrow: "Research artifacts" },
  ];

  const SCENARIOS = {
    "pod-kill": {
      label: "Pod Kill",
      target: "paymentservice",
      signal: "ready / available replicas",
      summary: "Pod를 종료해 Kubernetes 자체 복구와 추가 조치의 필요성을 비교합니다.",
    },
    "cpu-stress": {
      label: "CPU Stress",
      target: "paymentservice",
      signal: "container CPU usage",
      summary: "CPU 부하를 주입하고 관찰, 재시작, scale-out의 복구 효과를 비교합니다.",
    },
    "memory-stress": {
      label: "Memory Stress",
      target: "checkoutservice",
      signal: "working set / restart count",
      summary: "메모리 압박과 OOM 위험에서 action별 회복 특성을 측정합니다.",
    },
    "network-delay": {
      label: "Network Delay",
      target: "paymentservice",
      signal: "probe duration",
      summary: "서비스 통신 지연을 주입하고 응답시간 회복 여부를 관찰합니다.",
    },
  };

  const ACTIONS = [
    { key: "observe_only", label: "Observe", note: "Kubernetes 자체 복구 관찰" },
    { key: "rollout_restart", label: "Restart", note: "Deployment rollout restart" },
    { key: "scale_out", label: "Scale out", note: "Replica 증가" },
  ];

  const DOCUMENTS = [
    {
      label: "전체 실행 코드",
      path: "docs/submission/execution_code_guide.md",
      description: "환경 준비부터 mock, dry-run, real 실험까지의 실행 순서",
    },
    {
      label: "시험 가이드",
      path: "docs/submission/test_guide.md",
      description: "단위 시험과 서버 통합 시험의 검증 기준",
    },
    {
      label: "Agent 정책",
      path: "docs/design/agent_action_reward_policy.md",
      description: "4-Agent action, reward, 승인·거부 조건",
    },
    {
      label: "정량 분석",
      path: "docs/experiments/recovery_quantitative_analysis_guide.md",
      description: "성공률, 복구 시간, reward 비교와 그래프 생성 절차",
    },
    {
      label: "Control Plane UI",
      path: "docs/submission/control_plane_ui_guide.md",
      description: "연구 운영 플랫폼 실행과 안전 경계",
    },
  ];

  const state = {
    overview: null,
    agents: [],
    latestRun: null,
    mockResult: null,
    running: false,
    selectedScenario: "cpu-stress",
    form: {
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "cpu",
      value: "95",
      threshold: "80",
      backend: "python",
    },
  };

  function h(tag, attrs, children) {
    const element = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "className") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key === "disabled") element.disabled = Boolean(value);
      else if (key === "value") element.value = value;
      else if (key === "checked") element.checked = Boolean(value);
      else if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), value);
      } else {
        element.setAttribute(key, value);
      }
    });
    (children || []).forEach((child) => {
      if (child == null) return;
      element.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return element;
  }

  async function getJson(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  }

  function currentRoute() {
    const hash = window.location.hash || "#/dashboard";
    return ROUTES.find((route) => route.hash === hash) || ROUTES[0];
  }

  function navigate(hash) {
    if (window.location.hash === hash) {
      render();
      return;
    }
    window.location.hash = hash;
  }

  function render() {
    root.replaceChildren(layout());
  }

  function layout() {
    const route = currentRoute();
    return h("div", { className: "platform-shell" }, [
      sidebar(route),
      h("main", { className: "workspace" }, [
        workspaceHeader(route),
        h("div", { className: "workspace-body" }, [
          h("section", { className: `route-view route-${route.key}` }, [
            workspaceView(route.key),
          ]),
        ]),
      ]),
    ]);
  }

  function sidebar(route) {
    const health = (state.overview && state.overview.health) || {};
    const ready = Object.values(health).filter(Boolean).length;
    const total = Object.keys(health).length || 4;
    return h("aside", { className: "sidebar" }, [
      h("div", { className: "sidebar-brand" }, [
        h("div", { className: "brand-lockup" }, [
          h("span", { className: "brand-mark", text: "MC" }),
          h("div", {}, [
            h("strong", { text: "AI-MCMP" }),
            h("small", { text: "Research Control Plane" }),
          ]),
        ]),
        h("p", { text: "Safety-Bounded 4-Agent AIOps Framework" }),
      ]),
      h("nav", { className: "sidebar-nav", "aria-label": "연구 플랫폼 화면" },
        ROUTES.map((item, index) =>
          h("a", {
            href: item.hash,
            className: `nav-link${route.key === item.key ? " is-active" : ""}`,
          }, [
            h("span", { className: "nav-index", text: String(index + 1).padStart(2, "0") }),
            h("span", { className: "nav-copy" }, [
              h("strong", { text: item.label }),
              h("small", { text: item.eyebrow }),
            ]),
          ])
        )
      ),
      h("div", { className: "sidebar-context" }, [
        h("span", { className: "context-label", text: "Environment" }),
        contextRow("Workspace", "local UI"),
        contextRow("Execution", "CLI gated"),
        contextRow("Evidence", `${ready}/${total} ready`, ready === total),
      ]),
      h("div", { className: "sidebar-footer" }, [
        h("span", { className: "live-dot" }),
        h("span", { text: "Control plane online" }),
      ]),
    ]);
  }

  function contextRow(label, value, healthy) {
    return h("div", { className: "context-row" }, [
      h("span", { text: label }),
      h("strong", { className: healthy ? "healthy" : "", text: value }),
    ]);
  }

  function workspaceHeader(route) {
    return h("header", { className: "workspace-header" }, [
      h("div", {}, [
        h("p", { className: "workspace-eyebrow", text: route.eyebrow }),
        h("h1", { text: route.label }),
      ]),
      h("div", { className: "header-status" }, [
        statusPill("4 Agents", "ready"),
        statusPill("UI mode", "mock safe"),
      ]),
    ]);
  }

  function statusPill(label, value) {
    return h("div", { className: "status-pill" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function workspaceView(routeKey) {
    const views = {
      dashboard: dashboardView,
      experiments: experimentsView,
      decision: decisionView,
      safety: safetyView,
      evidence: evidenceView,
      documents: documentsView,
    };
    return views[routeKey]();
  }

  function dashboardView() {
    const overview = state.overview || {};
    const latest = state.latestRun;
    return h("div", { className: "view-stack" }, [
      h("div", { className: "status-strip" }, [
        statusMetric("등록 Agent", String(state.agents.length || 4), "역할 분리"),
        statusMetric("장애 시나리오", String((overview.scenarios || []).length || 4), "Chaos Mesh"),
        statusMetric("허용 Action", String((overview.actions || []).length || 3), "bounded"),
        statusMetric("최근 결과", latest ? String(latest.outcome_count) : "0", "JSONL records"),
      ]),
      h("section", { className: "surface research-focus" }, [
        h("div", {}, [
          h("p", { className: "section-kicker", text: "Research objective" }),
          h("h2", { text: "Agent의 판단을 검증 가능한 Kubernetes 복구 action으로 연결합니다." }),
          h("p", {
            text:
              "장애 관측, 역할별 판단, 교차 합의, 안전 검증, 실행 결과 수집을 하나의 폐쇄 루프로 구성합니다.",
          }),
        ]),
        h("div", { className: "focus-boundary" }, [
          h("span", { text: "현재 연구 경계" }),
          h("strong", { text: "실제 실행은 CLI에서 명시적으로 승인" }),
          h("small", { text: "웹 UI는 상태 확인과 mock 판단만 수행" }),
        ]),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("전체 운영 흐름", "관측부터 결과 축적까지 6단계"),
        pipelineFlow(),
      ]),
      h("div", { className: "dashboard-grid" }, [
        h("section", { className: "surface" }, [
          sectionTitle("4-Agent 구성", "역할별 독립 판단"),
          h("div", { className: "agent-brief-list" },
            state.agents.map((agent) => agentBrief(agent))
          ),
          textButton("Agent 판단 화면", "#/decision"),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("실험 준비 상태", "연구 자산 확인"),
          healthTable(),
          h("div", { className: "latest-note" }, [
            h("span", { text: "Latest run" }),
            h("strong", { text: latest ? latest.name : "서버 결과 미동기화" }),
            h("small", {
              text: latest
                ? `${latest.outcome_count}개 outcome 기록`
                : "로컬 UI에는 서버 runs 디렉터리가 없습니다.",
            }),
          ]),
          textButton("실험 결과 확인", "#/evidence"),
        ]),
      ]),
    ]);
  }

  function statusMetric(label, value, note) {
    return h("article", { className: "status-metric" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
      h("small", { text: note }),
    ]);
  }

  function sectionTitle(title, meta) {
    return h("div", { className: "section-title" }, [
      h("h2", { text: title }),
      meta ? h("span", { text: meta }) : null,
    ]);
  }

  function pipelineFlow() {
    const steps = [
      ["01", "장애 주입", "AIOpsLab / Chaos Mesh"],
      ["02", "상태 관측", "Prometheus / K8s"],
      ["03", "역할 판단", "4-Agent reviews"],
      ["04", "교차 합의", "Action / reward"],
      ["05", "안전 실행", "Validator / Guard"],
      ["06", "피드백", "Result / statistics"],
    ];
    return h("div", { className: "pipeline-flow" },
      steps.map(([number, title, detail]) =>
        h("article", { className: "pipeline-step" }, [
          h("span", { text: number }),
          h("strong", { text: title }),
          h("small", { text: detail }),
        ])
      )
    );
  }

  function agentBrief(agent) {
    return h("article", { className: "agent-brief" }, [
      h("span", { className: "agent-code", text: shortName(agent.name) }),
      h("div", {}, [
        h("strong", { text: agentLabel(agent) }),
        h("small", { text: conciseRole(agent.name) }),
      ]),
      h("span", { className: "agent-state", text: agent.enabled === false ? "off" : "ready" }),
    ]);
  }

  function healthTable() {
    const health = (state.overview && state.overview.health) || {};
    const labels = {
      agent_registry: "Agent Registry",
      recovery_config: "Recovery policy",
      chaos_manifests: "Chaos manifests",
      runs_dir: "Runs directory",
    };
    return h("div", { className: "health-list" },
      Object.entries(labels).map(([key, label]) =>
        h("div", { className: "health-row" }, [
          h("span", { text: label }),
          h("strong", {
            className: health[key] ? "health-ok" : "health-missing",
            text: health[key] ? "available" : "not found",
          }),
        ])
      )
    );
  }

  function textButton(label, hash) {
    return h("button", {
      className: "text-button",
      type: "button",
      onClick: () => navigate(hash),
      text: label,
    });
  }

  function experimentsView() {
    const selected = SCENARIOS[state.selectedScenario];
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("장애 시나리오", "실제 Chaos Mesh manifest 4종"),
        h("div", { className: "scenario-grid" },
          Object.entries(SCENARIOS).map(([key, scenario]) =>
            h("button", {
              type: "button",
              className: `scenario-card${state.selectedScenario === key ? " is-selected" : ""}`,
              onClick: () => {
                state.selectedScenario = key;
                render();
              },
            }, [
              h("span", { className: "scenario-state", text: state.selectedScenario === key ? "selected" : "scenario" }),
              h("strong", { text: scenario.label }),
              h("small", { text: scenario.target }),
            ])
          )
        ),
      ]),
      h("div", { className: "experiment-layout" }, [
        h("section", { className: "surface scenario-detail" }, [
          h("p", { className: "section-kicker", text: state.selectedScenario }),
          h("h2", { text: selected.label }),
          h("p", { text: selected.summary }),
          definitionRow("Target", selected.target),
          definitionRow("Primary evidence", selected.signal),
          definitionRow("Manifest", `k8s/chaos/${manifestName(state.selectedScenario)}`),
          h("div", { className: "command-panel" }, [
            h("span", { text: "실행 명령" }),
            h("code", {
              text:
                'GUARD_BACKEND=go MODE=real REPETITIONS=3 bash scripts/server_recovery_action_pilot.sh',
            }),
          ]),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("Action 비교군", "동일 장애에서 3개 bounded action 비교"),
          h("div", { className: "action-list" },
            ACTIONS.map((action, index) =>
              h("article", { className: "action-row" }, [
                h("span", { text: String(index + 1).padStart(2, "0") }),
                h("div", {}, [
                  h("strong", { text: action.label }),
                  h("small", { text: action.note }),
                ]),
                h("code", { text: action.key }),
              ])
            )
          ),
        ]),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("실험 매트릭스", "4 scenarios × 3 actions × 3 repetitions = 36 runs"),
        experimentMatrix(),
      ]),
    ]);
  }

  function manifestName(scenario) {
    const names = {
      "pod-kill": "paymentservice-pod-kill.yaml",
      "cpu-stress": "paymentservice-cpu-stress.yaml",
      "memory-stress": "checkoutservice-memory-stress.yaml",
      "network-delay": "paymentservice-network-delay.yaml",
    };
    return names[scenario];
  }

  function definitionRow(label, value) {
    return h("div", { className: "definition-row" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function experimentMatrix() {
    return h("div", { className: "table-wrap" }, [
      h("table", { className: "data-table" }, [
        h("thead", {}, [
          h("tr", {}, [
            h("th", { text: "Scenario" }),
            ...ACTIONS.map((action) => h("th", { text: action.label })),
            h("th", { text: "Repeats" }),
          ]),
        ]),
        h("tbody", {},
          Object.entries(SCENARIOS).map(([key, scenario]) =>
            h("tr", {}, [
              h("td", {}, [
                h("strong", { text: scenario.label }),
                h("small", { text: key }),
              ]),
              ...ACTIONS.map(() => h("td", {}, [h("span", { className: "matrix-check", text: "included" })])),
              h("td", { text: "3" }),
            ])
          )
        ),
      ]),
    ]);
  }

  function decisionView() {
    return h("div", { className: "decision-layout" }, [
      h("section", { className: "surface decision-input" }, [
        sectionTitle("장애 상태 입력", "mock mode"),
        h("form", { className: "decision-form", onSubmit: runMock }, [
          field("Namespace", "namespace"),
          field("Deployment", "deployment"),
          metricField(),
          field("Value", "value", "number"),
          field("Threshold", "threshold", "number"),
          guardField(),
          h("button", {
            className: "primary-button",
            type: "submit",
            disabled: state.running,
            text: state.running ? "Agent 판단 생성 중..." : "4-Agent 판단 실행",
          }),
        ]),
        h("div", { className: "mode-notice" }, [
          h("strong", { text: "안전 모드" }),
          h("span", { text: "이 화면은 실제 Kubernetes action을 실행하지 않습니다." }),
        ]),
      ]),
      h("section", { className: "surface decision-output" }, [
        sectionTitle("합의 결과", state.mockResult ? "latest mock decision" : "waiting for input"),
        state.mockResult ? decisionResult() : emptyDecision(),
      ]),
    ]);
  }

  function field(label, key, type) {
    return h("label", { className: "field" }, [
      h("span", { text: label }),
      h("input", {
        type: type || "text",
        value: state.form[key],
        onInput: (event) => {
          state.form[key] = event.target.value;
        },
      }),
    ]);
  }

  function metricField() {
    return h("label", { className: "field" }, [
      h("span", { text: "Metric" }),
      h("select", {
        value: state.form.metric,
        onChange: (event) => {
          state.form.metric = event.target.value;
        },
      }, [
        h("option", { value: "cpu", text: "CPU usage" }),
        h("option", { value: "memory", text: "Memory usage" }),
        h("option", { value: "availability", text: "Availability" }),
        h("option", { value: "latency", text: "Latency" }),
      ]),
    ]);
  }

  function guardField() {
    return h("label", { className: "field" }, [
      h("span", { text: "Validation backend" }),
      h("select", {
        value: state.form.backend,
        onChange: (event) => {
          state.form.backend = event.target.value;
        },
      }, [
        h("option", { value: "python", text: "Python Validator" }),
        h("option", { value: "go", text: "Go Guard" }),
      ]),
    ]);
  }

  function emptyDecision() {
    return h("div", { className: "empty-state" }, [
      h("span", { className: "empty-index", text: "4" }),
      h("strong", { text: "Agent별 검토 결과가 여기에 표시됩니다." }),
      h("p", { text: "장애 상태를 입력하고 mock 판단을 실행하세요." }),
    ]);
  }

  function decisionResult() {
    const reviews = state.mockResult.agent_reviews || [];
    const result = state.mockResult.result || {};
    return h("div", { className: "decision-result" }, [
      h("div", { className: "consensus-summary" }, [
        h("div", {}, [
          h("span", { text: "Consensus" }),
          h("strong", { text: (result.metadata && result.metadata.consensus) || "unknown" }),
        ]),
        h("div", {}, [
          h("span", { text: "Validation" }),
          h("strong", { text: result.valid ? "passed" : "rejected" }),
        ]),
        h("div", {}, [
          h("span", { text: "Reward total" }),
          h("strong", { text: (result.metadata && result.metadata.reward_total) || "-" }),
        ]),
      ]),
      h("div", { className: "table-wrap" }, [
        h("table", { className: "data-table" }, [
          h("thead", {}, [
            h("tr", {}, ["Agent", "Decision", "Action", "Reward"].map((name) => h("th", { text: name }))),
          ]),
          h("tbody", {},
            reviews.map((review) =>
              h("tr", {}, [
                h("td", { text: shortName(review.agent) }),
                h("td", { text: review.decision }),
                h("td", { text: review.action }),
                h("td", { text: review.reward == null ? "-" : Number(review.reward).toFixed(2) }),
              ])
            )
          ),
        ]),
      ]),
      h("div", { className: "command-panel" }, [
        h("span", { text: "Validated command" }),
        h("code", { text: result.command || result.stderr || "No command generated" }),
      ]),
    ]);
  }

  async function runMock(event) {
    event.preventDefault();
    state.running = true;
    render();
    try {
      const response = await fetch("/api/mock-alert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          namespace: state.form.namespace,
          deployment: state.form.deployment,
          metric: state.form.metric,
          value: Number(state.form.value),
          threshold: Number(state.form.threshold),
          backend: state.form.backend,
        }),
      });
      state.mockResult = await response.json();
    } catch (error) {
      state.mockResult = {
        result: { valid: false, stderr: String(error.message || error) },
        agent_reviews: [],
      };
    } finally {
      state.running = false;
      render();
    }
  }

  function safetyView() {
    const gates = [
      ["01", "Agent Registry", "등록된 Agent와 허용 action 확인", "policy"],
      ["02", "Consensus", "4개 역할의 승인·거부 결과 집계", "decision"],
      ["03", "Python Validator", "namespace, deployment, replica, 문법 검증", "required"],
      ["04", "Go Guard", "독립 구현으로 동일 정책 교차 검증", "optional"],
      ["05", "Kubernetes dry-run", "API server 호환성과 요청 유효성 확인", "required"],
      ["06", "Explicit real execution", "연구자가 CLI에서 real mode 승인", "gated"],
    ];
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("Safety-Bounded Action Pipeline", "Agent 출력은 직접 실행되지 않습니다."),
        h("div", { className: "gate-flow" },
          gates.map(([number, title, detail, status]) =>
            h("article", { className: "gate-step" }, [
              h("span", { className: "gate-number", text: number }),
              h("div", {}, [
                h("strong", { text: title }),
                h("small", { text: detail }),
              ]),
              h("span", { className: `gate-status status-${status}`, text: status }),
            ])
          )
        ),
      ]),
      h("div", { className: "safety-grid" }, [
        h("section", { className: "surface" }, [
          sectionTitle("허용 범위", "CommandValidator policy"),
          policyRow("Namespace", "allowlist only"),
          policyRow("Deployment", "allowlist only"),
          policyRow("Replica", "configured min–max"),
          policyRow("Command", "bounded kubectl patterns"),
          policyRow("Unknown metric", "observe only"),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("거부 조건", "safe failure"),
          rejectionRow("허용되지 않은 namespace"),
          rejectionRow("허용되지 않은 deployment"),
          rejectionRow("replica 상한 초과"),
          rejectionRow("위험하거나 구조화되지 않은 명령"),
          rejectionRow("Agent consensus rejected"),
        ]),
      ]),
    ]);
  }

  function policyRow(label, value) {
    return h("div", { className: "policy-row" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function rejectionRow(text) {
    return h("div", { className: "rejection-row" }, [
      h("span", { text: "blocked" }),
      h("strong", { text }),
    ]);
  }

  function evidenceView() {
    const latest = state.latestRun;
    const finalRun = state.overview && state.overview.latest_final_run;
    return h("div", { className: "view-stack" }, [
      h("div", { className: "status-strip evidence-strip" }, [
        statusMetric("Recovery outcomes", latest ? String(latest.outcome_count) : "0", "JSONL"),
        statusMetric("Reward ranking", latest && latest.has_reward_policy ? "ready" : "none", "Markdown"),
        statusMetric("Statistics", latest && latest.has_statistics ? "ready" : "none", "PNG / CSV"),
        statusMetric("Final summary", finalRun && finalRun.summary_exists ? "ready" : "none", "real run"),
      ]),
      latest
        ? latestEvidence(latest)
        : h("section", { className: "surface no-evidence" }, [
            h("span", { className: "empty-index", text: "0" }),
            h("h2", { text: "이 작업공간에는 서버 실험 결과가 없습니다." }),
            h("p", {
              text:
                "서버의 runs 디렉터리를 동기화하거나 서버에서 Control Plane을 실행하면 최신 결과가 표시됩니다.",
            }),
            h("div", { className: "command-panel" }, [
              h("span", { text: "결과 생성" }),
              h("code", { text: "bash scripts/server_recovery_statistics.sh" }),
            ]),
          ]),
    ]);
  }

  function latestEvidence(latest) {
    return h("div", { className: "evidence-layout" }, [
      h("section", { className: "surface" }, [
        sectionTitle("최신 recovery experiment", latest.name),
        definitionRow("Run path", latest.path),
        definitionRow("Outcome records", String(latest.outcome_count)),
        definitionRow("Reward comparison", latest.has_reward_policy ? "available" : "not found"),
        definitionRow("Quantitative statistics", latest.has_statistics ? "available" : "not found"),
        h("div", { className: "artifact-list" },
          (latest.statistics_files || []).map((path) =>
            h("a", { href: `/api/artifacts/${path}`, target: "_blank" }, [
              h("span", { text: path.split("/").pop() }),
              h("small", { text: "open" }),
            ])
          )
        ),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("Reward policy excerpt", "balanced / HA / cost / infra"),
        h("pre", {
          className: "evidence-excerpt",
          text: latest.reward_policy_excerpt || "Reward policy summary not found.",
        }),
      ]),
    ]);
  }

  function documentsView() {
    return h("div", { className: "documents-layout" }, [
      h("section", { className: "surface" }, [
        sectionTitle("연구 문서", "실행과 재현을 위한 핵심 문서"),
        h("div", { className: "document-list" },
          DOCUMENTS.map((document) =>
            h("a", {
              href: `/api/artifacts/${document.path}`,
              target: "_blank",
              className: "document-row",
            }, [
              h("span", { className: "document-type", text: "MD" }),
              h("div", {}, [
                h("strong", { text: document.label }),
                h("small", { text: document.description }),
              ]),
              h("code", { text: document.path.split("/").pop() }),
            ])
          )
        ),
      ]),
      h("section", { className: "surface architecture-panel" }, [
        sectionTitle("전체 아키텍처", "연구 구성도"),
        h("a", {
          href: "/api/artifacts/docs/assets/architecture_overview.png",
          target: "_blank",
          className: "architecture-link",
        }, [
          h("img", {
            src: "/api/artifacts/docs/assets/architecture_overview.png",
            alt: "AIOps 4-Agent 전체 아키텍처",
          }),
          h("span", { text: "원본 구성도 열기" }),
        ]),
      ]),
    ]);
  }

  function agentLabel(agent) {
    const labels = {
      AIServiceHASupportAgent: "AI서비스 HA 지원 Agent",
      AIApplicationManagementAgent: "AI응용관리 자동화 Agent",
      AISemiconductorInfraOpsAgent: "AI반도체 인프라 운용 Agent",
      CostOptimizationAgent: "비용 최적화 Agent",
    };
    return labels[agent.name] || agent.label || agent.name;
  }

  function conciseRole(name) {
    const roles = {
      AIServiceHASupportAgent: "장애 진단과 복구 필요성 판단",
      AIApplicationManagementAgent: "복구 action 제안과 배포 관리",
      AISemiconductorInfraOpsAgent: "자원 수용성과 인프라 제약 검토",
      CostOptimizationAgent: "비용·자원 증가와 과잉 대응 검토",
    };
    return roles[name] || "등록된 정책에 따라 역할별 판단 수행";
  }

  function shortName(name) {
    if (name.includes("HA")) return "HA";
    if (name.includes("Application")) return "APP";
    if (name.includes("Infra")) return "INF";
    if (name.includes("Cost")) return "COST";
    return "AG";
  }

  async function boot() {
    if (!window.location.hash || !ROUTES.some((route) => route.hash === window.location.hash)) {
      window.history.replaceState(null, "", "#/dashboard");
    }
    root.replaceChildren(h("main", { className: "loading" }, [
      h("span", { className: "loading-mark", text: "AI-MCMP" }),
      h("h1", { text: "Research Control Plane" }),
      h("p", { text: "연구 환경과 실험 근거를 불러오고 있습니다." }),
    ]));
    try {
      const [overview, agents, latest] = await Promise.all([
        getJson("/api/overview"),
        getJson("/api/agents"),
        getJson("/api/runs/latest"),
      ]);
      state.overview = overview;
      state.agents = agents.agents || [];
      state.latestRun = latest.available ? latest.run : null;
    } catch (error) {
      console.error(error);
    }
    render();
  }

  window.addEventListener("hashchange", render);
  boot();
})();
