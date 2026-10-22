# Model card: `njn-mnv3-logreg` 1.0.0-research

NJN jaundice class: MobileNetV3-Small + logistic head (backend). Status: **implemented · trained · evaluated · integrated (off by default) · not clinically validated**.

| Field | Value |
|---|---|
| Deployed in | FastAPI `/api/ml/neonatal-jaundice-class` (ONNX Runtime CPU) |
| Architecture | Frozen torchvision MobileNetV3-Small IMAGENET1K_V1 → 576-d pooled embedding → folded StandardScaler + LogisticRegressionCV → sigmoid, one ONNX graph (opset 17, 3.7 MB); cnn-v1 preprocessing; threshold 0.185 |
| Intended use | **Research only.** Reproduces the NJN dataset's folder class (`jaundice` vs `normal`). **Not a bilirubin estimate**, not a diagnosis, not a screening tool. |
| Extra caution | A CNN on whole-scene photos can use background, clothing or camera cues instead of skin colour. |
| Out of scope | Any mg/dL interpretation; clinical decisions; populations, skin tones or devices not in NJN (unknown) |
| Training data | NJN, 566 newborn photos (26% `jaundice`); labelling rule undocumented; no patient IDs |
| Split | Group-stratified 75/25 over perceptual-hash groups, seed 20261022 (`ml/splits/njn_v1.json`). Same-infant leakage cannot be ruled out. |
| Output | Score in [0, 1] plus a research operating threshold fixed from out-of-fold training scores (sensitivity ≥ 0.90). Not a clinical cut-off. |
| Ethical / data notes | Source, licence and consent unknown; artifact not committed or redistributed |
| Artifact | `models/njn_mnv3_logreg_v1.json` (sha256 `43087ed619d838e7…`), `models/njn_mnv3_logreg_v1.onnx` (sha256 `22e0094d5e0e68d9…`); pinned in `models/MODEL_REGISTRY.json` |
| Reproduce | `scripts/ml/train_njn.py --stage cv` then `--stage final` ([ml_integration.md §6](../ml_integration.md)) |

## Results (held-out test, single evaluation)

| Evaluation | Result |
|---|---|
| Test: 189 images (49 positive) | AUROC 0.920 [0.869, 0.963] · Brier 0.092 · sensitivity 0.92 [0.81, 0.97] · specificity 0.74 [0.66, 0.80] |
| Served path | identical AUROC and confusion matrix through the HTTP route |

Full methodology, CIs and limitations: [ml_evaluation.md](../ml_evaluation.md).
