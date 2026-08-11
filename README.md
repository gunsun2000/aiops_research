# AIOps 4-Agent Kubernetes 장애 복구 연구

![AIOps 4-Agent architecture](docs/assets/architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 서비스 장애를 판단하고, 안전 검증을 거친 복구 action만 실행하는 AIOps 연구 프로토타입**입니다.

## 공식 연구 문서

교수님·외부 검토자에게 공유하는 문서는 Markdown 원문이 아니라 아래의 Word 문서를 기준으로 합니다.

| 문서 | 용도 |
| --- | --- |
| [AIOps 4-Agent 연구 보고서](docs/deliverables/AIOps_4Agent_Research_Report.docx) | 연구 배경, 아키텍처, 실험 설계, 결과, 한계와 후속 연구 |
| [AIOps 실험 실행 및 검증 가이드](docs/deliverables/AIOps_Experiment_Operations_Guide.docx) | 설치, Control Plane, mock/dry-run/real 실험, 정량 분석 재현 |
| [4-Agent Action 및 Reward 정책 명세서](docs/deliverables/AIOps_Agent_Policy_Specification.docx) | Agent 역할, 합의, action/reward, 승인·거부와 안전 경계 |

Markdown 문서는 코드와 함께 갱신하기 쉬운 기술 원본으로 유지합니다. DOCX는 다음 명령으로 다시 생성할 수 있습니다.

```bash
python -m pip install -e ".[docs]"
python scripts/build_research_documents.py
```

연구의 중심은 다음 장애 감시/복구 흐름입니다.

```text
AIOpsLab / Chaos Mesh 장애 주입
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
-> Action / Reward 교차 검증
-> Python Validator
-> 선택적 Go Guard
-> kubectl mock / dry-run / real 실행
-> 결과 저장 및 정량 분석
```

## 연구 범위

| 구분 | 현재 처리 |
| --- | --- |
| 4-Agent 장애 판단 | 연구 본체 |
| Action / Reward 정책 | 연구 본체 |
| AIOpsLab / Chaos Mesh / Prometheus / Kubernetes 실험 | 연구 본체 |
| Python Validator | 기본 안전 검증 |
| Go Guard | 선택적 이중 안전 검증 |
| Agent Registry | Agent 역할과 허용 action 관리 |
| AutoGen GroupChat | structured multi-agent 보조 경로 |

Agent 등록 정보는 [config/agent_registry.json](config/agent_registry.json)에 있습니다.

## 빠른 실행

Ubuntu 연구실 서버 기준:

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen,ui,docs]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
export PROMETHEUS_URL="http://127.0.0.1:9091"
export AIOPS_AUTO_PORT_FORWARD=auto
export AIOPSLAB_ROOT="$HOME/geonhae/external/AIOpsLab"
export AIOPSLAB_PYTHON="$HOME/anaconda3/envs/aiopslab/bin/python"
export AIOPS_BIND_ADDRESS="127.0.0.1"
# Ubuntu 원격 서버에서 Control Plane이 듣는 포트입니다.
# VS Code Ports 탭에서는 이 포트를 로컬 18181로 전달합니다.
export PORT=18180

aiops-control-plane
```

Control Plane은 시작 시 Kubernetes와 Chaos Mesh를 확인하고, 로컬 Prometheus가
응답하지 않으면 `9091:9090` 포트포워딩을 자동으로 생성합니다. 준비된 외부
AIOpsLab 경로도 함께 확인하므로, 위 사전 환경이 설치되어 있으면 사이드바에
`Kubernetes 연결됨`, `Prometheus 자동 연결됨`, `Chaos Mesh 연결됨`,
`AIOpsLab 연결됨`이 표시됩니다. 플랫폼은 Kubernetes, Chaos Mesh, AIOpsLab을
새로 설치하지는 않습니다.

AutoGen까지 활성화할 때만 API 키를 서버 환경에 별도로 설정합니다. 키를 README나
Git 저장소에 기록하지 마십시오.

```bash
export OPENAI_API_KEY="<your-api-key>"
export AIOPS_OPENAI_MODEL="gpt-5.5"
```

실행 후 연결 상태는 다음 명령으로 확인합니다.

```bash
curl -sS http://127.0.0.1:18180/api/connections | python -m json.tool
```

Windows 로컬 기준:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pytest
```

Go Guard 검증:

```bash
cd go/aiops-guard
go test ./...
```

상세 실행 코드는 [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md)에 정리되어 있습니다.

## Control Plane과 실험 실행 경계

웹 Control Plane은 등록된 장애 시나리오를 영속 Job으로 실행하고, 하나의
`experiment_id` 아래에서 장애 주입, Evidence 수집, 4-Agent 상호감시,
안전 검증, Kubernetes Action, 복구 관찰, cleanup 이벤트를 추적합니다.
Job과 이벤트는 기본적으로
`runs/control-plane/experiment-jobs.sqlite3`에 저장되며, SSE로 화면에
실시간 전달됩니다. 실행 취소는 안전한 단계 경계에서 처리되고 cleanup은 항상
시도합니다. 서버 재시작 시 진행 중이던 Job은 자동 재실행하지 않고
`interrupted`로 표시하여 중복 장애 주입을 방지합니다.

실행 모드는 다음처럼 구분합니다.

| 모드 | Evidence 및 실행 경계 |
| --- | --- |
| `mock` | `FakeEvidenceProvider` 기반 합성 Evidence. Kubernetes를 변경하지 않음 |
| `dry-run` | 실제 대상과 명령을 검증하지만 Kubernetes 상태를 변경하지 않음 |
| `real` | Ubuntu 서버의 Prometheus, Chaos Mesh, Kubernetes를 사용해 제한된 Action을 실행 |

`real` 웹 실행은 서버 환경변수 `CONFIRM_REAL_RUN=YES`와 UI 확인 문구
`EXECUTE REAL EXPERIMENT`가 모두 필요합니다. 이 Gate를 통과해도 등록된
시나리오, allowlist, replica 제한, target lock, Validator와 cleanup 경계는
그대로 적용됩니다. Windows에서 통과한 테스트와 `mock` 결과는 실제 클러스터
실험 근거가 아닙니다.

Control Plane 실행에는 위 `빠른 실행` 블록을 사용합니다. Ubuntu 연구실 서버의
표준 포트는 `18180`이며 `PORT` 환경변수로 변경할 수 있습니다. `18181`은
VS Code Remote SSH에서 원격 `18180`을 Windows로 전달할 때 사용할 로컬 포트입니다.

Ubuntu 서버에서 직접 브라우저를 실행할 때:

```text
http://127.0.0.1:18180/
```

Windows에서 VS Code Remote SSH로 서버에 접속할 때는 VS Code의 Ports 탭에서
원격 포트 `18180`을 전달하고, 로컬 포트는 `18181`로 배정합니다. Ports 탭에
`18180 -> 127.0.0.1:18181`처럼 표시되면 Windows 브라우저에서는 다음 주소로
접속합니다.

```text
http://127.0.0.1:18181/
```

원격 서버에서 `PORT=18181`로 실행하고 VS Code가 원격 `18180`을 전달하도록
두 포트를 섞으면 브라우저가 연결되지 않습니다. 원격은 `18180`, Windows
브라우저는 전달된 `18181`을 사용해야 합니다.

브라우저에서 상태가 갱신되지 않으면 `Ctrl+Shift+R`로 캐시를 새로고침합니다.

상세 UI 가이드는 [docs/submission/control_plane_ui_guide.md](docs/submission/control_plane_ui_guide.md)에,
real runtime 검증 절차는 [docs/experiments/platform_real_runtime_guide.md](docs/experiments/platform_real_runtime_guide.md)에 있습니다.

### 현재 통합 범위

- 완료: core runtime, Prometheus/Kubernetes/Chaos Mesh adapter, lifecycle cleanup
- 완료: SQLite 영속 Job, 백그라운드 실행, SSE replay, 취소, 웹 `mock/dry-run/real` 요청
- 완료: 3영역 연구 콘솔에서 조건, 4-Agent 상호검토, 안전 검사, 결과를 동일 Job으로 표시
- 완료: AutoGen GroupChat을 선택 가능한 Controller로 연결하고 model/controller/transcript를 Job에 저장·표시
- 완료: AIOpsLab detection benchmark를 별도 영속 Job, SSE, 취소, Markdown/CSV 산출물로 연결
- 완료: Recovery Action 비교를 별도 영속 Job으로 실행하고 장애·Action·Reward 정책별 JSONL/CSV/Markdown/PNG/SVG를 자동 생성

AutoGen 웹 Job은 `autogen` 의존성과 `OPENAI_API_KEY`가 준비된 경우에만 활성화됩니다.
의존성이나 credential이 없으면 장애 주입 전에 안전하게 거부합니다. 로컬 자동 시험은
fake provider로 수행하므로 실제 OpenAI 네트워크 호출이나 real Kubernetes AutoGen 실험의
근거가 아닙니다. AIOpsLab 웹 Job도 로컬 fake executor 시험과 Ubuntu의 실제 외부
AIOpsLab 실행을 구분합니다. 실제 benchmark 결과는 외부 저장소와 kubeconfig가 준비된
Ubuntu 서버 실행 및 생성된 report 검토 후에만 연구 근거로 사용합니다.

AIOpsLab 웹 Benchmark를 Ubuntu에서 활성화하려면 Control Plane 시작 전에 서버 소유
경로를 설정합니다. 이 값들은 브라우저 요청으로 변경할 수 없습니다.

```bash
export AIOPSLAB_ROOT="$HOME/geonhae/external/AIOpsLab"
export AIOPSLAB_PYTHON="$HOME/anaconda3/envs/aiopslab/bin/python"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
aiops-control-plane
```

Recovery Action 비교는 웹의 `Recovery Action Comparison`에서 실행합니다.
`Mock`은 4개 장애 × 3개 Action의 분석·그래프 연결을 확인하는 합성 데이터이며,
실제 연구 근거가 아닙니다. Ubuntu `Real`은 다음 환경을 서버에서 준비한 뒤
`EXECUTE REAL COMPARISON` 확인 문구를 입력해야 시작됩니다.

```bash
export CONFIRM_REAL_RUN=YES
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
export PROMETHEUS_URL="http://127.0.0.1:9091"
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
aiops-control-plane
```

Real 비교는 4개 장애 × 3개 Action × 반복 횟수이며, 취소 요청은 현재
treatment의 cleanup이 끝난 안전한 경계에서 적용됩니다.

## 핵심 실험

Autonomous mock 확인:

```bash
aiops-k8s-agents autonomous-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

4-Agent 상호감시 mock 실험:

```bash
aiops-k8s-agents mutual-supervision-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

### Protocol profile selection

Protocol profiles are discovered only from `config/protocol_profiles` and are
selected by registered ID. File paths and path traversal are not accepted.

```bash
aiops-k8s-agents list-protocol-profiles

aiops-k8s-agents mutual-supervision-run \
  --mode mock \
  --protocol-profile four-agent-role-veto-v1 \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice \
  --no-save
```
