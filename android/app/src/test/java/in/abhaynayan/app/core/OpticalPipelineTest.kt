package in.abhaynayan.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OpticalPipelineTest {
    @Test fun normalizedManualGuideMapsToSafePixelBounds() {
        val bounds = OpticalPipeline.roiBounds(100, 50, NormalizedRect.MANUAL_CENTER_GUIDE)
        assertEquals(PixelRect(14, 17, 86, 33), bounds)
    }

    @Test fun cropCopiesOnlyPixelsInsideTheUserGuide() {
        val pixels = IntArray(4 * 3) { index -> 0xff000000.toInt() or (index + 1) }
        val crop = OpticalPipeline.crop(RgbImage(4, 3, pixels), PixelRect(1, 1, 3, 3))
        assertEquals(2, crop.width)
        assertEquals(2, crop.height)
        assertEquals(listOf(6, 7, 10, 11), crop.pixels.map { it and 0xff })
    }

    @Test fun featureExtractorReportsRgbRatiosLabYCrCbAndValidPixelCoverage() {
        val color = argb(100, 120, 140)
        val features = FeatureExtractor.extract(RgbImage(3, 2, IntArray(6) { color }))
        assertEquals(100.0, features.rMean, .001)
        assertEquals(120.0, features.gMean, .001)
        assertEquals(140.0, features.bMean, .001)
        assertEquals(100.0 / 120.0, features.rOverG, .001)
        assertEquals(6, features.sampleCount)
        assertEquals(100.0, features.validPixelPercent, .001)
        assertTrue(features.labLStar in 0.0..100.0)
        assertTrue(features.labAStar.isFinite())
        assertTrue(features.labBStar.isFinite())
        assertTrue(features.yMean > 0)
        assertTrue(features.crMean in 0.0..255.0)
        assertTrue(features.cbMean in 0.0..255.0)
        assertEquals(1.0, features.chromaticityR + features.chromaticityG + features.chromaticityB, .001)
        assertEquals(20, features.featureCount)
    }

    @Test fun clippedBlackAndWhitePixelsAreExcludedFromCoverage() {
        val pixels = intArrayOf(argb(100, 120, 140), argb(0, 0, 0), argb(255, 255, 255), argb(110, 125, 135))
        val features = FeatureExtractor.extract(RgbImage(4, 1, pixels))
        assertEquals(2, features.sampleCount)
        assertEquals(50.0, features.validPixelPercent, .001)
    }

    @Test(expected = IllegalArgumentException::class)
    fun featureExtractorRejectsRoiWithNoValidPixels() {
        FeatureExtractor.extract(RgbImage(2, 2, IntArray(4) { argb(0, 0, 0) }))
    }

    @Test fun differentialClipsNegativeChannelsAndReturnsInspectableFeatures() {
        val ambientPixel = argb(80, 100, 120)
        val flashPixel = argb(100, 95, 155)
        val result = OpticalPipeline.process(
            RgbImage(8, 8, IntArray(64) { ambientPixel }),
            RgbImage(8, 8, IntArray(64) { flashPixel }),
        )
        assertTrue(result.differentialApplied)
        assertTrue(result.note.contains("not calibrated", ignoreCase = true))
        val compensatedPixel = result.compensated.pixels.first()
        assertEquals(125, compensatedPixel ushr 16 and 0xff)
        assertEquals(0, compensatedPixel ushr 8 and 0xff)
        assertEquals(220, compensatedPixel and 0xff)
        assertNotEquals(ambientPixel, compensatedPixel)
        assertEquals(100.0, result.features.validPixelPercent, .001)
    }

    @Test fun missingFlashUsesAmbientFrameWithoutClaimingCorrection() {
        val ambient = RgbImage(8, 8, IntArray(64) { argb(60, 90, 120) })
        val result = OpticalPipeline.process(ambient, flash = null)
        assertFalse(result.differentialApplied)
        assertTrue(result.note.contains("Ambient-only"))
        assertEquals(ambient.pixels.toList(), result.compensated.pixels.toList())
    }

    @Test fun mismatchedFramesFallBackToAmbient() {
        val ambient = RgbImage(8, 8, IntArray(64) { argb(60, 90, 120) })
        val flash = RgbImage(7, 8, IntArray(56) { argb(80, 110, 140) })
        val result = OpticalPipeline.process(ambient, flash)
        assertFalse(result.differentialApplied)
        assertTrue(result.note.contains("Frame sizes differed"))
    }

    @Test fun offlineSyntheticPatternExercisesPipelineWithoutImitatingAnEye() {
        val (ambient, flash) = OpticalPipeline.createAbstractDemoPair()
        assertEquals(320, ambient.width)
        val result = OpticalPipeline.process(ambient, flash)
        assertTrue(result.differentialApplied)
        assertEquals(20, result.features.featureCount)
        assertTrue(result.features.validPixelPercent > 0)
    }

    @Test fun negativeOnlyDifferenceIsSafelySkipped() {
        val ambient = RgbImage(8, 8, IntArray(64) { argb(120, 140, 160) })
        val flash = RgbImage(8, 8, IntArray(64) { argb(100, 130, 140) })
        val result = OpticalPipeline.process(ambient, flash)
        assertFalse(result.differentialApplied)
        assertTrue(result.note.contains("nearly identical"))
        assertEquals(ambient.pixels.toList(), result.compensated.pixels.toList())
    }

    private fun argb(r: Int, g: Int, b: Int) =
        (0xff shl 24) or (r.coerceIn(0, 255) shl 16) or (g.coerceIn(0, 255) shl 8) or b.coerceIn(0, 255)
}
