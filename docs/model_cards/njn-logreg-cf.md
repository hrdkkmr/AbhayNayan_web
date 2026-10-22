# Model card: `njn-logreg-cf` 1.0.0-research

NJN jaundice class: colour-feature logistic regression (edge). Status: **implemented · trained · evaluated · integrated (off by default) · not clinically validated**.

| Field | Value |
|---|---|
| Deployed in | Android (pure Kotlin) research panel; server reference |
| Architecture | StandardScaler + LogisticRegressionCV (11 C values, 5-fold, AUROC); 25 coefficients; threshold 0.138 |
| Intended use | **Research only.** Reproduces the NJN dataset's folder class (`jaundice` vs `normal`). **Not a bilirubin estimate**, not a diagnosis, not a screening tool. |
| Out of scope | Any mg/dL interpretation; clinical decisions; populations, skin tones or devices not in NJN (unknown) |
| Training data | NJN, 566 newborn photos (26% `jaundice`); labelling rule undocumented; no patient IDs |
| Split | Group-stratified 75/25 over perceptual-hash groups, seed 20261022 (`ml/splits/njn_v1.json`). Same-infant leakage cannot be ruled out. |
| Output | Score in [0, 1] plus a research operating threshold fixed from out-of-fold training scores (sensitivity ≥ 0.90). Not a clinical cut-off. |
| Ethical / data notes | Source, licence and consent unknown; artifact not committed or redistributed |
| Artifact | `models/njn_logreg_cf_v1.json` (sha256 `742fa42bddef2f90…`); pinned in `models/MODEL_REGISTRY.json` |
| Reproduce | `scripts/ml/train_njn.py --stage cv` then `--stage final` ([ml_integration.md §6](../ml_integration.md)) |

## Results (held-out test, single evaluation)

| Evaluation | Result |
|---|---|
| Test: 189 images (49 positive) | AUROC 0.793 [0.721, 0.865] · Brier 0.151 · sensitivity 0.86 [0.73, 0.93] · specificity 0.53 [0.45, 0.61] |

Full methodology, CIs and limitations: [ml_evaluation.md](../ml_evaluation.md).
