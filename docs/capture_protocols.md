# Capture protocols

Status: **Design (Phase 3, 24 October 2026). Not implemented, except §1.1 orientation handling**, which was implemented in Phase 4 (backend `imageio.decode_image`/`read_path`, Android gallery import via `ImageTransforms.applyExifOrientation`). Implementation: Phase 5 (capture and quality), Phase 7 (compatibility gating). Outcomes are reported with the envelope in [prediction_contract.md](prediction_contract.md).

## Phase 5 implementation status (24 October 2026)

| Item | Status | Where |
|---|---|---|
| Separate protocols `anemia-palpebral` 2.0.0 and `newborn-skin` 1.0.0, each with its own guide, versioned quality rules and retry limit | **Implemented, unit-tested, emulator-checked** | Android `core/CaptureProtocol.kt` |
| Orientation (§1.1) | **Implemented** in Phase 4; Phase 5 records `input.orientation` in every envelope | backend `imageio`, Android gallery import |
| Multi-frame burst and frame selection (§1.2) | **Deferred.** The emulator camera cannot test burst quality robustly, and no device is available. Single-frame capture (plus the existing anemia flash pair) is used. Nothing selects frames by model output | — |
| Retry policy (§1.3): 3 rejected captures per attempt, then `CAPTURE_RETRY_LIMIT` with "record without a photo result" or "exit" | **Implemented, unit-tested, emulator-checked** | `ui/WorkflowTransitions.kt` |
| Quality block and compatibility block reported separately | **Implemented** in the contract 2.0 envelope (Android records; backend research routes) | `core/Workflow.kt`, `backend/app/main.py` |
| Newborn: no phone light | **Implemented** (`useTorch = false`; capture note "Phone light not used"), emulator-checked | `Camera2PreviewView.allowTorch` |
| Newborn: sclera capture retired; skin site (forehead / upper chest) chosen before capture | **Implemented** | Prepare stage |
| Body-site verification | **Not available**: no validated detector. Every app capture stays `unverified`, so no model runs (§2.3 point 1) | `BodySiteVerifier.NONE`, backend `BODY_SITE_VERIFIER` |
| Threshold calibration (§4) | **Not done.** Both rule sets are engineering heuristics. `quality-newborn-skin-0.1-uncalibrated` starts as a copy of the eye values, because no labelled skin captures exist | — |
| Clinician review of the newborn and anemia wording; native-speaker review of the Hindi/Bhojpuri strings | **Required, not done** | — |

### Exact model-compatibility restrictions in force

| Input | Hb models (`hb-*`) | NJN dataset-class model | Bilirubin |
|---|---|---|---|
| Android camera frame (guide rectangle) | `TARGET_REGION_INCOMPATIBLE`, model never called | not run (`MODALITY_UNSUPPORTED`: skin patch, not whole view) | `NO_VALIDATED_MODEL_FOR_TASK` |
| Android gallery image, opaque | `TARGET_REGION_INCOMPATIBLE` | not run | `NO_VALIDATED_MODEL_FOR_TASK` |
| Android gallery image with transparency (declared segmented) | `MODALITY_UNVERIFIED` (no verifier) | not run | `NO_VALIDATED_MODEL_FOR_TASK` |
| Synthetic colour chart | `MODALITY_UNSUPPORTED`; only an explicitly chosen demo fixture gives a value (`synthetic_fixture`) | not run | fixture only |
| Backend `/api/ml/hemoglobin` upload (research operator, flag on) | opaque → `TARGET_REGION_INCOMPATIBLE`; masked → quality → out-of-distribution check → `MODALITY_UNVERIFIED` (no verifier) | — | — |
| Backend `/api/ml/neonatal-jaundice-class` upload | — | masked → `MODALITY_UNSUPPORTED`; opaque → quality → OOD → `MODALITY_UNVERIFIED` | — |

**Why the backend also fails closed:** in a Phase 5 probe, random pink noise with a transparency mask passed the mask check and the feature-range (OOD) check in 20 of 20 trials. Without a verifier the server cannot distinguish noise from a conjunctiva crop. Research evaluation on dataset images continues offline through the model registry (`scripts/ml/*`), which these routes do not affect.

**Known imprecision:** 10 of the 54 Eyes-defy test crops store their segmentation as an opaque black background (alpha = 255 everywhere). The server classes them as unsegmented and refuses them as `TARGET_REGION_INCOMPATIBLE`, with a message that calls them rectangle crops. They also fail the glare check, so no estimate is lost, but the message is inaccurate for them.

**A protocol makes captures consistent and auditable. It does not make any model clinically valid.** Each protocol below can run with no model at all: the user then gets quality feedback, a saved record and `unable_to_estimate`, but never a number.

Two independent protocols are defined, and they share no thresholds, guides or models:

| Protocol ID | Workflow | Target | Models it may feed |
|---|---|---|---|
| `anemia-palpebral` | `maternal_anemia` | Lower-eyelid palpebral conjunctiva | `hemoglobin_from_palpebral_conjunctiva` only, and only with a segmented region (§2.3) |
| `newborn-skin` | `neonatal_jaundice` | Newborn skin (forehead or sternum), plus caregiver safety triage | `bilirubin_from_skin` (no model; blocked) and, only if framing matches, `newborn_jaundice_dataset_class` (§3.3) |

The current Android newborn flow photographs the **sclera** (`Strings.kt:24`, `WorkflowScreens.kt:238`). No dataset or model here uses sclera images, so `sclera_guide_crop` is **retired as an inference input**: it is recorded as `MODALITY_UNSUPPORTED` for every jaundice task. A future sclera protocol would need its own data and module.

## 1. Shared mechanics (both protocols, separately configured)

### 1.1 Orientation and normalisation

| Source | Rule | Recorded as |
|---|---|---|
| Camera2 frame | Rotate by `SENSOR_ORIENTATION` + display rotation to upright before the guide overlay and before any check | `orientation.applied = sensor_rotation` |
| Gallery / upload JPEG | Apply EXIF orientation (tags 1–8) before any check: Android `ExifInterface`, server `imageio.decode`, **and the training reader `read_path`** so training and serving match (audit M2: unrotated input moved the CNN score by up to 0.50) | `exif_transpose`, with `exif_tag` |
| PNG / no tag | No rotation | `none_needed` |
| Unreadable tag | For rotation-sensitive models (CNN), `unable_to_estimate` / `MODALITY_UNVERIFIED`. For cf-v1 colour models, proceed with warning `ORIENTATION_UNKNOWN` | `unknown` |

Colour handling stays as today and is documented, not changed: Camera2 YUV_420_888 → RGB with full-range BT.601 (`ImageAnalysis.kt:431`); embedded ICC profiles are ignored on both sides, consistently. Whether that BT.601 assumption holds is a per-device test item (§4), not a claim.

### 1.2 Multi-frame capture and selection

1. On "capture", take a short burst of `N` frames with exposure and white balance locked where the device supports it. `N` defaults to 5 and is configurable per protocol version.
2. Run the protocol's quality checks on **every** frame independently.
3. Select **one** frame: the passing frame with the highest sharpness (Laplacian variance), with ties broken by the lowest clipped fraction. Rule ID: `select-sharpest-v1`.
4. **Never** run inference on several frames and keep the best or average result. Doing so would pick on the output rather than the input, a form of the "loop until confident" pattern the brief forbids. Exactly one frame, chosen by input criteria, goes to the model.
5. Record `frames_captured`, `frames_passed`, `selected_index`, `selection_rule`, and per-frame failure codes.

The existing ambient + torch pair (`DifferentialAnalyzer`) stays a separate feature. Which frame matches a model's training illumination is a model-card question (§2.3), not a selection rule.

### 1.3 Retry policy

- If no frame in a burst passes, show the dominant failure's instruction (§2.2 / §3.2) and allow a retake.
- At most **3 bursts per screening attempt**, then stop with `unable_to_estimate` / `CAPTURE_RETRY_LIMIT` and the protocol's fallback message (confirmatory testing, or urgent care if any danger sign is present).
- A retake is always a **new** capture. Re-evaluating the same pixels does not count as a retry and is not allowed.

### 1.4 Gate order

`input validity → modality/body-site → quality → model availability/integrity → compatibility (region, OOD, population) → evidence/approval → inference → output validation`, as in [prediction_contract.md §4](prediction_contract.md). Quality and compatibility are separate results. A quality pass is never presented as suitability.

## 2. `anemia-palpebral` (v2, target)

### 2.1 Intended input

- **Modality / site:** photo of the everted lower-eyelid **palpebral conjunctiva**, captured with the rear camera.
- **What the existing models were trained on:** expert-segmented palpebral crops with a transparent background, from one standardised research device (Samsung Galaxy S6 + magnifying attachment + fixed white LED at constant distance: Eyes-defy-anemia, see [dataset_requirements.md](dataset_requirements.md)).
- **What the app produces today:** the rectangle `NormalizedRect(.14,.34,.86,.66)` of a ~640×480 whole-eye frame. **Audit §5.1:** on the same 54 held-out patients this changed backend R² from 0.47 to −0.99 and edge R² from 0.51 to −6.82 (bias −6.12 g/dL), while 54/54 crops passed the quality gate.

**Consequence written into the protocol:** a guide-rectangle crop is `body_site = palpebral_conjunctiva_guide_crop` and is **never** a compatible input for any existing Hb model (`TARGET_REGION_INCOMPATIBLE`). Only `palpebral_conjunctiva_segmented` can be compatible.

### 2.2 Capture guidance and checks

Guidance shown to the user (wording to be reviewed by a clinician and in the three app languages):

1. Wash hands. Sit the person facing a window or even indoor light; avoid direct sunlight.
2. Ask the person to look up. Gently draw the lower eyelid down with a clean fingertip to show the inner pink surface. Do not touch the eye itself and stop if it hurts.
3. Hold the phone about a hand's width away, parallel to the eyelid, and fit the inner eyelid inside the guide. Hold still for the burst.

| Check | Current value (where) | Status | Instruction on failure |
|---|---|---|---|
| Minimum dimension | 64 px (`ImageQualityChecker.MIN_DIMENSION`); server 32 px | heuristic | "Move closer" |
| Too dark / too bright (mean luma) | < 40 / > 215 (Android) | heuristic | "Move to better light" / "Avoid direct sunlight" |
| Glare / clipping | ≤ 10 % camera, ≤ 25 % masked/server | **inconsistent across platforms; must be unified per `rules_version`** | "Tilt the phone slightly" |
| Sharpness (Laplacian variance) | ≥ 8.0 Android; ≥ 2.0 server (different scale) | heuristic | "Hold still, tap to focus" |
| Target texture (ROI std-dev) | ≥ 3.0 | heuristic | "Place the inner eyelid inside the guide" |
| Motion between burst frames | `MAX_SHIFT_FRACTION` 0.10 (flash pair) | heuristic | "Hold still" |
| Focus | not measured directly (sharpness proxy only) | gap | — |

**None of these values is calibrated.** §4 defines how they will be.

### 2.3 Model compatibility checks (all must pass for `compatible`)

1. **Segmented region present.** One of these must produce the segmented region:
   - **(a)** an on-device conjunctiva segmentation model, with its own licence, model card and validation against expert masks; or
   - **(b)** a guided manual mask, where the user adjusts a polygon on the eyelid. This is acceptable only after an experiment shows that user-drawn masks reproduce expert-mask Hb error within a pre-registered margin. The Eyes-defy expert masks make this testable offline, but the data-licence gate still applies.
   
   Until (a) or (b) passes, the result is `TARGET_REGION_INCOMPATIBLE`. **This is the expected outcome for every app capture today.**
2. **Body-site verification**, method `detector:<id>@<ver>`. User confirmation alone is recorded but is not verification (audit H1: pink noise scored 13.4 g/dL).
3. **Feature-range (OOD) check** against the model card's `feature_min/feature_max` ± margin; any feature outside ⇒ `INPUT_OUT_OF_DISTRIBUTION`. This was 54/54 for guide crops and 2/54 for segmented test images.
4. **Illumination match.** The model card must state which frame (ambient or torch) matches its training illumination. This is unresolved today: training used a fixed LED, while the app feeds the ambient frame (`WorkflowEngine.modelInput`). It needs an experiment, not an assumption.
5. **Population.** The model card's population must include the subject's. No model covers pregnancy (the intended maternal population) ⇒ `POPULATION_UNSUPPORTED` for pregnant subjects with any current model.

### 2.4 Unsupported input behaviour

Non-eye images, sclera images, skin, documents, synthetic noise, or anything the detector cannot confirm ⇒ `unable_to_estimate` (`MODALITY_UNVERIFIED` or `MODALITY_UNSUPPORTED`). The heuristics cannot recognise every non-eye image; the negative test set in §4 measures how many they catch, and the measured rate is what gets reported.

### 2.5 Provenance recorded

Protocol id/version, rules version, source, orientation handling, stream size, frame metadata (exposure, ISO, torch, timestamps, already in `FrameMetadata`), burst summary (§1.2), body-site method and status, segmentation method, per-check measured values, device model and Android version (no device identifiers), and app version. The image itself is **not** retained by default ([record_contract.md](record_contract.md)).

## 3. `newborn-skin` (v1, target)

### 3.1 Safety first: triage before any photo

The protocol starts with the existing danger-sign and age questions (`DangerSign`, `ReferralRules.urgency` in `Clinical.kt`), and **they always win**:

- Any danger sign (yellow palms or soles; not feeding; very sleepy, hard to wake or floppy; convulsions; fever or body feels cold) ⇒ urgent referral now. The camera step becomes optional and is never required to proceed.
- Visible jaundice at under 24 hours of age ⇒ urgent referral (current rule).
- The app never says "wait for the result", never shows a reassuring number, and every outcome screen shows the referral line from `ReferralRules`, independent of any model.
- Positioning guidance must be safe: baby lying on their back on a flat, warm surface, held by the caregiver, kept warm and not undressed longer than needed. No pressure on the baby, no repositioning to get a better photo, no flash in the eyes. Wording to be reviewed by a paediatric clinician.

### 3.2 Capture guidance and checks

1. Natural daylight near a window if possible, not direct sun or coloured light. Note that phototherapy lights make the photo unusable (recorded context).
2. Photograph the forehead or the upper chest (sternum) at the distance shown by the guide, which follows the forehead/sternum dataset's 640×480 framing. Which site is used is recorded.
3. Hold still for the burst.

Checks: same check types as §2.2 but a **separate `rules_version`** with skin-specific thresholds. All values are uncalibrated until §4. Today's camera thresholds were tuned on eye frames and must not be reused unexamined.

### 3.3 Model compatibility checks

| Task | Rule |
|---|---|
| `bilirubin_from_skin` | **Always `unable_to_estimate` / `NO_VALIDATED_MODEL_FOR_TASK`.** No bilirubin labels exist. Enabling it needs paired TSB/TcB labels ([dataset_requirements.md §3](dataset_requirements.md)), held-out evaluation in the app's capture format, independent validation, and a MAJOR schema revision ([prediction_contract.md §14](prediction_contract.md)) |
| `newborn_jaundice_dataset_class` | Accepts only `newborn_skin_whole_view`, the NJN framing (1000×1000 photos; labelling rule, site and framing undocumented). Forehead/sternum close-ups and sclera crops are **`MODALITY_UNSUPPORTED`**. The output is a research score for the dataset's folder label, never mg/dL, never shown as a bilirubin level, never used for urgency |

The NJN score card is shown only in an authorized research context ([security_and_permissions.md §5](security_and_permissions.md)) and never on a caregiver-facing screen.

### 3.4 Unsupported input and fallback

Any incompatibility ⇒ `unable_to_estimate` with the reason code. The screen always shows the clinical fallback: "A phone photo cannot measure bilirubin. Have the baby checked by a health worker; if any danger sign is present, go now."

### 3.5 Provenance recorded

As §2.5, plus infant age in hours (required before capture), skin site, phototherapy yes/no/unknown, and gestational age at birth if known. No skin-tone field is collected until a reviewed, non-identifying scale and a reason to use it exist.

## 4. Calibrating thresholds and verifying protocols (before any inference is enabled)

Thresholds are established empirically, versioned (`rules_version`), and never tuned on a model's test set.

1. **Capture-quality set.** App captures from at least 2 phone models in several lighting conditions, each rated "usable / unusable for the target" by two reviewers blind to each other. Agreement is reported.
2. **Choose thresholds** on a development part of that set to meet a pre-registered target false-accept rate for unusable frames. Report false-reject and false-accept rates with 95 % CIs on a separate held-out part.
3. **Negative-modality set.** Synthetic noise and solid colours (reproducible, as in `scripts/audit/smoke_api.py`), plus documented non-target photos (skin for the anemia protocol, eye/sclera for the newborn protocol, documents, objects). Report the fraction rejected per category. **Report the measured rate; never claim complete rejection.**
4. **Orientation set.** Each test image in all 8 EXIF orientations. Required: identical cf-v1 features within 1e-6 after normalisation, and identical CNN input tensors.
5. **Per-device colour check.** A printed colour reference card photographed on each target phone to check the BT.601 assumption and auto-white-balance spread. This is descriptive; it does not calibrate the model.

Acceptance criteria for these are in [phase3_acceptance_criteria.md](phase3_acceptance_criteria.md) (AC-CAP-*).
