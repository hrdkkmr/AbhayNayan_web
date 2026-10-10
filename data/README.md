# Data directory

This directory holds **metadata only**. Raw datasets, images, spreadsheets and archives are excluded by `.gitignore` and must never be committed.

| Path | Purpose | In Git? |
|---|---|---|
| `DATASET_MANIFEST.json` | Inventory of every file in the shared Drive folder: size, counts, labels, identifiers, and licence/consent status | Yes |
| `raw/` | Local working copies of raw data for authorised contributors | **No** (ignored) |
| `private/` | Any other identifiable or unreviewed material | **No** (ignored) |
| `derived/` | Reserved for a sanitised, approved derived dataset. Empty: nothing is approved yet | Only after approval |

None of the five source files has a verified licence, consent basis or redistribution permission. See [`docs/DATA_PROVENANCE.md`](../docs/DATA_PROVENANCE.md) for the access process and release checklist.
