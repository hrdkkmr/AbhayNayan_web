# ML evaluation: methods, results and limitations

All numbers come from `ml/runs/{hb-v1,njn-v1,serving-v1}/*.json` (aggregate only). 95% CIs: bootstrap (2,000 resamples) for regression metrics and AUROC; Wilson intervals for proportions. **None of this is clinical validation.** It is internal and limited external evaluation on small public research datasets of unverified provenance.

## 1. Protocol (identical for both tasks)

1. **Split first** (`scripts/ml/prepare_datasets.py`, seed 20261022), before any model was fitted; IDs are in `ml/splits/*.json`.
   - CP-AnemiC: whole **hospitals** held out (3 sites, chosen by size and prevalence before modelling).
   - Eyes-defy-anemia: **patient-level** 75/25 per country (one image per patient).
   - NJN: group-stratified 75/25 over perceptual-hash groups (no patient IDs exist).
2. **Select on training data only** (`--stage cv`): grouped 5-fold CV (hospital groups for CP-AnemiC, patient groups for Eyes-defy, hash groups for NJN). Hyperparameters were either fixed in advance (gradient boosting) or tuned by inner CV inside each training fold (`RidgeCV`, `LogisticRegressionCV`). Scalers are fitted inside the folds.
3. **Record the choice** (`selection.json`, timestamped before the test run).
4. **Test once** (`--stage final`): refit the chosen models on the full training partition and score the untouched test partition. NJN classification thresholds come from out-of-fold *training* scores (sensitivity ≥ 0.90).
5. **Reproducibility**: single-threaded BLAS (`scripts/ml/_threads.py`; multithreaded summation changed a near-singular logistic fit between runs) gives byte-identical artifacts across repeated runs (verified). Environment: Python 3.13.7, numpy 2.3.5, pandas 3.0.6, scikit-learn 1.8.0, OpenCV 4.11 (headless), torch 2.14.1+cpu, torchvision 0.29.1, Windows 11, Intel Core Ultra 5 125H, CPU only.

Re-running the final stage after the first test evaluation (to fix a learning-curve plot bug and to add feature ranges to the artifacts) changed no metric and re-selected nothing.

## 2. Hemoglobin (g/dL)

### 2.1 Candidate comparison: grouped CV on training partitions only

| Training data → CV scored on | Mean baseline | Ridge, colour (`ridge_cf`) | Gradient boosting, colour (`hgb_cf`) | MobileNetV3-S + Ridge | Colour + MobileNetV3 |
|---|---|---|---|---|---|
| Eyes-defy → Eyes-defy (patients) | MAE 2.03, R² −0.01 | 1.32, **+0.50** | **1.30**, **+0.50** | 1.43, +0.42 | 1.40, +0.43 |
| CP-AnemiC → CP-AnemiC (hospitals) | 1.72, −0.03 | 1.64, +0.01 | 1.50, +0.13 | 1.71, −0.03 | 1.70, −0.03 |
| Pooled → Eyes-defy | 2.27, −0.26 | 1.65, +0.26 | 1.44, +0.39 | 1.55, +0.36 | 1.46, +0.42 |
| Pooled → CP-AnemiC | 1.65, −0.10 | 1.68, −0.09 | 1.54, +0.09 | 1.70, −0.08 | 1.70, −0.09 |

Decision (from CV): train on Eyes-defy only. Edge = `ridge_cf`, backend = `hgb_cf`. Pooling hurt, and the CNN did not help. No CP-AnemiC-trained artifact was produced, because no candidate meaningfully beat the mean across hospitals.

### 2.2 Held-out test (single evaluation)

| Model (trained on Eyes-defy, n=163) | Test set | n | MAE [95% CI] | RMSE [95% CI] | R² [95% CI] | Bias |
|---|---|---|---|---|---|---|
| Mean baseline | Eyes-defy patients | 54 | 1.97 [1.62, 2.33] | 2.38 [1.99, 2.75] | −0.00 | +0.07 |
| **Edge `hb-ridge-cf`** | Eyes-defy patients | 54 | **1.30 [1.04, 1.58]** | **1.66 [1.30, 2.02]** | **0.51 [0.35, 0.65]** | +0.12 |
| **Backend `hb-hgb-cf`** | Eyes-defy patients | 54 | **1.26 [0.97, 1.59]** | 1.74 [1.27, 2.17] | 0.47 [0.24, 0.66] | +0.23 |
| Mean baseline | CP-AnemiC, 3 unseen hospitals | 110 | 2.25 [1.91, 2.62] | 2.97 | −0.81 | +1.98 |
| Edge `hb-ridge-cf` | CP-AnemiC, 3 unseen hospitals | 110 | 2.07 [1.74, 2.45] | 2.82 | **−0.64** [−1.27, −0.18] | +1.36 |
| Backend `hb-hgb-cf` | CP-AnemiC, 3 unseen hospitals | 110 | 1.89 [1.61, 2.20] | 2.47 | **−0.25** [−0.55, −0.02] | +1.10 |
| Reference: `hgb_cf` trained on CP-AnemiC (n=290) | CP-AnemiC, 3 unseen hospitals | 110 | 1.67 [1.42, 1.92] | 2.14 | 0.06 [−0.11, 0.18] | +0.14 |
| Reference: CP-AnemiC mean | CP-AnemiC, 3 unseen hospitals | 110 | 1.79 | 2.21 | −0.01 | +0.16 |

**Calibration and residuals** (Eyes-defy test): edge slope of measured-on-predicted 1.07 (intercept −1.06); backend 0.94. Residuals rise with measured Hb (slope 0.49–0.52): **strong regression to the mean**.

| Measured Hb band (Eyes-defy test) | n | Edge MAE / bias | Backend MAE / bias |
|---|---|---|---|
| 7–10 g/dL | 9 | 2.72 / **+2.72** | 2.69 / **+2.69** |
| 10–12 g/dL | 9 | 1.17 / +0.28 | 1.03 / +0.45 |
| ≥12 g/dL | 36 | 0.98 / −0.57 | 0.96 / −0.44 |

Anemic patients are over-estimated by about 2.7 g/dL, so the people who most need detection look healthier than they are.

**Subgroups (Eyes-defy test):** India n=24, edge MAE 1.38; Italy n=30, edge MAE 1.24; women n=17, edge MAE 1.78 (backend 1.94); men n=37, edge MAE 1.08. These are small groups, so treat them as descriptive only.

**Screening (descriptive):** predicted Hb below the dataset's WHO cut-off vs measured below it, with no tuning.

| | Sensitivity [CI] | Specificity [CI] |
|---|---|---|
| Edge, Eyes-defy (23 anemic / 31 not) | 0.83 [0.63, 0.93] | 0.74 [0.57, 0.86] |
| Backend, Eyes-defy | 0.78 [0.58, 0.90] | 0.77 [0.60, 0.89] |
| Edge, CP-AnemiC (52 / 58) | 0.38 [0.26, 0.52] | 0.81 [0.69, 0.89] |
| Backend, CP-AnemiC | 0.27 [0.17, 0.40] | 0.86 [0.75, 0.93] |

**Interpretation.** On unseen patients captured with the *same* standardised device, both models carry real signal (R² ≈ 0.5, MAE ≈ 1.3 g/dL against 2.0 for the mean). On children from other hospitals with a different capture setup, they are **worse than predicting the mean** and miss most anemia. An MAE of 1.3 g/dL is about the width of a WHO severity band. These models are not fit for any screening use.

### 2.3 Quality gate interaction

The server gate refuses images with more than 25% of the target region clipped (glare). It fails 12.9% of Eyes-defy and 4.1% of CP-AnemiC *training* images (0% of NJN). The models were trained on all images, so the test figures above include images that the live server would refuse. Through the **served** path, 44 of 54 Eyes-defy test images pass the gate. On those 44: backend MAE 1.31, RMSE 1.84, R² 0.38; edge MAE 1.28, RMSE 1.67, R² 0.49 (`serving-v1`; estimates rounded to 0.1 g/dL).

## 3. NJN jaundice/normal class (not bilirubin)

### 3.1 CV on the training split (566 images, 26% positive)

| Candidate | AUROC | Brier | Specificity at OOF sensitivity 0.90 |
|---|---|---|---|
| `logreg_cf` (colour) | 0.805 | 0.155 | 0.52 |
| `hgb_cf` (colour) | 0.780 | 0.156 | 0.42 |
| `logreg_mnv3` (MobileNetV3-S embeddings) | **0.888** | **0.116** | **0.67** |

Decision: backend = `logreg_mnv3` (best CV), edge = `logreg_cf` (no runtime, reproducible in Kotlin).

### 3.2 Held-out test (189 images, 49 positive)

| Model | AUROC [95% CI] | Brier | Threshold (from training OOF) | Sensitivity [CI] | Specificity [CI] | PPV | NPV |
|---|---|---|---|---|---|---|---|
| **Backend `njn-mnv3-logreg`** | **0.920 [0.869, 0.963]** | 0.092 | 0.185 | 0.92 [0.81, 0.97] | 0.74 [0.66, 0.80] | 0.55 | 0.96 |
| **Edge `njn-logreg-cf`** | 0.793 [0.721, 0.865] | 0.151 | 0.138 | 0.86 [0.73, 0.93] | 0.53 [0.45, 0.61] | 0.39 | 0.91 |

Reliability (backend): mean score vs observed rate per bin 0.06/0.04, 0.28/0.27, 0.49/0.50, 0.70/0.79, 0.93/1.00, which is reasonably calibrated *on this dataset*.

**Limitations specific to NJN.**

- The label is a folder name with no documented definition.
- There are no patient IDs. An embedding nearest-neighbour probe found that half of the test images have a training image with cosine similarity > 0.9, and 96% of those pairs share the class. This is inconclusive (one-image-per-patient conjunctiva data scores even higher), but **same-infant leakage cannot be ruled out, and test performance may be optimistic**, especially for the CNN, which can also use background and scene cues.
- Skin tone, phototherapy, age and lighting are unknown.
- This is a classifier of the dataset's own labels. It does **not** estimate bilirubin and must not be read as a mg/dL proxy.

## 4. Edge vs backend on identical inputs (`serving-v1`)

| Task | Agreement |
|---|---|
| Hb, 44 gate-passing Eyes-defy test images | mean abs. difference 0.69 g/dL (max 1.94); Pearson r 0.86; edge − backend mean −0.21 g/dL; same side of the population cut-off in 77% of images |
| NJN, 189 test images | same class at each model's research threshold for 68%; Spearman 0.57 |

The edge and backend models are *different* architectures, so they are not expected to be equivalent. Preprocessing is identical: cf-v1 features match between Python and Kotlin to 1e-6 on golden vectors, and the edge JSON artifacts give the same outputs in Kotlin and Python to 1e-6. One known difference remains: the Android gallery importer downsizes images to ≤ 640 px with bilinear filtering before features are computed, while the server uses the original pixels. Colour means barely move, but percentiles can shift slightly.

## 5. Performance (local development machine; not production claims)

| Measure | Value | Method |
|---|---|---|
| Server model load | hb-hgb-cf 2.7 ms; njn-mnv3-logreg 85 ms (ONNX session); all four 90 ms | `Registry.get`, cold, one process |
| Server request latency, Hb | median 13.8 ms, p90 16.1 ms | 44 sequential requests via TestClient (decode, gate, features, model, JSON) |
| Server request latency, NJN | median 39.6 ms, p90 44.0 ms | 189 sequential requests, ONNX Runtime 1 thread |
| Rejected request (bad bytes) | median 1.1 ms | 50 requests |
| Concurrency | 40 NJN requests over 8 threads: all 200, 74.6 req/s, scores identical to sequential | ThreadPoolExecutor through TestClient |
| Training time | Ridge 3 ms, gradient boosting 57 ms (fit) | CPU |
| Memory | not measured (`psutil` not installed) | — |
| Android | see `AbhayNayan_apk/AbhayNayan/docs/edge_ai.md` | no device or emulator available |

## 6. What these results do not show

- Nothing about pregnant women, the app's intended maternal population.
- Nothing about phone captures made with the app. All Hb training and test images are expert-segmented crops from research capture setups.
- Nothing about bilirubin.
- Nothing about prospective, multi-site or device-independent performance.
