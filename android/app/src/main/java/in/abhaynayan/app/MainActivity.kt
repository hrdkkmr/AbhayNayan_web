package in.abhaynayan.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import in.abhaynayan.app.core.LocalImageQuality
import in.abhaynayan.app.core.LocalScreeningResult
import in.abhaynayan.app.core.ScreeningType
import in.abhaynayan.app.data.AbhayDatabase
import in.abhaynayan.app.data.PatientEntity
import in.abhaynayan.app.data.ScreeningEntity
import in.abhaynayan.app.interop.buildLocalDemoBundle
import in.abhaynayan.app.services.CounselingSpeaker
import in.abhaynayan.app.vision.Camera2PreviewView
import kotlinx.coroutines.launch
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
    var lastResult by remember { mutableStateOf<LocalScreeningResult?>(null) }
    var lastScreeningId by remember { mutableStateOf("") }
    var language by remember { mutableStateOf("en") }
    var showSafetyDialog by remember { mutableStateOf(false) }

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
                    onNew = { page = NativePage.SETUP; captured = false; syntheticCapture = false; regionConfirmed = false },
                    onSafety = { showSafetyDialog = true },
                    onOpenResult = { row ->
                        lastScreeningId = row.screeningId
                        val fixture = DemoInference.cases(ScreeningType.entries.firstOrNull { it.wireName == row.screeningType } ?: ScreeningType.MATERNAL_ANEMIA)
                            .firstOrNull { it.demoTag == row.demoTag } ?: DemoInference.cases(ScreeningType.MATERNAL_ANEMIA).first()
                        lastResult = LocalScreeningResult(ScreeningType.entries.firstOrNull { it.wireName == row.screeningType } ?: ScreeningType.MATERNAL_ANEMIA, fixture)
                        selectedPatient = patients.firstOrNull { it.patientId == row.patientId }
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
                    onRegionConfirmed = { regionConfirmed = it },
                    onCapture = { bitmap ->
                        val result = LocalImageQuality.measure(bitmap.width, bitmap.height) { x, y -> bitmap.getPixel(x, y) }
                        qualityScore = result.qualityScore.toFloat()
                        qualityReady = result.readyBeforeManualConfirmation
                        captured = true; syntheticCapture = false; regionConfirmed = false
                        bitmap.recycle()
                    },
                    onSynthetic = { captured = true; syntheticCapture = true; qualityScore = .91f; qualityReady = true; regionConfirmed = true },
                    onBack = { page = NativePage.SETUP },
                    onContinue = { page = NativePage.CASES },
                )
                NativePage.CASES -> NativeCaseStep(
                    type = screeningType,
                    cases = DemoInference.cases(screeningType),
                    selectedCaseId = selectedCaseId,
                    canRun = selectedPatient?.isSyntheticDemo == true && syntheticCapture && qualityReady && regionConfirmed,
                    onSelect = { selectedCaseId = it },
                    onBack = { page = NativePage.CAMERA },
                    onRun = {
                        val person = selectedPatient
                        if (person == null || !person.isSyntheticDemo || !syntheticCapture || !qualityReady || !regionConfirmed) return@NativeCaseStep
                        val result = LocalScreeningResult(screeningType, DemoInference.byId(screeningType, selectedCaseId))
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
                        lastResult = result; lastScreeningId = screeningId; page = NativePage.RESULT
                    },
                )
                NativePage.RESULT -> {
                    val result = lastResult
                    if (result == null) NativeEmptyResult(onBack = { page = NativePage.HOME }) else NativeResult(
                        patient = selectedPatient, result = result, screeningId = lastScreeningId,
                        qualityScore = qualityScore, language = language,
                        onLanguage = { language = it }, onSpeak = { text -> speaker.speak(text, language) },
                        onShareFhir = {
                            selectedPatient?.let { person -> shareText(context, "AbhayNayan prototype FHIR Bundle", buildLocalDemoBundle(person, result, lastScreeningId)) }
                        },
                        onShareReferral = { shareText(context, "AbhayNayan prototype referral", referralText(selectedPatient, result)) },
                        onNew = { page = NativePage.SETUP; captured = false; syntheticCapture = false; regionConfirmed = false },
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
                    Text("Turn an entry-level Android phone into a frontline screening assistant.", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold, lineHeight = 27.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Native Kotlin / Compose shell · Camera2 preview · Room-local demo records", color = Color(0xFFC8E4DE), fontSize = 11.sp)
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
    onRegionConfirmed: (Boolean) -> Unit,
    onCapture: (Bitmap) -> Unit,
    onSynthetic: () -> Unit,
    onBack: () -> Unit,
    onContinue: () -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(11.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("2 · Camera & quality", type.displayName) }
        item { Camera2CapturePanel(onCapture = onCapture, onSynthetic = onSynthetic) }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Color.White), border = BorderStroke(1.dp, Color(0xFFDCE7E8))) {
                Column(Modifier.padding(14.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Local quality gate", color = Navy, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                        Text(if (captured && qualityReady && regionConfirmed) "READY" else "WAITING", color = if (captured && qualityReady && regionConfirmed) Teal else Color(0xFFAA6D1E), fontWeight = FontWeight.Bold, fontSize = 10.sp)
                    }
                    Spacer(Modifier.height(5.dp))
                    Text(if (captured) "Brightness/edge proxy: ${(qualityScore * 100).toInt()}% · ${if (syntheticCapture) "synthetic image" else "Camera2 preview frame"}" else "No frame captured yet.", color = Body, fontSize = 10.sp)
                    if (captured && !syntheticCapture) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = regionConfirmed, onCheckedChange = onRegionConfirmed)
                            Text("I manually confirm the ${if (type == ScreeningType.MATERNAL_ANEMIA) "conjunctiva" else "sclera"} is in the guide. No landmark model is present.", color = Body, fontSize = 9.sp)
                        }
                    }
                    Text("Manual guide and simple engineering score only; no clinical capture standard or anatomy detection is claimed.", color = Body, fontSize = 9.sp)
                }
            }
        }
        item { SafetyCard(onClick = {}) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f)) { Text("Back") }
                Button(onClick = onContinue, enabled = captured && qualityReady && regionConfirmed, modifier = Modifier.weight(1f)) { Text("Review demo cases →") }
            }
        }
    }
}

@Composable
private fun Camera2CapturePanel(onCapture: (Bitmap) -> Unit, onSynthetic: () -> Unit) {
    val context = LocalContext.current
    var permissionGranted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    var preview by remember { mutableStateOf<Camera2PreviewView?>(null) }
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
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { preview?.snapshotPreview()?.let(onCapture) }, enabled = preview != null, modifier = Modifier.weight(1f)) { Text("Capture preview frame") }
                    OutlinedButton(onClick = onSynthetic, modifier = Modifier.weight(1f)) { Text("Use synthetic image") }
                }
            } else {
                Text("Camera permission is optional. The app still works in synthetic demo mode.", color = Color.White, fontSize = 10.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }, modifier = Modifier.weight(1f)) { Text("Allow Camera2") }
                    OutlinedButton(onClick = onSynthetic, modifier = Modifier.weight(1f)) { Text("Use synthetic image") }
                }
            }
        }
    }
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
        item { InfoCard("Optical feature vectors are not connected to a biomarker estimator. The value below is selected from a deterministic synthetic case.") }
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
            if (!canRun) SafetyCard(onClick = {}) else InfoCard("Eligible only because both the profile and capture are synthetic. This fixture is not linked to patient pixels.")
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
    onLanguage: (String) -> Unit,
    onSpeak: (String) -> Unit,
    onShareFhir: () -> Unit,
    onShareReferral: () -> Unit,
    onNew: () -> Unit,
    onHome: () -> Unit,
) {
    val copy = counseling(result.screeningType, language)
    LazyColumn(verticalArrangement = Arrangement.spacedBy(11.dp), modifier = Modifier.fillMaxSize()) {
        item { StepTitle("SYNTHETIC FIXTURE · ${result.screeningType.displayName}", "Demo estimate — not a diagnosis") }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Navy), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(20.dp)) {
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
                    Text("Capture-quality proxy: ${(qualityScore * 100).toInt()}% · manual target guide · no landmark detector · no model inference · captured pixels were not persisted.", color = Body, fontSize = 10.sp)
                    Text("Screening ID: $screeningId", color = Body, fontSize = 9.sp)
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
