(function () {
  const root = document.getElementById("root");
  const state = {
    overview: null,
    agents: [],
    latestRun: null,
    mockResult: null,
    errors: [],
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

  function node(tag, attrs, children) {
    const element = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "className") element.className = value;
      else if (key === "text") element.textContent = value;
      else if (key === "html") element.innerHTML = value;
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
      element.appendChild(
        typeof child === "string" ? document.createTextNode(child) : child
      );
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
    return node("div", { className: "shell" }, [
      sidebar(),
      node("main", { className: "main" }, [
        header(),
        metricStrip(),
        architecturePanel(),
        node("section", { className: "section grid columns-2 wide-left" }, [
          agentsPanel(),
          statusPanel(),
        ]),
        node("section", { className: "section grid columns-2" }, [
          operationPanel(),
          consensusPanel(),
        ]),
        resultsPanel(),
        footerNote(),
      ]),
    ]);
  }

  function sidebar() {
    const items = [
      ["Overview", "연구 구조"],
      ["Agents", "4-Agent 역할"],
      ["Safety", "안전 검증"],
      ["Evidence", "실험 근거"],
      ["Artifacts", "논문 자료"],
    ];
    return node("aside", { className: "sidebar" }, [
      node("div", { className: "brand-mark", text: "AI-MCMP" }),
      node("h2", { className: "brand-title", text: "AIOps Research Control Plane" }),
      node("p", {
        className: "brand-subtitle",
        text:
          "4-Agent 기반 Kubernetes 장애 대응 연구를 시연하고, 실험 근거를 한 곳에서 확인하는 인터페이스입니다.",
      }),
      node(
        "nav",
        { className: "nav-section" },
        items.map(([en, ko], index) =>
          node("div", { className: `nav-item ${index === 0 ? "active" : ""}` }, [
            node("span", { text: en }),
            node("small", { text: ko }),
          ])
        )
      ),
      node("div", { className: "side-note" }, [
        node("strong", { text: "Research boundary" }),
        node("p", {
          text:
            "Real 제어는 CLI에서 명시적으로 실행하고, 이 화면은 연구 설명, mock 판단, 결과 조회를 중심으로 제공합니다.",
        }),
      ]),
    ]);
  }

  function header() {
    const ready = Object.values((state.overview && state.overview.health) || {}).filter(Boolean).length;
    const total = Object.keys((state.overview && state.overview.health) || {}).length || 4;
    return node("section", { className: "topbar" }, [
      node("div", {}, [
        node("div", { className: "eyebrow", text: "Graduate Research Prototype" }),
        node("h1", { text: "Safety-Bounded 4-Agent AIOps Framework" }),
        node("p", {
          className: "lead",
          text:
            "장애 주입, 관측 데이터, 역할 기반 Agent 판단, 이중 안전 검증, Kubernetes 복구 실행, 정량 분석을 하나의 연구 프레임워크로 묶었습니다.",
        }),
      ]),
      node("div", { className: "status-stack" }, [
        statusPill("Repository", "Ready"),
        statusPill("Evidence files", `${ready}/${total}`),
        statusPill("UI mode", "safe mock"),
      ]),
    ]);
  }

  function statusPill(label, value) {
    return node("div", { className: "status-pill" }, [
      node("span", { text: label }),
      node("span", {}, [node("i", { className: "dot" }), document.createTextNode(` ${value}`)]),
    ]);
  }

  function metricStrip() {
    const scenarios = state.overview ? state.overview.scenarios.length : 4;
    const actions = state.overview ? state.overview.actions.length : 3;
    const latestCount = state.latestRun ? state.latestRun.outcome_count : 0;
    const metrics = [
      ["Agents", "4", "HA / App / Infra / Cost"],
      ["Fault scenarios", String(scenarios), "Chaos Mesh 기반"],
      ["Bounded actions", String(actions), "Observe / Restart / Scale"],
      ["Latest records", String(latestCount), "JSONL 실험 근거"],
    ];
    return node(
      "section",
      { className: "grid columns-4 section" },
      metrics.map(([label, value, caption]) =>
        node("div", { className: "panel metric-card" }, [
          node("div", { className: "metric-label", text: label }),
          node("div", { className: "metric-value", text: value }),
          node("div", { className: "metric-caption", text: caption }),
        ])
      )
    );
  }

  function architecturePanel() {
    const steps = [
      ["1", "장애 주입", "AIOpsLab / Chaos Mesh"],
      ["2", "상태 관측", "Prometheus / K8s snapshot"],
      ["3", "Agent 판단", "4개 역할별 action 검토"],
      ["4", "교차 합의", "Action / reward 기반 조정"],
      ["5", "안전 검증", "Python Validator + optional Go Guard"],
      ["6", "피드백", "JSONL / CSV / graph 분석"],
    ];
    return node("section", { className: "panel pad section" }, [
      sectionTitle("전체 프레임워크 흐름", "장애 대응 판단이 어디에서 생성되고, 어디에서 차단되며, 어떤 결과로 남는지 보여줍니다."),
      node(
        "div",
        { className: "pipeline" },
        steps.map(([num, title, copy]) =>
          node("div", { className: "pipeline-step" }, [
            node("div", { className: "step-index", text: num }),
            node("div", { className: "step-title", text: title }),
            node("div", { className: "step-copy", text: copy }),
          ])
        )
      ),
      node("div", { className: "architecture-band" }, [
        bandItem("Input", "metric / log / event"),
        bandItem("Reasoning", "Coordinator + 4-Agent"),
        bandItem("Boundary", "allowlist / replica limit / command validation"),
        bandItem("Evidence", "run report / statistics / policy ranking"),
      ]),
    ]);
  }

  function bandItem(label, value) {
    return node("div", { className: "band-item" }, [
      node("span", { text: label }),
      node("strong", { text: value }),
    ]);
  }

  function sectionTitle(title, caption) {
    return node("div", { className: "section-title-row" }, [
      node("div", {}, [
        node("h2", { className: "panel-title", text: title }),
        caption ? node("p", { className: "section-caption", text: caption }) : null,
      ]),
    ]);
  }

  function agentsPanel() {
    return node("section", { className: "panel pad" }, [
      sectionTitle("4-Agent 역할 구조", "각 Agent는 독립 역할과 허용 action을 갖고, 최종 조치는 합의와 안전 검증 후에만 실행됩니다."),
      node(
        "div",
        { className: "agent-list" },
        state.agents.map((agent) =>
          node("article", { className: "agent-row" }, [
            node("div", { className: "agent-initial", text: shortAgent(agent.name) }),
            node("div", { className: "agent-body" }, [
              node("div", { className: "agent-name", text: agent.label || agent.name }),
              node("div", { className: "agent-role", text: agent.role || "role is not configured" }),
              node(
                "div",
                { className: "tag-row" },
                (agent.bounded_actions || []).slice(0, 4).map((action) =>
                  node("span", { className: "tag", text: action })
                )
              ),
            ]),
          ])
        )
      ),
    ]);
  }

  function shortAgent(name) {
    if (name.includes("HA")) return "HA";
    if (name.includes("Application")) return "APP";
    if (name.includes("Infra")) return "INF";
    if (name.includes("Cost")) return "CST";
    return "AG";
  }

  function statusPanel() {
    const health = (state.overview && state.overview.health) || {};
    const rows = [
      ["Agent Registry", health.agent_registry],
      ["Recovery Config", health.recovery_config],
      ["Chaos Manifests", health.chaos_manifests],
      ["Runs Directory", health.runs_dir],
    ];
    return node("section", { className: "panel pad" }, [
      sectionTitle("연구 산출물 상태", "실험 재현에 필요한 설정, 장애 manifest, 실행 결과 폴더를 확인합니다."),
      node(
        "table",
        { className: "decision-table" },
        [
          node("thead", {}, [
            node("tr", {}, [
              node("th", { text: "Item" }),
              node("th", { text: "Status" }),
            ]),
          ]),
          node(
            "tbody",
            {},
            rows.map(([label, ok]) =>
              node("tr", {}, [
                node("td", { text: label }),
                node("td", {}, [
                  node("span", {
                    className: ok ? "status-text ok" : "status-text warn",
                    text: ok ? "available" : "missing",
                  }),
                ]),
              ])
            )
          ),
        ]
      ),
      docsLinks(),
    ]);
  }

  function docsLinks() {
    const links = [
      ["실행 가이드", "docs/submission/execution_code_guide.md"],
      ["시험 가이드", "docs/submission/test_guide.md"],
      ["Agent 정책", "docs/design/agent_action_reward_policy.md"],
      ["정량 분석", "docs/experiments/recovery_quantitative_analysis_guide.md"],
    ];
    return node(
      "div",
      { className: "doc-links" },
      links.map(([label, path]) =>
        node("a", { href: `/api/artifacts/${path}`, target: "_blank", rel: "noreferrer" }, [
          node("span", { text: label }),
          node("small", { text: path }),
        ])
      )
    );
  }

  function operationPanel() {
    return node("section", { className: "panel pad" }, [
      sectionTitle("Controlled 4-Agent Decision", "실제 클러스터를 건드리지 않는 mock 모드에서 Agent 판단과 최종 명령을 확인합니다."),
      node("div", { className: "form-grid" }, [
        field("Namespace", "namespace"),
        field("Deployment", "deployment"),
        field("Metric", "metric"),
        field("Value", "value", "number"),
        field("Threshold", "threshold", "number"),
        guardSelect(),
      ]),
      node("div", { className: "button-row" }, [
        node("button", {
          className: "primary-button",
          disabled: state.running,
          onClick: runMockDecision,
          text: state.running ? "Running decision..." : "Generate 4-Agent Decision",
        }),
        node("button", {
          className: "secondary-button",
          disabled: true,
          text: "Real mode is CLI-gated",
        }),
      ]),
      state.mockResult
        ? node("pre", {
            className: "result-box section",
            text: JSON.stringify(state.mockResult.result, null, 2),
          })
        : node("p", {
            className: "helper-text",
            text: "기본 입력은 안전한 smoke test입니다. real 실행은 별도 CLI와 명시 확인 절차에서 수행합니다.",
          }),
    ]);
  }

  function field(label, key, type) {
    return node("label", { className: "field" }, [
      node("span", { text: label }),
      node("input", {
        type: type || "text",
        value: state.form[key],
        onInput: (event) => {
          state.form[key] = event.target.value;
        },
      }),
    ]);
  }

  function guardSelect() {
    return node("label", { className: "field" }, [
      node("span", { text: "Guard backend" }),
      node("select", {
        value: state.form.backend,
        onChange: (event) => {
          state.form.backend = event.target.value;
        },
      }, [
        node("option", { value: "python", text: "Python Validator" }),
        node("option", { value: "go", text: "Go Guard" }),
      ]),
    ]);
  }

  async function runMockDecision() {
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
        result: {
          valid: false,
          stderr: String(error.message || error),
        },
        agent_reviews: [],
      };
    } finally {
      state.running = false;
      render();
    }
  }

  function consensusPanel() {
    const reviews = state.mockResult ? state.mockResult.agent_reviews || [] : [];
    return node("section", { className: "panel pad" }, [
      sectionTitle("Consensus and Safety Boundary", "Agent별 decision, action, reward를 분리해서 보여줍니다."),
      reviews.length
        ? node("table", { className: "decision-table" }, [
            node("thead", {}, [
              node("tr", {}, [
                node("th", { text: "Agent" }),
                node("th", { text: "Decision" }),
                node("th", { text: "Action" }),
                node("th", { text: "Reward" }),
              ]),
            ]),
            node(
              "tbody",
              {},
              reviews.map((review) =>
                node("tr", {}, [
                  node("td", { text: review.agent }),
                  node("td", { text: review.decision }),
                  node("td", { text: review.action }),
                  node("td", {
                    text:
                      review.reward == null || Number.isNaN(review.reward)
                        ? "-"
                        : Number(review.reward).toFixed(2),
                  }),
                ])
              )
            ),
          ])
        : node("div", { className: "empty-state" }, [
            node("strong", { text: "No decision generated yet" }),
            node("p", { text: "왼쪽에서 mock 판단을 실행하면 4개 Agent의 합의 결과가 표시됩니다." }),
          ]),
      safetyList(),
    ]);
  }

  function safetyList() {
    const items = [
      "namespace / deployment allowlist",
      "replica min-max bound",
      "dangerous command rejection",
      "mock, dry-run, real mode separation",
    ];
    return node(
      "div",
      { className: "safety-list" },
      items.map((item) => node("span", { text: item }))
    );
  }

  function resultsPanel() {
    const latest = state.latestRun;
    const graphs = latest
      ? (latest.statistics_files || []).filter((path) => path.endsWith(".png")).slice(0, 4)
      : [];
    return node("section", { className: "section grid columns-2" }, [
      node("div", { className: "panel pad" }, [
        sectionTitle("Latest Recovery Experiment", "최근 recovery-action-pilot 결과와 reward policy ranking을 확인합니다."),
        latest
          ? node("div", {}, [
              node("div", { className: "run-meta" }, [
                node("span", { text: latest.path }),
                node("strong", { text: `${latest.outcome_count} outcomes` }),
              ]),
              node("pre", {
                className: "markdown-excerpt section",
                text:
                  latest.reward_policy_excerpt ||
                  "Reward policy summary has not been generated yet.",
              }),
            ])
          : node("p", { className: "lead", text: "아직 recovery-action-pilot 실행 결과가 없습니다." }),
      ]),
      node("div", { className: "panel pad" }, [
        sectionTitle("Quantitative Artifacts", "성공률, 복구 시간, reward 차이를 논문용 근거로 정리합니다."),
        graphs.length
          ? node(
              "div",
              { className: "graph-list" },
              graphs.map((path) =>
                node("figure", { className: "graph-card" }, [
                  node("img", { src: `/api/artifacts/${path}`, alt: path }),
                  node("figcaption", { className: "graph-caption", text: path }),
                ])
              )
            )
          : node("p", {
              className: "lead",
              text: "scripts/server_recovery_statistics.sh 실행 후 PNG/SVG/CSV/JSON 결과가 표시됩니다.",
            }),
      ]),
    ]);
  }

  function footerNote() {
    return node("p", {
      className: "footer-note",
      text:
        "이 UI는 연구 설명과 안전한 mock 판단 확인을 위한 Control Plane입니다. 실제 Kubernetes real 실험은 README의 CLI 절차와 명시적 확인 변수를 통해 수행합니다.",
    });
  }

  async function boot() {
    root.replaceChildren(
      node("main", { className: "main" }, [
        node("section", { className: "panel pad loading-panel" }, [
          node("h1", { text: "AIOps Research Control Plane" }),
          node("p", { className: "lead", text: "연구 상태와 실험 근거를 불러오는 중입니다." }),
        ]),
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
      state.errors.push(String(error.message || error));
    }
    render();
  }

  boot();
})();
