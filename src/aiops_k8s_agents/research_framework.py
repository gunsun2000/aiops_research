from __future__ import annotations

from dataclasses import dataclass


AIOPS_PHASE_ORDER = ("detection", "localization", "analysis", "mitigation")


@dataclass(frozen=True)
class AIOpsPhaseProfile:
    name: str
    korean_name: str
    purpose: str
    evidence_sources: tuple[str, ...]


@dataclass(frozen=True)
class ResearchAgentProfile:
    name: str
    korean_name: str
    role: str
    responsibilities: tuple[str, ...]
    bounded_actions: tuple[str, ...]
    reward_signals: tuple[str, ...]


@dataclass(frozen=True)
class RefereeDecision:
    valid: bool
    phase: str
    reason: str


AIOPS_PHASES: dict[str, AIOpsPhaseProfile] = {
    "detection": AIOpsPhaseProfile(
        name="detection",
        korean_name="장애 탐지",
        purpose="서비스가 정상인지, 장애 신호가 있는지 판단합니다.",
        evidence_sources=("logs", "alerts", "service status"),
    ),
    "localization": AIOpsPhaseProfile(
        name="localization",
        korean_name="장애 위치 추정",
        purpose="문제가 어느 서비스, 의존성, 인프라 영역에서 발생했는지 좁힙니다.",
        evidence_sources=("logs", "dependency errors", "pod status"),
    ),
    "analysis": AIOpsPhaseProfile(
        name="analysis",
        korean_name="원인 분석",
        purpose="metric과 상태 데이터를 이용해 원인과 심각도를 해석합니다.",
        evidence_sources=("prometheus metrics", "time-series data", "resource usage"),
    ),
    "mitigation": AIOpsPhaseProfile(
        name="mitigation",
        korean_name="완화 및 복구",
        purpose="검증된 Kubernetes action으로 서비스 상태를 복구하거나 완화합니다.",
        evidence_sources=("validated action", "kubeconfig", "kubectl result"),
    ),
}


AGENT_RESEARCH_PROFILES: dict[str, ResearchAgentProfile] = {
    "AIServiceHASupportAgent": ResearchAgentProfile(
        name="AIServiceHASupportAgent",
        korean_name="AI서비스 HA 지원 에이전트",
        role="장애진단, 예측, 자율복구",
        responsibilities=(
            "서비스 가용성 저하 신호를 탐지합니다.",
            "장애 여부를 Yes/No 또는 복구 필요 여부로 판단합니다.",
            "불필요한 복구 action을 억제합니다.",
        ),
        bounded_actions=(
            "ha_collect_logs",
            "ha_anomaly_detected",
            "ha_no_log_anomaly",
            "ha_submit_anomaly_yes",
            "ha_submit_anomaly_no",
            "ha_scale_out_required",
            "ha_no_action",
        ),
        reward_signals=(
            "장애를 빠르게 탐지하면 양의 reward",
            "정상 상태에서 불필요한 조치를 피하면 양의 reward",
            "장애를 놓치거나 과잉 복구하면 낮은 reward 또는 penalty",
        ),
    ),
    "AIApplicationManagementAgent": ResearchAgentProfile(
        name="AIApplicationManagementAgent",
        korean_name="AI응용관리 자동화 에이전트",
        role="자동 배포, 제어, 수준 최적화",
        responsibilities=(
            "서비스 로그와 metric을 기반으로 application-level action을 제안합니다.",
            "scale, metric collection, final submission 같은 실행 가능한 action을 구조화합니다.",
            "서비스 안정성과 응답 품질을 우선합니다.",
        ),
        bounded_actions=(
            "app_observe_service_logs",
            "app_collect_metrics",
            "app_submit_detection_result",
            "app_scale_deployment",
        ),
        reward_signals=(
            "정확한 application action을 제안하면 양의 reward",
            "metric 확인 없이 성급하게 실행하면 낮은 reward",
            "서비스 안정성 회복에 기여하면 높은 reward",
        ),
    ),
    "AISemiconductorInfraOpsAgent": ResearchAgentProfile(
        name="AISemiconductorInfraOpsAgent",
        korean_name="AI반도체 인프라 운용 자동화 에이전트",
        role="최적자원 추천, 수집데이터 기반 추론, 자원 최적화",
        responsibilities=(
            "GPU/NPU 또는 노드 자원 관점에서 action 가능 여부를 검토합니다.",
            "서비스 장애가 인프라 또는 의존성 문제인지 범위를 좁힙니다.",
            "replica 증가가 인프라 용량을 넘지 않는지 확인합니다.",
        ),
        bounded_actions=(
            "infra_no_change",
            "infra_observe_only",
            "infra_dependency_failure_detected",
            "infra_fault_scope_confirmed",
            "infra_no_fault_scope_confirmed",
            "infra_capacity_approved",
            "infra_capacity_rejected",
            "scale_deployment",
        ),
        reward_signals=(
            "용량 한도 내 action을 승인하면 양의 reward",
            "용량 초과 action을 차단하면 양의 reward",
            "잘못된 인프라 원인 추정은 penalty",
        ),
    ),
    "CostOptimizationAgent": ResearchAgentProfile(
        name="CostOptimizationAgent",
        korean_name="비용 최적화 지원 에이전트",
        role="자원사용량, 사용 패턴 기반 비용 최적화",
        responsibilities=(
            "복구 action의 비용 증가를 감시합니다.",
            "replica 수와 관측 action이 비용 정책을 넘지 않는지 판단합니다.",
            "필요한 복구와 과잉 자원 사용 사이의 균형을 조정합니다.",
        ),
        bounded_actions=(
            "cost_no_change",
            "cost_observation_only",
            "cost_no_remediation_cost",
            "cost_budget_approved",
            "cost_budget_rejected",
            "scale_deployment",
        ),
        reward_signals=(
            "비용 한도 내 복구를 승인하면 양의 reward",
            "과도한 scale-out을 차단하면 양의 reward",
            "불필요한 자원 증가를 승인하면 penalty",
        ),
    ),
}


def agent_action_space(agent_name: str) -> tuple[str, ...]:
    return AGENT_RESEARCH_PROFILES[agent_name].bounded_actions


def validate_agent_action(agent_name: str, action: str) -> bool:
    profile = AGENT_RESEARCH_PROFILES.get(agent_name)
    if profile is None:
        return False
    return action in profile.bounded_actions


def infer_aiopslab_api_phase(api_call: str) -> str:
    if api_call.startswith("get_logs("):
        return "detection"
    if api_call.startswith("get_metrics("):
        return "analysis"
    if api_call.startswith("submit("):
        return "detection"
    return "mitigation"


def referee_aiopslab_api_call(
    api_call: str,
    *,
    namespace: str,
    service: str,
    metrics_duration_minutes: int,
) -> RefereeDecision:
    phase = infer_aiopslab_api_phase(api_call)
    allowed_calls = {
        f'get_logs("{namespace}", "{service}")',
        f'get_metrics("{namespace}", {metrics_duration_minutes})',
        'submit("Yes")',
        'submit("No")',
    }
    if api_call in allowed_calls:
        return RefereeDecision(
            valid=True,
            phase=phase,
            reason="bounded AIOpsLab action space 안의 API call입니다.",
        )
    return RefereeDecision(
        valid=False,
        phase=phase,
        reason="허용되지 않은 AIOpsLab API call입니다.",
    )
