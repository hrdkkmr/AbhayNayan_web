# Datasets: what was used, what is wrong with them, and what is needed

Inspection date: 22 October 2026. Source: copies the project lead placed in `Programming/AbhayNayan/` (outside both Git repositories). Nothing was uploaded anywhere. Manifests with labels are written to `data/private/` (gitignored). Split files in `ml/splits/` contain image IDs only.

Reproduce: `python scripts/ml/prepare_datasets.py --data-root .. --extracted-root ../datasets_extracted` (the RARs/ZIPs were extracted with 7-Zip into `Programming/AbhayNayan/datasets_extracted/`).

## 1. Per-dataset audit

### Eyes-defy-anemia (`archive/dataset anemia`), used for Hb

| Item | Value |
|---|---|
| Source / permitted use | Dataset description (`Dataset anemia.docx`) asks users to cite Maglietta et al., Dimauro et al. (Appl. Sci. 2020, 10, 4804; Electronics 2020, 9, 997). It is offered free of charge for research. No formal licence text is in the archive, and redistribution terms are **unverified**. |
| Samples | 218 patients (India 95, Italy 123); per patient one full-eye JPEG plus expert-segmented palpebral, forniceal and palpebral+forniceal PNGs (RGBA, background transparent; one RGB with black background) |
| Label | Hgb, g/dL, "measured in the laboratory" (method and analyser not stated) |
| Linkage | folder number = `Number` row in the country sheet; one palpebral PNG per patient |
| Quality issues | 187 PNGs have a bad iCCP CRC (readable with libpng); 15 decimal-comma Hb values; 1 row `ELIMINATO` / missing Hb (excluded); 0 duplicate images |
| Grouping | patient folder (one image per patient) |
| Acquisition | Samsung Galaxy S6 with a magnifying attachment, fixed white LED, constant distance; two image resolutions are present (800×1067 and 3984×2988), so the capture setup was probably not identical throughout |
| Demographics | adults; India age 19–75, Italy 20–88; sex recorded; pregnancy not recorded |
| Used | 217 patients → train 163 / test 54 (patient-level, per-country 75/25, seed 20261022) |

### CP-AnemiC (Ghana), used for Hb (external check)

| Item | Value |
|---|---|
| Source / permitted use | Title identifies the published CP-AnemiC conjunctival pallor dataset (Ghana). The archive contains no licence file, so the licence and consent terms are **unverified**. |
| Samples | 710 PNG crops of palpebral conjunctiva (RGBA mask), 79–513 × 33–273 px |
| Label | `HB_LEVEL` g/dL (3.1–15.0); `Severity` and `REMARK` match the WHO 2011 child cut-offs exactly (<7, 7–9.9, 10–10.9, ≥11). Measurement method is not in the sheet. |
| Linkage | `IMAGE_ID` = filename; folder (Anemic/Non-anemic) agrees with `REMARK` for all rows |
| **Defect** | 91 groups of byte-identical images (303 rows) are labelled as different children: different hospitals, ages, sexes, and Hb up to 7.1 g/dL apart. All are excluded. 7 further perceptual near-duplicates (dHash ≤ 4/256) are excluded as well. |
| Grouping | No patient ID. Assumed one image per child; near-copies (dHash ≤ 8) share a split group. |
| Demographics | age 6–60 months; 10 hospitals, 4 regions; sex recorded |
| Used | 400 rows → train 290 (7 hospitals) / test 110 (Bolgatanga Regional, Kintampo Municipal, Manhyia District, plus 2 images pulled in by near-copy groups) |

### NJN (`NJN.rar`), used for the jaundice-class task

| Item | Value |
|---|---|
| Source / permitted use | Unknown. No README, licence or citation in the archive. **Unverified.** |
| Samples | 200 `jaundice/` + 560 `normal/` JPEGs, 1000×1000. 5 exact duplicates (same class) were removed, leaving 755. |
| Label | folder name only. What defined "jaundice" (clinician assessment, TSB/TcB threshold, age) is **not documented**. |
| Side files | `train.csv` (761 rows: mean red/green/blue/Y/Cb/Cr + class), not linkable to filenames (561 vs 560 normal); not used |
| Grouping | **No patient IDs.** Several photos of the same infant may straddle the split; dHash ≤ 8 groups were kept together, but this cannot detect different shots of one baby. |
| Used | train 566 / test 189 (group-stratified, 26% positive in each) |

### Not usable for training

| Dataset | Reason |
|---|---|
| Neonatal Jaundice Assessment (forehead/sternum, 478 JPEGs) | No bilirubin values in the archive; filenames carry no label |
| `Anemia_Dataset.csv` (104 rows) | No images; the %RGB pipeline is undocumented, so the features cannot be reproduced from a photo (unchanged from the earlier audit) |

## 2. Population thresholds used in evaluation (not in the apps)

Screening metrics apply each dataset's population-specific WHO cut-off to *predicted* Hb, with no tuning: children 6–59 months <11.0 g/dL (as encoded in CP-AnemiC; the 2024 WHO guideline revises 6–23 months to <10.5), non-pregnant women <12.0, men <13.0 (WHO 2011, *Haemoglobin concentrations for the diagnosis of anaemia and assessment of severity*, WHO/NMH/NHD/MNM/11.1). These numbers describe the datasets. They are **not** thresholds for the app's intended maternal population (pregnancy <11.0 g/dL, which no dataset here covers).

## 3. What is needed to unblock or upgrade

| Need | Why | Minimum specification |
|---|---|---|
| **Bilirubin-labelled neonatal images** | The bilirubin model is blocked without them | Per image: TSB (preferred) or TcB, with device/method stated; time between photo and blood draw (≤ 2 h); age in hours; gestational age; skin tone/phototherapy status; capture device and lighting; pseudonymous infant ID. Ideally the label table for the forehead/sternum dataset from its original publisher, under its licence. |
| **Maternal (pregnant) Hb images** | No training or test data matches the intended population | Lab or HemoCue Hb (method stated), gestational week, the app's own capture protocol on target phones, pseudonymous ID, multiple sites |
| **App-captured images with labels** | Models were trained on expert-segmented crops from a dedicated device; phone guide crops are a different input | Paired phone captures through the app's Camera2 pipeline and lab Hb, ≥ 2 device models, recorded lighting |
| **Patient IDs for NJN** | Leakage across the split cannot be ruled out | Infant ID per photo, capture session, labelling rule |
| **Licence/consent confirmation** | Required before any artifact or derived data is published | Original publisher URL, licence text, consent scope ([DATA_PROVENANCE.md §6](DATA_PROVENANCE.md)) |
| **Cleaned CP-AnemiC sheet** | 303 rows lost to conflicting duplicates | The publisher's corrected image–label mapping |
