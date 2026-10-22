# Model card: `hb-ridge-cf` 1.0.0-research

Hemoglobin: colour-feature Ridge (edge). Status: **implemented · trained · evaluated · integrated (off by default) · not clinically validated**.

| Field | Value |
|---|---|
| Deployed in | Android (pure Kotlin) and server reference |
| Architecture | StandardScaler + Ridge, α chosen by efficient LOO-CV from 25 values (10⁻²–10⁴); selected α = 3.16; 25 coefficients |
| Intended use | **Research only.** Exploring whether conjunctival colour carries hemoglobin signal. Not for screening, diagnosis, triage or treatment. |
| Out of scope | Pregnant women (the app's target population; no data), children (fails on CP-AnemiC), phone photos taken with the app, any care decision |
| Training data | Eyes-defy-anemia, 163 adult patients (India + Italy), one expert-segmented palpebral PNG each; label = laboratory Hgb (g/dL) |
| Split | Patient-level 75/25 per country, seed 20261022 (`ml/splits/eyes_defy_anemia_v1.json`); selection by grouped 5-fold CV on training data (`ml/runs/hb-v1/selection.json`) |
| Input | cf-v1 colour features of a segmented conjunctiva crop ([ml_architecture.md §3](../ml_architecture.md)) |
| Output | Hb, g/dL; no uncertainty (`confidence: null`), no category |
| Ethical / data notes | Dataset licence and consent unverified; artifact not committed or redistributed |
| Artifact | `models/hb_ridge_cf_v1.json` (sha256 `a55048ccc38904ba…`); pinned in `models/MODEL_REGISTRY.json` |
| Reproduce | `scripts/ml/train_hb.py --stage cv` then `--stage final` ([ml_integration.md §6](../ml_integration.md)) |

## Results (held-out test, single evaluation)

| Evaluation | Result |
|---|---|
| Test: Eyes-defy, 54 unseen patients | MAE 1.30 [1.04, 1.58] g/dL · RMSE 1.66 · R² 0.51 [0.35, 0.65] · mean baseline MAE 1.97 |
| Test: CP-AnemiC, 110 children, 3 unseen hospitals | MAE 2.07 · R² **−0.64** (worse than the mean) |
| Screening (descriptive, WHO adult cut-offs, Eyes-defy) | sensitivity 0.83 [0.63, 0.93], specificity 0.74 [0.57, 0.86] |
| Known failure modes | Over-estimates Hb 7–10 g/dL by ≈ +2.7 g/dL; larger error in women (MAE 1.78, n=17); fails across population/device; trained on segmented crops, not app captures |

Full methodology, CIs and limitations: [ml_evaluation.md](../ml_evaluation.md).
