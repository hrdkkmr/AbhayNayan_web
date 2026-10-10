package in.abhaynayan.app.interop

import in.abhaynayan.app.core.LocalScreeningResult
import in.abhaynayan.app.data.PatientEntity
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** FHIR R4-style local demo export. Never sends data to a server. */
fun buildLocalDemoBundle(patient: PatientEntity, result: LocalScreeningResult, screeningId: String): String {
    require(result.synthetic) { "Only synthetic prototype fixtures can be exported by this demo." }
    val patientResourceId = patient.patientId.replace(Regex("[^A-Za-z0-9.-]"), "-").take(64)
    val encounterId = "enc-${screeningId.take(48)}"
    val observationId = "obs-${screeningId.take(48)}"
    val reportId = "report-${screeningId.take(45)}"
    val observation = JSONObject()
        .put("resourceType", "Observation")
        .put("id", observationId)
        .put("status", "preliminary")
        .put("code", JSONObject().put("text", if (result.screeningType.wireName == "maternal_anemia") "Optical hemoglobin screening estimate" else "Optical bilirubin screening estimate"))
        .put("subject", JSONObject().put("reference", "Patient/$patientResourceId"))
        .put("encounter", JSONObject().put("reference", "Encounter/$encounterId"))
        .put("valueQuantity", JSONObject().put("value", result.demoCase.estimate).put("unit", result.demoCase.unit).put("system", "http://unitsofmeasure.org").put("code", result.demoCase.unit))
        .put("method", JSONObject().put("text", "Fixed synthetic smartphone-workflow fixture; not inferred from patient pixels"))
        .put("note", JSONArray().put(JSONObject().put("text", result.safetyNote)))
        .put("meta", JSONObject().put("tag", JSONArray().put(JSONObject().put("system", "urn:abhaynayan:tag").put("code", "synthetic-demo"))))
    val patientResource = JSONObject()
        .put("resourceType", "Patient").put("id", patientResourceId).put("active", true)
        .put("identifier", JSONArray().put(JSONObject().put("system", "urn:abhaynayan:demo-patient-id").put("value", patientResourceId)))
        .put("name", JSONArray().put(JSONObject().put("text", patient.displayName)))
        .put("meta", JSONObject().put("tag", JSONArray().put(JSONObject().put("system", "urn:abhaynayan:tag").put("code", "synthetic-demo"))))
    val encounter = JSONObject().put("resourceType", "Encounter").put("id", encounterId).put("status", "finished")
        .put("class", JSONObject().put("system", "http://terminology.hl7.org/CodeSystem/v3-ActCode").put("code", "AMB"))
        .put("subject", JSONObject().put("reference", "Patient/$patientResourceId"))
    val report = JSONObject().put("resourceType", "DiagnosticReport").put("id", reportId).put("status", "preliminary")
        .put("code", JSONObject().put("text", "AbhayNayan prototype screening report"))
        .put("subject", JSONObject().put("reference", "Patient/$patientResourceId"))
        .put("result", JSONArray().put(JSONObject().put("reference", "Observation/$observationId")))
        .put("conclusion", result.safetyNote)
    val entries = JSONArray()
    listOf(patientResource, encounter, observation, report).forEach { resource ->
        entries.put(JSONObject().put("fullUrl", "https://fhir.abhaynayan.invalid/${resource.getString("resourceType")}/${resource.getString("id")}").put("resource", resource))
    }
    return JSONObject().put("resourceType", "Bundle").put("id", UUID.randomUUID().toString()).put("type", "collection")
        .put("entry", entries).toString(2)
}
