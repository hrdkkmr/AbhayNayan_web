package in.abhaynayan.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.foundation.Image
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.room.Room
import in.abhaynayan.app.core.DEMO_SAFETY_NOTE
import in.abhaynayan.app.core.DemoCase
import in.abhaynayan.app.core.DemoInference
import in.abhaynayan.app.core.DemoScreeningModel
import in.abhaynayan.app.core.LocalImageQuality
import in.abhaynayan.app.core.LocalScreeningResult
import in.abhaynayan.app.core.OpticalPipeline
import in.abhaynayan.app.core.OpticalPipelineResult
import in.abhaynayan.app.core.RgbImage
import in.abhaynayan.app.core.ScreeningType
import in.abhaynayan.app.data.AbhayDatabase
import in.abhaynayan.app.data.PatientEntity
import in.abhaynayan.app.data.ScreeningEntity
import in.abhaynayan.app.interop.buildLocalDemoBundle
import in.abhaynayan.app.services.CounselingSpeaker
import in.abhaynayan.app.vision.Camera2PreviewView
import in.abhaynayan.app.vision.DualPreviewCapture
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant

private val Navy = Color(0xFF123642)
private val Teal = Color(0xFF0B817D)
private val Canvas = Color(0xFFF4F8F8)
private val Body = Color(0xFF526A70)
private val Amber = Color(0xFFFFF4DF)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val database = Room.databaseBuilder(applicationContext, AbhayDatabase::class.java, "abhaynayan-local.db").build()
        setContent {
            MaterialTheme {
                AbhayNayanNativeApp(database)
            }
        }
    }
}

private enum class NativePage { HOME, SETUP, CAMERA, CASES, RESULT }

@Composable
private fun AbhayNayanNativeApp(database: AbhayDatabase) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val patients by database.patientDao().observeAll().collectAsState(initial = emptyList())
    val records by database.screeningDao().observeAll().collectAsState(initial = emptyList())
    val speaker = remember { CounselingSpeaker(context) }
    DisposableEffect(speaker) { onDispose { speaker.shutdown() } }

    var page by remember { mutableStateOf(NativePage.HOME) }
    var screeningType by remember { mutableStateOf(ScreeningType.MATERNAL_ANEMIA) }
    var profileName by remember { mutableStateOf("Synthetic Demo Patient") }
    var isSyntheticProfile by remember { mutableStateOf(true) }
    var consentRecorded by remember { mutableStateOf(true) }
    var selectedPatient by remember { mutableStateOf<PatientEntity?>(null) }
    var selectedCaseId by remember { mutableStateOf("maternal-normal") }
    var captured by remember { mutableStateOf(false) }
    var syntheticCapture by remember { mutableStateOf(false) }
    var regionConfirmed by remember { mutableStateOf(false) }
    var qualityScore by remember { mutableStateOf(0f) }
    var qualityReady by remember { mutableStateOf(false) }
    var opticalAudit by remember { mutableStateOf<OpticalPipelineResult?>(null) }
    var isProcessingCapture by remember { mutableStateOf(false) }
    var processingError by remember { mutableStateOf("") }
    var captureSource by remember { mutableStateOf("") }
    var captureNote by remember { mutableStateOf("") }
    var captureLatencyMs by remember { mutableStateOf(0L) }
    var localProcessingMs by remember { mutableStateOf(0L) }
    var lastFeatureCount by remember { mutableStateOf(0) }
    var lastCaptureSource by remember { mutableStateOf("") }
    var lastCaptureLatencyMs by remember { mutableStateOf(0L) }
    var lastLocalProcessingMs by remember { mutableStateOf(0L) }
    var captureJob by remember { mutableStateOf<Job?>(null) }
    var lastResult by remember { mutableStateOf<LocalScreeningResult?>(null) }
    var lastScreeningId by remember { mutableStateOf("") }
    var language by remember { mutableStateOf("en") }
    var showSafetyDialog by remember { mutableStateOf(false) }

    fun resetCaptureState() {
        captureJob?.cancel()
        captureJob = null
        captured = false
        syntheticCapture = false
        regionConfirmed = false
        qualityScore = 0f
        qualityReady = false
        opticalAudit = null
        isProcessingCapture = false
        processingError = ""
        captureSource = ""
        captureNote = ""
        captureLatencyMs = 0L
        localProcessingMs = 0L
    }

    fun analyzeCapture(ambient: RgbImage, flash: RgbImage?, source: String, latencyMs: Long, note: String, isSynthetic: Boolean) {
        captured = true
        syntheticCapture = isSynthetic
        regionConfirmed = false
        qualityScore = 0f
        qualityReady = false
        opticalAudit = null
        processingError = ""
        captureSource = source
        captureLatencyMs = latencyMs
        captureNote = note
        isProcessingCapture = true
        captureJob?.cancel()
        captureJob = scope.launch {
            try {
                val startedAt = SystemClock.elapsedRealtimeNanos()
                val (quality, result) = withContext(Dispatchers.Default) {
                    val measuredQuality = LocalImageQuality.measure(ambient.width, ambient.height) { x, y -> ambient.pixel(x, y) }
                    val processed = OpticalPipeline.process(ambient, flash)
                    measuredQuality to processed
                }
                localProcessingMs = ((SystemClock.elapsedRealtimeNanos() - startedAt) / 1_000_000L).coerceAtLeast(0L)
                qualityScore = quality.qualityScore.toFloat()
                qualityReady = quality.readyBeforeManualConfirmation
                regionConfirmed = isSynthetic && quality.readyBeforeManualConfirmation
                opticalAudit = result
                if (!quality.readyBeforeManualConfirmation) {
                    processingError = when {
                        quality.brightnessMean < 32 -> "Improve lighting and capture again."
                        quality.brightnessMean > 228 -> "Reduce glare or direct sunlight and capture again."
                        else -> "Hold the phone steady and capture a sharper frame."
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                qualityReady = false
                regionConfirmed = false
                processingError = error.message?.takeIf { it.isNotBlank() } ?: "Local image processing failed. Retry the capture."
            } finally {
                isProcessingCapture = false
            }
        }
    }

    LaunchedEffect(Unit) {
        if (database.patientDao().count() == 0) {
            database.patientDao().upsert(PatientEntity("ABH-ANDROID-0001", "Synthetic Demo Patient", true, true, Instant.now().toString()))
        }
    }
    LaunchedEffect(patients) { if (selectedPatient == null) selectedPatient = patients.firstOrNull() }

    Scaffold(containerColor = Canvas, topBar = {
        Column(Modifier.fillMaxWidth().background(Navy).padding(horizontal = 18.dp, vertical = 13.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Column {
                    Text("ABHAYNAYAN", color = Color.White, fontWeight = FontWeight.ExtraBold, letterSpacing = 1.7.sp, fontSize = 16.sp)
                    Text("FRONTLINE SCREENING · ANDROID SOURCE PROTOTYPE", color = Color(0xFFA9D9CE), fontSize = 9.sp, letterSpacing = 1.sp)
                }
                Text("DEMO ONLY", color = Color(0xFFE7F7F0), fontSize = 9.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(Color(0xFF285A5D), RoundedCornerShape(20.dp)).padding(horizontal = 10.dp, vertical = 6.dp))
            }
        }
    }) { inset ->
        Column(Modifier.fillMaxSize().padding(inset).padding(horizontal = 16.dp, vertical = 13.dp)) {
            when (page) {
                NativePage.HOME -> NativeHome(
                    records = records,
                    onNew = { resetCaptureState(); page = NativePage.SETUP },
                    onSafety = { showSafetyDialog = true },
                    onOpenResult = { row ->
                        lastScreeningId = row.screeningId
                        val fixture = DemoInference.cases(ScreeningType.entries.firstOrNull { it.wireName == row.screeningType } ?: ScreeningType.MATERNAL_ANEMIA)
                            .firstOrNull { it.demoTag == row.demoTag } ?: DemoInference.cases(ScreeningType.MATERNAL_ANEMIA).first()
                        lastResult = LocalScreeningResult(ScreeningType.entries.firstOrNull { it.wireName == row.screeningType } ?: ScreeningType.MATERNAL_ANEMIA, fixture)
                        selectedPatient = patients.firstOrNull { it.patientId == row.patientId }
                        lastFeatureCount = 0
                        lastCaptureSource = "Not retained in history"
                        lastCaptureLatencyMs = 0L
                        lastLocalProcessingMs = 0L
                        page = NativePage.RESULT
                    },
                )
                NativePage.SETUP -> NativeSetup(
                    profileName = profileName,
                    onNameChange = { profileName = it; selectedPatient = null },
                    isSynthetic = isSyntheticProfile,
                    onSyntheticChange = { isSyntheticProfile = it; selectedPatient = null },
                    consent = consentRecorded,
                    onConsentChange = { consentRecorded = it; selectedPatient = null },
                    screeningType = screeningType,
                    onTypeChange = { type -> screeningType = type; selectedCaseId = DemoInference.cases(type).first().id },
                    existingPatients = patients,
                    selectedPatient = selectedPatient,
                    onSelectPatient = { person -> selectedPatient = person; profileName = person.displayName; isSyntheticProfile = person.isSyntheticDemo; consentRecorded = person.consentRecorded },
                    onContinue = {
                        if (!consentRecorded || profileName.isBlank()) return@NativeSetup
                        scope.launch {
                            val existing = patients.firstOrNull { it.patientId == selectedPatient?.patientId }
                            val patient = existing ?: PatientEntity(
                                patientId = "ABH-ANDROID-${(patients.size + 1).toString().padStart(4, '0')}",
                                displayName = profileName.trim(), isSyntheticDemo = isSyntheticProfile,
                                consentRecorded = consentRecorded, createdAtUtc = Instant.now().toString(),
                            ).also { database.patientDao().upsert(it) }
                            selectedPatient = patient
                            page = NativePage.CAMERA
                        }
                    },
                    onBack = { page = NativePage.HOME },
                )
                NativePage.CAMERA -> NativeCameraStep(
                    type = screeningType,
                    qualityScore = qualityScore,
                    captured = captured,
                    syntheticCapture = syntheticCapture,
                    regionConfirmed = regionConfirmed,
                    qualityReady = qualityReady,
                    opticalAudit = opticalAudit,
                    isProcessing = isProcessingCapture,
                    processingError = processingError,
                    captureSource = captureSource,
                    captureNote = captureNote,
                    captureLatencyMs = captureLatencyMs,
                    localProcessingMs = localProcessingMs,
                    onRegionConfirmed = { regionConfirmed = it },
                    onCapture = { frames ->
                        try {
                            val ambient = frames.ambient.toRgbImage()
                            val flash = frames.flash?.toRgbImage()
                            frames.ambient.recycle()
                            frames.flash?.recycle()
                            analyzeCapture(ambient, flash, "Camera2 preview snapshot", frames.elapsedMs, frames.note, false)
                        } catch (error: Exception) {
                            frames.ambient.recycle()
                            frames.flash?.recycle()
                            processingError = error.message ?: "Could not read the local camera frame. Retry."
                            qualityReady = false
                            captured = true
                        }
                    },
                    onSynthetic = {
                        val (ambient, flash) = OpticalPipeline.createAbstractDemoPair()
                        analyzeCapture(ambient, flash, "Abstract synthetic color-chart pattern", 0L, "Synthetic test pixels only; not an anatomical image.", true)
                    },
                    onBack = { resetCaptureState(); page = NativePage.SETUP },
                    onContinue = { if (!isProcessingCapture && opticalAudit != null) page = NativePage.CASES },
                )
                NativePage.CASES -> NativeCaseStep(
                    type = screeningType,
                    cases = DemoInference.cases(screeningType),
                    selectedCaseId = selectedCaseId,
                    canRun = selectedPatient?.isSyntheticDemo == true && captured && !isProcessingCapture && opticalAudit != null && qualityReady && regionConfirmed,
                    onSelect = { selectedCaseId = it },
                    onBack = { page = NativePage.CAMERA },
                    onRun = {
                        val person = selectedPatient
                        if (person == null || !person.isSyntheticDemo || !captured || isProcessingCapture || opticalAudit == null || !qualityReady || !regionConfirmed) return@NativeCaseStep
                        val selectedFixture = DemoInference.byId(screeningType, selectedCaseId)
                        val demoModel = DemoScreeningModel(screeningType)
                        val modelStatus = demoModel.load()
                        if (!modelStatus.available) return@NativeCaseStep
                        val prediction = try {
                            demoModel.predict(selectedCaseId)
                        } catch (_: Exception) {
                            return@NativeCaseStep
                        } finally {
                            demoModel.close()
                        }
                        if (!prediction.synthetic || prediction.caseId != selectedFixture.id || prediction.value != selectedFixture.estimate || prediction.unit != selectedFixture.unit) return@NativeCaseStep
                        val result = LocalScreeningResult(screeningType, selectedFixture, modelVersion = prediction.modelVersion)
                        val screeningId = "scr-${java.util.UUID.randomUUID()}"
                        scope.launch {
                            database.screeningDao().insert(ScreeningEntity(
                                screeningId = screeningId, patientId = person.patientId,
                                screeningType = screeningType.wireName, estimate = result.demoCase.estimate,
                                unit = result.demoCase.unit, demoTag = result.demoCase.demoTag,
                                confidencePlaceholder = result.demoCase.confidencePlaceholder,
                                captureQualityProxy = qualityScore.toDouble(), modelMode = "DEMO",
                                synthetic = true, confirmationRequired = true, createdAtUtc = result.generatedAtUtc,
                            ))
                        }
                        lastFeatureCount = opticalAudit?.features?.featureCount ?: 0
                        lastCaptureSource = captureSource
                        lastCaptureLatencyMs = captureLatencyMs
                        lastLocalProcessingMs = localProcessingMs
                        opticalAudit = null // release the temporary frame buffers after local review
                        lastResult = result; lastScreeningId = screeningId; page = NativePage.RESULT
                    },
                )
                NativePage.RESULT -> {
                    val result = lastResult
                    if (result == null) NativeEmptyResult(onBack = { page = NativePage.HOME }) else NativeResult(
                        patient = selectedPatient, result = result, screeningId = lastScreeningId,
                        qualityScore = qualityScore, language = language,
                        captureSource = lastCaptureSource,
                        captureLatencyMs = lastCaptureLatencyMs,
                        localProcessingMs = lastLocalProcessingMs,
                        featureCount = lastFeatureCount,
                        onLanguage = { language = it }, onSpeak = { text -> speaker.speak(text, language) },
                        onShareFhir = {
                            selectedPatient?.let { person -> shareText(context, "AbhayNayan prototype FHIR Bundle", buildLocalDemoBundle(person, result, lastScreeningId)) }
                        },
                        onShareReferral = { shareText(context, "AbhayNayan prototype referral", referralText(selectedPatient, result)) },
                        onNew = { resetCaptureState(); page = NativePage.SETUP },
                        onHome = { page = NativePage.HOME },
                    )
                }
            }
        }
    }
    if (showSafetyDialog) {
        AlertDialog(onDismissRequest = { showSafetyDialog = false },
            title = { Text("Prototype safety boundary") },
            text = { Text("All numerical values are selected synthetic fixtures, not clinical measurements. This app does not diagnose, triage, or replace CBC, serum bilirubin testing, or clinician review. Camera frames remain in local memory and are not saved.") },
            confirmButton = { TextButton(onClick = { showSafetyDialog = false }) { Text("Understood") } })
    }
}

@Composable
private fun NativeHome(
    records: List<ScreeningEntity>,
    onNew: () -> Unit,
    onSafety: () -> Unit,
    onOpenResult: (ScreeningEntity) -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxSize()) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Navy), shape = RoundedCornerShape(20.dp)) {
                Column(Modifier.padding(20.dp)) {
                    Text("Bringing AI-assisted screening and clinical guidance to the doorstep.", color = Color.White, fontSize = 21.sp, fontWeight = FontWeight.Bold, lineHeight = 27.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Native Kotlin / Compose prototype · local Camera2 processing · Room demo records", color = Color(0xFFC8E4DE), fontSize = 11.sp)
                    Spacer(Modifier.height(15.dp))
                    Button(onClick = onNew, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE2F5EC), contentColor = Navy)) { Text("＋ Start a synthetic demo") }
                }
            }
        }
        item { SafetyCard(onSafety) }
        item { Text("Local screening history", color = Navy, fontWeight = FontWeight.Bold, fontSize = 15.sp) }
        if (records.isEmpty()) item { InfoCard("No screenings on this device yet. Use the abstract synthetic image to explore a disconnected fixture demo.") }
        items(records, key = { it.screeningId }) { row ->
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFDCE7E8))) {
                Row(Modifier.fillMaxWidth().padding(13.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${row.screeningType.replace('_', ' ')} · ${row.patientId}", color = Navy, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Text("${"%.1f".format(row.estimate)} ${row.unit} · ${row.demoTag} · DEMO", color = Body, fontSize = 10.sp)
                    }
                    TextButton(onClick = { onOpenResult(row) }) { Text("Review") }
                }
            }
        }
    }
}

@Composable
private fun NativeSetup(
    profileName: String,
    onNameChange: (String) -> Unit,
    isSynthetic: Boolean,
    onSyntheticChange: (Boolean) -> Unit,
    consent: Boolean,
    onConsentChange: (Boolean) -> Unit,
    screeningType: ScreeningType,
    onTypeChange: (ScreeningType) -> Unit,
    existingPatients: List<PatientEntity>,
    selectedPatient: PatientEntity?,
    onSelectPatient: (PatientEntity) -> Unit,
    onContinue: () -> Unit,
    onBack: () -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("1 · Patient & pathway", "Choose a local patient and screening workflow") }
        if (existingPatients.isNotEmpty()) item {
            Column {
                Text("Existing local profiles", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                existingPatients.take(4).forEach { person ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = selectedPatient?.patientId == person.patientId, onClick = { onSelectPatient(person) })
                        Column {
                            Text(person.displayName, color = Navy, fontSize = 11.sp)
                            Text("${person.patientId} · ${if (person.isSyntheticDemo) "synthetic demo" else "local only"}", color = Body, fontSize = 9.sp)
                        }
                    }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    Text("Create / use profile on device", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    OutlinedTextField(value = profileName, onValueChange = onNameChange, label = { Text("Display name · local only") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Switch(checked = isSynthetic, onCheckedChange = onSyntheticChange)
                        Spacer(Modifier.width(8.dp))
                        Column { Text("Synthetic demo profile", color = Navy, fontSize = 11.sp, fontWeight = FontWeight.Bold); Text("Turn off for a real/local profile; demo estimate will be disabled.", color = Body, fontSize = 9.sp) }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = consent, onCheckedChange = onConsentChange)
                        Text("I consent to storing this profile locally on this device.", color = Body, fontSize = 10.sp)
                    }
                }
            }
        }
        item {
            Text("Select pathway", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            ScreeningType.entries.forEach { type ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = screeningType == type, onClick = { onTypeChange(type) })
                    Column {
                        Text(type.displayName, color = Navy, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                        Text(if (type == ScreeningType.MATERNAL_ANEMIA) "Manual conjunctiva guide · synthetic Hb fixture" else "Manual sclera guide · synthetic bilirubin fixture", color = Body, fontSize = 9.sp)
                    }
                }
            }
        }
        item { InfoCard("Profile fields are stored using Room on this device. The current native prototype has no network permission or image-upload path.") }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text("Back") }
                Button(onClick = onContinue, enabled = consent && profileName.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Continue →") }
            }
        }
    }
}

@Composable
private fun NativeCameraStep(
    type: ScreeningType,
    qualityScore: Float,
    captured: Boolean,
    syntheticCapture: Boolean,
    regionConfirmed: Boolean,
    qualityReady: Boolean,
    opticalAudit: OpticalPipelineResult?,
    isProcessing: Boolean,
    processingError: String,
    captureSource: String,
    captureNote: String,
    captureLatencyMs: Long,
    localProcessingMs: Long,
    onRegionConfirmed: (Boolean) -> Unit,
    onCapture: (DualPreviewCapture) -> Unit,
    onSynthetic: () -> Unit,
    onBack: () -> Unit,
    onContinue: () -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(11.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("2 · Camera & quality", type.displayName) }
        item { Camera2CapturePanel(onCapture = onCapture, onSynthetic = onSynthetic, isProcessing = isProcessing) }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFDCE7E8))) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Local engineering checks", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        val status = when {
                            isProcessing -> "PROCESSING"
                            captured && qualityReady && regionConfirmed -> "REVIEW READY"
                            captured && qualityReady -> "CONFIRM ROI"
                            captured -> "RETRY"
                            else -> "WAITING"
                        }
                        Text(status, color = if (captured && qualityReady && regionConfirmed && !isProcessing) Teal else Color(0xFFAA6D1E), fontWeight = FontWeight.Bold, fontSize = 10.sp)
                    }
                    if (isProcessing) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = Teal)
                            Text("Checking local pixels and extracting the manual ROI…", color = Body, fontSize = 10.sp)
                        }
                    }
                    if (captured && !isProcessing) {
                        Text("Brightness/edge engineering proxy: ${(qualityScore * 100).toInt()}% · not a clinical quality metric", color = Body, fontSize = 10.sp)
                        Text("Source: $captureSource${if (captureLatencyMs > 0) " · capture sequence ${captureLatencyMs} ms" else ""}", color = Body, fontSize = 9.sp)
                        if (captureNote.isNotBlank()) Text(captureNote, color = Body, fontSize = 9.sp)
                        if (processingError.isNotBlank()) Text(processingError, color = Color(0xFF9A4E21), fontWeight = FontWeight.SemiBold, fontSize = 10.sp)
                        if (!syntheticCapture && qualityReady) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = regionConfirmed, onCheckedChange = onRegionConfirmed, enabled = qualityReady)
                                Text("I manually confirm the ${if (type == ScreeningType.MATERNAL_ANEMIA) "lower-eyelid guide" else "eye-region guide"} is positioned. No face/eye landmark model is installed.", color = Body, fontSize = 9.sp)
                            }
                        }
                        if (syntheticCapture) Text("Abstract synthetic color chart · not an eye, patient, or anatomical image. ROI is geometric only.", color = Body, fontSize = 9.sp)
                        if (localProcessingMs > 0) Text("Local image processing: ${localProcessingMs} ms · this is not model-inference time", color = Body, fontSize = 9.sp)
                    } else if (!captured) Text("No frame captured yet. Live Camera2 frames stay in memory and are not saved or uploaded.", color = Body, fontSize = 10.sp)
                    Text("Face/eyes, blink, distance, and motion detection are not implemented. This basic brightness/edge check and manual region confirmation are not a validated capture gate.", color = Body, fontSize = 9.sp)
                }
            }
        }
        if (opticalAudit != null) item {
            val audit = opticalAudit
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFDCE7E8))) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Developer view · local optical pipeline", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    Text("Ambient-light compensation prototype · exploratory F−A preview difference; not mathematically invariant or clinically calibrated.", color = Body, fontSize = 9.sp)
                    if (audit != null) {
                        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            RgbPreviewTile("Ambient", audit.ambient)
                            RgbPreviewTile("Flash", audit.flash ?: audit.ambient, note = if (audit.flash == null) "fallback" else "")
                            RgbPreviewTile("Compensated", audit.compensated)
                            RgbPreviewTile("Manual ROI", audit.roi)
                        }
                        Text(audit.note, color = Body, fontSize = 9.sp)
                        val f = audit.features
                        Text("RGB mean ${"%.1f".format(f.rMean)} / ${"%.1f".format(f.gMean)} / ${"%.1f".format(f.bMean)} · ratios R/G ${"%.3f".format(f.rOverG)}, R/B ${"%.3f".format(f.rOverB)}, G/B ${"%.3f".format(f.gOverB)}", color = Navy, fontSize = 9.sp)
                        Text("CIE Lab* ${"%.1f".format(f.labLStar)} / ${"%.1f".format(f.labAStar)} / ${"%.1f".format(f.labBStar)} · YCrCb ${"%.1f".format(f.yMean)} / ${"%.1f".format(f.crMean)} / ${"%.1f".format(f.cbMean)}", color = Navy, fontSize = 9.sp)
                        Text("RGB SD ${"%.1f".format(f.rStdDev)} / ${"%.1f".format(f.gStdDev)} / ${"%.1f".format(f.bStdDev)} · chromaticity ${"%.3f".format(f.chromaticityR)} / ${"%.3f".format(f.chromaticityG)} / ${"%.3f".format(f.chromaticityB)}", color = Navy, fontSize = 9.sp)
                        Text("${f.featureCount} engineering features · valid pixels ${"%.1f".format(f.validPixelPercent)}% · ${f.sampleCount} pixels · not supplied to clinical inference", color = Body, fontSize = 9.sp)
                    }
                }
            }
        }
        item { SafetyCard(onClick = {}) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text("Back") }
                Button(onClick = onContinue, enabled = captured && !isProcessing && opticalAudit != null && qualityReady && regionConfirmed, modifier = Modifier.weight(1f)) { Text("Review demo cases →") }
            }
        }
    }
}

@Composable
private fun Camera2CapturePanel(onCapture: (DualPreviewCapture) -> Unit, onSynthetic: () -> Unit, isProcessing: Boolean) {
    val context = LocalContext.current
    var permissionGranted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    var preview by remember { mutableStateOf<Camera2PreviewView?>(null) }
    var captureBusy by remember { mutableStateOf(false) }
    var cameraMessage by remember { mutableStateOf("") }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permissionGranted = it }
    DisposableEffect(preview) { onDispose { preview?.close() } }
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF102B31)), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
            if (permissionGranted) {
                Box(Modifier.fillMaxWidth().height(230.dp), contentAlignment = Alignment.Center) {
                    AndroidView(factory = { ctx -> Camera2PreviewView(ctx).also { preview = it; it.start() } }, modifier = Modifier.fillMaxSize(), update = {})
                    Box(Modifier.fillMaxWidth(.72f).height(72.dp).border(2.dp, Color(0xFFE2C878), RoundedCornerShape(30.dp)))
                    Text(if (preview == null) "Opening local Camera2 preview…" else "MANUAL TARGET GUIDE · NO LANDMARKS", color = Color.White, fontSize = 9.sp,
                        modifier = Modifier.align(Alignment.BottomCenter).background(Color(0x990C272D), RoundedCornerShape(20.dp)).padding(horizontal = 10.dp, vertical = 5.dp))
                }
                Text("Best-effort ambient + flash preview snapshots. Auto exposure remains enabled; not a locked still-photo pair.", color = Color(0xFFD4E5E2), fontSize = 9.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        cameraMessage = ""
                        captureBusy = true
                        val activePreview = preview
                        if (activePreview == null) {
                            captureBusy = false
                            cameraMessage = "Camera is not ready. Retry or use the synthetic pattern."
                        } else {
                            activePreview.captureDualPreviewFrames { capture ->
                                captureBusy = false
                                if (capture == null) cameraMessage = "No camera preview frame was available. Check permission and retry."
                                else {
                                    cameraMessage = capture.note
                                    onCapture(capture)
                                }
                            }
                        }
                    }, enabled = !captureBusy && !isProcessing, modifier = Modifier.weight(1f)) {
                        Text(if (captureBusy) "CAPTURING…" else "Capture / retry ambient + flash")
                    }
                    OutlinedButton(onClick = onSynthetic, enabled = !captureBusy && !isProcessing, modifier = Modifier.weight(1f)) { Text("Use synthetic pattern") }
                }
                if (captureBusy) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp, color = Color(0xFFA9D9CE))
                    Text("Ambient frame ✓ · preparing flash frame…", color = Color.White, fontSize = 9.sp)
                }
                if (cameraMessage.isNotBlank()) Text(cameraMessage, color = Color(0xFFD4E5E2), fontSize = 9.sp)
            } else {
                Text("Camera permission is optional. The offline abstract pattern still exercises the local processing pipeline.", color = Color.White, fontSize = 10.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }, modifier = Modifier.weight(1f)) { Text("Allow Camera2") }
                    OutlinedButton(onClick = onSynthetic, enabled = !isProcessing, modifier = Modifier.weight(1f)) { Text("Use synthetic pattern") }
                }
            }
        }
    }
}

@Composable
private fun RgbPreviewTile(title: String, image: RgbImage, note: String = "") {
    val bitmap = remember(image) { Bitmap.createBitmap(image.pixels, image.width, image.height, Bitmap.Config.ARGB_8888) }
    val imageBitmap = remember(bitmap) { bitmap.asImageBitmap() }
    DisposableEffect(bitmap) { onDispose { if (!bitmap.isRecycled) bitmap.recycle() } }
    Column(Modifier.width(112.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(title, color = Navy, fontWeight = FontWeight.Bold, fontSize = 9.sp)
        Image(imageBitmap, contentDescription = "$title local pixel preview", contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().height(70.dp).background(Color(0xFFE7EEEE), RoundedCornerShape(6.dp)))
        if (note.isNotBlank()) Text(note, color = Body, fontSize = 8.sp)
    }
}

private fun Bitmap.toRgbImage(): RgbImage {
    val argb = IntArray(width * height)
    getPixels(argb, 0, width, 0, 0, width, height)
    return RgbImage(width, height, argb)
}

@Composable
private fun NativeCaseStep(
    type: ScreeningType,
    cases: List<DemoCase>,
    selectedCaseId: String,
    canRun: Boolean,
    onSelect: (String) -> Unit,
    onBack: () -> Unit,
    onRun: () -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("3 · Choose a fixed demo fixture", type.displayName) }
        item { InfoCard("Demo mode only: the fixed synthetic value is selected separately from the image. Camera pixels and extracted features are not used to calculate it; no clinical model is bundled.") }
        items(cases, key = { it.id }) { item ->
            Card(colors = CardDefaults.cardColors(containerColor = if (selectedCaseId == item.id) Color(0xFFF0F8F5) else Color.White), border = BorderStroke(1.dp, if (selectedCaseId == item.id) Teal else Color(0xFFDCE7E8))) {
                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = selectedCaseId == item.id, onClick = { onSelect(item.id) })
                    Column(Modifier.weight(1f)) {
                        Text(item.label, color = Navy, fontWeight = FontWeight.Bold, fontSize = 11.sp)
                        Text("${"%.1f".format(item.estimate)} ${item.unit} · ${item.demoTag} · FIXED SYNTHETIC", color = Body, fontSize = 9.sp)
                    }
                }
            }
        }
        item {
            if (!canRun) SafetyCard(onClick = {}) else InfoCard("Eligible because this is a synthetic demo profile and the local image review gate passed. The fixed case is independent of camera pixels and features.")
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text("Back") }
                Button(onClick = onRun, enabled = canRun, modifier = Modifier.weight(1f)) { Text("Run fixed demo") }
            }
        }
    }
}

@Composable
private fun NativeResult(
    patient: PatientEntity?,
    result: LocalScreeningResult,
    screeningId: String,
    qualityScore: Float,
    language: String,
    captureSource: String,
    captureLatencyMs: Long,
    localProcessingMs: Long,
    featureCount: Int,
    onLanguage: (String) -> Unit,
    onSpeak: (String) -> Unit,
    onShareFhir: () -> Unit,
    onShareReferral: () -> Unit,
    onNew: () -> Unit,
    onHome: () -> Unit,
) {
    val copy = counseling(result.screeningType, language)
    val qualityLabel = if (captureSource == "Not retained in history") "not retained in history" else "${(qualityScore * 100).toInt()}% engineering proxy"
    LazyColumn(verticalArrangement = Arrangement.spacedBy(11.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("SYNTHETIC FIXTURE · ${result.screeningType.displayName}", "Demo estimate — not a diagnosis") }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Navy), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(20.dp)) {
                    Text("FIXED DEMO VALUE · NOT FROM IMAGE", color = Color(0xFFA9D9CE), fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = .8.sp)
                    Text("${"%.1f".format(result.demoCase.estimate)} ${result.demoCase.unit}", color = Color.White, fontSize = 37.sp, fontWeight = FontWeight.ExtraBold)
                    Text(result.demoCase.label, color = Color(0xFFD2E7E1), fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("${result.demoCase.demoTag} · ${result.modelMode} · ${patient?.patientId ?: "local demo"}", color = Color(0xFFA9D9CE), fontSize = 10.sp)
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Amber), border = BorderStroke(1.dp, Color(0xFFEBDDBD))) {
                Column(Modifier.padding(13.dp)) {
                    Text("SAFETY NOTICE", color = Color(0xFF705322), fontWeight = FontWeight.ExtraBold, fontSize = 10.sp)
                    Spacer(Modifier.height(4.dp))
                    Text(DEMO_SAFETY_NOTE, color = Color(0xFF705322), fontSize = 10.sp)
                    Text("This value was selected from a fixed fixture, not computed from the camera or a patient image. Do not use it to diagnose, triage, delay care, or change treatment.", color = Color(0xFF705322), fontSize = 10.sp)
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Counselling · deterministic local fallback", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                        listOf("en" to "English", "hi" to "हिन्दी", "bho" to "भोजपुरी").forEach { (code, label) ->
                            val colors = if (language == code) ButtonDefaults.buttonColors(containerColor = Teal) else ButtonDefaults.outlinedButtonColors()
                            if (language == code) Button(onClick = { onLanguage(code) }, colors = colors, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 4.dp)) { Text(label, fontSize = 9.sp) }
                            else OutlinedButton(onClick = { onLanguage(code) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 4.dp)) { Text(label, fontSize = 9.sp) }
                        }
                    }
                    Text(copy, color = Body, fontSize = 11.sp, lineHeight = 17.sp)
                    OutlinedButton(onClick = { onSpeak(copy) }) { Text("▶ Speak with on-device TTS") }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("Local workflow audit", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    Text("Capture: ${captureSource.ifBlank { "not retained in history" }} · simple brightness/edge ${qualityLabel} · manual ROI only; no face/eye landmarks.", color = Body, fontSize = 10.sp)
                    Text("Measured capture sequence: ${if (captureLatencyMs > 0) "$captureLatencyMs ms" else "not stored"} · local image pipeline: ${if (localProcessingMs > 0) "$localProcessingMs ms" else "not stored"} · feature count: ${if (featureCount > 0) featureCount else "not retained"}. These are not model-inference timings; the fixed fixture is independent of image pixels.", color = Body, fontSize = 9.sp)
                    Text("Temporary frames were held only in memory and are not stored with this record. Screening ID: $screeningId", color = Body, fontSize = 9.sp)
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(onClick = onShareFhir, modifier = Modifier.weight(1f)) { Text("Share FHIR JSON", fontSize = 9.sp) }
                OutlinedButton(onClick = onShareReferral, modifier = Modifier.weight(1f)) { Text("Share referral brief", fontSize = 9.sp) }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onHome, modifier = Modifier.weight(1f)) { Text("Home") }
                Button(onClick = onNew, modifier = Modifier.weight(1f)) { Text("New demo") }
            }
        }
    }
}

@Composable
private fun NativeEmptyResult(onBack: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("No result selected", color = Navy, fontWeight = FontWeight.Bold)
        OutlinedButton(onClick = onBack) { Text("Back to home") }
    }
}

@Composable
private fun SafetyCard(onClick: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Amber), border = BorderStroke(1.dp, Color(0xFFEBDDBD)), onClick = onClick) {
        Column(Modifier.padding(12.dp)) {
            Text("PROTOTYPE · NOT FOR CLINICAL DECISIONS", color = Color(0xFF705322), fontWeight = FontWeight.ExtraBold, fontSize = 9.sp)
            Text("Synthetic estimates are not lab results or validated measurements. Confirm with appropriate clinical testing and qualified clinicians under local protocol.", color = Color(0xFF705322), fontSize = 9.sp)
        }
    }
}

@Composable
private fun InfoCard(text: String) {
    Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFEFF8F6)), border = BorderStroke(1.dp, Color(0xFFD5EBE5))) {
        Text(text, Modifier.padding(12.dp), color = Body, fontSize = 10.sp, lineHeight = 15.sp)
    }
}

@Composable
private fun StepTitle(eyebrow: String, title: String) {
    Column(Modifier.padding(vertical = 4.dp)) {
        Text(eyebrow.uppercase(), color = Teal, fontSize = 9.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 1.sp)
        Text(title, color = Navy, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

private fun counseling(type: ScreeningType, language: String): String = when (type) {
    ScreeningType.MATERNAL_ANEMIA -> when (language) {
        "hi" -> "यह केवल कृत्रिम डेमो अनुमान है, लैब रिपोर्ट या निदान नहीं। स्वास्थ्य केंद्र में उपयुक्त जांच से पुष्टि करें और स्थानीय मातृ-स्वास्थ्य प्रोटोकॉल का पालन करें। इस डेमो मान से दवा शुरू, बंद या न बदलें।"
        "bho" -> "ई खाली कृत्रिम डेमो के अंदाजा बा, लैब रिपोर्ट भा निदान नइखे। स्वास्थ्य केंद्र पर उचित जांच से पुष्टि कराईं आ स्थानीय मातृ-स्वास्थ्य नियम मानीं। एह मान से दवाई शुरू, बंद भा बदलीं मत।"
        else -> "This is a synthetic demo estimate, not a lab result or diagnosis. Confirm with appropriate testing and local maternal-care protocol. Do not start, stop, or change treatment based on this demo value."
    }
    ScreeningType.NEONATAL_JAUNDICE -> when (language) {
        "hi" -> "यह कृत्रिम डेमो अनुमान है, सीरम बिलीरुबिन रिपोर्ट या निदान नहीं। नवजात की समीक्षा उसकी सही उम्र, गर्भकाल, लक्षण और स्थानीय प्रोटोकॉल पर निर्भर करती है। योग्य चिकित्सक से शीघ्र समीक्षा और उपयुक्त जांच कराएं।"
        "bho" -> "ई कृत्रिम डेमो के अंदाजा बा, सीरम बिलीरुबिन जांच भा निदान नइखे। नवजात के जांच ओकर सही उमिर, जनम के समय, लक्षण आ स्थानीय नियम पर निर्भर बा। योग्य डॉक्टर से जल्दी समीक्षा आ उचित जांच कराईं।"
        else -> "This is a synthetic demo estimate, not a serum bilirubin result or diagnosis. Newborn review depends on exact age, gestational age, symptoms, and local protocol. Arrange qualified clinician review and appropriate testing."
    }
}

private fun referralText(patient: PatientEntity?, result: LocalScreeningResult): String = buildString {
    appendLine("ABHAYNAYAN · PROTOTYPE REFERRAL BRIEF")
    appendLine("Patient ID: ${patient?.patientId ?: "local demo"}")
    appendLine("${result.screeningType.displayName}: ${"%.1f".format(result.demoCase.estimate)} ${result.demoCase.unit}")
    appendLine("Demo tag: ${result.demoCase.demoTag} · mode ${result.modelMode}")
    appendLine("Next step: confirm with appropriate clinical testing and qualified clinician review under local protocol.")
    appendLine(result.safetyNote)
}

private fun shareText(context: android.content.Context, title: String, content: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, title)
        putExtra(Intent.EXTRA_TEXT, content)
    }
    context.startActivity(Intent.createChooser(intent, title))
}
