# 설치와 실행 가이드

이 문서는 프로젝트를 처음 보는 사람이 **무엇을 설치하고, 어떤 환경에서, 어떤 명령을 실행해야 하는지** 헷갈리지 않도록 정리한 가이드입니다.

## 1. 이 프로젝트가 하는 일

이 저장소는 AIOpsLab 자체가 아니라, AIOpsLab과 Kubernetes 위에서 동작하는 **4-agent AIOps 자동 감시/관리 모듈**입니다.

전체 흐름은 아래와 같습니다.

```text
AIOpsLab / Kubernetes 장애 상태
-> logs / metrics / alerts 수집
-> 4개 에이전트가 역할별 판단
-> action/reward 기반 합의
-> Referee / Validator 안전 검증
-> AIOpsLab API 또는 kubectl action 실행
-> 결과를 JSON / CSV / Markdown으로 저장
```

현재 초기 연구 검증 단계에서는 두 종류의 실험을 사용합니다.

| 실험 | 성격 | 목적 |
| --- | --- | --- |
| CPU 95% synthetic alert | 사람이 만든 가짜 alert | Kubernetes `scale deployment` action 생성과 검증 |
| AIOpsLab Hotel Reservation detection | AIOpsLab 공식 장애 주입 | 실제 fault injection 환경에서 4-agent 자동 탐지 검증 |

## 2. 폴더 구조

| 경로 | 의미 |
| --- | --- |
| `src/aiops_k8s_agents/` | 우리 4-agent AIOps 코드 |
| `tests/` | pytest 자동 검증 코드 |
| `scripts/` | 로컬/서버 실행 스크립트 |
| `k8s/` | kind, Prometheus, Chaos Mesh 관련 Kubernetes yaml |
| `docs/` | 연구 설명, 설치, 실행, 결과 정리 문서 |
| `runs/` | 실험 결과 JSON/CSV/Markdown 저장 폴더, GitHub에는 올리지 않음 |
| `external/AIOpsLab/` | Microsoft AIOpsLab 외부 코드, GitHub에는 올리지 않음 |

`src/aiops_k8s_agents/` 안의 4대 에이전트 구조는 아래처럼 나누었습니다.

| 파일 | 담당 |
| --- | --- |
| `ha_agent.py` | AI서비스 HA 지원 에이전트. 장애 위험과 HA 복구 필요성 판단 |
| `application_agent.py` | AI응용관리 자동화 에이전트. 실제 Kubernetes 응용 제어 액션 생성 |
| `infra_agent.py` | AI반도체 인프라 운용 자동화 에이전트. GPU/NPU/인프라 용량 관점 검토 |
| `cost_agent.py` | 비용 최적화 지원 에이전트. 자원 증가가 비용 정책 안에 있는지 검토 |
| `coordinator.py` | AI-MCMP 통합 관리 에이전트. 4대 에이전트 결정을 모아 최종 실행 여부 결정 |
| `agent_decision.py` | 각 에이전트가 내는 action, reward, 승인 여부 구조체 |
| `agents.py` | 예전 import 경로를 유지하기 위한 호환용 입구 |

중요한 구분:

```text
aiops_research
= 우리 프로젝트 코드
= GitHub에 올라가는 저장소

external/AIOpsLab
= 외부 Microsoft AIOpsLab 코드
= 서버에 따로 clone해서 사용
= 우리 GitHub에는 올리지 않음
```

## 3. conda 환경 차이

서버에서는 Python 환경을 3개로 나눠서 생각하면 됩니다.

| 환경 | 뜻 | 주로 하는 일 |
| --- | --- | --- |
| `(base)` | Anaconda 기본 환경 | `cd`, `ls`, `git pull` 같은 일반 작업 |
| `(aiops_research)` | 우리 프로젝트 실행 환경 | `pytest`, `aiops-k8s-agents run`, AutoGen 실험 |
| `(aiopslab)` | AIOpsLab 공식 코드 실행 환경 | `python cli.py`, AIOpsLab 자동 runner |

핵심만 외우면 아래와 같습니다.

```text
우리 코드만 돌릴 때
-> conda activate aiops_research

AIOpsLab과 같이 돌릴 때
-> conda activate aiopslab
```

명령별 권장 환경:

| 하고 싶은 일 | 환경 | 명령 예시 |
| --- | --- | --- |
| 우리 코드 테스트 | `aiops_research` | `python -m pytest` |
| CPU 95% synthetic alert | `aiops_research` | `aiops-k8s-agents run ...` |
| AutoGen GroupChat | `aiops_research` | `aiops-k8s-agents autogen-run ...` |
| AIOpsLab 공식 CLI | `aiopslab` | `python cli.py` |
| AIOpsLab 자동 detection | `aiopslab` | `bash scripts/server_aiopslab_auto_detection.sh` |
| AIOpsLab 반복 실험 | `aiopslab` | `RUNS=3 ... bash scripts/server_aiopslab_repeat_detection.sh` |

## 4. VSCode Python 선택 창이 뜰 때

VSCode에서 아래와 같은 창이 뜰 수 있습니다.

```text
환경 관리자 선택
- 빠리 만들기 venv
- venv
- Global
- Conda
- 인터프리터 경로 입력
```

이 창은 pip 설치 창이 아니라, **VSCode 편집기가 어떤 Python을 사용할지 고르는 창**입니다.

서버에서 AIOpsLab 실험 중이면:

```text
Conda 선택
-> aiopslab 선택
```

직접 경로를 넣어야 하면:

```text
/home/ubuntu216/anaconda3/envs/aiopslab/bin/python
```

우리 프로젝트 테스트용이면:

```text
Conda 선택
-> aiops_research 선택
```

직접 경로:

```text
/home/ubuntu216/anaconda3/envs/aiops_research/bin/python
```

이미 터미널 프롬프트가 `(aiopslab)` 또는 `(aiops_research)`로 되어 있으면, 터미널 명령은 그 환경에서 실행됩니다.

## 5. 로컬 Windows 설치

로컬 Windows에서는 주로 코드 수정, unit test, mock/dry-run 실험을 합니다.

```powershell
cd C:\Users\geonhae\Documents\aiops_research
```

PowerShell에서 가상환경 실행이 막히면 현재 터미널에만 실행 권한을 열어줍니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

가상환경을 켭니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

패키지를 설치합니다.

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev,autogen]"
```

검증:

```powershell
python -m pytest
```

정상 기대값:

```text
52 passed
```

## 6. 서버 설치와 기본 설정

서버 접속:

```powershell
ssh -p 7877 ubuntu216@163.180.117.216
```

우리 프로젝트 폴더:

```bash
cd ~/geonhae/aiops_research
```

최신 코드 받기:

```bash
git pull origin master
```

우리 프로젝트 환경:

```bash
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
python -m pytest
```

AIOpsLab 자동 실험 환경:

```bash
conda activate aiopslab
cd ~/geonhae/aiops_research
python -m pip install -e ".[dev,autogen]"
```

kind/kubectl 경로 설정:

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
kubectl get nodes
```

정상 기대값:

```text
geonhae-aiops-control-plane   Ready
```

## 7. 실행 순서: 우리 코드 기본 검증

먼저 우리 코드가 깨지지 않았는지 확인합니다.

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research
python -m pytest
```

## 8. 실행 순서: CPU 95% synthetic alert

이 실험은 실제 장애 주입이 아니라, 4-agent가 Kubernetes scale action을 잘 만드는지 확인하는 synthetic validation입니다.

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research

aiops-k8s-agents run \
  --mode mock \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is 95 percent" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

정상 결과의 핵심:

```text
"valid": true
"command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
```

kind 클러스터에서 실제 실행하려면 `--mode real`을 사용합니다. 단, 반드시 개인 kind 클러스터인지 확인한 뒤 실행합니다.

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

aiops-k8s-agents run \
  --mode real \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is 95 percent" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

확인:

```bash
kubectl get deployment paymentservice -n online-boutique
kubectl get pods -n online-boutique -l app=paymentservice
```

## 9. 실행 순서: AutoGen LLM GroupChat

AutoGen 경로는 OpenAI API를 사용합니다. 기본 모델은 `gpt-4o-mini`입니다.

```bash
export OPENAI_API_KEY="sk-..."
```

실행:

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research

aiops-k8s-agents autogen-run \
  --mode mock \
  --show-transcript \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is 95 percent" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

정상 결과의 핵심:

```text
"valid": true
"autogen": "groupchat"
"transcript": "AIServiceHASupportAgent: action=..."
```

모델을 바꾸고 싶으면:

```bash
--model gpt-4o-mini
```

부분을 다른 모델명으로 바꿀 수 있습니다. 현재 기본값은 `gpt-4o-mini`입니다.

## 10. 실행 순서: AIOpsLab 자동 detection

AIOpsLab 자동 detection은 반드시 `aiopslab` 환경에서 실행합니다.

```bash
conda activate aiopslab
cd ~/geonhae/aiops_research
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

bash scripts/server_aiopslab_auto_detection.sh
```

정상 흐름:

```text
AIOpsLab problem start
-> get_logs("test-hotel-reservation", "geo")
-> panic/no reachable servers 감지
-> get_metrics("test-hotel-reservation", 10)
-> submit("Yes")
-> Detection Accuracy: Correct
-> Saved report: runs/<timestamp>_aiopslab_auto_detection.json
```

## 11. 실행 순서: AIOpsLab 반복 실험

논문/발표용 결과는 단발 실행보다 반복 실행 결과가 중요합니다.

```bash
conda activate aiopslab
cd ~/geonhae/aiops_research
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

RUNS=3 SLEEP_SECONDS=15 bash scripts/server_aiopslab_repeat_detection.sh
```

결과 확인:

```bash
cat runs/aiopslab_detection_summary.md
cat runs/aiopslab_detection_summary.csv
```

현재 서버 결과 예시:

```text
total_runs: 12
correct_runs: 12
metric_success_runs: 11
average_ttd_seconds: 4.117
average_steps: 3.000
average_final_reward: 3.100
```

발표용 문장:

```text
AIOpsLab Hotel Reservation detection 문제를 대상으로 4-agent 자동 탐지 실험을 12회 반복 수행한 결과,
12회 모두 Correct detection으로 평가되었다. 평균 TTD는 4.117초, 평균 action step은 3.0,
평균 최종 reward는 3.10으로 측정되었다.
```

## 12. 결과 지표 해석

| 지표 | 의미 |
| --- | --- |
| `total_runs` | 총 반복 실험 횟수 |
| `correct_runs` | AIOpsLab이 Correct로 평가한 횟수 |
| `metric_success_runs` | Prometheus metric export 성공 횟수 |
| `average_ttd_seconds` | 평균 detection 시간 |
| `average_steps` | 평균 API action 단계 수 |
| `average_final_reward` | 최종 제출 단계의 평균 reward 합 |
| `phase_coverage` | detection / analysis / mitigation 중 실험에서 사용된 단계 |

## 13. 자주 헷갈리는 것

### CPU 95%는 진짜 장애인가?

아닙니다. CPU 95%는 synthetic alert입니다.

```text
목적: scale action 생성과 kubectl validator 검증
성격: 기능 검증용 가짜 alert
```

실제 장애 주입은 AIOpsLab Hotel Reservation detection에서 수행합니다.

### AIOpsLab은 우리 GitHub에 왜 없나?

AIOpsLab은 외부 Microsoft 프로젝트이기 때문입니다.

```text
~/geonhae/external/AIOpsLab
```

에 따로 clone해서 쓰고, 우리 GitHub에는 올리지 않습니다.

### XGBoost와 PPO를 쓰나?

현재는 쓰지 않습니다.

```text
XGBoost 예측 모델 학습 X
PPO 강화학습 policy 학습 X
4-agent orchestration + action/reward + validator O
```

XGBoost/PPO는 참고 PPT의 방식이고, 우리 초기 연구 검증 단계의 핵심은 아닙니다.

### LLM 모델은 무엇인가?

AutoGen GroupChat 경로의 기본 모델은 `gpt-4o-mini`입니다.

LLM을 쓰는 명령:

```text
aiops-k8s-agents autogen-run
aiops-k8s-agents autogen-prometheus-run
aiops-k8s-agents feedback-loop --autogen
```

LLM을 쓰지 않는 명령:

```text
aiops-k8s-agents run
aiops-k8s-agents prometheus-run
AIOpsLab auto detection runner
```

### localhost:32000은 왜 안 뜨나?

`32000`은 AIOpsLab이 실험 중 임시로 여는 Prometheus port-forward입니다.
실험이 끝나면 닫히는 것이 정상입니다.

Prometheus UI 확인은 보통 아래를 씁니다.

```text
http://127.0.0.1:9090
```

### `aiops-k8s-agents: command not found`가 뜨면?

현재 환경에 우리 패키지가 설치되지 않은 것입니다.

```bash
cd ~/geonhae/aiops_research
python -m pip install -e ".[dev,autogen]"
```

그 다음 다시 확인합니다.

```bash
aiops-k8s-agents run --help
```

### `OPENAI_API_KEY missing`이 뜨면?

AutoGen 명령은 OpenAI API key가 필요합니다.

```bash
export OPENAI_API_KEY="sk-..."
```

API key는 GitHub나 문서에 저장하지 않습니다.

### kubectl permission denied가 뜨면?

서버 기본 kubeconfig가 공용 Kubernetes 또는 권한 없는 kubelet 인증서를 가리킬 수 있습니다.
우리 실험에서는 개인 kind kubeconfig를 사용합니다.

```bash
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
kubectl config current-context
kubectl get nodes
```

기대 context:

```text
kind-geonhae-aiops
```

## 14. 가장 짧은 실행 요약

우리 코드 검증:

```bash
conda activate aiops_research
cd ~/geonhae/aiops_research
python -m pytest
```

AIOpsLab 자동 실험:

```bash
conda activate aiopslab
cd ~/geonhae/aiops_research
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
bash scripts/server_aiopslab_auto_detection.sh
```

반복 실험:

```bash
RUNS=3 SLEEP_SECONDS=15 bash scripts/server_aiopslab_repeat_detection.sh
```

최종 결과 확인:

```bash
cat runs/aiopslab_detection_summary.md
```
