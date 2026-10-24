# ML integration: API contract, operations and the Android connection

## 1. What changed (contract 1.0.0 → 1.1.0, additive)

| Change | Compatibility |
|---|---|
| New `GET /api/ml/models`, `POST /api/ml/hemoglobin`, `POST /api/ml/neonatal-jaundice-class` | Additive. Existing clients are unaffected. |
| `GET /api/model/status` gains `image_models` and `image_models_enabled` | Additive response fields |
| `GET /api/vision/capabilities` and `/api/pipeline` report image upload as enabled **only** when the operator flag is set | Unchanged values by default (`false`) |
| New error codes: `EMPTY_IMAGE`, `IMAGE_TOO_SMALL`, `IMAGE_TOO_LARGE` (413), `UNSUPPORTED_MEDIA_TYPE` (415), `CORRUPT_IMAGE`, `IMAGE_QUALITY_REJECTED`, `OUTPUT_OUT_OF_RANGE`, `MODEL_INTEGRITY_FAILED`, `MODEL_INCOMPATIBLE`, `RUNTIME_UNAVAILABLE` | Same error envelope as 1.0.0 |
| `POST /api/screenings`, `/api/sync`, the bilirubin adapter and the demo fixtures | **Unchanged.** Image-model results are not attached to screening records, so the existing provenance rules and the disabled bilirubin path stay intact. |

## 2. Endpoints

All three are off by default. `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=1` enables them. Without it, the POST routes return **503 `MODEL_DISABLED` before reading the body**.

**Since contract 1.2.0 (Phase 4)** the POST routes also require `Authorization: Bearer <token>` with the `research_operator` role. Authentication, role and per-operator rate limits are checked first (`401`/`403`/`429`), then the flag. Tokens are minted server-side with `scripts/issue_access_token.py` ([configuration.md §4](configuration.md)). Uploaded images are normalised to EXIF display orientation, reported in `input.orientation`.

### `POST /api/ml/hemoglobin`

Request: raw PNG or JPEG bytes as the body, `Content-Type: image/png` or `image/jpeg`. No multipart and no JSON. Intended input: a segmented palpebral-conjunctiva crop (transparent background) like the training data.

```bash
curl -s -X POST http://localhost:8000/api/ml/hemoglobin -H 'Content-Type: image/png' --data-binary @crop.png
```

200 response, captured from the running API for the synthetic golden image `tests/fixtures/ml_golden/pink_masked.png` (long fields abbreviated):

```json
{
  "task": "hemoglobin", "status": "OK", "provenance": "EXPERIMENTAL_RESEARCH_ONLY", "synthetic": false,
  "model_id": "hb-hgb-cf", "model_version": "1.0.0-research", "feature_version": "cf-v1",
  "estimate": 13.5, "unit": "g/dL", "confidence": null,
  "warnings": ["RESEARCH_ONLY_NOT_VALIDATED"], "out_of_distribution_features": [],
  "quality": {"passed": true, "issues": [], "metrics": {"valid_pixels": 4057.0, "valid_fraction": 1.0, "clipped_fraction": 0.0, "mean_brightness": 0.7845, "sharpness": 700.715}},
  "input": {"width": 120, "height": 60, "channels": 4, "valid_pixels": 4057, "image_retained": false},
  "interpretation": "No anemia category is given: no threshold is validated for the intended population.",
  "evaluation_summary": {"held_out_test": {"eyes_defy_anemia": {"n": 54, "mae": 1.26, "...": "..."}, "cp_anemic": {"...": "..."}}},
  "generated_at": "2026-10-22T13:40:00+00:00", "timing_ms": {"decode": 19.7, "total": 29.41},
  "safety_note": "Experimental research output ... Not a measurement or diagnosis ..."
}
```

### `POST /api/ml/neonatal-jaundice-class`

The request format is the same. The response has `score` (0–1), `unit: null`, `research_threshold`, `dataset_class_at_research_threshold` (`jaundice_like` / `normal_like`) and an interpretation stating that this is **not bilirubin**. It never has an `estimate` field and never uses mg/dL.

### Errors (no value is ever returned with an error)

| Situation | Status | `error.code` |
|---|---|---|
| Flag off | 503 | `MODEL_DISABLED` |
| Artifact missing / registry missing | 503 | `MODEL_UNAVAILABLE` |
| Artifact hash ≠ `models/MODEL_REGISTRY.json` | 503 | `MODEL_INTEGRITY_FAILED` |
| Malformed card, wrong feature contract, unknown type, non-research status, corrupt ONNX | 503 | `MODEL_INCOMPATIBLE` |
| `onnxruntime` not installed (NJN backend model) | 503 | `RUNTIME_UNAVAILABLE` |
| Empty body | 422 | `EMPTY_IMAGE` |
| > 8 MB (Content-Length or streamed) / > 40 MP in the header | 413 | `IMAGE_TOO_LARGE` |
| Wrong Content-Type, or bytes that do not match it | 415 | `UNSUPPORTED_MEDIA_TYPE` |
| Undecodable / truncated | 422 | `CORRUPT_IMAGE` |
| < 32 px | 422 | `IMAGE_TOO_SMALL` |
| Quality gate failed (issues listed in `error.fields`) or < 100 usable pixels | 422 | `IMAGE_QUALITY_REJECTED` |
| Hb outside 2–25 g/dL | 422 | `OUTPUT_OUT_OF_RANGE` |
| Model exception / non-finite or invalid output | 500 | `INFERENCE_FAILED` (retryable; message has no internals) |

### `GET /api/ml/models`

This reports per task `status` (`DISABLED` / `UNAVAILABLE` / `READY_EXPERIMENTAL`), `model_id`, `version`, `load_ms`, the held-out evaluation summary, or `reason_code`/`reason`. It never includes file paths. It also states `bilirubin_mg_dl_model: DISABLED_NO_VALID_MODEL`.

## 3. Privacy

Image bytes are read into memory with a size cap, decoded, used and discarded. They are never written to disk or the database, never logged (error logs record only the exception type) and never sent to Gemini. Responses say `image_retained: false`. Enabling the flag still creates a server-side image-processing path for health images. Before using it with any real person, obtain consent and complete a privacy review (TLS, hosting location, retention).

## 4. Operating the server

```bash
pip install -r requirements.txt               # backend
pip install -r requirements-ml.txt            # optional: onnxruntime for the NJN backend model
# place the artifact files listed in models/MODEL_REGISTRY.json into models/ (they are NOT in Git)
ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=1 uvicorn app.main:app --app-dir backend
curl -s localhost:8000/api/ml/models
```

- Artifacts are loaded lazily, once per process, and cached; there is no retraining or reloading per request. `ABHAYNAYAN_ONNX_THREADS` (default 1) sets ONNX Runtime intra-op threads.
- **Deployment readiness.** The Docker image copies only `models/anemia_color_baseline.json`. Because the trained artifacts are deliberately gitignored (unverified dataset licences), a Git-based deploy (Docker, Render) will report `UNAVAILABLE` even with the flag set. That is the intended fail-closed outcome. To serve them, you need licence clearance, a controlled artifact store, an image step that downloads and checks them against `MODEL_REGISTRY.json`, and `onnxruntime` in the image. ONNX Runtime CPU adds about 40 MB of wheels; process memory was not measured here, so check the host's memory limit before enabling it on a small instance.

## 5. Android connection

The phone runs its **own** edge models locally; it does not call `/api/ml/*`, and no photo is uploaded. That is unchanged from contract 1.0.0. Hb results from the edge model are stored on the phone with `resultMode = EXPERIMENTAL_RESEARCH_ONLY`. The existing sync endpoint accepts only synthetic demo records, so these stay local (`LOCAL_ONLY`). The NJN class score is shown in a separate research panel and is neither saved nor synced. Details: `AbhayNayan_apk/AbhayNayan/docs/edge_ai.md`.

## 6. Reproduce everything

```bash
python -m venv --system-site-packages .venv-ml          # research env: torch, torchvision, onnx, onnxruntime, sklearn, openpyxl
.venv/Scripts/python scripts/ml/prepare_datasets.py --data-root .. --extracted-root ../datasets_extracted
.venv-ml/Scripts/python scripts/ml/train_hb.py  --stage cv          # selection on training data
.venv-ml/Scripts/python scripts/ml/train_hb.py  --stage final       # reads ml/runs/hb-v1/selection.json
.venv-ml/Scripts/python scripts/ml/train_njn.py --stage cv
.venv-ml/Scripts/python scripts/ml/train_njn.py --stage final
.venv/Scripts/python scripts/ml/write_registry.py                    # SHA-256 pins
.venv/Scripts/python scripts/ml/export_golden_vectors.py --android-dir <apk>/AbhayNayan/android/app/src/test/resources/ml_golden
.venv/Scripts/python scripts/ml/export_android_assets.py --apk-android <apk>/AbhayNayan/android
.venv/Scripts/python scripts/ml/verify_serving.py                     # served metrics, edge vs backend, latency
.venv/Scripts/python -m pytest -q
```
