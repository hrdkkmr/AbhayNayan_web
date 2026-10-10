package in.abhaynayan.app.core

import java.time.Instant

const val DEMO_SAFETY_NOTE = "Synthetic prototype estimate only — not a diagnosis or validated clinical measurement. Confirm with appropriate clinical testing and local protocol."

enum class ScreeningType(val wireName: String, val displayName: String) {
    MATERNAL_ANEMIA("maternal_anemia", "Maternal anemia"),
    NEONATAL_JAUNDICE("neonatal_jaundice", "Neonatal jaundice"),
}

data class DemoCase(
    val id: String,
    val label: String,
    val estimate: Double,
    val unit: String,
    val demoTag: String,
    val confidencePlaceholder: Double,
    val fixtureQualityPlaceholder: Double,
)

object DemoInference {
    fun cases(type: ScreeningType): List<DemoCase> = when (type) {
        ScreeningType.MATERNAL_ANEMIA -> listOf(
            DemoCase("maternal-normal", "Normal-like synthetic", 11.8, "g/dL", "DEMO_LOW", .82, .91),
            DemoCase("maternal-moderate", "Moderate-risk-like synthetic", 9.4, "g/dL", "DEMO_MODERATE", .82, .91),
            DemoCase("maternal-high", "Higher-review synthetic", 7.8, "g/dL", "DEMO_HIGH", .79, .90),
        )
        ScreeningType.NEONATAL_JAUNDICE -> listOf(
            DemoCase("jaundice-review", "Review case synthetic", 12.8, "mg/dL", "REQUIRES_REVIEW", .79, .90),
            DemoCase("jaundice-escalate", "Escalation-like synthetic", 18.0, "mg/dL", "DEMO_ESCALATE", .76, .88),
        )
    }

    fun byId(type: ScreeningType, caseId: String): DemoCase =
        cases(type).firstOrNull { it.id == caseId } ?: error("Select a named synthetic demo case.")
}

interface BiomarkerModel {
    val modelAvailable: Boolean
    fun predict(featureVector: FloatArray): Nothing
}

class MissingClinicalModel : BiomarkerModel {
    override val modelAvailable: Boolean = false
    override fun predict(featureVector: FloatArray): Nothing =
        error("No approved TFLite model and model card are bundled. Optical features are not converted to a clinical estimate.")
}

data class LocalQualityResult(
    val brightnessMean: Double,
    val sharpnessProxy: Double,
    val qualityScore: Double,
    val readyBeforeManualConfirmation: Boolean,
)

object LocalImageQuality {
    /** A low-resolution engineering proxy only. It is not a clinical image-quality standard. */
    fun measure(width: Int, height: Int, argbAt: (Int, Int) -> Int): LocalQualityResult {
        require(width > 2 && height > 2) { "Image must be at least 3x3 pixels." }
        var lumSum = 0.0
        var edge = 0.0
        var count = 0
        val stride = maxOf(1, minOf(width, height) / 40)
        var y = 1
        while (y < height - 1) {
            var x = 1
            while (x < width - 1) {
                val center = luma(argbAt(x, y))
                val right = luma(argbAt(x + 1, y))
                val down = luma(argbAt(x, y + 1))
                lumSum += center
                edge += kotlin.math.abs(center - right) + kotlin.math.abs(center - down)
                count++
                x += stride
            }
            y += stride
        }
        val brightness = lumSum / maxOf(1, count)
        val sharpness = (edge / maxOf(1, count) / 36.0).coerceIn(0.0, 1.0)
        val lightScore = (1.0 - kotlin.math.abs(brightness - 126.0) / 126.0).coerceIn(0.0, 1.0)
        val total = (lightScore * .65 + sharpness * .35).coerceIn(0.0, 1.0)
        val inRange = brightness in 32.0..228.0 && sharpness >= .05
        return LocalQualityResult(brightness, sharpness, total, inRange)
    }

    private fun luma(color: Int): Double {
        val r = (color shr 16 and 0xff).toDouble()
        val g = (color shr 8 and 0xff).toDouble()
        val b = (color and 0xff).toDouble()
        return .2126 * r + .7152 * g + .0722 * b
    }
}

data class LocalScreeningResult(
    val screeningType: ScreeningType,
    val demoCase: DemoCase,
    val generatedAtUtc: String = Instant.now().toString(),
    val safetyNote: String = DEMO_SAFETY_NOTE,
) {
    val synthetic: Boolean get() = true
    val modelMode: String get() = "DEMO"
    val requiresConfirmation: Boolean get() = true
}
