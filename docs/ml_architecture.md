# ML architecture, preprocessing contracts and inference flows

Status words in this repository mean exactly this:

| Term | Meaning |
|---|---|
| **Implemented** | code exists |
| **Trained** | optimisation completed on identified training data |
| **Evaluated** | metrics computed on a documented, held-out split |
| **Integrated** | an application calls the intended inference code |
| **Clinically validated** | independent clinical evidence for an intended use. **Nothing in this project is clinically validated.** |

## 1. Tasks are separate problems

| Task | Target | Data | Output | State |
|---|---|---|---|---|
| Hemoglobin | Measured Hb, g/dL (regression) | Eyes-defy-anemia (adults, laboratory Hgb); CP-AnemiC (children, `HB_LEVEL`) | g/dL, research only | implemented, trained, evaluated, integrated (off by default) |
| NJN jaundice class | NJN folder class `jaundice` vs `normal` | NJN (760 photos, no bilirubin, no patient IDs) | score in [0, 1] for the dataset class; **not bilirubin** | implemented, trained, evaluated, integrated (off by default) |
| Bilirubin | Total serum / transcutaneous bilirubin, mg/dL | **none available** | none | **BLOCKED: insufficient labelled data**; the adapter stays `DISABLED_NO_VALID_MODEL` |

An anemia model is never used for jaundice. Separate artifacts, IDs, routes and Kotlin types enforce this.

## 2. Flow

```text
              Eye / skin photograph (PNG/JPEG; RGBA mask = pre-segmented ROI)
                                   │
          ┌────────────────────────┴────────────────────────┐
     Android (edge)                                    FastAPI (server)
 Camera2 / gallery → ImageQualityChecker          bounded decode (imageio.py) → quality.py
   (mask-aware for RGBA)                            (separate from prediction; 422 if failed)
          │                                                 │
 WorkflowEngine.modelInput: raw ambient             cf-v1 features (features.py)
   colours; whole image if masked                           │  cnn-v1 tensor (cnn_preprocess.py)
          │                                                 │
 ColourFeatures.kt (cf-v1 port)                    registry.py: SHA-256-pinned artifacts,
          │                                          JSON trees / linear / ONNX Runtime
 hb-ridge-cf  ·  njn-logreg-cf                     hb-hgb-cf  ·  njn-mnv3-logreg
 (pure Kotlin, offline)                                     │
          │                                                 │
 ModelOutputValidator (discard, never clamp)       range/finite checks (422/500, no value)
          │                                                 │
 ResultMode EXPERIMENTAL_RESEARCH_ONLY             provenance EXPERIMENTAL_RESEARCH_ONLY,
 + out-of-distribution reason                      model_version, warnings, OOD features
```

## 3. Preprocessing contract `cf-v1` (shared, both platforms)

Source of truth: [`backend/app/ml/features.py`](../backend/app/ml/features.py). Kotlin port: `AbhayNayan_apk/.../core/ColourFeatures.kt`. Training imports the Python module directly, so training and serving use one implementation.

| Step | Rule |
|---|---|
| Input | uint8, H×W×3 (RGB) or H×W×4 (RGBA), **RGB channel order**, sRGB assumed. No resizing, no colour correction. |
| Subsample | `step = ceil(max(H, W) / 256)`; keep pixels at `(y·step, x·step)` |
| Valid pixels | alpha ≥ 128 (if present) **and** max(R,G,B) < 250 (not clipped) **and** max(R,G,B) ≥ 20 (not dark/masked background) |
| Minimum | ≥ 100 valid pixels, otherwise `FeatureError` / `FeatureException` (no prediction) |
| Features (25, float64) | per-channel mean, population SD and chromaticity; R/G/B medians; R and G 10th/90th percentiles; mean HSV saturation and value; mean CIE L\*a\*b\* (sRGB→linear→XYZ D65, explicit matrices); a\* 10th/90th percentiles; erythema index ln(R̄+ε) − ln(Ḡ+ε); yellow index ln((R̄+Ḡ)/2+ε) − ln(B̄+ε), ε = 1e-4 |
| Percentiles | "lower": `sorted[floor(q·(n−1))]` |
| Parity | Golden vectors from 6 **synthetic** images (`tests/fixtures/ml_golden/`): Python and Kotlin agree to 1e-6 (tested on both sides) |

Colour features are orientation-invariant, so EXIF rotation does not change them.

## 4. CNN contract `cnn-v1` (server only)

[`backend/app/ml/cnn_preprocess.py`](../backend/app/ml/cnn_preprocess.py): RGBA composited on black, letterboxed onto 224×224 black (INTER_AREA), /255, ImageNet mean/std, NCHW float32 `[1,3,224,224]`. The backbone is torchvision MobileNetV3-Small `IMAGENET1K_V1`, frozen; the 576-d pooled embedding goes through a folded StandardScaler + logistic head and a sigmoid, all exported as a single ONNX graph. ONNX output matches the scikit-learn pipeline to within 1e-3 (checked at export).

## 5. Models

| ID | Role | Task | Architecture | Artifact | Size | Runtime |
|---|---|---|---|---|---|---|
| `hb-ridge-cf` | edge | Hb g/dL | StandardScaler + Ridge (α by LOO-CV) on cf-v1 | JSON (coefficients) | 4.5 KB | pure Kotlin / pure Python |
| `hb-hgb-cf` | backend | Hb g/dL | HistGradientBoosting (depth 3, 200 iter, lr 0.05) on cf-v1, exported to JSON trees | JSON | 217 KB | pure Python evaluator (no pickle) |
| `njn-logreg-cf` | edge | NJN class | StandardScaler + LogisticRegressionCV on cf-v1 | JSON | 4.0 KB | pure Kotlin / pure Python |
| `njn-mnv3-logreg` | backend | NJN class | frozen MobileNetV3-Small + logistic head | ONNX + JSON card | 3.7 MB | ONNX Runtime 1.31 CPU (optional dependency) |

**Why colour features on the edge.** Grouped CV on the training data found that frozen MobileNetV3 embeddings did **not** beat colour features for Hb (Eyes-defy CV R² 0.42 vs 0.50). A CNN runtime (LiteRT/TFLite) would add megabytes to the APK and a native dependency for no measured gain. For NJN the CNN was better (CV AUROC 0.888 vs 0.805), so the server uses it while the phone keeps the dependency-free model. Quantisation was not needed, because the edge models are tens of floats. The selection evidence is in [ml_evaluation.md](ml_evaluation.md).

## 6. Fail-closed rules (both platforms)

- Off unless an operator or developer opts in: `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=1` on the server, Settings → *Research models (developer)* on Android.
- The server pins every artifact by SHA-256 in [`models/MODEL_REGISTRY.json`](../models/MODEL_REGISTRY.json) and checks schema and feature contract. Android checks `model.json` against `artifact_sha256` in the bundled `metadata.json`. A missing, tampered or incompatible artifact means no model and a stated reason; a demo value is never substituted.
- Only `RESEARCH_ONLY` artifacts load. No `VALIDATED` path exists in this build.
- Outputs must be finite and plausible (Hb 2–25 g/dL; score 0–1). Otherwise the request fails and no value is returned.
- Inputs outside the training feature range (±10%) add an out-of-distribution warning.
- No anemia category or clinical threshold is attached to Hb output, because no threshold is validated for the intended (maternal) population.
