(function () {
  const root = document.getElementById("root");
  const state = {
    overview: null,
    agents: [],
    latestRun: null,
    mockResult: null,
    running: false,
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

  function render() {
    root.replaceChildren(layout());
  }

  function layout() {
    return h("div", { className: "research-site" }, [
      sidebar(),
      h("main", { className: "page" }, [
        hero(),
        contributionSection(),
        architectureSection(),
        agentSection(),
        evidenceAndDemo(),
        footer(),
      ]),
    ]);
  }

  function sidebar() {
    const health = (state.overview && state.overview.health) || {};
    const ready = Object.values(health).filter(Boolean).length;
    const total = Object.keys(health).length || 4;
    return h("aside", { className: "sidebar" }, [
      h("div", { className: "sidebar-brand" }, [
        h("div", { className: "mark", text: "AI-MCMP" }),
        h("h2", { text: "4-Agent AIOps" }),
        h("p", { text: "Kubernetes 장애 대응을 위한 역할 기반 Agent 연구 프레임워크" }),
      ]),
      h("nav", { className: "sidebar-nav" }, [
        link("Overview", "연구 개요", "#overview"),
        link("Architecture", "전체 구조", "#architecture"),
        link("Agents", "역할 설계", "#agents"),
        link("Evidence", "실험 근거", "#evidence"),
        link("Demo", "안전 데모", "#demo"),
      ]),
      h("section", { className: "side-panel" }, [
        h("h3", { text: "Current State" }),
        sideMetric("Evidence", `${ready}/${total}`),
        sideMetric("Mode", "mock-gated UI"),
        sideMetric("Latest records", state.latestRun ? String(state.latestRun.outcome_count) : "0"),
      ]),
      h("section", { className: "side-panel" }, [
        h("h3", { text: "Documents" }),
        doc("실행 코드", "docs/submission/execution_code_guide.md"),
        doc("시험 가이드", "docs/submission/test_guide.md"),
        doc("정량 분석", "docs/experiments/recovery_quantitative_analysis_guide.md"),
      ]),
    ]);
  }

  function link(top, bottom, href) {
    return h("a", { href, className: "nav-link" }, [
      h("span", { text: top }),
      h("small", { text: bottom }),
    ]);
  }

  function sideMetric(label, value) {
    return h("div", { className: "side-metric" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function doc(label, path) {
    return h("a", { className: "doc-link", href: `/api/artifacts/${path}`, target: "_blank" }, [
      h("span", { text: label }),
      h("small", { text: path.split("/").pop() }),
    ]);
  }

  function hero() {
    return h("section", { className: "hero", id: "overview" }, [
      h("div", { className: "hero-main" }, [
        h("p", { className: "kicker", text: "Graduate Research Framework" }),
        h("h1", { text: "4-Agent 기반 Kubernetes 장애 대응 자동화" }),
        h("p", {
          className: "hero-text",
          text:
            "본 연구는 장애 관측 데이터로부터 HA, 응용관리, 인프라, 비용 Agent가 복구 조치를 교차 검토하고, 안전 검증을 통과한 action만 Kubernetes에 적용하는 AIOps 제어 구조를 제안합니다.",
        }),
        h("div", { className: "hero-tags" }, [
          h("span", { text: "Chaos Mesh" }),
          h("span", { text: "Prometheus" }),
          h("span", { text: "4-Agent Consensus" }),
          h("span", { text: "Safety-Bounded Control" }),
        ]),
      ]),
      h("aside", { className: "thesis-card" }, [
        h("span", { className: "card-label", text: "Research statement" }),
        h("h2", { text: "장애 복구 자동화에서 LLM Agent 판단을 안전하게 실행 가능한가?" }),
        h("p", {
          text:
            "핵심은 더 많은 명령을 자동 실행하는 것이 아니라, Agent 판단을 구조화하고 검증 가능한 action으로 제한하는 것입니다.",
        }),
      ]),
    ]);
  }

  function contributionSection() {
    const items = [
      ["01", "역할 기반 판단", "HA, 응용관리, 인프라, 비용 Agent가 동일 장애를 각자의 정책 관점에서 검토합니다."],
      ["02", "안전한 실행 경계", "자유 텍스트 명령을 직접 실행하지 않고, allowlist와 replica 제한을 통과한 action만 허용합니다."],
      ["03", "재현 가능한 실험 근거", "Chaos Mesh 장애, Prometheus 관측, Kubernetes 상태, reward 결과를 파일로 남깁니다."],
    ];
    return h("section", { className: "section compact" }, [
      sectionHead("연구 기여", "교수님께 가장 먼저 보여줄 핵심은 세 가지로 압축했습니다."),
      h("div", { className: "contribution-grid" },
        items.map(([num, title, body]) =>
          h("article", { className: "contribution-card" }, [
            h("span", { text: num }),
            h("h3", { text: title }),
            h("p", { text: body }),
          ])
        )
      ),
    ]);
  }

  function architectureSection() {
    const steps = [
      ["장애 주입", "AIOpsLab / Chaos Mesh"],
      ["상태 관측", "Prometheus / K8s"],
      ["Agent 판단", "AI-MCMP Coordinator"],
      ["교차 검증", "Action / Reward"],
      ["안전 실행", "Validator / Guard"],
      ["피드백", "Result / Statistics"],
    ];
    return h("section", { className: "section", id: "architecture" }, [
      sectionHead("전체 시스템 구조", "복잡한 구현보다 데이터와 의사결정 흐름을 먼저 보이도록 구성했습니다."),
      h("div", { className: "flow" },
        steps.map(([title, body], index) =>
          h("article", { className: "flow-node" }, [
            h("span", { text: String(index + 1) }),
            h("h3", { text: title }),
            h("p", { text: body }),
          ])
        )
      ),
      h("figure", { className: "architecture-figure" }, [
        h("img", {
          src: "/api/artifacts/docs/assets/architecture_overview.png",
          alt: "AIOps 4-Agent architecture overview",
        }),
        h("figcaption", {
          text:
            "AIOpsLab/Chaos Mesh 장애 주입, Prometheus 관측, 4-Agent 판단, 안전 검증, Kubernetes 실행, 피드백 분석으로 이어지는 연구 구조",
        }),
      ]),
    ]);
  }

  function agentSection() {
    return h("section", { className: "section", id: "agents" }, [
      sectionHead("4-Agent 역할 설계", "하나의 거대한 Agent가 아니라, 분리된 역할들이 교차 검증하는 구조입니다."),
      h("div", { className: "agent-grid" },
        state.agents.map((agent) =>
          h("article", { className: "agent-card" }, [
            h("span", { className: "agent-code", text: shortName(agent.name) }),
            h("h3", { text: agentLabel(agent) }),
            h("p", { text: agent.role || "역할 설명이 설정되지 않았습니다." }),
            h("div", { className: "tag-row" },
              (agent.bounded_actions || []).slice(0, 3).map((action) =>
                h("span", { text: action })
              )
            ),
          ])
        )
      ),
    ]);
  }

  function agentLabel(agent) {
    const labels = {
      AIServiceHASupportAgent: "AI서비스 HA 지원 에이전트",
      AIApplicationManagementAgent: "AI응용관리 자동화 에이전트",
      AISemiconductorInfraOpsAgent: "AI반도체 인프라 운용 에이전트",
      CostOptimizationAgent: "비용 최적화 지원 에이전트",
    };
    return labels[agent.name] || agent.label || agent.name;
  }

  function shortName(name) {
    if (name.includes("HA")) return "HA";
    if (name.includes("Application")) return "APP";
    if (name.includes("Infra")) return "INF";
    if (name.includes("Cost")) return "COST";
    return "AG";
  }

  function evidenceAndDemo() {
    return h("section", { className: "split-section", id: "evidence" }, [
      evidencePanel(),
      demoPanel(),
    ]);
  }

  function evidencePanel() {
    const latest = state.latestRun;
    return h("article", { className: "section evidence-panel" }, [
      sectionHead("실험 근거", "실험 결과는 논문용 근거로 남기되, 첫 화면에서는 숨 쉬게 보여줍니다."),
      latest
        ? h("div", { className: "run-card" }, [
            sideMetric("Run path", latest.path),
            sideMetric("Outcomes", String(latest.outcome_count)),
            h("pre", {
              className: "excerpt",
              text: latest.reward_policy_excerpt || "Reward policy summary가 아직 없습니다.",
            }),
          ])
        : h("p", {
            className: "muted",
            text:
              "현재 이 환경에는 recovery-action-pilot 결과가 없습니다. 서버에서 실험을 돌리면 reward ranking과 정량 artifact가 표시됩니다.",
          }),
    ]);
  }

  function demoPanel() {
    return h("article", { className: "section demo-panel", id: "demo" }, [
      sectionHead("안전한 판단 데모", "실제 클러스터를 건드리지 않는 mock 모드에서만 Agent 합의를 확인합니다."),
      h("form", { className: "demo-form", onSubmit: runMock }, [
        field("Namespace", "namespace"),
        field("Deployment", "deployment"),
        field("Metric", "metric"),
        field("Value", "value", "number"),
        field("Threshold", "threshold", "number"),
        guardField(),
        h("button", {
          className: "primary-button",
          disabled: state.running,
          text: state.running ? "판단 생성 중..." : "4-Agent 판단 생성",
        }),
      ]),
      state.mockResult ? decisionTable() : h("p", {
        className: "muted",
        text: "버튼을 누르면 Agent별 decision, action, reward와 최종 mock 명령이 표시됩니다.",
      }),
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

  function guardField() {
    return h("label", { className: "field" }, [
      h("span", { text: "Guard" }),
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

  function decisionTable() {
    const reviews = state.mockResult.agent_reviews || [];
    return h("div", { className: "decision-result" }, [
      h("table", {}, [
        h("thead", {}, [
          h("tr", {}, ["Agent", "Decision", "Action", "Reward"].map((name) => h("th", { text: name }))),
        ]),
        h("tbody", {}, reviews.map((review) =>
          h("tr", {}, [
            h("td", { text: shortName(review.agent) }),
            h("td", { text: review.decision }),
            h("td", { text: review.action }),
            h("td", { text: review.reward == null ? "-" : Number(review.reward).toFixed(2) }),
          ])
        )),
      ]),
      h("pre", {
        className: "command-box",
        text: JSON.stringify(state.mockResult.result, null, 2),
      }),
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

  function sectionHead(title, text) {
    return h("div", { className: "section-head" }, [
      h("h2", { text: title }),
      text ? h("p", { text }) : null,
    ]);
  }

  function footer() {
    return h("footer", { className: "footer" }, [
      h("span", { text: "AIOps 4-Agent Kubernetes Recovery Research" }),
      h("span", { text: "Real-mode control remains CLI-gated for safety." }),
    ]);
  }

  async function boot() {
    root.replaceChildren(h("main", { className: "loading" }, [
      h("h1", { text: "AIOps Research Control Plane" }),
      h("p", { text: "연구 화면을 준비하고 있습니다." }),
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

  boot();
})();
