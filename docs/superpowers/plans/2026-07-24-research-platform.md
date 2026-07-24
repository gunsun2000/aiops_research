# AIOps Research Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 긴 단일 페이지 UI를 사이드바 기반의 독립 화면형 AIOps 연구 운영 플랫폼으로 재구성한다.

**Architecture:** 기존 FastAPI API와 정적 파일 배포 방식은 유지한다. 브라우저의 hash route를 단일 상태로 관리하고, route별 view renderer가 중앙 workspace 하나를 교체한다.

**Tech Stack:** FastAPI, vanilla JavaScript, CSS Grid/Flexbox, pytest, Chrome headless rendering

## Global Constraints

- 실제 Kubernetes real action은 UI에서 실행하지 않는다.
- 기존 `/api/mock-alert`의 mock 판단 기능과 기존 CLI를 유지한다.
- 외부 JavaScript/CSS 의존성을 추가하지 않는다.
- 모든 사용자 표시 문구는 UTF-8 한글로 작성한다.

---

### Task 1: 멀티뷰 라우팅 계약

**Files:**
- Create: `tests/test_control_plane_ui.py`
- Modify: `ui/control_plane_static/app.js`

**Interfaces:**
- Consumes: `window.location.hash`, 기존 `/api/overview`, `/api/agents`, `/api/runs/latest`
- Produces: `ROUTES`, `currentRoute()`, `navigate()`, `workspaceView()`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_control_plane_uses_independent_hash_routes():
    source = Path("ui/control_plane_static/app.js").read_text(encoding="utf-8")
    for route in ("dashboard", "experiments", "decision", "safety", "evidence", "documents"):
        assert f'"#/{route}"' in source
    assert '"#overview"' not in source
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: FAIL because the current navigation uses section anchors.

- [ ] **Step 3: route 기반 workspace 구현**

`ROUTES`에 여섯 route를 선언하고, sidebar click과 `hashchange`가 중앙
`workspaceView()`를 다시 렌더링하도록 구현한다.

- [ ] **Step 4: 테스트 확인**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: PASS

### Task 2: 화면별 연구 플랫폼 구성

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`

**Interfaces:**
- Consumes: `state.overview`, `state.agents`, `state.latestRun`, `state.mockResult`
- Produces: `dashboardView()`, `experimentsView()`, `decisionView()`, `safetyView()`, `evidenceView()`, `documentsView()`

- [ ] **Step 1: 화면 구성 테스트 확장**

각 route label과 화면 renderer가 정적 소스에 존재하고, 기존의 단일 `hero()` 기반
레이아웃이 제거되는지 검사한다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: FAIL because the route views do not exist yet.

- [ ] **Step 3: 여섯 화면 구현**

대시보드는 상태와 연구 흐름만 표시하고, 실험·판단·안전·결과·문서는 각각 별도
renderer로 분리한다. Agent 판단 폼은 기존 `runMock()`을 그대로 사용한다.

- [ ] **Step 4: 전문적인 운영 콘솔 CSS 구현**

고정 사이드바, workspace header, 상태 strip, 표, scenario grid, pipeline flow,
mobile navigation을 구현하고 모든 요소에 안정적인 최소 너비와 반응형 규칙을 둔다.

- [ ] **Step 5: 테스트 확인**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: PASS

### Task 3: 전체 검증과 시각 점검

**Files:**
- Verify: `ui/control_plane_static/app.js`
- Verify: `ui/control_plane_static/styles.css`

**Interfaces:**
- Consumes: 실행 중인 `aiops-control-plane`
- Produces: 정상 API/브라우저 렌더링 증거

- [ ] **Step 1: 정적 문법 및 전체 테스트**

Run:

```powershell
node --check ui/control_plane_static/app.js
python -m pytest
cd go/aiops-guard
go test ./...
```

Expected: all commands exit with status 0.

- [ ] **Step 2: API 확인**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:18080/healthz
Invoke-RestMethod http://127.0.0.1:18080/api/overview
```

Expected: service health is `ok` and overview JSON is returned.

- [ ] **Step 3: 화면 렌더링 확인**

Chrome headless로 `#/dashboard`, `#/decision`, `#/evidence`를 1920x1080과
390x844에서 캡처하고 겹침, 잘림, 빈 화면이 없는지 확인한다.

