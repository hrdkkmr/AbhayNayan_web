# Data provenance, manifest and redistribution policy

Inspection date: 10 October 2026 · Source: [shared Drive folder](https://drive.google.com/drive/folders/1IpWRau2BggdvbUQSX4mnbyiyfnlNfF6u) · Machine-readable manifest: [`data/DATASET_MANIFEST.json`](../data/DATASET_MANIFEST.json)

**Decision: nothing from the Drive folder is committed to this repository.** No file has a verified licence, consent basis or redistribution permission. Several contain direct identifiers or biometric images. A shared link does not grant redistribution rights.

## 1. How the folder was inspected

- The folder listing showed 5 files at the top level and no subfolders.
- **ZIP archives:** only the central directory (the file list) was read, using HTTP byte-range requests. No image or spreadsheet bytes were downloaded (at most about 103 KB read per archive). Reproduce with `python scripts/inspect_dataset_archives.py "<download URL>"`.
- **CSV:** downloaded to a temporary directory outside the repository, audited with aggregate-only output (`scripts/audit_anemia_csv.py`; no names printed), then deleted.
- **RAR files:** not opened.

## 2. Manifest

| File | Size | Contents | Labels | Identifiers | Licence / consent | Public release |
|---|---|---|---|---|---|---|
| `Anemia_Dataset.csv` | 4,445 B | 104 rows: `Name, Sex, %Red Pixel, %Green pixel, %Blue pixel, Hb, Anaemic` | Hb (g/dL) 104/104; Anaemic Yes 26 / No 78 | **Direct: `Name`** (104 unique); Sex | Unverified / unverified | **No** |
| `archive.zip` | 666,269,625 B | 865 members: 218 JPG, 644 PNG, 2 XLSX, 1 DOCX under `dataset anemia/{India,Italy}/<n>/` | Hgb per patient in `India.xlsx`, `Italy.xlsx` | **Eye photographs (biometric)**; age, gender in XLSX | Unverified / unverified | **No** |
| `CP-AnemiC (A Conjunctival Pallor) Dataset from Ghana.zip` | 8,080,717 B | One nested `CP-AnemiC dataset.rar` | Unknown | Unknown | Unverified / unverified | **No** |
| `Neonatal Jaundice Assessment … Bilirubin Estimation.zip` | 32,854,665 B | 478 JPG: `Forehead/` 239, `Sternum/` 239, named `<n>.jpg` | **None** (no label member) | Infant skin images | Unverified / unverified | **No** |
| `NJN.rar` | 76,900,495 B | Not inspected | Unknown | Unknown | Unverified / unverified | **No** |

CSV SHA-256: `fb346fb81c64972678596d5d7eb4ea386a49c932ed1d445e889b1fdb0ae2df81`.

### Provenance notes

- **`archive.zip`** matches the Kaggle dataset that the Colab notebook reads (`harshwardhanfartale/eyes-defy-anemia`, with `India.xlsx`/`Italy.xlsx` columns `Number, Hgb, Gender, Age, Note`). Kaggle mirrors are often re-uploads; the original publisher and terms were not confirmed.
- **Neonatal ZIP:** the title names a published dataset intended for bilirubin estimation. If the publisher distributes labels separately, they are not in this copy.
- **CSV:** origin unknown. The colour percentages were computed by an undocumented pipeline. Data-quality findings are in [ML_MODEL_CARD.md §2](ML_MODEL_CARD.md).

## 3. Why deleting `Name` would not be enough

Removing the `Name` column does not anonymise the CSV:

- the remaining rows (sex plus exact Hb plus colour features) are a small, unique-per-person table;
- the source population and recruitment context are unknown;
- no consent covers republication.

Images of eyes and infant skin are biometric or health data and cannot be anonymised by renaming files. Nothing derived from these files may be published until §5 is complete.

## 4. What is in the repository

| Path | What it is | Contains source data? |
|---|---|---|
| `models/anemia_color_baseline.json` | 3 Ridge coefficients, scaler means/scales, aggregate CV metrics | No rows, names or per-person predictions. It does contain the feature means and standard deviations of the 104 rows, which are aggregate statistics |
| `data/DATASET_MANIFEST.json` | File-level metadata above | No |
| `scripts/train_anemia_baseline.py`, `scripts/audit_anemia_csv.py`, `scripts/inspect_dataset_archives.py` | Reproducible preparation and audit tools; they print aggregates only | No |

`.gitignore` excludes `data/raw/`, `data/private/`, `*.csv` (except `data/derived/`), `*.xlsx`, `*.zip`, `*.rar`, `*.7z` and model weights (`*.keras`, `*.h5`, `*.tflite`, `*.onnx`, `*.pt`, `*.pth`).

## 5. Getting access as an authorised contributor

1. Ask the project lead (the Drive folder owner) for access. Record your name, purpose and date in the team's access log, which is kept outside Git.
2. Download into `data/raw/` (ignored) or another encrypted location. Never into a tracked path, notebook output that gets committed, an issue or a chat.
3. Use the scripts above; they print aggregates only. Do not commit notebook outputs that display rows or images.
4. Delete local copies when the work is done.

## 6. Checklist before any public release

All of these must be true and written down in this file:

- [ ] Original source identified, with a citation and URL for the publisher (not a re-upload)
- [ ] Licence text reviewed and redistribution permitted, including derived works
- [ ] Participant consent and ethics approval cover the intended reuse
- [ ] A data-protection review approves the specific derived artifact
- [ ] Sanitisation recorded: identifiers removed, small cells suppressed, re-identification risk assessed
- [ ] Derived artifact, its manifest entry and its preparation script committed together under `data/derived/`
- [ ] Large artifacts (>50 MB) stored in versioned artifact storage (for example DVC, Git LFS, or a release bucket with checksums), not plain Git

None of these is satisfied today.
