package in.abhaynayan.app.core

import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.sqrt

/** Immutable, in-memory ARGB image. It is never persisted by this module. */
data class RgbImage(val width: Int, val height: Int, val pixels: IntArray) {
    init {
        require(width > 0 && height > 0) { "Image dimensions must be positive." }
        require(pixels.size == width * height) { "Pixel buffer does not match image dimensions." }
    }

    fun pixel(x: Int, y: Int): Int {
        require(x in 0 until width && y in 0 until height) { "Pixel coordinate is outside the image." }
        return pixels[y * width + x]
    }
}

/** A user-positioned guide rectangle, normalized to the full image. */
data class NormalizedRect(val left: Double, val top: Double, val right: Double, val bottom: Double) {
    init {
        require(listOf(left, top, right, bottom).all { it.isFinite() && it in 0.0..1.0 }) {
            "ROI coordinates must be finite and within the image."
        }
        require(left < right && top < bottom) { "ROI rectangle must have non-zero area." }
    }

    companion object {
        /** Matches the central manual guide shown in the Compose preview; not an anatomical detector. */
        val MANUAL_CENTER_GUIDE = NormalizedRect(.14, .34, .86, .66)
    }
}

data class PixelRect(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
}

data class FeatureVector(
    val rMean: Double,
    val gMean: Double,
    val bMean: Double,
    val rStdDev: Double,
    val gStdDev: Double,
    val bStdDev: Double,
    val rOverG: Double,
    val rOverB: Double,
    val gOverB: Double,
    val labLStar: Double,
    val labAStar: Double,
    val labBStar: Double,
    val yMean: Double,
    val crMean: Double,
    val cbMean: Double,
    val chromaticityR: Double,
    val chromaticityG: Double,
    val chromaticityB: Double,
    val validPixelPercent: Double,
    val sampleCount: Int,
) {
    /** Count of scalar measurements, not evidence of predictive or clinical validity. */
    val featureCount: Int get() = 20
}

data class OpticalPipelineResult(
    val ambient: RgbImage,
    val flash: RgbImage?,
    val compensated: RgbImage,
    val roi: RgbImage,
    val roiBounds: PixelRect,
    val features: FeatureVector,
    val differentialApplied: Boolean,
    val note: String,
)

/**
 * Local visualization and feature extraction only. The output is not calibrated and is never
 * translated into a hemoglobin or bilirubin value by this module.
 */
object OpticalPipeline {
    /** An abstract color-chart pattern for offline pipeline smoke tests; it is not an eye or patient image. */
    fun createAbstractDemoPair(width: Int = 320, height: Int = 180): Pair<RgbImage, RgbImage> {
        require(width >= 16 && height >= 16) { "Synthetic preview must be at least 16x16 pixels." }
        val palette = arrayOf(
            Triple(45, 125, 190), Triple(65, 165, 105), Triple(205, 120, 45),
            Triple(155, 85, 175), Triple(55, 175, 175), Triple(185, 185, 55),
        )
        val ambient = IntArray(width * height)
        val flash = IntArray(width * height)
        for (y in 0 until height) for (x in 0 until width) {
            val blockX = x * 6 / width
            val blockY = y * 3 / height
            val base = palette[(blockX + blockY * 2) % palette.size]
            val texture = if ((x / 6 + y / 6) % 2 == 0) 0 else 9
            val r = (base.first + texture).coerceAtMost(245)
            val g = (base.second + texture).coerceAtMost(245)
            val b = (base.third + texture).coerceAtMost(245)
            val index = y * width + x
            ambient[index] = (0xff shl 24) or (r shl 16) or (g shl 8) or b
            flash[index] = (0xff shl 24) or
                ((r + 18).coerceAtMost(250) shl 16) or
                ((g + 14).coerceAtMost(250) shl 8) or
                (b + 22).coerceAtMost(250)
        }
        return RgbImage(width, height, ambient) to RgbImage(width, height, flash)
    }

    fun process(
        ambient: RgbImage,
        flash: RgbImage? = null,
        roiGuide: NormalizedRect = NormalizedRect.MANUAL_CENTER_GUIDE,
    ): OpticalPipelineResult {
        var compensated = ambient
        var differentialApplied = false
        var note = "Ambient-only frame; no flash differential was calculated."

        if (flash != null && flash.width == ambient.width && flash.height == ambient.height) {
            val candidate = positiveDifferential(ambient, flash)
            if (candidate != null) {
                compensated = candidate
                differentialApplied = true
                note = "Ambient-light compensation prototype: clipped, normalized flash-minus-ambient preview difference. Not calibrated or proven lighting-invariant."
            } else {
                note = "Frames were nearly identical; differential was skipped and the ambient preview frame was used."
            }
        } else if (flash != null) {
            note = "Frame sizes differed; differential was skipped and the ambient preview frame was used."
        }

        var bounds = roiBounds(ambient.width, ambient.height, roiGuide)
        var crop = crop(compensated, bounds)
        val features = try {
            FeatureExtractor.extract(crop)
        } catch (error: IllegalArgumentException) {
            if (!differentialApplied) throw error
            // A dark/clipped difference image should not make the rest of the demo fail.
            compensated = ambient
            differentialApplied = false
            note = "Differential ROI was not usable; ambient-only feature visualization used. ${error.message.orEmpty()}"
            bounds = roiBounds(ambient.width, ambient.height, roiGuide)
            crop = crop(compensated, bounds)
            FeatureExtractor.extract(crop)
        }

        return OpticalPipelineResult(
            ambient = ambient,
            flash = flash,
            compensated = compensated,
            roi = crop,
            roiBounds = bounds,
            features = features,
            differentialApplied = differentialApplied,
            note = note,
        )
    }

    fun roiBounds(width: Int, height: Int, guide: NormalizedRect): PixelRect {
        require(width > 0 && height > 0) { "Image dimensions must be positive." }
        val left = (guide.left * width).toInt().coerceIn(0, width - 1)
        val top = (guide.top * height).toInt().coerceIn(0, height - 1)
        val right = ceil(guide.right * width).toInt().coerceIn(left + 1, width)
        val bottom = ceil(guide.bottom * height).toInt().coerceIn(top + 1, height)
        return PixelRect(left, top, right, bottom)
    }

    fun crop(image: RgbImage, bounds: PixelRect): RgbImage {
        require(bounds.left >= 0 && bounds.top >= 0 && bounds.right <= image.width && bounds.bottom <= image.height) {
            "ROI is outside the image."
        }
        require(bounds.width > 0 && bounds.height > 0) { "ROI is empty." }
        val pixels = IntArray(bounds.width * bounds.height)
        for (y in 0 until bounds.height) {
            val sourceOffset = (bounds.top + y) * image.width + bounds.left
            val destinationOffset = y * bounds.width
            image.pixels.copyInto(pixels, destinationOffset, sourceOffset, sourceOffset + bounds.width)
        }
        return RgbImage(bounds.width, bounds.height, pixels)
    }

    /**
     * Positive, clipped F-A difference normalized using a robust 99th-percentile per-pixel peak.
     * This is only a visualization prototype. It is not a physical reflectance estimate.
     */
    private fun positiveDifferential(ambient: RgbImage, flash: RgbImage): RgbImage? {
        val pixelCount = ambient.width * ambient.height
        val histogram = IntArray(256)
        var totalSignal = 0L
        for (index in 0 until pixelCount) {
            val a = ambient.pixels[index]
            val f = flash.pixels[index]
            val dr = ((f ushr 16 and 0xff) - (a ushr 16 and 0xff)).coerceAtLeast(0)
            val dg = ((f ushr 8 and 0xff) - (a ushr 8 and 0xff)).coerceAtLeast(0)
            val db = ((f and 0xff) - (a and 0xff)).coerceAtLeast(0)
            val peak = max(dr, max(dg, db))
            histogram[peak]++
            totalSignal += dr + dg + db
        }
        if (totalSignal < pixelCount.toLong() * 3L) return null

        val percentileRank = ceil(pixelCount * .99).toInt().coerceAtLeast(1)
        var cumulative = 0
        var scalePeak = 0
        for (value in histogram.indices) {
            cumulative += histogram[value]
            if (cumulative >= percentileRank) {
                scalePeak = value
                break
            }
        }
        if (scalePeak <= 1) return null
        // Stay below sensor-clipping white so normalized channel data remains inspectable.
        val scale = 220.0 / scalePeak
        val output = IntArray(pixelCount)
        for (index in 0 until pixelCount) {
            val a = ambient.pixels[index]
            val f = flash.pixels[index]
            val dr = ((f ushr 16 and 0xff) - (a ushr 16 and 0xff)).coerceAtLeast(0)
            val dg = ((f ushr 8 and 0xff) - (a ushr 8 and 0xff)).coerceAtLeast(0)
            val db = ((f and 0xff) - (a and 0xff)).coerceAtLeast(0)
            val r = (dr * scale).toInt().coerceIn(0, 255)
            val g = (dg * scale).toInt().coerceIn(0, 255)
            val b = (db * scale).toInt().coerceIn(0, 255)
            output[index] = (0xff shl 24) or (r shl 16) or (g shl 8) or b
        }
        return RgbImage(ambient.width, ambient.height, output)
    }
}

object FeatureExtractor {
    fun extract(roi: RgbImage): FeatureVector {
        val total = roi.pixels.size
        var count = 0
        var rSum = 0.0; var gSum = 0.0; var bSum = 0.0
        var rSq = 0.0; var gSq = 0.0; var bSq = 0.0
        var labLSum = 0.0; var labASum = 0.0; var labBSum = 0.0
        var ySum = 0.0; var crSum = 0.0; var cbSum = 0.0
        var chromaRSum = 0.0; var chromaGSum = 0.0; var chromaBSum = 0.0

        for (pixel in roi.pixels) {
            val alpha = pixel ushr 24 and 0xff
            val r = (pixel ushr 16 and 0xff).toDouble()
            val g = (pixel ushr 8 and 0xff).toDouble()
            val b = (pixel and 0xff).toDouble()
            val allNearBlack = r <= 2 && g <= 2 && b <= 2
            val allNearWhite = r >= 253 && g >= 253 && b >= 253
            if (alpha < 128 || allNearBlack || allNearWhite) continue

            count++
            rSum += r; gSum += g; bSum += b
            rSq += r * r; gSq += g * g; bSq += b * b
            val lab = srgbToLab(r, g, b)
            labLSum += lab.first; labASum += lab.second; labBSum += lab.third
            ySum += .299 * r + .587 * g + .114 * b
            crSum += 128.0 + .5 * r - .418688 * g - .081312 * b
            cbSum += 128.0 - .168736 * r - .331264 * g + .5 * b
            val chromaSum = r + g + b
            if (chromaSum > 0) {
                chromaRSum += r / chromaSum
                chromaGSum += g / chromaSum
                chromaBSum += b / chromaSum
            }
        }

        require(count > 0) { "ROI contains no valid, non-clipped RGB pixels." }
        val rMean = rSum / count; val gMean = gSum / count; val bMean = bSum / count
        fun std(sumSquares: Double, mean: Double) = sqrt((sumSquares / count - mean * mean).coerceAtLeast(0.0))
        fun safeRatio(numerator: Double, denominator: Double) = numerator / denominator.coerceAtLeast(1e-6)

        return FeatureVector(
            rMean = rMean,
            gMean = gMean,
            bMean = bMean,
            rStdDev = std(rSq, rMean),
            gStdDev = std(gSq, gMean),
            bStdDev = std(bSq, bMean),
            rOverG = safeRatio(rMean, gMean),
            rOverB = safeRatio(rMean, bMean),
            gOverB = safeRatio(gMean, bMean),
            labLStar = labLSum / count,
            labAStar = labASum / count,
            labBStar = labBSum / count,
            yMean = ySum / count,
            crMean = crSum / count,
            cbMean = cbSum / count,
            chromaticityR = chromaRSum / count,
            chromaticityG = chromaGSum / count,
            chromaticityB = chromaBSum / count,
            validPixelPercent = count * 100.0 / total,
            sampleCount = count,
        )
    }

    private fun srgbToLab(r8: Double, g8: Double, b8: Double): Triple<Double, Double, Double> {
        fun linear(value: Double): Double {
            val normalized = value / 255.0
            return if (normalized <= .04045) normalized / 12.92 else ((normalized + .055) / 1.055).pow(2.4)
        }
        val r = linear(r8); val g = linear(g8); val b = linear(b8)
        val x = (.4124564 * r + .3575761 * g + .1804375 * b) / .95047
        val y = (.2126729 * r + .7151522 * g + .0721750 * b)
        val z = (.0193339 * r + .1191920 * g + .9503041 * b) / 1.08883
        fun f(value: Double): Double = if (value > .008856) value.pow(1.0 / 3.0) else 7.787 * value + 16.0 / 116.0
        val fx = f(x); val fy = f(y); val fz = f(z)
        return Triple(116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))
    }
}
