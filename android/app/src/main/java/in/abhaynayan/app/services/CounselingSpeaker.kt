package in.abhaynayan.app.services

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** Optional on-device TTS helper; the UI remains usable if a language voice is unavailable. */
class CounselingSpeaker(context: Context) : TextToSpeech.OnInitListener {
    private val engine = TextToSpeech(context.applicationContext, this)
    @Volatile private var ready = false

    override fun onInit(status: Int) { ready = status == TextToSpeech.SUCCESS }

    fun speak(text: String, languageCode: String) {
        if (!ready || text.isBlank()) return
        val locale = when (languageCode) {
            "hi" -> Locale("hi", "IN")
            "bho" -> Locale("bho", "IN")
            else -> Locale("en", "IN")
        }
        val availability = engine.isLanguageAvailable(locale)
        if (availability >= TextToSpeech.LANG_AVAILABLE) engine.language = locale
        else engine.language = Locale("en", "IN")
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "abhaynayan-counsel")
    }

    fun shutdown() { engine.stop(); engine.shutdown(); ready = false }
}
