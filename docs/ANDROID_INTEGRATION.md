# Android integration guide

For: the Android developer working in [`shubhamcore/AbhayNayan_apk`](https://github.com/shubhamcore/AbhayNayan_apk). Contract: [API_CONTRACT.md](API_CONTRACT.md), version `1.0.0`.

## 1. Which source is canonical

| Location | Status |
|---|---|
| `AbhayNayan_apk` → `AbhayNayan/android/` | **Canonical Android source.** It adds `OpticalPipeline.kt`, `DualPreviewCapture`, Room schema exports and `OpticalPipelineTest.kt`. Its `ARCHITECTURE.md` reports 19 passing unit tests and a debug APK build; that was not re-run in this audit. |
| This repo → `android/` | **Stale snapshot.** Example: `package in.abhaynayan.app` is not escaped, and `in` is a Kotlin keyword, so this copy will not compile. The canonical repo uses `` package `in`.abhaynayan.app ``. Do not develop here; this folder can be removed or replaced once the team agrees. |

## 2. Where the Android app stands against contract 1.0

Audited from commit `8f65b73` of `AbhayNayan_apk`.

| Area | Android today | Contract 1.0 | Action |
|---|---|---|---|
| Network | No `INTERNET` permission, no HTTP client; fully local | Optional sync, counselling and referral endpoints | Add `INTERNET` permission, an HTTP client and a `SyncWorker` only when sync is wanted. Keep the app usable offline |
| Demo tags | `REQUIRES_REVIEW` for `jaundice-review` | `DEMO_REVIEW` (all demo tags start `DEMO_`) | Rename. The server still accepts the old string |
| Confidence | `ModelPrediction.confidence = null` ✓; `DemoCase.confidencePlaceholder` and `ScreeningEntity.confidencePlaceholder` hold 0.76–0.82 | `confidence: null` for fixtures | Send `null`; drop or ignore the placeholder |
| Quality | `captureQualityProxy` stored on the screening | `result.quality_score` is `null` for fixtures; capture quality is device-local engineering metadata | Keep it local; do not send it as `quality_score` |
| Provenance | `modelMode = "DEMO"`, `synthetic = true` | Also `provenance: "DEMO_SYNTHETIC"`, `model_version: "fixed-demo-fixtures-v1"` | Add both fields (Room migration v1→v2) |
| Newborn age | Not on `ScreeningEntity` | `context.infant_age_hours` (0–8760) | Capture it in the neonatal flow and store it |
| Sync state | None | `sync_status`, `sync_attempts`, `last_sync_error` (§6 of the contract) | Add an outbox table or columns |
| IDs | `screeningId` chosen locally | Client id `scr-<uuid>`, reused on every retry | Use `UUID.randomUUID()` once at creation |
| Model adapter | `ScreeningModel` with `DemoScreeningModel` and fail-closed `MissingClinicalModel` ✓ | Same semantics: status `DISABLED_NO_VALID_MODEL` and no fallback to a fixture | Keep. Map `MissingClinicalModel` → `DISABLED_NO_VALID_MODEL` |
| FHIR preview | Local JSON | Server marks synthetic data `meta.security HTEST` and uses text-only codes | Mirror these tags in `FhirPreview.kt` |

## 3. Kotlin models (kotlinx.serialization)

```kotlin
@Serializable enum class Provenance { DEMO_SYNTHETIC, EXPERIMENTAL_RESEARCH_ONLY, VALIDATED_FOR_INTENDED_USE }

@Serializable data class PatientRef(
    @SerialName("patient_id") val patientId: String,   // pseudonymous only
    val demo: Boolean = true,
)

@Serializable data class ScreeningContext(
    @SerialName("infant_age_hours") val infantAgeHours: Int? = null,
    @SerialName("gestational_week") val gestationalWeek: Int? = null,
    val pregnancy: Boolean? = null,
)

@Serializable data class ScreeningResult(
    @SerialName("screening_type") val screeningType: String,          // "maternal_anemia" | "neonatal_jaundice"
    val estimate: Double,
    val unit: String,                                                  // "g/dL" | "mg/dL"
    @SerialName("risk_category") val riskCategory: String,
    val confidence: Double? = null,                                    // null = not produced
    @SerialName("quality_score") val qualityScore: Double? = null,
    @SerialName("requires_confirmation") val requiresConfirmation: Boolean = true,
    @SerialName("model_mode") val modelMode: String = "DEMO",
    val synthetic: Boolean = true,
    val provenance: Provenance = Provenance.DEMO_SYNTHETIC,
    @SerialName("model_version") val modelVersion: String? = null,
    @SerialName("case_id") val caseId: String? = null,
    @SerialName("case_label") val caseLabel: String? = null,
    @SerialName("generated_at") val generatedAt: String,               // ISO-8601 UTC
    val limitations: List<String> = emptyList(),
    @SerialName("safety_note") val safetyNote: String,
)

@Serializable data class ScreeningRecord(
    val id: String,                                                    // "scr-<uuid>", reused on retry
    val patient: PatientRef,
    val result: ScreeningResult,
    val context: ScreeningContext? = null,
    @SerialName("worker_id") val workerId: String = "demo-worker",
    val phc: String = "Demo PHC",
    val village: String? = null,                                       // send null
    @SerialName("created_at") val createdAt: String,
    @SerialName("id_origin") val idOrigin: String = "client",
    @SerialName("sync_status") val syncStatus: String = "queued",      // wire values: queued | synced
    @SerialName("fhir_bundle") val fhirBundle: JsonObject? = null,     // always send null
)

@Serializable data class ApiErrorBody(val code: String, val message: String, val status: Int,
                                      val retryable: Boolean = false, val fields: List<JsonObject> = emptyList())
@Serializable data class SyncItemResult(val id: String?, val status: String, val error: ApiErrorBody? = null)
@Serializable data class SyncResponse(val accepted: Int, val duplicate: Int, val conflict: Int = 0, val rejected: Int = 0,
                                      @SerialName("synced_ids") val syncedIds: List<String>,
                                      val results: List<SyncItemResult> = emptyList(),
                                      @SerialName("server_time") val serverTime: String)
```

Configure `Json { ignoreUnknownKeys = true; explicitNulls = true }`. Ignoring unknown keys is required for MINOR-version compatibility.

## 4. Sync algorithm (WorkManager)

```text
on screening saved:  insert ScreeningEntity(sync_status=queued, sync_attempts=0); enqueue unique work "abn-sync" (KEEP)
SyncWorker:
  batch = outbox.oldest(100)
  try   resp = POST /api/sync {records: batch.map(toWire)}
  catch IOException / 5xx / error.retryable -> for each: attempts++, last_error=msg; return Result.retry()  (exponential backoff)
  for item in batch:
    r = resp.results.first { it.id == item.id } ?: continue      // unacknowledged stays queued
    when (r.status) accepted, duplicate -> mark synced, remove from outbox
                    conflict, rejected   -> mark r.status, keep row, remove from outbox, store r.error.message
  return Result.success()
```

Constraints: `NetworkType.CONNECTED`. Run one unique work chain. Never delete the local row.

## 5. Model status and edge inference

Both adapters are `DISABLED_NO_VALID_MODEL` (see [ML_MODEL_CARD.md](ML_MODEL_CARD.md)). No model artifact suitable for on-device use exists. The notebook's MobileNetV3-Small was never exported and performed worse than predicting the mean. Until a model card changes this:

- Do not bundle a `.tflite` or show any pixel-derived number. Keep `MissingClinicalModel` fail-closed.
- Do not call `POST /api/screenings` with `inference_mode: "MODEL"` in production builds. It returns `503 MODEL_DISABLED`; show the adapter `reason` from `/api/model/status`.
- No latency, memory or 2–4 GB device compatibility figures have been measured. Do not state any.

A future on-device model must ship with: exact runtime and version, input tensor shape/normalisation, output unit and range, model version string, a measured latency and memory profile on named devices, and a model-card status. `ScreeningResult.provenance` then comes from that card.

## 6. Privacy rules for the app

- Camera frames stay on the device. There is no image upload endpoint.
- Never send names, phone numbers, villages, photos or free text to the server or Gemini. `patient_id` must be pseudonymous.
- The Gemini key lives only in server environment variables. Never put a key in `BuildConfig`, resources or code.
- Room data is not encrypted in the current source. Use synthetic profiles only until encryption (for example SQLCipher plus Android Keystore) is added.

## 7. Build status (carried over from the earlier `ANDROID_STATUS.md`)

- This repo's `android/` copy has a Gradle 8.13 wrapper. A CI job (`.github/workflows/ci.yml`) runs `:app:testDebugUnitTest :app:assembleDebug`; it has not been observed running for this repo.
- An earlier sandbox build reached resource/KSP tasks and then the Gradle daemon exited under low memory. No APK was produced there.
- The canonical repo reports a successful debug build and 19 unit tests. No emulator or device run has been documented.
- Build on a provisioned machine with JDK 17 and Android SDK 36: `cd android && ./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug`. Only call an APK verified after the command succeeds and the app has been installed and checked on a device.
