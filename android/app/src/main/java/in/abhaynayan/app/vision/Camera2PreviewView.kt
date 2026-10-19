package in.abhaynayan.app.vision

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Size
import android.view.Surface
import android.view.TextureView
import androidx.core.content.ContextCompat

/** A local preview-frame pair. The images are held only in memory by the caller. */
data class DualPreviewCapture(
    val ambient: Bitmap,
    val flash: Bitmap?,
    val flashAvailable: Boolean,
    val elapsedMs: Long,
    val note: String,
)

/**
 * Local Camera2 preview utility. Captures best-effort TextureView preview snapshots (not still-photo
 * captures); when supported, the flash is toggled briefly between frames. Manual exposure/ISO lock,
 * anatomical landmarks, and calibrated illumination correction are not provided here.
 */
class Camera2PreviewView(context: Context) : TextureView(context), TextureView.SurfaceTextureListener {
    @Volatile private var cameraDevice: CameraDevice? = null
    @Volatile private var captureSession: CameraCaptureSession? = null
    @Volatile private var previewSurface: Surface? = null
    @Volatile private var previewReady = false
    private var backgroundThread: HandlerThread? = null
    private var backgroundHandler: Handler? = null
    @Volatile private var requested = false
    @Volatile private var closed = false
    @Volatile private var flashAvailable = false

    init { surfaceTextureListener = this }

    fun start() {
        requested = true
        closed = false
        previewReady = false
        if (backgroundThread == null) {
            backgroundThread = HandlerThread("abhaynayan-camera2").also { it.start() }
            backgroundHandler = Handler(backgroundThread!!.looper)
        }
        if (isAvailable) openCameraIfPermitted()
    }

    fun snapshotPreview(): Bitmap? {
        if (!isAvailable || closed || !previewReady) return null
        return try { getBitmap(640, 360) } catch (_: RuntimeException) { null }
    }

    /**
     * Captures an ambient preview frame, briefly enables the LED torch when available, and captures
     * a second preview frame. Exposure and ISO remain under device auto-control. Missing flash or
     * Camera2 failures return a usable ambient-only capture rather than throwing into the UI.
     */
    fun captureDualPreviewFrames(callback: (DualPreviewCapture?) -> Unit) {
        val startedAt = SystemClock.elapsedRealtime()
        val ambient = snapshotPreview()
        if (ambient == null) {
            callback(null)
            return
        }
        if (!flashAvailable || !setTorch(true)) {
            setTorch(false) // best-effort restore the preview flash to off after any partial failure
            callback(DualPreviewCapture(
                ambient = ambient,
                flash = null,
                flashAvailable = false,
                elapsedMs = SystemClock.elapsedRealtime() - startedAt,
                note = "Ambient preview captured. Flash unavailable or unsupported; single-frame fallback used.",
            ))
            return
        }

        // Allow the preview stream and auto-exposure to react to the torch; this is not a locked-exposure capture.
        postDelayed({
            val flash = if (closed) null else snapshotPreview()
            val restored = setTorch(false)
            val safeFlash = flash.takeIf { restored && it != null }
            if (flash != null && safeFlash == null) flash.recycle()
            callback(DualPreviewCapture(
                ambient = ambient,
                flash = safeFlash,
                flashAvailable = safeFlash != null,
                elapsedMs = SystemClock.elapsedRealtime() - startedAt,
                note = if (safeFlash != null) {
                    "Two local Camera2 preview snapshots captured. Auto exposure remained enabled; differential is experimental."
                } else {
                    "Flash-frame capture failed or torch restore was unavailable; ambient-only fallback used."
                },
            ))
        }, 350L)
    }

    @SuppressLint("MissingPermission")
    private fun openCameraIfPermitted() {
        if (!requested || closed || cameraDevice != null) return
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        try {
            val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val cameraId = manager.cameraIdList.firstOrNull { id ->
                manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
            } ?: manager.cameraIdList.firstOrNull() ?: return
            manager.openCamera(cameraId, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    if (closed) { camera.close(); return }
                    cameraDevice = camera
                    flashAvailable = try {
                        val managerNow = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
                        managerNow.getCameraCharacteristics(camera.id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
                    } catch (_: Exception) { false }
                    createPreviewSession(camera)
                }
                override fun onDisconnected(camera: CameraDevice) {
                    camera.close(); cameraDevice = null; flashAvailable = false; previewReady = false
                }
                override fun onError(camera: CameraDevice, error: Int) {
                    camera.close(); cameraDevice = null; flashAvailable = false; previewReady = false
                }
            }, backgroundHandler)
        } catch (_: SecurityException) {
            // Permission can be revoked while the view is alive; synthetic mode stays available.
        } catch (_: Exception) {
            // Camera is optional. Demo mode remains usable through the local synthetic path.
        }
    }

    private fun createPreviewSession(camera: CameraDevice) {
        val texture = surfaceTexture ?: return
        val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val characteristics = manager.getCameraCharacteristics(camera.id)
        val map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return
        val sizes = map.getOutputSizes(SurfaceTexture::class.java)?.toList().orEmpty()
        val size = sizes.minByOrNull { kotlin.math.abs(it.width - 640) + kotlin.math.abs(it.height - 360) } ?: Size(640, 360)
        texture.setDefaultBufferSize(size.width, size.height)
        val surface = Surface(texture)
        previewSurface = surface
        try {
            camera.createCaptureSession(listOf(surface), object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    if (closed) { session.close(); return }
                    captureSession = session
                    if (!setTorch(false)) {
                        try {
                            val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                addTarget(surface)
                                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                            }.build()
                            session.setRepeatingRequest(request, null, backgroundHandler)
                            previewReady = true
                        } catch (_: Exception) { previewReady = false; session.close(); captureSession = null }
                    }
                }
                override fun onConfigureFailed(session: CameraCaptureSession) { previewReady = false; session.close() }
            }, backgroundHandler)
        } catch (_: Exception) { surface.release() }
    }

    private fun setTorch(enabled: Boolean): Boolean {
        val camera = cameraDevice ?: return false
        val session = captureSession ?: return false
        val surface = previewSurface ?: return false
        if (closed || (enabled && !flashAvailable)) return false
        return try {
            val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(surface)
                set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                set(CaptureRequest.FLASH_MODE, if (enabled) CaptureRequest.FLASH_MODE_TORCH else CaptureRequest.FLASH_MODE_OFF)
            }.build()
            session.setRepeatingRequest(request, null, backgroundHandler)
            previewReady = true
            true
        } catch (_: Exception) {
            previewReady = false
            false
        }
    }

    fun close() {
        closed = true
        requested = false
        flashAvailable = false
        previewReady = false
        try { captureSession?.stopRepeating() } catch (_: Exception) { }
        try { captureSession?.close() } catch (_: Exception) { }
        captureSession = null
        try { cameraDevice?.close() } catch (_: Exception) { }
        cameraDevice = null
        try { previewSurface?.release() } catch (_: Exception) { }
        previewSurface = null
        backgroundThread?.quitSafely()
        backgroundThread = null
        backgroundHandler = null
    }

    override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) { openCameraIfPermitted() }
    override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = Unit
    override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit
    override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean { close(); return true }
}
