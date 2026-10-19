# 4-minute hackathon demo script

## Setup (before judges arrive)

- Start the PWA/API and open `http://localhost:8000` on the presentation device.
- Use the preloaded **Demo Patient** only. Do not enter real patient identifiers or use a real patient's photo in a result flow.
- Confirm the prototype ribbon is visible and the API health indicator loads. The demo still works locally with no Gemini key or network.
- Have a synthetic maternal case ready; prepare a second run for jaundice or offline sync if time permits.
- No live API key is required. Do not reveal or request secret keys.

## Narration and click path

### 0:00–0:30 — Problem and boundary

> “AbhayNayan is an offline-first screening-workflow prototype for frontline workers. The build shows how a low-cost phone can guide capture, local image-quality checks, counselling, referral paperwork, and interoperability. The values we show today are synthetic fixtures—not diagnoses, not lab results, and not computed from the camera.”

Point out the permanent **PROTOTYPE / DEMO MODE** label and local-first privacy copy.

### 0:30–1:30 — Maternal anemia workflow

1. Click **New screening** → choose the preloaded synthetic Demo Patient and **Maternal anemia**.
2. Click **Use abstract synthetic image**.
3. Point to the local quality gate, manual conjunctiva guide, synthetic-image label, and browser-only RGB/HSV/Lab/YCrCb feature preview.
4. State clearly: “Those features are for pipeline visualization; they do not feed the estimate.”
5. Select **Moderate-risk-like (synthetic)** and run the case.
6. Show the `DEMO` badge, fixed value, confidence/quality placeholder labels, and safety note. Explain that a clinical result requires appropriate testing and clinician review.

### 1:30–2:15 — Multilingual counselling and referral

1. Switch counselling to Hindi and then Bhojpuri.
2. Explain: “This is deterministic local safety copy when no server key is configured. If enabled, the optional server-side Gemini step receives structured fields only; no image or name is sent. It is not medical judgment.”
3. Create the referral brief. Show the PDF link or use **Print / save PDF**.
4. Download **FHIR JSON** and identify the Patient, Encounter, preliminary Observation, DiagnosticReport, and prototype/synthetic notes.

### 2:15–3:00 — Offline and sync

1. Navigate to **Sync queue** and switch on **Simulate offline**.
2. Create another synthetic screening; explain that a pseudonymous record stays in IndexedDB and the image/name do not enter the outbox.
3. Show the queued record and offline badge. Turn the simulation off and press **Sync**.
4. State: “This is a demo SQLite endpoint with idempotent IDs, not a production health-record exchange.”

### 3:00–3:30 — PHC and data transparency

1. Open **PHC dashboard** and show the synthetic record and referral brief.
2. Open **Model & data audit**. Explain that the available anemia CSV is small and contains a direct name field; names are not shipped. Mention the exploratory metrics only as grouped internal research results, not screening accuracy.
3. Explain that the inspected neonatal ZIP had no bilirubin label table, so no jaundice model was trained.

### 3:30–4:00 — Close with implementation status

> “The reusable pieces are the transparent local workflow, quality/feature utilities, offline persistence, FHIR-style export, and strict demo boundaries. This workspace does not contain an approved TFLite model or a verified native Android APK. We are not claiming clinical performance or replacing standard tests.”

Point to `docs/FINAL_DEMO_CHECKLIST.md` for build/test status and `docs/SAFETY.md` for the full limitations.

## Optional camera segment

For the PWA, camera/file pixels are local quality/feature visualizations only. For the Android source, if Camera2 works, capture an ambient preview snapshot and a brief torch-on preview snapshot; if flash is unavailable, show the ambient-only fallback. This is not a still-photo pair and does not lock ISO/exposure. Point out the manual geometric ROI and the local experimental F−A/RGB/Lab*/YCrCb panel; there is no MediaPipe landmark detector. A fixed fixture may follow only for a synthetic demo profile and remains `NOT FROM IMAGE`; do not use the camera to justify the value. Real/local profiles cannot run synthetic fixtures. If permission or preview fails, use the abstract synthetic color-chart pattern instead.

## Avoid saying

- “The camera measures hemoglobin/bilirubin.”
- “The AI detected anemia/jaundice,” “clinically accurate,” “validated,” or “ready for patient care.”
- “The confidence percentage is a probability of disease.”
- Any unmeasured latency, battery, memory, offline-reliability, or accuracy claim.
- “We trained on the supplied neonatal images” or “the Colab model is validated.”
- “This is an APK” unless a reproducible Android build succeeds and the resulting artifact is actually verified.
