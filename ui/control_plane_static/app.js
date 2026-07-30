(function () {
  const root = document.getElementById("root");

  const ROUTES = [
    { key: "dashboard", hash: "#/dashboard", label: "연구 개요", eyebrow: "Research overview" },
    { key: "experiments", hash: "#/experiments", label: "운영 실험", eyebrow: "Unified experiment" },
    { key: "decision", hash: "#/decision", label: "4-Agent 판단", eyebrow: "Agent decision" },
    { key: "supervision", hash: "#/supervision", label: "상호감시", eyebrow: "Mutual supervision" },
    { key: "safety", hash: "#/safety", label: "안전 경계", eyebrow: "Safety boundary" },
    { key: "evidence", hash: "#/evidence", label: "실험 근거", eyebrow: "Evidence archive" },
    { key: "documents", hash: "#/documents", label: "연구 문서", eyebrow: "Research artifacts" },
  ];

  const FALLBACK_SCENARIOS = [
    {
      scenario_id: "pod-kill",
      label: "Pod Kill",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "availability",
      value: 0,
      threshold: 1,
      signal: "ready / available replicas",
      summary: "Pod 종료 이후 Kubernetes 자가복구와 Agent 대응 필요성을 비교합니다.",
      mode: "mock",
    },
    {
      scenario_id: "cpu-stress",
      label: "CPU Stress",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "cpu",
      value: 95,
      threshold: 80,
      signal: "container CPU usage",
      summary: "CPU 포화 상태에서 4-Agent가 bounded recovery Action을 합의합니다.",
      mode: "mock",
    },
    {
      scenario_id: "memory-stress",
      label: "Memory Stress",
      namespace: "online-boutique",
      deployment: "checkoutservice",
      metric: "memory",
      value: 95.7,
      threshold: 80,
      signal: "working set / restart count",
      summary: "메모리 포화와 OOM 위험에 대한 Agent 합의와 복구 Action을 검증합니다.",
      mode: "mock",
    },
    {
      scenario_id: "network-delay",
      label: "Network Delay",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "latency",
      value: 0.234,
      threshold: 0.1,
      signal: "probe duration",
      summary: "서비스 지연 Evidence에 대한 진단, 재시작, 사후평가를 검증합니다.",
      mode: "mock",
    },
  ];

  const EXPERIMENT_STAGES = [
    ["condition", "조건 설정"],
    ["evidence", "Evidence"],
    ["diagnosis", "Agent 진단"],
    ["consensus", "상호검토·합의"],
    ["safety", "안전 검증"],
    ["execution", "실행·복구 관찰"],
    ["result", "결과·산출물"],
  ];

  const AGENT_META = {
    AIServiceHASupportAgent: {
      code: "HA",
      label: "AI 서비스 HA 지원",
      role: "장애 원인과 가용성 위험을 진단합니다.",
      tone: "blue",
    },
    AIApplicationManagementAgent: {
      code: "APP",
      label: "AI 응용관리 자동화",
      role: "허용된 Kubernetes 복구 Action을 제안합니다.",
      tone: "green",
    },
    AISemiconductorInfraOpsAgent: {
      code: "INF",
      label: "AI 인프라 운용",
      role: "Replica와 자원 안전성을 교차 검토합니다.",
      tone: "orange",
    },
    CostOptimizationAgent: {
      code: "CST",
      label: "비용 최적화",
      role: "과잉 대응과 비용 정책 위반을 검사합니다.",
      tone: "violet",
    },
  };

  const DOCUMENTS = [
    {
      label: "4-Agent 연구 보고서",
      path: "docs/deliverables/AIOps_4Agent_Research_Report.docx",
      sourcePath: "docs/core_submission_summary.md",
      description: "연구 배경, 구조, 실험 설계, 결과와 한계",
    },
    {
      label: "실험 실행 및 검증 가이드",
      path: "docs/deliverables/AIOps_Experiment_Operations_Guide.docx",
      sourcePath: "docs/submission/execution_code_guide.md",
      description: "mock, dry-run, real 실험 재현 절차",
    },
    {
      label: "Agent Action 및 Reward 정책서",
      path: "docs/deliverables/AIOps_Agent_Policy_Specification.docx",
      sourcePath: "docs/design/agent_action_reward_policy.md",
      description: "Agent 역할, 합의, reward와 안전 경계",
    },
  ];

  const state = {
    overview: null,
    agents: [],
    scenarios: FALLBACK_SCENARIOS,
    latestRun: null,
    currentSession: null,
    experimentHistory: [],
    selectedScenario: "cpu-stress",
    backend: "python",
    running: false,
    lastError: "",
  };

  function h(tag, attrs, children) {
    const element = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value == null || value === false) return;
      if (key === "className") {
        element.className = value;
      } else if (key === "text") {
        element.textContent = value;
      } else if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "disabled") {
        element.disabled = Boolean(value);
      } else {
        element.setAttribute(key, value === true ? "" : String(value));
      }
    });
    (children || []).filter(Boolean).forEach((child) => {
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return element;
  }

  function currentRoute() {
    const hash = window.location.hash || "#/dashboard";
    return ROUTES.find((route) => route.hash === hash) || ROUTES[0];
  }

  function render() {
    const route = currentRoute();
    root.replaceChildren(
      h("div", { className: "platform-shell" }, [
        sidebar(route),
        h("main", { className: "workspace" }, [
          workspaceHeader(route),
          h("div", { className: "workspace-body" }, [
            h("div", { className: "route-view" }, [workspaceView(route.key)]),
          ]),
        ]),
      ])
    );
  }

  function sidebar(route) {
    const session = state.currentSession;
    return h("aside", { className: "sidebar" }, [
      h("div", { className: "sidebar-brand" }, [
        h("div", { className: "brand-lockup" }, [
          h("span", { className: "brand-mark", text: "MC" }),
          h("div", {}, [
            h("strong", { text: "AI-MCMP" }),
            h("small", { text: "Research Control Plane" }),
          ]),
        ]),
        h("p", { text: "Safety-Bounded Closed-Loop 4-Agent AIOps Framework" }),
      ]),
      h(
        "nav",
        { className: "sidebar-nav", "aria-label": "연구 플랫폼 화면" },
        ROUTES.map((item, index) =>
          h(
            "a",
            {
              href: item.hash,
              className: `nav-link${route.key === item.key ? " is-active" : ""}`,
            },
            [
              h("span", { className: "nav-index", text: String(index + 1).padStart(2, "0") }),
              h("span", { className: "nav-copy" }, [
                h("strong", { text: item.label }),
                h("small", { text: item.eyebrow }),
              ]),
            ]
          )
        )
      ),
      h("div", { className: "sidebar-context" }, [
        h("span", { className: "context-label", text: "Current experiment" }),
        contextRow("Mode", session ? session.mode : "mock safe", true),
        contextRow("Scenario", session ? session.condition.scenario : state.selectedScenario),
        contextRow("Status", session ? session.status : "ready", session && session.status === "recovered"),
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
      h("strong", { className: healthy ? "healthy" : "", text: value || "-" }),
    ]);
  }

  function workspaceHeader(route) {
    const session = state.currentSession;
    return h("header", { className: "workspace-header" }, [
      h("div", {}, [
        h("p", { className: "workspace-eyebrow", text: route.eyebrow }),
        h("h1", { text: route.label }),
      ]),
      h("div", { className: "header-status" }, [
        statusPill("4 Agents", "ready"),
        statusPill("Execution", state.running ? "running" : "mock gated"),
        statusPill("Session", session ? compactId(session.experiment_id) : "not started"),
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
      supervision: supervisionView,
      safety: safetyView,
      evidence: evidenceView,
      documents: documentsView,
    };
    return views[routeKey]();
  }

  function dashboardView() {
    const session = state.currentSession;
    const overview = state.overview || {};
    return h("div", { className: "view-stack" }, [
      h("div", { className: "status-strip" }, [
        statusMetric("등록 Agent", String(state.agents.length || 4), "역할 기반 Registry"),
        statusMetric("장애 시나리오", String(state.scenarios.length), "Chaos Mesh profile"),
        statusMetric("실험 세션", String(state.experimentHistory.length), "현재 브라우저"),
        statusMetric("안전 경계", "2", "Validator + optional Guard"),
      ]),
      h("section", { className: "surface research-focus" }, [
        h("div", {}, [
          h("p", { className: "section-kicker", text: "Research objective" }),
          h("h2", { text: "4-Agent가 서로 검토하고, 안전 범위 안에서 복구 Action을 결정합니다." }),
          h("p", {
            text:
              "장애 조건, Evidence, 역할별 진단, 상호검토, 합의, 안전 검증, 실행 결과를 하나의 실험 ID로 연결합니다.",
          }),
        ]),
        h("div", { className: "focus-boundary" }, [
          h("span", { text: "Execution boundary" }),
          h("strong", { text: "웹은 재현 가능한 mock 연구 흐름" }),
          h("small", { text: "실제 Kubernetes real 제어는 CLI에서 별도로 승인합니다." }),
        ]),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("폐쇄 루프 연구 흐름", "한 세션 · 일곱 단계"),
        stageStrip(session),
      ]),
      h("div", { className: "dashboard-grid" }, [
        h("section", { className: "surface" }, [
          sectionTitle("현재 연구 세션", session ? compactId(session.experiment_id) : "waiting"),
          session ? sessionSnapshot(session) : emptyState("아직 실행된 실험이 없습니다.", "운영 실험에서 시나리오를 선택해 시작하세요."),
          textLink("운영 실험 열기", "#/experiments"),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("연구 자산 상태", "repository evidence"),
          healthList(overview.health || {}),
          textLink("실험 근거 열기", "#/evidence"),
        ]),
      ]),
    ]);
  }

  function experimentsView() {
    const scenario = selectedScenario();
    const session = state.currentSession;
    return h("div", { className: "experiment-console" }, [
      h("section", { className: "surface experiment-control-bar" }, [
        h("div", { className: "control-heading" }, [
          h("p", { className: "section-kicker", text: "Fault scenario" }),
          h("h2", { text: "장애 시나리오를 선택하고 4-Agent 폐쇄 루프를 실행합니다." }),
        ]),
        h(
          "div",
          { className: "scenario-switcher", role: "group", "aria-label": "장애 시나리오 선택" },
          state.scenarios.map((item) =>
            h("button", {
              type: "button",
              className: `scenario-button${item.scenario_id === state.selectedScenario ? " is-selected" : ""}`,
              "data-scenario": item.scenario_id,
              "aria-pressed": item.scenario_id === state.selectedScenario ? "true" : "false",
              onClick: () => selectScenario(item.scenario_id),
            }, [
              h("span", { text: item.label }),
              h("small", { text: item.deployment }),
            ])
          )
        ),
        h("label", { className: "backend-control" }, [
          h("span", { text: "Guard" }),
          h("select", {
            value: state.backend,
            onChange: (event) => {
              state.backend = event.target.value;
            },
          }, [
            h("option", {
              value: "python",
              selected: state.backend === "python",
              text: "Python Validator",
            }),
            h("option", {
              value: "go",
              selected: state.backend === "go",
              text: "Go Guard",
            }),
          ]),
        ]),
        h("button", {
          id: "run-experiment",
          type: "button",
          className: "run-button",
          disabled: state.running,
          onClick: runScenario,
        }, [
          h("span", { className: state.running ? "run-spinner" : "run-icon", text: state.running ? "" : "▶" }),
          h("span", { text: state.running ? "4-Agent 분석 중" : "실험 실행" }),
        ]),
      ]),
      state.lastError
        ? h("div", { className: "error-banner", role: "alert" }, [
            h("strong", { text: "실험 요청 실패" }),
            h("span", { text: state.lastError }),
          ])
        : null,
      h("section", { className: "surface stage-surface" }, [
        stageStrip(session),
      ]),
      h("div", { className: "console-grid" }, [
        h("div", { className: "console-main" }, [
          evidencePanel(scenario, session),
          agentPanel(session),
          consensusPanel(session),
          recoveryPanel(session),
        ]),
        decisionInspector(scenario, session),
      ]),
      activityTrace(session),
    ]);
  }

  function evidencePanel(scenario, session) {
    const evidence = stagePayload(session, "evidence");
    const metric = evidence.metric_values || { [scenario.metric]: scenario.value };
    const metricEntry = Object.entries(metric)[0] || [scenario.metric, scenario.value];
    return h("section", { className: "surface evidence-panel" }, [
      sectionTitle("01 · Evidence", session ? "session evidence" : "scenario preset"),
      h("div", { className: "evidence-grid" }, [
        evidenceCell("Scenario", scenario.label, scenario.scenario_id),
        evidenceCell("Target", scenario.deployment, scenario.namespace),
        evidenceCell("Observed signal", `${metricEntry[0]} ${formatNumber(metricEntry[1])}`, `threshold ${formatNumber(scenario.threshold)}`),
        evidenceCell("Source", evidence.source || "control-plane-fake", session ? "collected" : "ready"),
      ]),
      h("div", { className: "evidence-note" }, [
        h("strong", { text: scenario.signal }),
        h("span", { text: scenario.summary }),
      ]),
    ]);
  }

  function evidenceCell(label, value, meta) {
    return h("div", { className: "evidence-cell" }, [
      h("span", { text: label }),
      h("strong", { text: value || "-" }),
      h("small", { text: meta || "" }),
    ]);
  }

  function agentPanel(session) {
    const diagnosisStage = stagePayload(session, "diagnosis");
    const consensus = stagePayload(session, "consensus");
    const result = stagePayload(session, "result");
    const decisions = diagnosisStage.initial_decisions || [];
    const reviews = consensus.peer_reviews || [];
    const contributions = result.agent_contributions || {};
    const activeAgents = session ? session.active_agents : Object.keys(AGENT_META);
    return h("section", { className: "surface agent-panel" }, [
      sectionTitle("02 · 4-Agent 상호감시", session ? `${reviews.length} peer reviews` : "waiting for evidence"),
      h(
        "div",
        { className: "agent-board" },
        activeAgents.map((name) => {
          const meta = AGENT_META[name] || { code: "AG", label: name, role: "Registered Agent", tone: "blue" };
          const decision = decisions.find((item) => item.agent === name);
          const agentReviews = reviews.filter((item) => item.reviewer === name);
          const contribution = contributions[name] || {};
          const verdict = agentReviews.find((item) => item.verdict === "veto")
            ? "veto"
            : agentReviews.length
              ? agentReviews[0].verdict
              : decision
                ? "proposed"
                : "ready";
          return h("article", { className: `agent-work-card tone-${meta.tone}` }, [
            h("div", { className: "agent-work-head" }, [
              h("span", { className: "agent-monogram", text: meta.code }),
              h("div", {}, [
                h("strong", { text: meta.label }),
                h("small", { text: meta.role }),
              ]),
              h("span", { className: `verdict verdict-${verdict}`, text: verdict }),
            ]),
            h("div", { className: "agent-work-body" }, [
              h("p", {
                text:
                  (decision && decision.reason) ||
                  (agentReviews[0] && agentReviews[0].reason) ||
                  "Evidence 수집 후 역할 범위 안에서 판단합니다.",
              }),
              h("div", { className: "agent-metrics" }, [
                miniMetric("decision", decision ? "1" : "0"),
                miniMetric("reviews", String(agentReviews.length)),
                miniMetric("reward", contribution.reward == null ? "-" : Number(contribution.reward).toFixed(3)),
              ]),
            ]),
          ]);
        })
      ),
    ]);
  }

  function miniMetric(label, value) {
    return h("span", {}, [
      h("small", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function consensusPanel(session) {
    const consensus = stagePayload(session, "consensus");
    const negotiation = consensus.negotiation || {};
    const action = consensus.selected_action || {};
    const safety = stagePayload(session, "safety");
    const execution = stagePayload(session, "execution");
    return h("section", { className: "surface consensus-panel" }, [
      sectionTitle("03 · 합의와 안전 경계", session ? negotiation.strategy || "role_based_veto" : "not started"),
      h("div", { className: "consensus-flow" }, [
        flowNode("합의", negotiation.consensus || "waiting", `round ${negotiation.round_count || 0}`),
        flowArrow(),
        flowNode("Action", action.kind || "not selected", action.replicas ? `replicas ${action.replicas}` : "bounded action"),
        flowArrow(),
        flowNode(
          "Validator",
          safety.valid === true ? "passed" : safety.valid === false ? "rejected" : "waiting",
          session ? session.guard_backend : state.backend
        ),
        flowArrow(),
        flowNode("Execution", execution.valid === true ? execution.mode : "waiting", execution.valid === true ? "validated" : "not executed"),
      ]),
      h("div", { className: "command-panel" }, [
        h("span", { text: "Bounded command" }),
        h("code", { text: execution.command || safety.command || "실험 실행 후 검증된 명령이 표시됩니다." }),
      ]),
    ]);
  }

  function flowNode(label, value, meta) {
    return h("div", { className: "flow-node" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
      h("small", { text: meta }),
    ]);
  }

  function flowArrow() {
    return h("span", { className: "flow-arrow", text: "→" });
  }

  function recoveryPanel(session) {
    const result = stagePayload(session, "result");
    const recovery = result.recovery_monitoring || {};
    const improved = Number(recovery.metric_improvement || 0);
    const percentage = Math.max(8, Math.min(100, Math.round(improved * 100)));
    return h("section", { className: "surface recovery-panel" }, [
      sectionTitle("04 · 복구 평가", session ? session.status : "waiting"),
      h("div", { className: "recovery-layout" }, [
        h("div", { className: "recovery-summary" }, [
          h("span", { className: `recovery-indicator${session && session.status === "recovered" ? " is-recovered" : ""}` }),
          h("div", {}, [
            h("strong", { text: session ? statusLabel(session.status) : "실험 대기" }),
            h("small", {
              text: session
                ? `${(result.post_execution_reviews || []).length}개 사후 검토 완료`
                : "Agent 실행 결과가 아직 없습니다.",
            }),
          ]),
        ]),
        h("div", { className: "metric-chart" }, [
          h("div", { className: "chart-scale" }, [
            h("span", { text: "0" }),
            h("span", { text: "metric improvement" }),
            h("span", { text: "1.0" }),
          ]),
          h("div", { className: "chart-track" }, [
            h("span", { className: "chart-bar", style: `width:${percentage}%` }),
          ]),
          h("div", { className: "chart-value" }, [
            h("strong", { text: session ? improved.toFixed(2) : "-" }),
            h("span", { text: recovery.replanning_required ? "replan required" : "no replan" }),
          ]),
        ]),
      ]),
    ]);
  }

  function decisionInspector(scenario, session) {
    const diagnosisStage = stagePayload(session, "diagnosis");
    const diagnosis = diagnosisStage.diagnosis || {};
    const consensus = stagePayload(session, "consensus");
    const action = consensus.selected_action || {};
    const safety = stagePayload(session, "safety");
    return h("aside", { className: "surface decision-inspector" }, [
      h("div", { className: "inspector-head" }, [
        h("p", { className: "section-kicker", text: "Decision inspector" }),
        h("h2", { text: scenario.label }),
        h("span", { className: `session-status status-${session ? session.status : "ready"}`, text: session ? session.status : "ready" }),
      ]),
      inspectorGroup("Experiment", [
        inspectorRow("ID", session ? compactId(session.experiment_id) : "not started"),
        inspectorRow("Profile", session ? session.protocol_profile.profile_id : "four-agent-role-veto-v1"),
        inspectorRow("Target", `${scenario.namespace}/${scenario.deployment}`),
      ]),
      inspectorGroup("Diagnosis", [
        inspectorRow("Cause", diagnosis.cause || "waiting"),
        inspectorRow("Severity", diagnosis.severity || "-"),
        inspectorRow("Confidence", diagnosis.confidence == null ? "-" : Number(diagnosis.confidence).toFixed(2)),
      ]),
      inspectorGroup("Final decision", [
        inspectorRow("Action", action.kind || "waiting"),
        inspectorRow("Replicas", action.replicas == null ? "-" : String(action.replicas)),
        inspectorRow("Safety", safety.valid === true ? "passed" : safety.valid === false ? "rejected" : "waiting"),
      ]),
      h("div", { className: "research-boundary-note" }, [
        h("strong", { text: "Mock research boundary" }),
        h("p", { text: "이 화면의 실행 결과는 실제 Kubernetes 변경이 아닌 재현 가능한 mock evidence입니다." }),
      ]),
    ]);
  }

  function inspectorGroup(title, rows) {
    return h("section", { className: "inspector-group" }, [
      h("h3", { text: title }),
      ...rows,
    ]);
  }

  function inspectorRow(label, value) {
    return h("div", { className: "inspector-row" }, [
      h("span", { text: label }),
      h("strong", { text: value || "-" }),
    ]);
  }

  function activityTrace(session) {
    const evidence = stagePayload(session, "evidence");
    const diagnosisStage = stagePayload(session, "diagnosis");
    const consensus = stagePayload(session, "consensus");
    const execution = stagePayload(session, "execution");
    const items = session
      ? [
          ["Evidence", `${Object.keys(evidence.metric_values || {})[0] || "metric"} 관측 완료`],
          ["HA", (diagnosisStage.diagnosis && diagnosisStage.diagnosis.cause) || "진단 완료"],
          ["Peers", `${(consensus.peer_reviews || []).length}개 상호검토 수집`],
          ["Consensus", (consensus.negotiation && consensus.negotiation.consensus) || "검토 중"],
          ["Execution", execution.valid ? `${execution.mode} 검증 완료` : "실행 없음"],
        ]
      : [["System", "시나리오를 선택하고 실험을 실행하세요."]];
    return h("section", { className: "surface activity-trace" }, [
      sectionTitle("Live experiment trace", session ? compactId(session.experiment_id) : "idle"),
      h("div", { className: "trace-list" }, items.map(([actor, message], index) =>
        h("div", { className: "trace-row" }, [
          h("span", { className: "trace-time", text: `T+${String(index).padStart(2, "0")}` }),
          h("strong", { text: actor }),
          h("span", { text: message }),
        ])
      )),
    ]);
  }

  function decisionView() {
    const session = state.currentSession;
    const diagnosis = stagePayload(session, "diagnosis");
    const decisions = diagnosis.initial_decisions || [];
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("Agent Registry", "4-Agent 기본 프로파일"),
        h("div", { className: "registry-grid" }, (state.agents.length ? state.agents : Object.keys(AGENT_META).map((name) => ({ name }))).map((agent) => {
          const meta = AGENT_META[agent.name] || { code: "AG", label: agent.label || agent.name, role: agent.role || "Registered Agent", tone: "blue" };
          return h("article", { className: `registry-card tone-${meta.tone}` }, [
            h("span", { className: "agent-monogram", text: meta.code }),
            h("strong", { text: meta.label }),
            h("p", { text: meta.role }),
            h("small", { text: agent.enabled === false ? "disabled" : "enabled" }),
          ]);
        })),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("현재 세션의 초기 판단", session ? compactId(session.experiment_id) : "waiting"),
        decisions.length
          ? h("div", { className: "decision-ledger" }, decisions.map((decision) => decisionLedgerRow(decision)))
          : emptyState("초기 판단 기록이 없습니다.", "운영 실험을 먼저 실행하세요."),
      ]),
    ]);
  }

  function decisionLedgerRow(decision) {
    const meta = AGENT_META[decision.agent] || { code: "AG", label: decision.agent };
    return h("article", { className: "ledger-row" }, [
      h("span", { className: "agent-monogram small", text: meta.code }),
      h("div", {}, [
        h("strong", { text: meta.label }),
        h("p", { text: decision.reason }),
      ]),
      h("span", { className: "ledger-type", text: decision.decision_type }),
      h("strong", { text: Number(decision.reward || 0).toFixed(2) }),
    ]);
  }

  function supervisionView() {
    const session = state.currentSession;
    const consensus = stagePayload(session, "consensus");
    const reviews = consensus.peer_reviews || [];
    const negotiation = consensus.negotiation || {};
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("상호감시 프로토콜", "review · revise · veto · consensus"),
        h("div", { className: "protocol-strip" }, [
          protocolStep("01", "초기 판단", "HA · Application"),
          protocolStep("02", "동료 검토", "HA · Infra · Cost"),
          protocolStep("03", "재협상", "최대 2회"),
          protocolStep("04", "안전 검증", "Validator / Guard"),
          protocolStep("05", "사후 평가", "4-Agent"),
        ]),
      ]),
      h("div", { className: "supervision-layout" }, [
        h("section", { className: "surface" }, [
          sectionTitle("Peer review ledger", `${reviews.length} records`),
          reviews.length
            ? h("div", { className: "review-ledger" }, reviews.map((review) => reviewRow(review)))
            : emptyState("상호검토 기록이 없습니다.", "운영 실험을 먼저 실행하세요."),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("Consensus state", negotiation.strategy || "role_based_veto"),
          summaryGrid([
            ["Consensus", negotiation.consensus || "waiting"],
            ["Rounds", String(negotiation.round_count || 0)],
            ["Action", (consensus.selected_action || {}).kind || "-"],
            ["Human review", session && session.human_review_required ? "required" : "not required"],
          ]),
        ]),
      ]),
    ]);
  }

  function protocolStep(number, title, detail) {
    return h("article", { className: "protocol-step" }, [
      h("span", { text: number }),
      h("strong", { text: title }),
      h("small", { text: detail }),
    ]);
  }

  function reviewRow(review) {
    const reviewer = AGENT_META[review.reviewer] || { code: "AG", label: review.reviewer };
    const target = AGENT_META[review.target_agent] || { label: review.target_agent };
    return h("article", { className: "review-row" }, [
      h("span", { className: "agent-monogram small", text: reviewer.code }),
      h("div", {}, [
        h("strong", { text: `${reviewer.label} → ${target.label}` }),
        h("p", { text: review.reason }),
      ]),
      h("span", { className: `verdict verdict-${review.verdict}`, text: review.verdict }),
    ]);
  }

  function safetyView() {
    const session = state.currentSession;
    const safety = stagePayload(session, "safety");
    const execution = stagePayload(session, "execution");
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("Safety-Bounded Action Pipeline", "Agent 출력은 직접 실행되지 않습니다."),
        h("div", { className: "gate-flow" }, [
          gateStep("01", "Agent Registry", "등록된 Agent와 허용 Action"),
          gateStep("02", "Role consensus", "역할별 veto와 재협상"),
          gateStep("03", "Python Validator", "대상·명령·Replica 검증"),
          gateStep("04", "Optional Go Guard", "독립 구현 교차 검증"),
          gateStep("05", "Execution boundary", "mock / dry-run / real 분리"),
        ]),
      ]),
      h("div", { className: "safety-grid" }, [
        h("section", { className: "surface" }, [
          sectionTitle("현재 안전 검증", session ? compactId(session.experiment_id) : "waiting"),
          summaryGrid([
            ["Validation", safety.valid === true ? "passed" : safety.valid === false ? "rejected" : "waiting"],
            ["Backend", session ? session.guard_backend : state.backend],
            ["Execution mode", execution.mode || "-"],
            ["Result", execution.valid === true ? "validated" : "not executed"],
          ]),
          h("div", { className: "command-panel" }, [
            h("span", { text: "Validated command" }),
            h("code", { text: execution.command || safety.command || "No validated command" }),
          ]),
        ]),
        h("section", { className: "surface" }, [
          sectionTitle("항상 유지되는 경계", "invariants"),
          policyRow("Namespace", "allowlist only"),
          policyRow("Deployment", "allowlist only"),
          policyRow("Replica", "configured min–max"),
          policyRow("Unknown metric", "observe only"),
          policyRow("Consensus failure", "safe stop + human review"),
        ]),
      ]),
    ]);
  }

  function gateStep(number, title, detail) {
    return h("article", { className: "gate-step" }, [
      h("span", { className: "gate-number", text: number }),
      h("div", {}, [
        h("strong", { text: title }),
        h("small", { text: detail }),
      ]),
    ]);
  }

  function evidenceView() {
    const session = state.currentSession;
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("ExperimentSession archive", `${state.experimentHistory.length} browser records`),
        state.experimentHistory.length
          ? h("div", { className: "history-list" }, state.experimentHistory.map((item) => historyRow(item)))
          : emptyState("저장된 브라우저 세션이 없습니다.", "실행 결과는 서버의 in-memory store에도 보관됩니다."),
      ]),
      h("section", { className: "surface" }, [
        sectionTitle("현재 세션 원본", session ? compactId(session.experiment_id) : "waiting"),
        h("pre", { className: "json-view", text: session ? JSON.stringify(session, null, 2) : "{}" }),
      ]),
    ]);
  }

  function historyRow(session) {
    const action = stagePayload(session, "consensus").selected_action || {};
    return h("button", {
      type: "button",
      className: `history-row${state.currentSession && state.currentSession.experiment_id === session.experiment_id ? " is-current" : ""}`,
      onClick: () => {
        state.currentSession = session;
        state.selectedScenario = session.condition.scenario;
        render();
      },
    }, [
      h("span", { text: compactId(session.experiment_id) }),
      h("strong", { text: session.condition.scenario }),
      h("span", { text: action.kind || "-" }),
      h("span", { className: `session-status status-${session.status}`, text: session.status }),
    ]);
  }

  function documentsView() {
    return h("div", { className: "view-stack" }, [
      h("section", { className: "surface" }, [
        sectionTitle("연구 문서", "편집 가능한 DOCX와 원본 연구 기록"),
        h("div", { className: "document-list" }, DOCUMENTS.map((document) =>
          h("article", { className: "document-row" }, [
            h("span", { className: "document-type", text: "DOCX" }),
            h("div", {}, [
              h("strong", { text: document.label }),
              h("p", { text: document.description }),
              h("code", { text: document.path }),
              h("a", {
                className: "document-source",
                href: `/api/artifacts/${document.sourcePath}`,
                target: "_blank",
                rel: "noreferrer",
                text: "MD 원본",
              }),
            ]),
            h("a", {
              className: "document-link",
              href: `/api/artifacts/${document.path}`,
              target: "_blank",
              rel: "noreferrer",
              text: "열기",
            }),
          ])
        )),
      ]),
    ]);
  }

  function stageStrip(session) {
    return h("div", { className: "experiment-stage-strip" }, EXPERIMENT_STAGES.map(([key, label], index) => {
      const status = session ? ((session.stages[key] || {}).status || "pending") : index === 0 ? "ready" : "pending";
      return h("article", { className: `experiment-stage stage-${status}` }, [
        h("span", { text: String(index + 1) }),
        h("div", {}, [
          h("strong", { text: label }),
          h("small", { text: status }),
        ]),
      ]);
    }));
  }

  function sessionSnapshot(session) {
    const action = stagePayload(session, "consensus").selected_action || {};
    return h("div", { className: "session-snapshot" }, [
      summaryGrid([
        ["Scenario", session.condition.scenario],
        ["Target", session.condition.deployment],
        ["Action", action.kind || "-"],
        ["Status", session.status],
      ]),
    ]);
  }

  function healthList(health) {
    const labels = {
      agent_registry: "Agent Registry",
      recovery_config: "Recovery policy",
      chaos_manifests: "Chaos manifests",
      runs_dir: "Runs directory",
    };
    return h("div", { className: "health-list" }, Object.entries(labels).map(([key, label]) =>
      h("div", { className: "health-row" }, [
        h("span", { text: label }),
        h("strong", { className: health[key] ? "health-ok" : "health-missing", text: health[key] ? "available" : "missing" }),
      ])
    ));
  }

  function summaryGrid(items) {
    return h("div", { className: "summary-grid" }, items.map(([label, value]) =>
      h("div", { className: "summary-cell" }, [
        h("span", { text: label }),
        h("strong", { text: value || "-" }),
      ])
    ));
  }

  function policyRow(label, value) {
    return h("div", { className: "policy-row" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function sectionTitle(title, meta) {
    return h("div", { className: "section-title" }, [
      h("h2", { text: title }),
      meta ? h("span", { text: meta }) : null,
    ]);
  }

  function statusMetric(label, value, note) {
    return h("article", { className: "status-metric" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
      h("small", { text: note }),
    ]);
  }

  function emptyState(title, detail) {
    return h("div", { className: "empty-state" }, [
      h("span", { className: "empty-index", text: "—" }),
      h("strong", { text: title }),
      h("p", { text: detail }),
    ]);
  }

  function textLink(label, href) {
    return h("a", { className: "text-button", href, text: label });
  }

  function selectedScenario() {
    return state.scenarios.find((item) => item.scenario_id === state.selectedScenario) || state.scenarios[0];
  }

  function selectScenario(scenarioId) {
    if (
      state.currentSession
      && state.currentSession.condition
      && state.currentSession.condition.scenario !== scenarioId
    ) {
      state.currentSession = null;
    }
    state.selectedScenario = scenarioId;
    state.lastError = "";
    render();
  }

  function stagePayload(session, stageName) {
    if (!session || !session.stages || !session.stages[stageName]) return {};
    return session.stages[stageName].payload || {};
  }

  async function runScenario() {
    state.running = true;
    state.lastError = "";
    render();
    try {
      const response = await fetch("/api/experiments/mock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario_id: state.selectedScenario,
          backend: state.backend,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      state.currentSession = payload;
      state.experimentHistory = [
        payload,
        ...state.experimentHistory.filter((item) => item.experiment_id !== payload.experiment_id),
      ].slice(0, 20);
    } catch (error) {
      state.lastError = String(error.message || error);
    } finally {
      state.running = false;
      render();
    }
  }

  function compactId(value) {
    if (!value) return "-";
    return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
  }

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    if (Math.abs(number) < 1 && number !== 0) return number.toFixed(3);
    if (Number.isInteger(number)) return String(number);
    return number.toFixed(1);
  }

  function statusLabel(status) {
    const labels = {
      recovered: "복구 확인",
      recovered_after_replan: "재계획 후 복구",
      safe_stopped: "안전 중단",
      consensus_rejected: "합의 거부",
      safe_failure: "안전 실패",
    };
    return labels[status] || status;
  }

  async function boot() {
    try {
      const [overviewResponse, agentsResponse, scenariosResponse, latestResponse] = await Promise.all([
        fetch("/api/overview"),
        fetch("/api/agents"),
        fetch("/api/scenarios"),
        fetch("/api/runs/latest"),
      ]);
      state.overview = await overviewResponse.json();
      state.agents = (await agentsResponse.json()).agents || [];
      const scenarioPayload = await scenariosResponse.json();
      state.scenarios = scenarioPayload.scenarios && scenarioPayload.scenarios.length
        ? scenarioPayload.scenarios
        : FALLBACK_SCENARIOS;
      const latestPayload = await latestResponse.json();
      state.latestRun = latestPayload.available ? latestPayload.run : null;
    } catch (error) {
      state.lastError = `초기 데이터 로드 실패: ${String(error.message || error)}`;
    }
    render();
  }

  window.addEventListener("hashchange", render);
  boot();
})();
