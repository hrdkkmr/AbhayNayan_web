# ADR-006: Edge runtime stays pure Kotlin until a tensor model earns its place

Status: **Accepted by evidence** (22 Oct 2026 evaluation), recorded 24 Oct 2026

## Context
On the training data, frozen MobileNetV3-Small embeddings did not beat 25 colour features for hemoglobin (grouped CV R² 0.42 vs 0.50). For the NJN class, the MobileNetV3 head did beat colour features (held-out AUROC 0.920 vs 0.793), but leakage between same-infant images cannot be ruled out ([ml_evaluation.md](../ml_evaluation.md)).

## Decision
- Edge models stay JSON linear models run in Kotlin (SHA-256 pinned, no code execution on load).
- LiteRT (TensorFlow Lite) is added only for a module where a tensor model beats the colour model on a documented held-out set **and** its on-device latency/size is measured on named phones. The float baseline comes first; float16/int8 quantization is evaluated against it afterwards.
- The backend may serve a different, larger model, but it is reported as a separate result with its own `model_version` and never overwrites the edge result.

## Consequences
The APK has no ML runtime today. The NJN CNN stays server-only until the leakage question is resolved with patient-identified data.
