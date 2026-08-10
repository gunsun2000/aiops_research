# Reference-Faithful Research Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 참고 이미지 5장의 정보 구조와 시각적 명확성을 현재 4-Agent AIOps 연구 플랫폼에 적용하면서 기존 API, Job, SSE, 안전 경계와 실제 데이터 표시 원칙을 유지한다.

**Architecture:** 기존 `index.html`의 화면 구분과 DOM ID를 유지하고, `styles.css`를 공통 토큰·레이아웃·화면별 스타일로 정리한다. `reference-ui.js`는 화면 전환, 결과 탭, 상세 화면과 AIOpsLab 프레젠테이션을 담당하며, `app.js`는 기존 실험 실행과 API 상태 관리의 권위 있는 구현으로 유지한다. 후처리 스크립트는 필요한 데이터 보강만 수행하고 정적 예시 값은 생성하지 않는다.

**Tech Stack:** HTML5, CSS3, Vanilla JavaScript, FastAPI static hosting, pytest source-contract tests, in-app browser visual QA

## Global Constraints

- 기존 Python API, Experiment Job, SSE, cancel, Real confirmation Gate를 변경하지 않는다.
- 연결 상태와 연구 수치는 백엔드 응답 또는 저장된 실험 결과만 표시한다.
- Mock, Dry-run, Real을 시각적으로 구분하고 합성 데이터를 Real 결과처럼 표현하지 않는다.
- 주요 화면은 시스템 개요, 복구 실험, AIOpsLab Benchmark, 실험 결과, 실험 상세 다섯 개다.
- 1440x900, 1920x1080, 390x844에서 텍스트 겹침과 잘림이 없어야 한다.
- 기존 `ai-ops/`와 `tmp/`는 수정하거나 Git에 포함하지 않는다.

---

### Task 1: UI 구조 계약 강화

**Files:**
- Modify: `tests/test_complete_research_console_ui.py`
- Modify: `tests/test_control_plane_ui.py`
- Modify: `ui/control_plane_static/index.html`

**Interfaces:**
- Consumes: 기존 `data-view`, `data-view-panel`, 주요 DOM ID
- Produces: 화면별 명시적 레이아웃 클래스와 실제 데이터용 빈 상태 컨테이너

- [ ] **Step 1: 참고 화면 계약 테스트 추가**

```python
def test_reference_console_has_clear_page_actions_and_workspace_sections():
    html = source(INDEX)
    for marker in (
        "overview-status-strip",
        "reference-recovery-setup",
        "aiopslab-reference-grid",
        "results-reference-grid",
        "detail-reference-layout",
    ):
        assert marker in html
    assert "선택된 실험 요약" in html
    assert "시스템 연결 상태" in html
```

- [ ] **Step 2: 테스트가 기존 구조의 부족한 부분을 검출하는지 확인**

Run: `python -m pytest tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py -q`

Expected: 새 요구사항과 불일치하는 항목이 있으면 FAIL

- [ ] **Step 3: `index.html` 화면 구조 정리**

각 화면에 다음 구조를 사용한다.

```html
<section class="view-panel" data-view-panel="experiment">
  <header class="page-heading recovery-header">...</header>
  <div class="reference-recovery-setup">
    <section class="recovery-main">...</section>
    <aside class="surface selected-summary">...</aside>
  </div>
</section>
```

손상된 아이콘 문자열은 의미 있는 텍스트 또는 CSS 기반 아이콘으로 교체하고, 모든 버튼·탭·폼에 접근 가능한 이름을 유지한다.

- [ ] **Step 4: 구조 계약 테스트 통과 확인**

Run: `python -m pytest tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py -q`

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add ui/control_plane_static/index.html tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py
git commit -m "refactor: clarify research console screen structure"
```

### Task 2: 공통 디자인 시스템과 반응형 셸 정리

**Files:**
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: Task 1의 화면 클래스
- Produces: sidebar, surface, buttons, badges, responsive grid의 권위 있는 스타일

- [ ] **Step 1: 스타일 계약 테스트 추가**

```python
def test_reference_shell_uses_stable_workspace_dimensions():
    css = _compact(_source(STYLES_CSS))
    assert "--sidebar-width:252px" in css
    assert "max-width:1560px" in css
    assert "grid-template-columns:var(--sidebar-width)minmax(0,1fr)" in css
    assert "@media(max-width:760px)" in css
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_control_plane_ui.py::test_reference_shell_uses_stable_workspace_dimensions -q`

Expected: FAIL

- [ ] **Step 3: CSS 토큰과 셸 구현**

```css
:root {
  --sidebar-width: 252px;
  --navy: #06264f;
  --navy-deep: #031b39;
  --blue: #0b5de8;
  --surface: #ffffff;
  --canvas: #f4f7fb;
  --line: #d9e2ef;
  --radius: 8px;
}

.platform-shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  min-height: 100vh;
}

.view-panel {
  width: min(100%, 1560px);
  margin: 0 auto;
}
```

사이드바와 본문의 대비, 선택 상태, 버튼 크기, 테이블 행 높이, 스크롤 영역을 참고 이미지에 맞춘다. `font-size`를 viewport 단위로 조절하지 않는다.

- [ ] **Step 4: 데스크톱·모바일 스타일 계약 확인**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add ui/control_plane_static/styles.css tests/test_control_plane_ui.py
git commit -m "style: refine research console workspace"
```

### Task 3: 시스템 개요와 복구 실험 렌더링 명확화

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/stage-flow-ui.js`
- Modify: `tests/test_complete_research_console_ui.py`

**Interfaces:**
- Consumes: `/api/connections`, `/api/experiments`, Experiment SSE events
- Produces: 실제 연결 상태, 8단계 진행, Agent 판단, 선택 요약

- [ ] **Step 1: 실제 상태만 표시하는 테스트 강화**

```python
def test_overview_and_recovery_use_runtime_data_without_reference_numbers():
    scripts = source(APP) + source(REFERENCE) + source(FLOW)
    for fabricated in ("14.32", "4.12", "0.842", "0.901"):
        assert fabricated not in scripts
    assert "/api/connections" in scripts
    assert "post_execution_reviews" in scripts
```

- [ ] **Step 2: 테스트 실행**

Run: `python -m pytest tests/test_complete_research_console_ui.py -q`

Expected: PASS 또는 새 계약 불일치 시 FAIL

- [ ] **Step 3: 개요 렌더링 함수 분리**

다음 책임을 명시적으로 유지한다.

```javascript
function renderOverviewContext(job) {}
function renderOverviewStages(job, events) {}
function renderOverviewAgents(report) {}
function renderOverviewResult(job) {}
```

진행 상태는 `queued`, `running`, `completed`, `blocked`, `failed`, `cancelled`를 서로 다른 배지로 표현한다.

- [ ] **Step 4: 복구 설정과 실행 화면 전환 정리**

시나리오·Controller·Mode 선택 시 우측 요약을 즉시 갱신한다. AutoGen이 준비되지 않았으면 선택 카드에 API 설정 사유를 표시한다. 실행 시 설정 화면을 숨기지 않고, 아래 실행 진행 영역을 확장하여 단계와 로그를 보여준다.

- [ ] **Step 5: UI 계약 테스트 확인**

Run: `python -m pytest tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py -q`

Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add ui/control_plane_static/app.js ui/control_plane_static/reference-ui.js ui/control_plane_static/stage-flow-ui.js tests/test_complete_research_console_ui.py
git commit -m "feat: clarify live recovery experiment workflow"
```

### Task 4: AIOpsLab, 결과 목록, 상세 화면 정돈

**Files:**
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/research-console-polish.js`
- Modify: `ui/control_plane_static/bulk-delete-ui.js`
- Modify: `tests/test_complete_research_console_ui.py`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: `/api/benchmarks/aiopslab`, `/api/benchmarks/aiopslab/jobs`, `/api/experiments`
- Produces: benchmark 3탭, 결과 필터·통계, 상세 6탭

- [ ] **Step 1: 데이터 경계 테스트 추가**

```python
def test_results_and_benchmark_render_only_supported_metrics():
    scripts = source(REFERENCE) + source(POLISH)
    for metric in ("Accuracy", "Average TTD", "Average Steps", "Average Reward"):
        assert metric in scripts
    assert "저장된 실제 Benchmark Job 결과만 집계합니다." in scripts
```

- [ ] **Step 2: 중복 후처리 제거 테스트 추가**

```python
def test_reference_rendering_is_event_driven_without_broad_observers():
    for path in (REFERENCE, POLISH, BULK):
        assert "MutationObserver" not in source(path)
```

- [ ] **Step 3: AIOpsLab 화면 정리**

평가, 비교, 이력 탭이 동일한 catalog와 persisted job 데이터를 사용하게 한다. 지표가 없으면 `—`와 설명을 표시하고 임의 값을 만들지 않는다.

- [ ] **Step 4: 결과와 상세 화면 정리**

결과 목록은 필터, 페이지네이션, 삭제, 상세 열기를 유지한다. 상세 화면은 요약·타임라인·Agent·Evidence·로그·이벤트 탭을 같은 `experiment_id`로 렌더링한다.

- [ ] **Step 5: 관련 테스트 통과 확인**

Run: `python -m pytest tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py tests/test_experiment_result_deletion.py -q`

Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add ui/control_plane_static/reference-ui.js ui/control_plane_static/research-console-polish.js ui/control_plane_static/bulk-delete-ui.js tests/test_complete_research_console_ui.py tests/test_control_plane_ui.py
git commit -m "feat: refine benchmark and result workspaces"
```

### Task 5: 전체 검증과 문서 갱신

**Files:**
- Modify: `docs/submission/control_plane_ui_guide.md`
- Test: `tests/test_control_plane_web.py`
- Test: `tests/test_complete_research_console_ui.py`

**Interfaces:**
- Consumes: Tasks 1-4 전체 구현
- Produces: 검증된 UI와 실행 가이드

- [ ] **Step 1: UI 가이드 갱신**

다섯 화면의 목적, 실제 데이터 경계, Mock/Dry-run/Real 구분과 실행 방법을 현재 화면 명칭에 맞춘다.

- [ ] **Step 2: Python 전체 테스트**

Run: `python -m pytest`

Expected: 0 failures

- [ ] **Step 3: Go Guard 테스트**

Run: `cd go/aiops-guard && go test ./...`

Expected: PASS

- [ ] **Step 4: 로컬 서버 시작**

Run: `aiops-k8s-agents control-plane-web --host 127.0.0.1 --port 18180`

Expected: `http://127.0.0.1:18180/` 응답

- [ ] **Step 5: 브라우저 시각 검증**

다음 화면을 1440x900, 1920x1080, 390x844에서 확인한다.

```text
#overview
#experiment
#aiopslab
#analysis
#history
```

각 화면에서 겹침, 잘림, 비어 있는 아이콘, 콘솔 오류가 없어야 한다. Mock 실험 1회를 실행하고 결과 상세까지 같은 `experiment_id`로 연결되는지 확인한다.

- [ ] **Step 6: 최종 커밋**

```bash
git add docs/submission/control_plane_ui_guide.md
git commit -m "docs: update research console usage guide"
```

- [ ] **Step 7: 원격 브랜치 푸시**

```bash
git push -u origin codex/reference-faithful-console-redesign
```
