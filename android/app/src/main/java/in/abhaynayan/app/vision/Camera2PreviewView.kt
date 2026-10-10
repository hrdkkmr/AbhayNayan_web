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
import android.util.Size
import android.view.Surface
import android.view.TextureView
import androidx.core.content.ContextCompat

/** Local Camera2 preview utility. Captured preview frames are returned in memory and never persisted. */
class Camera2PreviewView(context: Context) : TextureView(context), TextureView.SurfaceTextureListener {
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var previewSurface: Surface? = null
    private var backgroundThread: HandlerThread? = null
    private var backgroundHandler: Handler? = null
    private var requested = false
    private var closed = false

    init { surfaceTextureListener = this }

    fun start() {
        requested = true
        closed = false
        if (backgroundThread == null) {
            backgroundThread = HandlerThread("abhaynayan-camera2").also { it.start() }
            backgroundHandler = Handler(backgroundThread!!.looper)
        }
        if (isAvailable) openCameraIfPermitted()
    }

    fun snapshotPreview(): Bitmap? {
        if (!isAvailable) return null
        return try { getBitmap(640, 360) } catch (_: RuntimeException) { null }
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
                    createPreviewSession(camera)
                }
                override fun onDisconnected(camera: CameraDevice) { camera.close(); cameraDevice = null }
                override fun onError(camera: CameraDevice, error: Int) { camera.close(); cameraDevice = null }
            }, backgroundHandler)
        } catch (_: SecurityException) {
            // The Compose host requests permission before constructing the preview.
        } catch (_: Exception) {
            // Camera is optional. Demo mode remains usable through the abstract synthetic capture.
        }
    }

    private fun createPreviewSession(camera: CameraDevice) {
        val texture = surfaceTexture ?: return
        val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val cameraId = camera.id
        val characteristics = manager.getCameraCharacteristics(cameraId)
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
                    try {
                        val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                            addTarget(surface)
                            set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                            set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                        }.build()
                        session.setRepeatingRequest(request, null, backgroundHandler)
                    } catch (_: Exception) {
                        session.close(); captureSession = null
                    }
                }
                override fun onConfigureFailed(session: CameraCaptureSession) { session.close() }
            }, backgroundHandler)
        } catch (_: Exception) { surface.release() }
    }

    fun close() {
        closed = true
        requested = false
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
