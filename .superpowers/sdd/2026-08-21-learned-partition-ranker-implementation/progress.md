# SDD ledger — plan: docs/superpowers/plans/2026-08-21-learned-partition-ranker-implementation.md

## Preflight

| Producer | Consumer | Shared file/interface | Finding |
| --- | --- | --- | --- |
| Task 1 | Task 2 | `RankingContext`, `CandidateSelection`, candidate identity | Compatible; Feature module owns hashing implementation and Task 1 consumes it after Task 2 without changing selection semantics. |
| Task 1 | Task 3 | `CandidateRanker`, `GuardedCandidateSelector`, `PartitionExecutionPlan.selection` | Compatible; Task 3 extends the deterministic contract with learned predictions. |
| Task 1 | Task 6 | selection serialization in `partition_models.py` | Compatible; Task 6 persists the Task 1 contract without redefining it. |
| Task 2 | Task 3 | Feature vector and Model Artifact | Compatible; runtime inference uses the exact `FEATURE_ORDER` and verified JSON Artifact. |
| Task 2 | Task 4 | candidate Key and Feature extraction | Compatible; Dataset rows reuse runtime Feature extraction and do not create a second schema. |
| Task 2 | Task 5 | Artifact repository and Feature normalization fields | Compatible; trainer exports the Artifact that the runtime repository already validates. |
| Task 2 | Task 6 | Model registry path and registered version | Compatible; Service receives only a registry root and version token. |
| Task 2 | Task 7 | registered Model status | Compatible; API reads status through the repository rather than arbitrary paths. |
| Task 3 | Task 6 | selection modes and fallback reasons | Compatible; Service passes trusted mode/version to the selector. |
| Task 3 | Task 8 | ranking entries and Feature contributions | Compatible; UI renders stored Metadata and never computes model output. |
| Task 4 | Task 5 | observed Dataset JSONL and manifest | Compatible; trainer consumes the versioned Dataset and verifies its Hash/scope. |
| Task 4 | Task 6 | persisted evaluation and selection sidecars | Compatible; Dataset scanner reads committed reports only. |
| Task 4 | Task 9 | evidence-scope documentation | Compatible; docs explicitly separate observed from predicted/mock/dry-run. |
| Task 5 | Task 6 | trainer/evaluator CLI functions | Compatible; CLI is a thin adapter over the learning module. |
| Task 5 | Task 7 | guarded eligibility metrics | Compatible; status API uses Artifact validation metrics and policy thresholds. |
| Task 5 | Task 8 | Model eligibility and training scope | Compatible; UI receives server-derived status. |
| Task 6 | Task 7 | `run_partition_planning` and repository | Compatible; API forwards only validated request fields. |
| Task 6 | Task 9 | executable CLI commands | Compatible; documentation is written after CLI names stabilize. |
| Task 7 | Task 8 | ranker routes and plan request contract | Compatible; UI calls the server API and uses registered versions. |
| Task 8 | Task 9 | visible research boundaries | Compatible; documentation uses the same Baseline/AI/Final and external Scheduler terminology. |

| Task | Internal consistency | Finding |
| --- | --- | --- |
| 1 | Tests vs contract/refactor | Consistent; default deterministic result is preserved while signature provenance is versioned. |
| 2 | Tests vs Feature/Artifact files | Consistent; canonical Key and Hash validation are covered. |
| 3 | Tests vs learned/guarded behavior | Consistent; invalid candidates and fallback codes are explicit. |
| 4 | Tests vs Dataset rules | Consistent; only observed selected candidates enter the default scope. |
| 5 | Tests vs optional trainer | Consistent; sklearn is training-only and Runtime remains dependency-free. |
| 6 | Tests vs Service/CLI integration | Consistent; feedback exclusions and persistence remain authoritative. |
| 7 | Tests vs API changes | Consistent; default request remains deterministic and arbitrary paths are rejected. |
| 8 | Tests vs UI changes | Consistent; existing four-stage workspace is retained. |
| 9 | Tests vs docs/verification | Consistent; exact repository example paths exist under `config/examples`. |

Ruling: The plan text originally requested exact compatibility while the spec requires Ranker provenance in `deterministic_signature`; preserve deterministic candidate selection but version the signature payload to include selection provenance — this may change historical signature strings but preserves reproducibility and repository safety.

## Task Ledger

| Task | Base SHA | Status | Implementer | Report |
| --- | --- | --- | --- | --- |
| 1. Ranker contract and deterministic compatibility | `5edecb5cf996384bc6b1f08062154a549afa974d` | approved at `7dea02f3c7308c141af55d9aab11df1bd6e9d922` | `01a0238c-d248-7870-998e-09940556126b` | `task-1-report.md` |

Task 1 review: approved with one non-blocking suggestion to add a focused signature-provenance regression test in a later integration pass.
| 2. Feature schema and model registry | `7dea02f3c7308c141af55d9aab11df1bd6e9d922` | approved after fixes at `187192641623859174c485c1f173d839720ba69b` | `01a0239a-6e48-7633-ae8a-5a4805492853` | `task-2-report.md`, `task-2-fix-report.md` |

Task 2 review loop: fixed symlink/junction escape, strict artifact parsing, and forecast source duplication; re-review approved with no remaining findings.
| 3. Learned ranker and guarded fallback | `187192641623859174c485c1f173d839720ba69b` | approved after fixes at `5ddc753ee8f1162bf2ebf6d2633a4184d49cc2ec` | `01a023b5-97a6-7972-a0a3-08c9f1518b40` | `task-3-report.md`, `task-3-fix-report.md` |

Task 3 review loop: restricted deployment to observed Ridge artifacts and made OOD 0.20 an inclusive fallback boundary; re-review approved.
| 4. Observed dataset builder | `5ddc753ee8f1162bf2ebf6d2633a4184d49cc2ec` | approved after fixes at `8c6bf5227a5cf7130f4b06bd99ef9252cca2e08f` | `01a023ce-54b2-7aa3-a6d6-aae480d3f292` | `task-4-report.md`, `task-4-fix-report.md` |

Task 4 review loop: aligned observed metric/timestamp validation with the Evaluator contract and excluded committed-plus-pending artifacts; re-review approved.
| 5. Offline Ridge trainer and evaluator | `8c6bf5227a5cf7130f4b06bd99ef9252cca2e08f` | approved after fixes at `ef9d23c63298cd929b3006003ca9cef6e981422b` | `01a023e2-5f3a-7bd3-879c-c4e8f44f4df0`, `01a02411-0f98-7322-bf21-15ec22943f6c` | `task-5-report.md`, `task-5-fix-report.md`, `task-5-fix2-report.md`, `task-5-schema-fix-report.md` |

Task 5 ruling: fix the exact `validation_metrics` artifact schema inside Task 5. The missing production `runtime_outcome_ref` generation is an explicit Task 6 service/repository integration dependency, because only that layer owns committed runtime outcomes; Task 6 acceptance must include a production-path observed dataset test without manually mutating persisted reports.

Task 5 review loop: fixed source/provenance and independent-evaluation issues, then enforced the exact 13-field validation metric contract. Final focused review approved spec compliance and code quality; full Python suite reported 923 passed with one pre-existing deprecation warning.

| 6. Service, repository, feedback, and CLI integration | `ef9d23c63298cd929b3006003ca9cef6e981422b` | approved after fixes at `0226f56d5b46bcc1ce7dd037eb5f3119246257b1` plus closure fix `c9bc069c7b621b4316f0e535ece1165e95ad5444` | `01a0241c-065f-7b40-b36e-66526cd435f4` | `task-6-report.md`, `task-6-fix-report.md` |

Task 6 review loop: added a production-path observed outcome binding, HMAC-authenticated the complete observed artifact set using externally supplied signing material, rejected coordinated report/input tampering and undeclared files, restricted Dataset CLI scope to the supported observed contract, and preserved deterministic defaults. Closure review approved spec compliance and code quality; full Python suite reported 940 passed with one pre-existing deprecation warning.

| 7. Control Plane ranker API and status | `0226f56d5b46bcc1ce7dd037eb5f3119246257b1` | approved after fixes at `7930ff8` | `01a0244f-82a3-7c31-8332-a088265161d9` | `task-7-report.md`, `task-7-fix-report.md` |

Task 7 review loop: separated invalid tokens from corrupted registered artifacts, routed encoded path-like versions through explicit 422 validation, rejected HTTP attempts to provide server-owned registry/HMAC fields, and moved model enumeration behind a symlink/junction-safe repository boundary. Direct closure verification passed 71 focused API/control-plane tests; implementer reported 958 full-suite tests passed with one pre-existing deprecation warning.

| 8. Platform UI Baseline vs learned comparison | `7930ff8` | approved at `b8167a8` | Codex local implementation | `task-8-report.md` |

Task 8 retained the four-stage orchestration workspace, added registered ranker mode/model controls, disabled ineligible guarded selection, and exposed Baseline, AI recommendation, final selection, Feature contribution, fallback, and provenance evidence without moving inference into the browser. Focused UI/API verification passed 105 tests with one pre-existing deprecation warning.
