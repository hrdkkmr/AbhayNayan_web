# Model card: `hb-hgb-cf` 1.0.0-research

Hemoglobin: colour-feature gradient boosting (backend). Status: **implemented · trained · evaluated · integrated (off by default) · not clinically validated**.

| Field | Value |
|---|---|
| Deployed in | FastAPI `/api/ml/hemoglobin` |
| Architecture | HistGradientBoostingRegressor(max_depth 3, lr 0.05, 200 iterations, min_samples_leaf 20, l2 1.0), fixed before training; exported to JSON trees (no pickle), evaluator parity 0.0 |
| Intended use | **Research only.** Exploring whether conjunctival colour carries hemoglobin signal. Not for screening, diagnosis, triage or treatment. |
| Out of scope | Pregnant women (the app's target population; no data), children (fails on CP-AnemiC), phone photos taken with the app, any care decision |
| Training data | Eyes-defy-anemia, 163 adult patients (India + Italy), one expert-segmented palpebral PNG each; label = laboratory Hgb (g/dL) |
| Split | Patient-level 75/25 per country, seed 20261022 (`ml/splits/eyes_defy_anemia_v1.json`); selection by grouped 5-fold CV on training data (`ml/runs/hb-v1/selection.json`) |
| Input | cf-v1 colour features of a segmented conjunctiva crop ([ml_architecture.md §3](../ml_architecture.md)) |
| Output | Hb, g/dL; no uncertainty (`confidence: null`), no category |
| Ethical / data notes | Dataset licence and consent unverified; artifact not committed or redistributed |
| Artifact | `models/hb_hgb_cf_v1.json` (sha256 `f2b1798fb074600f…`); pinned in `models/MODEL_REGISTRY.json` |
| Reproduce | `scripts/ml/train_hb.py --stage cv` then `--stage final` ([ml_integration.md §6](../ml_integration.md)) |

## Results (held-out test, single evaluation)

| Evaluation | Result |
|---|---|
| Test: Eyes-defy, 54 unseen patients | MAE 1.26 [0.97, 1.59] g/dL · RMSE 1.74 · R² 0.47 [0.24, 0.66] |
| Served path (44 images passing the quality gate) | MAE 1.31 · RMSE 1.84 · R² 0.38 |
| Test: CP-AnemiC, 110 children, 3 unseen hospitals | MAE 1.89 · R² **−0.25** |
| Screening (descriptive, Eyes-defy) | sensitivity 0.78 [0.58, 0.90], specificity 0.77 [0.60, 0.89] |
| Known failure modes | as for hb-ridge-cf (regression to the mean: +2.7 g/dL at 7–10 g/dL; women MAE 1.94) |

Full methodology, CIs and limitations: [ml_evaluation.md](../ml_evaluation.md).
