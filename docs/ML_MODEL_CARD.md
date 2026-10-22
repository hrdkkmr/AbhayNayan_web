# ML model card and integration decisions

Audit date: 10 October 2026. Sources inspected: this repository, the [Colab notebook](https://colab.research.google.com/drive/1E8TjWOY8JaLXKe7-plhOmzs0DofCmphM) (downloaded as `.ipynb`; its saved cell outputs were read, it was **not re-executed**), and the [shared Drive folder](https://drive.google.com/drive/folders/1IpWRau2BggdvbUQSX4mnbyiyfnlNfF6u) (see [DATA_PROVENANCE.md](DATA_PROVENANCE.md)).

> **Update, 22 October 2026.** This card describes the 10 October audit. Since then, image models have been trained and evaluated on Eyes-defy-anemia, CP-AnemiC and NJN, and integrated behind off-by-default research flags. See [ml_audit.md](ml_audit.md), [ml_evaluation.md](ml_evaluation.md), [ml_integration.md](ml_integration.md) and [model_cards/](model_cards/). Bilirubin (mg/dL) remains `DISABLED_NO_VALID_MODEL`. The Ridge baseline and adapter described below are unchanged.

**Bottom line (10 October):** no model in any inspected source predicts hemoglobin (g/dL) or bilirubin (mg/dL) well enough to show to a person, and no bilirubin model exists at all. Both runtime adapters are `DISABLED_NO_VALID_MODEL`. The app shows only `DEMO_SYNTHETIC` fixtures.

## 1. Decisions

| Candidate | Target | Artifact present? | Status | Reason |
|---|---|---|---|---|
| Demo fixtures (`backend/app/core/inference.py`, `web-dashboard/js/inference.js`) | none | yes | `DEMO_SYNTHETIC` | Fixed values chosen by the user. Never presented as inference |
| Ridge colour baseline (`models/anemia_color_baseline.json`) | Hb g/dL | yes (coefficients, 1,449-byte JSON) | `EXPERIMENTAL_RESEARCH_ONLY` as an artifact; **runtime adapter disabled** | Weak internal evidence; inputs cannot be reproduced from the camera pipeline. See §2 |
| Notebook MobileNetV3-Small regression (cell 5) | Hb g/dL | **no.** Saved to `/kaggle/working/hemovision_baseline.keras`; not in the repo or Drive | `DISABLED_NO_VALID_MODEL` | Test R² −0.197, worse than predicting the mean |
| Notebook colour random forest / GBM / linear (cell 8) | Hb g/dL | no | `DISABLED_NO_VALID_MODEL` | Best test R² −0.345 on 10 patients |
| Neonatal bilirubin | bilirubin mg/dL | no | `DISABLED_NO_VALID_MODEL` | The only neonatal image set has no bilirubin labels |
| `MobileNetV3SmallModel` / TFLite placeholder (removed in this change) | — | no weights | n/a | Interface placeholder only; it also exposed a filesystem path in status output |

`VALIDATED_FOR_INTENDED_USE` is assigned to nothing. It would require external, prospective, device-specific validation, subgroup analysis, clinical governance sign-off and regulatory review, none of which exists.

## 2. Ridge colour baseline (104-row CSV)

| Item | Detail |
|---|---|
| Intended target | Hemoglobin concentration, g/dL |
| Inputs | `%Red Pixel`, `%Green pixel`, `%Blue pixel`, precomputed in the CSV (sum = 100). The ROI, device, lighting and extraction code that produced them are **undocumented** |
| Preprocessing | `StandardScaler` → `Ridge(alpha=1.0)` |
| Labels | `Hb` column; its measurement method (lab analyser, HemoCue, …) is unknown |
| Samples / grouping | 104 rows; `Name` used as the group key, 104 unique names → each group has one row |
| Split | `GroupKFold(5)` (`scripts/train_anemia_baseline.py`). With one row per group this is equivalent to unshuffled 5-fold CV; it cannot detect a person recorded under two names |
| Reported metrics (reproduced exactly on 10 Oct 2026) | MAE **1.5041**, RMSE **1.9392**, R² **0.3987** g/dL |
| Baseline comparison (new) | Predicting the training mean: MAE 1.9518, RMSE 2.5030, R² −0.0017 |
| Split sensitivity (new) | Shuffled 5-fold, seeds 0–4: MAE 1.535–1.605, R² 0.310–0.379. The reported split is at the favourable end |
| Data-quality findings (new) | 22 rows labelled `Anaemic=No` have Hb below WHO non-pregnant sex-specific cut-offs (13 g/dL male, 12 g/dL female), so the label rule is unknown. 2 rows have Hb below 5 g/dL (implausibly low for a screening population). 1 duplicated feature row |
| Leakage checks | Group key excluded from features. Cannot rule out repeat subjects or shared capture sessions |
| Format / runtime | JSON coefficients evaluated in pure Python by `MaternalAnemiaAdapter`; no external runtime |
| Output | g/dL, rounded to 0.1. Range not bounded by the model; the training Hb range was 2.8–16.3 |
| Uncertainty | None. `confidence` is `null` |
| Provenance / permission | Dataset source, licence and consent unverified ([DATA_PROVENANCE.md](DATA_PROVENANCE.md)) |

Reproduce both the metrics and the extra checks with a permitted local copy of the CSV. Output is aggregate only:

```bash
pip install -r requirements-research.txt
python scripts/train_anemia_baseline.py --csv /private/Anemia_Dataset.csv --out /tmp/check.json
python scripts/audit_anemia_csv.py --csv /private/Anemia_Dataset.csv
```

**Why the runtime adapter stays disabled.** An MAE of about 1.5 g/dL is roughly the width of the clinical anemia severity bands. The evidence is one small internal split. Most importantly, the app's camera features (`backend/app/core/vision.py`, `web-dashboard/js/vision.js`) come from a different, uncalibrated pipeline, so feeding them to these coefficients would produce numbers with no known relationship to Hb.

**Opt-in research mode.** Setting `ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA=1` lets `POST /api/screenings` with `inference_mode: "MODEL"` run the coefficients. This works only on features declared `research_dataset_precomputed` and only for demo/research profiles. Output is labelled `EXPERIMENTAL_RESEARCH_ONLY` with a non-measurement safety note. Camera-pipeline features are rejected (`UNSUPPORTED_INPUT`). This mode exists for controlled research demonstrations and tests, not for screening.

## 3. Notebook experiments (Eyes-defy-anemia)

The notebook has 11 code cells written for Kaggle (`/kaggle/input/datasets/harshwardhanfartale/eyes-defy-anemia`). Cells 2, 6, 7 and 9 end in errors (placeholder CSV path, column detection failures, missing input). The figures below come from the saved outputs of cells 5 and 8.

| Item | Cell 5: MobileNetV3-Small | Cell 8: colour features |
|---|---|---|
| Data | India.xlsx (95 rows) + Italy.xlsx (123 rows) → 202 valid Hb; 429 palpebral PNGs; 398 matched, **110 unreadable** → 288 images / 145 patients | Different matching logic: 148 matched, 51 unreadable → 97 images / 50 patients |
| Inputs | Palpebral conjunctiva crop, resized 224×224, `mobilenet_v3.preprocess_input` | ~30 RGB/HSV/Lab statistics per image |
| Model | ImageNet MobileNetV3-Small (frozen, 939k params) + GAP → Dropout → Dense(64) → Dense(1); MSE loss, 30 epochs max, early stopping | Linear regression, random forest, gradient boosting |
| Split | Patient-level `train_test_split` 70/15/15 (101/22/22 patients) | Patient-level 80/20 (40/10 patients) |
| Test result | MAE 1.838, RMSE 2.190, **R² −0.197** g/dL | Best (RF): MAE 2.053, RMSE 2.305, **R² −0.345**; 22.2% within 1 g/dL |
| Artifact | `.keras` written to the Kaggle session only | none |

A negative R² means the model does worse than always predicting the average Hb. The two cells also disagree on how many images match a label (398 vs 148), which suggests the image-to-patient matching is itself unreliable. Neither result supports deployment.

## 4. Neonatal bilirubin

The Drive copy of "Neonatal Jaundice Assessment: A Dataset of Forehead and Sternum Images for Bilirubin Estimation" holds 478 JPEGs (239 `Forehead/`, 239 `Sternum/`). The ZIP central directory has **no** CSV, XLSX, JSON or text member, and filenames are sequential integers. With no bilirubin ground truth linked to images, no regression can be trained or evaluated. Labels must not be derived from filenames or borrowed from the anemia model. If the original publisher distributes a label table separately, it must be obtained under its terms and linked by a documented key before any work starts.

## 5. Adapter contract

`backend/app/core/model_adapters.py` holds `MaternalAnemiaAdapter` and `NeonatalJaundiceAdapter`, which are kept separate. Each exposes `card()` (status, target, unit, version, reason, inference location, limitations, evaluation) and `infer()`. `infer()`:

- validates input type, source and range, then applies the documented preprocessing;
- raises `InferenceError(code, message)` for `MODEL_DISABLED`, `MODEL_UNAVAILABLE`, `INVALID_INPUT`, `UNSUPPORTED_INPUT` or `INFERENCE_FAILED`. Messages contain no paths or internals;
- never substitutes a synthetic value;
- returns a typed `ScreeningResult` with `provenance`, `model_version`, `unit`, `confidence: null` and `limitations`.

## 6. Edge vs server inference

| Question | Answer today |
|---|---|
| Is there an on-device model? | No. No `.tflite`/`.onnx` exists in any inspected source |
| Server path? | Only the opt-in Ridge research path, which takes three numbers and **no images**. The API has no image upload |
| Latency, memory, 2–4 GB devices? | Not measured. No claim is made |
| Offline biomarker prediction? | Not available |

Before any model is enabled, record: runtime and version, input spec, output unit and range, artifact hash, measured latency and memory on named devices, and, for server inference, a privacy assessment for image transfer (consent, encryption in transit and at rest, retention). Then update this card and `CANDIDATE_MODELS`.
