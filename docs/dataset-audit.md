# Dataset audit — AbhayNayan prototype

**Audit date:** 8 October 2026  
**Inputs:** the user-shared [Drive folder](https://drive.google.com/drive/folders/1IpWRau2BggdvbUQSX4mnbyiyfnlNfF6u?usp=sharing) and [Colab notebook](https://colab.research.google.com/drive/1E8TjWOY8JaLXKe7-plhOmzs0DofCmphM?usp=sharing).

## What was available

| Input | Observed contents | Prototype use / limitation |
|---|---|---|
| `Anemia_Dataset.csv` | 104 rows; 3 precomputed RGB pixel-percentage features, Hb, anemia label, sex, and a direct `Name` field. | Direct identifiers were never copied into the repository or model artifact. The name/group column was used transiently only to group validation folds, then dropped. A small Ridge regression baseline was trained from the three numeric features. It is research-only and disabled by default. |
| `Neonatal Jaundice Assessment ... .zip` | 478 JPEG images: 239 `Forehead/` and 239 `Sternum/`. The ZIP contains no CSV/XLSX/JSON/text label table linking images to serum bilirubin. | No bilirubin model can be trained or evaluated from this archive alone. Images are not placed in the public demo or ZIP. Jaundice values in the app are deterministic synthetic cases only. |
| `CP-AnemiC ... .zip` | A nested RAR archive. | Not extracted; the runtime lacks a RAR extractor. Labels, identifiers, license, and consent were not reviewed. Not used for training. |
| `archive.zip` (about 635 MB) and `NJN.rar` | Large archives listed in the folder. | Not downloaded or inspected to avoid unnecessary bulk/sensitive-data handling. Their labels, contents, license, and consent are unverified. |
| Shared Colab notebook | 11 code cells, primarily Kaggle `/kaggle/input` workflows with several repeated anemia baseline drafts and a placeholder CSV read cell. | Read statically; not executed. It is not a self-contained, reproducible experiment in this environment and cannot substantiate performance claims by itself. |

## Exploratory anemia baseline

An internal five-fold `GroupKFold` split by subject/group identifier was run on the three precomputed color features after excluding the `Name` field from model inputs. The model was a standardized Ridge regression (`alpha=1.0`).

- **n = 104** valid rows / 104 groups
- **MAE = 1.5041 g/dL**
- **RMSE = 1.9392 g/dL**
- **R² = 0.3987**

These values are only an exploratory internal split on one small shared dataset. They are **not external validation**, do not establish camera robustness or fairness, and are not adequate for patient-level decisions. The feature file does not contain the raw images needed to verify ROI, capture, color calibration, or ambient-light processing. The resulting weights are included only as a disabled research artifact in `models/anemia_color_baseline.json`; the main demo result is deterministic and synthetic.

## Privacy and release controls

- The raw CSV contains direct identifiers. It was downloaded only to a temporary directory outside this project and is **not** included in source, demo assets, APK, or ZIP.
- No raw infant/neonatal photographs are included in this repository or demo.
- The dataset share owner/license, participant consent, intended reuse, and any institutional approvals remain unverified. Confirm these before redistribution, further training, publication, or clinical use.
- The public app must not upload camera images to Gemini or the backend. The demo computes local optical measurements only for pipeline visualization; demo biomarker estimates are selected from synthetic case fixtures.

## Reproduce the sanitized exploratory baseline

Install the optional pins in `requirements-research.txt`, obtain a permitted local copy of the shared CSV, then run:

```bash
python scripts/train_anemia_baseline.py \
  --csv /path/to/Anemia_Dataset.csv \
  --out models/anemia_color_baseline.json
```

The script requires a subject/group field for grouped validation, excludes it from the feature matrix, and writes only model coefficients and aggregate metrics. It never writes names or per-subject predictions. Do not use this artifact for screening or care decisions.
