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

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "disabled") node.disabled = Boolean(value);
      else if (key === "value") node.value = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else {
        node.setAttribute(key, value);
      }
    });
    (children || []).forEach((child) => {
      if (child == null) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  async function getJson(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  }

  function render() {
    root.replaceChildren(page());
  }

  function page() {
    return el("div", { className: "site" }, [
      header(),
      el("div", { className: "content-layout" }, [
        sideRail(),
        el("main", { className: "content-main" }, [
          hero(),
          researchFocus(),
          systemFlow(),
          agentsSection(),
          evidenceSection(),
          safeDemoSection(),
        ]),
      ]),
      footer(),
    ]);
  }

  function header() {
    return el("header", { className: "site-header" }, [
      el("a", { className: "brand", href: "#" }, [
        el("span", { className: "brand-symbol", text: "AI" }),
        el("span", {}, [
          el("strong", { text: "AIOps 4-Agent" }),
          el("small", { text: "Research Control Plane" }),
        ]),
      ]),
      el("nav", { className: "top-nav" }, [
        navLink("연구 개요", "#overview"),
        navLink("시스템 구조", "#framework"),
        navLink("실험 근거", "#evidence"),
        navLink("안전 데모", "#demo"),
      ]),
    ]);
  }

  function sideRail() {
    const health = state.overview ? state.overview.health || {} : {};
    const readyCount = Object.values(health).filter(Boolean).length;
    const total = Object.keys(health).length || 4;
    return el("aside", { className: "side-rail" }, [
      el("div", { className: "side-card side-identity" }, [
        el("div", { className: "side-mark", text: "AI-MCMP" }),
        el("h2", { text: "4-Agent AIOps" }),
        el("p", {
          text:
            "장애 대응 판단, 안전 검증, 실험 근거를 연결하는 연구용 Control Plane입니다.",
        }),
      ]),
      el("nav", { className: "side-menu" }, [
        navLink("연구 개요", "#overview"),
        navLink("시스템 구조", "#framework"),
        navLink("실험 근거", "#evidence"),
        navLink("안전 데모", "#demo"),
      ]),
      el("div", { className: "side-card" }, [
        el("h3", { text: "Research status" }),
        statusLine("Evidence", `${readyCount}/${total}`),
        statusLine("Mode", "mock-gated UI"),
        statusLine("Records", state.latestRun ? `${state.latestRun.outcome_count}` : "0"),
      ]),
      el("div", { className: "side-card" }, [
        el("h3", { text: "Documents" }),
        sideDoc("실행 코드", "docs/submission/execution_code_guide.md"),
        sideDoc("시험 가이드", "docs/submission/test_guide.md"),
        sideDoc("정량 분석", "docs/experiments/recovery_quantitative_analysis_guide.md"),
      ]),
    ]);
  }

  function sideDoc(label, path) {
    return el("a", { className: "side-doc", href: `/api/artifacts/${path}`, target: "_blank" }, [
      el("span", { text: label }),
      el("small", { text: path.split("/").pop() }),
    ]);
  }

  function navLink(label, href) {
    return el("a", { href, text: label });
  }

  function hero() {
    const health = state.overview ? state.overview.health || {} : {};
    const readyCount = Object.values(health).filter(Boolean).length;
    const total = Object.keys(health).length || 4;
    return el("section", { className: "hero", id: "overview" }, [
      el("div", { className: "hero-copy" }, [
        el("p", { className: "eyebrow", text: "Kyung Hee University · Graduate Research" }),
        el("h1", { text: "Safety-Bounded 4-Agent AIOps Framework" }),
        el("p", {
          className: "hero-lead",
          text:
            "Kubernetes 장애 상황에서 4개의 역할 기반 Agent가 복구 action을 판단하고, 안전 검증을 거친 명령만 실행하도록 설계한 폐쇄 루프 AIOps 연구 프레임워크입니다.",
        }),
        el("div", { className: "hero-actions" }, [
          el("a", { className: "button primary", href: "#framework", text: "구조 보기" }),
          el("a", { className: "button secondary", href: "#demo", text: "안전 데모 실행" }),
        ]),
      ]),
      el("aside", { className: "hero-status" }, [
        el("div", { className: "status-label", text: "Current Research State" }),
        statusLine("Evidence files", `${readyCount}/${total}`),
        statusLine("Execution modes", "mock / dry-run / real"),
        statusLine("UI execution", "mock-gated"),
        statusLine("Latest records", state.latestRun ? `${state.latestRun.outcome_count}` : "not loaded"),
      ]),
    ]);
  }

  function statusLine(label, value) {
    return el("div", { className: "status-line" }, [
      el("span", { text: label }),
      el("strong", { text: value }),
    ]);
  }

  function researchFocus() {
    const items = [
      [
        "역할 분리",
        "HA, 응용관리, 인프라, 비용 Agent가 동일 장애를 서로 다른 관점에서 검토합니다.",
      ],
      [
        "안전 경계",
        "LLM/Agent 판단을 자유 명령으로 실행하지 않고, 구조화 action과 validator를 통과시킵니다.",
      ],
      [
        "실험 근거",
        "Chaos Mesh, Prometheus, Kubernetes 결과를 JSONL, CSV, 그래프로 남겨 논문 실험으로 확장합니다.",
      ],
    ];
    return el("section", { className: "section narrow" }, [
      sectionHeading("연구의 핵심", "첫 화면에서는 복잡한 세부 로그보다 연구 질문과 기여를 먼저 보여줍니다."),
      el(
        "div",
        { className: "focus-grid" },
        items.map(([title, copy]) =>
          el("article", { className: "focus-card" }, [
            el("h3", { text: title }),
            el("p", { text: copy }),
          ])
        )
      ),
    ]);
  }

  function systemFlow() {
    const steps = [
      ["Fault", "AIOpsLab / Chaos Mesh"],
      ["Observe", "Prometheus + Kubernetes snapshot"],
      ["Reason", "AI-MCMP Coordinator + 4-Agent"],
      ["Guard", "Python Validator / optional Go Guard"],
      ["Act", "kubectl mock, dry-run, real"],
      ["Report", "reward, recovery, graph"],
    ];
    return el("section", { className: "section", id: "framework" }, [
      sectionHeading("시스템 구조", "장애를 입력으로 받아 안전한 복구 action과 실험 결과로 변환하는 흐름입니다."),
      el(
        "div",
        { className: "flow-row" },
        steps.map(([title, copy], index) =>
          el("article", { className: "flow-step" }, [
            el("span", { className: "step-number", text: String(index + 1) }),
            el("h3", { text: title }),
            el("p", { text: copy }),
          ])
        )
      ),
    ]);
  }

  function agentsSection() {
    return el("section", { className: "section two-column" }, [
      el("div", {}, [
        sectionHeading("4-Agent 판단 구조", "Agent는 하나의 거대한 모델이 아니라 역할이 나뉜 협업 판단 단위입니다."),
        el(
          "div",
          { className: "agent-grid" },
          state.agents.map((agent) =>
            el("article", { className: "agent-card" }, [
              el("span", { className: "agent-code", text: shortAgent(agent.name) }),
              el("div", {}, [
                el("h3", { text: agent.label || agent.name }),
                el("p", { text: agent.role || "No role configured." }),
                el(
                  "div",
                  { className: "tag-row" },
                  (agent.bounded_actions || []).slice(0, 3).map((action) =>
                    el("span", { className: "tag", text: action })
                  )
                ),
              ]),
            ])
          )
        ),
      ]),
      el("aside", { className: "note-panel" }, [
        el("h3", { text: "Safety principle" }),
        el("p", {
          text:
            "Agent가 만든 action은 바로 실행되지 않습니다. namespace, deployment, replica 범위, 위험 명령 여부를 검증한 뒤 mock, dry-run, real 단계를 분리합니다.",
        }),
      ]),
    ]);
  }

  function shortAgent(name) {
    if (name.includes("HA")) return "HA";
    if (name.includes("Application")) return "APP";
    if (name.includes("Infra")) return "INF";
    if (name.includes("Cost")) return "COST";
    return "AG";
  }

  function evidenceSection() {
    const latest = state.latestRun;
    const graphs = latest
      ? (latest.statistics_files || []).filter((path) => path.endsWith(".png")).slice(0, 2)
      : [];
    return el("section", { className: "section two-column", id: "evidence" }, [
      el("div", { className: "evidence-panel" }, [
        sectionHeading("실험 근거", "최근 recovery 실험 결과와 정량 산출물을 논문 근거로 정리합니다."),
        latest
          ? el("div", {}, [
              el("div", { className: "run-summary" }, [
                statusLine("latest run", latest.path),
                statusLine("outcomes", String(latest.outcome_count)),
              ]),
              el("pre", {
                className: "excerpt",
                text:
                  latest.reward_policy_excerpt ||
                  "Reward policy summary has not been generated yet.",
              }),
            ])
          : el("p", {
              className: "muted",
              text: "현재 로컬에는 recovery-action-pilot 결과가 없습니다. 서버에서 실험을 실행하면 이 영역에 결과가 표시됩니다.",
            }),
      ]),
      el("div", { className: "artifact-panel" }, [
        el("h3", { text: "Research artifacts" }),
        docLink("실행 코드 가이드", "docs/submission/execution_code_guide.md"),
        docLink("시험 가이드", "docs/submission/test_guide.md"),
        docLink("Action / Reward 정책", "docs/design/agent_action_reward_policy.md"),
        docLink("정량 분석 가이드", "docs/experiments/recovery_quantitative_analysis_guide.md"),
        graphs.length
          ? el(
              "div",
              { className: "graph-strip" },
              graphs.map((path) => el("img", { src: `/api/artifacts/${path}`, alt: path }))
            )
          : null,
      ]),
    ]);
  }

  function docLink(label, path) {
    return el("a", { className: "doc-link", href: `/api/artifacts/${path}`, target: "_blank" }, [
      el("span", { text: label }),
      el("small", { text: path }),
    ]);
  }

  function safeDemoSection() {
    return el("section", { className: "section demo-section", id: "demo" }, [
      sectionHeading("안전한 4-Agent 판단 데모", "실제 클러스터를 건드리지 않는 mock 모드에서 Agent 합의와 최종 명령을 확인합니다."),
      el("div", { className: "demo-grid" }, [
        el("form", { className: "demo-form", onSubmit: submitMock }, [
          field("Namespace", "namespace"),
          field("Deployment", "deployment"),
          field("Metric", "metric"),
          field("Value", "value", "number"),
          field("Threshold", "threshold", "number"),
          guardSelect(),
          el("button", {
            className: "button primary",
            disabled: state.running,
            text: state.running ? "Running..." : "Generate Decision",
          }),
        ]),
        decisionResult(),
      ]),
    ]);
  }

  function field(label, key, type) {
    return el("label", { className: "field" }, [
      el("span", { text: label }),
      el("input", {
        type: type || "text",
        value: state.form[key],
        onInput: (event) => {
          state.form[key] = event.target.value;
        },
      }),
    ]);
  }

  function guardSelect() {
    return el("label", { className: "field" }, [
      el("span", { text: "Guard backend" }),
      el("select", {
        value: state.form.backend,
        onChange: (event) => {
          state.form.backend = event.target.value;
        },
      }, [
        el("option", { value: "python", text: "Python Validator" }),
        el("option", { value: "go", text: "Go Guard" }),
      ]),
    ]);
  }

  function decisionResult() {
    const reviews = state.mockResult ? state.mockResult.agent_reviews || [] : [];
    return el("div", { className: "decision-panel" }, [
      el("h3", { text: "Agent consensus" }),
      reviews.length
        ? el("table", { className: "decision-table" }, [
            el("thead", {}, [
              el("tr", {}, [
                el("th", { text: "Agent" }),
                el("th", { text: "Decision" }),
                el("th", { text: "Action" }),
                el("th", { text: "Reward" }),
              ]),
            ]),
            el(
              "tbody",
              {},
              reviews.map((review) =>
                el("tr", {}, [
                  el("td", { text: shortAgent(review.agent) }),
                  el("td", { text: review.decision }),
                  el("td", { text: review.action }),
                  el("td", {
                    text:
                      review.reward == null || Number.isNaN(review.reward)
                        ? "-"
                        : Number(review.reward).toFixed(2),
                  }),
                ])
              )
            ),
          ])
        : el("p", {
            className: "muted",
            text: "Generate Decision을 누르면 Agent별 판단 결과가 표시됩니다.",
          }),
      state.mockResult
        ? el("pre", {
            className: "command-box",
            text: JSON.stringify(state.mockResult.result, null, 2),
          })
        : null,
    ]);
  }

  async function submitMock(event) {
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

  function sectionHeading(title, caption) {
    return el("div", { className: "section-heading" }, [
      el("h2", { text: title }),
      caption ? el("p", { text: caption }) : null,
    ]);
  }

  function footer() {
    return el("footer", { className: "site-footer" }, [
      el("span", { text: "AIOps 4-Agent Kubernetes Recovery Research" }),
      el("span", { text: "Real-mode experiments remain CLI-gated for safety." }),
    ]);
  }

  async function boot() {
    root.replaceChildren(
      el("main", { className: "loading" }, [
        el("h1", { text: "AIOps Research Control Plane" }),
        el("p", { text: "연구 상태를 불러오는 중입니다." }),
      ])
    );
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
