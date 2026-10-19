# Clinical safety, privacy, and evidence boundary

**Status:** Hackathon prototype; not a medical device, clinical decision-support system, approved EHR, or diagnostic service.

## Non-negotiable use boundary

- Every Hb and bilirubin number in the demo is a fixed synthetic fixture chosen by the user. It is **not derived** from a person, image, camera pixels, optical features, or a clinically approved model.
- Demo risk tags are software examples only. They are not clinical risk categories, triage instructions, thresholds, or validated referral rules.
- Never use an app value to diagnose, reassure, triage, delay care, start/stop/change treatment, or override a clinician.
- Clinical confirmation must use appropriate established testing (for example, CBC for hemoglobin or serum bilirubin testing as appropriate) and qualified clinician review under local protocol. This prototype does not replace those services.
- Neonatal jaundice decisions depend on the exact age in hours, gestational age, symptoms, clinical condition, and applicable protocol. The synthetic examples do not calculate a treatment line or safe/unsafe threshold.
- If a real person needs assessment, follow local referral/emergency pathways; do not use the prototype as a source of medical advice.

## UI safeguards

- Persistent prototype ribbon and synthetic labels on workflow/result screens.
- The result page names the inference mode, states that the number did not come from pixels, and shows a safety note and confirmation step.
- A real/local patient profile may use camera quality and feature visualization only; the synthetic estimate action is disabled for that profile.
- Optical RGB/HSV/Lab/YCrCb summaries are uncalibrated engineering features. Manual ROI guides are not anatomical segmentation. Brightness/blur scores are not validated capture-quality standards.
- The PWA's flash/ambient concept is visualization-only. Native Android attempts sequential Camera2 preview snapshots with a brief torch toggle, but it does not lock exposure/ISO or synchronize still captures; its clipped F−A output is not clinical color correction or proven lighting invariance.
- No approved TFLite model is bundled. The optional TFLite interface does not guess tensor shape or output mapping in the absence of a model artifact and model card.
- Performance figures are not benchmarked. The README/model page labels the small research baseline precisely and does not promote it as accuracy for patient screening.

## Data handling

- Use the synthetic demo profile for presentations.
- Patient names/demographics in the optional local profile are stored in this browser's IndexedDB/localStorage only; browser storage is not encrypted by this prototype. Android's source-only Room database is also not encrypted. Do not store real patient information in either client. The browser camera/import image and Android Camera2 preview snapshots are held in memory during local processing and are not saved with a screening record. The current web app persists only minimal capture-source/quality metadata locally; the RGB/HSV/Lab feature vector is not persisted.
- The backend has no image-upload endpoint. `/api/counselling` does not accept image data or direct patient identifiers. `/api/sync` uses a pseudonymous patient ID and synthetic fixture fields only; the client strips local FHIR bundle/profile details before sync.
- Local JSON backup and local print/PDF may contain locally stored names if the operator elects to include them; handle such files as sensitive. Server-generated referral PDFs use the pseudonymous ID, not the local patient name.
- The backend has no authentication or access-control system. Do not expose it to public networks or use it for real patient data.
- The synthetic demo database has no approved clinical retention policy. Reset or delete local/demo data after a presentation.
- Gemini is optional. A server-side environment key is never returned to the client or written to logs. Only structured screening fields are sent, not images or patient names; the provider may still process the request under its own service terms. Review consent, provider terms, jurisdiction, and data-processing controls before enabling it.
- A previously exposed API key should be rotated through the provider. Never paste a replacement key into this repository, client code, or chat.

## Dataset and model evidence

- The supplied anemia CSV contained 104 rows and a direct `Name` field. The name/group field was used transiently only to group validation folds and is not present in the derived artifact. The five-fold grouped Ridge run on three precomputed RGB percentages yielded MAE **1.5041 g/dL**, RMSE **1.9392 g/dL**, R² **0.3987**. This is a small internal exploratory split, not independent or external validation, not prospective evidence, and not suitable for patient decisions.
- The inspected jaundice ZIP contained 478 JPEG files in Forehead/Sternum folders, with no discovered bilirubin label table. No jaundice model was trained or evaluated from these images.
- Dataset license, provenance, consent, ethics approvals, representativeness, and intended reuse are unverified. Do not redistribute, train further, publish, or claim validation without permission and review.
- The user's Colab notebook was inspected statically but not run. Its repeated draft code and Kaggle input assumptions are not evidence of a trained or validated model.
- Raw datasets and images are not part of this source tree or distributable package. See `dataset-audit.md` for the inspection summary.

## Human factors and implementation change review

Any future model, label, threshold, referral logic, measurement, or claim requires review by qualified clinical, data-protection, and regulatory stakeholders. At minimum, the team should maintain:

1. a documented intended use, excluded uses, user population, and escalation policy;
2. an evidence-backed model card and provenance/permission record;
3. representative external/temporal validation and subgroup analysis;
4. target-device/lighting robustness, repeatability, calibration, and uncertainty assessment;
5. usability testing with frontline workers and language review by fluent speakers;
6. security review, access control, data minimization, auditability, retention, and incident handling;
7. an appropriate regulatory and clinical governance pathway before any clinical deployment.

Until then, keep the synthetic-only boundary intact.
