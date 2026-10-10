package in.abhaynayan.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DemoInferenceTest {
    @Test fun maternalFixturesHaveExpectedUnitsAndCount() {
        val cases = DemoInference.cases(ScreeningType.MATERNAL_ANEMIA)
        assertEquals(3, cases.size)
        assertTrue(cases.all { it.unit == "g/dL" })
    }

    @Test fun neonatalFixturesHaveExpectedUnitsAndCount() {
        val cases = DemoInference.cases(ScreeningType.NEONATAL_JAUNDICE)
        assertEquals(2, cases.size)
        assertTrue(cases.all { it.unit == "mg/dL" })
    }

    @Test fun selectedDemoCaseIsFixedAndSynthetic() {
        val result = LocalScreeningResult(ScreeningType.MATERNAL_ANEMIA, DemoInference.byId(ScreeningType.MATERNAL_ANEMIA, "maternal-moderate"))
        assertEquals(9.4, result.demoCase.estimate, 0.001)
        assertTrue(result.synthetic)
        assertEquals("DEMO", result.modelMode)
    }

    @Test(expected = IllegalStateException::class)
    fun unknownCaseIsRejected() {
        DemoInference.byId(ScreeningType.MATERNAL_ANEMIA, "not-a-case")
    }

    @Test(expected = IllegalStateException::class)
    fun clinicalModelIsUnavailableRatherThanGuessed() {
        val model = MissingClinicalModel()
        assertFalse(model.modelAvailable)
        model.predict(floatArrayOf(0.2f, 0.3f))
    }

    @Test(expected = IllegalArgumentException::class)
    fun qualityMeasurementRejectsTinyImages() {
        LocalImageQuality.measure(2, 2) { _, _ -> 0 }
    }

    @Test fun qualityMeasurementReturnsBoundedScore() {
        val report = LocalImageQuality.measure(100, 100) { x, y ->
            val value = if ((x / 4 + y / 4) % 2 == 0) 110 else 145
            (0xff shl 24) or (value shl 16) or (value shl 8) or value
        }
        assertTrue(report.qualityScore in 0.0..1.0)
        assertTrue(report.brightnessMean in 32.0..228.0)
    }
}
