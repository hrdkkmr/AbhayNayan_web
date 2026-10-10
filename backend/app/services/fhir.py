from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

PROTOTYPE_NOTE = ('Preliminary synthetic prototype screening estimate only; not a diagnosis or validated clinical measurement. '
                  'Confirm with appropriate clinical testing and local protocol.')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(value: str) -> str:
    clean = ''.join(c if c.isalnum() or c in '.-' else '-' for c in value)
    return clean[:64] or str(uuid4())


def _related_id(prefix: str, source: str) -> str:
    raw = str(source)
    stem = _id(raw)[:48]
    digest = sha256(raw.encode('utf-8')).hexdigest()[:8]
    return f'{prefix}-{stem}-{digest}'[:64]


class FHIRGenerator:
    """FHIR R4-like demonstration resources; values are preliminary synthetic estimates."""

    def generate_patient(self, patient: dict[str, Any]) -> dict[str, Any]:
        pid = _id(str(patient.get('id') or patient.get('patient_id') or uuid4()))
        resource: dict[str, Any] = {
            'resourceType': 'Patient', 'id': pid, 'active': True,
            'identifier': [{'system': 'urn:abhaynayan:demo-patient-id', 'value': pid}],
            'meta': {'tag': [{'system': 'urn:abhaynayan:tag', 'code': 'prototype', 'display': 'Prototype demonstration record'}]},
        }
        if patient.get('name'):
            resource['name'] = [{'text': str(patient['name'])[:100]}]
        sex = str(patient.get('sex', '')).lower()
        resource['gender'] = 'male' if sex in {'male', 'm'} else 'female' if sex in {'female', 'f'} else 'unknown'
        if patient.get('village'):
            resource['address'] = [{'text': str(patient['village'])[:100]}]
        return resource

    def generate_observation(self, result: dict[str, Any], patient_id: str, encounter_id: str, observation_id: str | None = None) -> dict[str, Any]:
        screening_type = result['screening_type']
        text = 'Optical hemoglobin screening estimate' if screening_type == 'maternal_anemia' else 'Optical bilirubin screening estimate'
        unit = 'g/dL' if screening_type == 'maternal_anemia' else 'mg/dL'
        return {
            'resourceType': 'Observation', 'id': _id(observation_id or f"obs-{uuid4()}"),
            'status': 'preliminary',
            'category': [{'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/observation-category', 'code': 'exam', 'display': 'Exam'}]}],
            'code': {'text': text}, 'subject': {'reference': f'Patient/{patient_id}'},
            'encounter': {'reference': f'Encounter/{encounter_id}'},
            'effectiveDateTime': str(result.get('generated_at') or _now()),
            'valueQuantity': {'value': float(result['estimate']), 'unit': unit, 'system': 'http://unitsofmeasure.org', 'code': unit},
            'method': {'text': 'Smartphone optical screening prototype; synthetic demo case'},
            'note': [{'text': PROTOTYPE_NOTE}],
            'interpretation': [{'text': str(result.get('risk_category', 'DEMO_ONLY'))}],
            'meta': {'tag': [{'system': 'urn:abhaynayan:tag', 'code': 'synthetic-demo', 'display': 'Synthetic demo only'}]},
        }

    def generate_encounter(self, patient_id: str, encounter_id: str, worker: dict[str, Any] | None = None,
                           effective: str | None = None) -> dict[str, Any]:
        period = effective or _now()
        resource: dict[str, Any] = {
            'resourceType': 'Encounter', 'id': encounter_id, 'status': 'finished',
            'class': {'system': 'http://terminology.hl7.org/CodeSystem/v3-ActCode', 'code': 'AMB', 'display': 'ambulatory'},
            'subject': {'reference': f'Patient/{patient_id}'}, 'period': {'start': period, 'end': period},
            'meta': {'tag': [{'system': 'urn:abhaynayan:tag', 'code': 'prototype', 'display': 'Prototype encounter'}]},
        }
        if worker and worker.get('phc'):
            resource['serviceProvider'] = {'display': str(worker['phc'])[:100]}
        return resource

    def generate_diagnostic_report(self, patient_id: str, encounter_id: str, observation_id: str,
                                   report_id: str, effective: str | None = None) -> dict[str, Any]:
        return {
            'resourceType': 'DiagnosticReport', 'id': report_id, 'status': 'preliminary',
            'code': {'text': 'AbhayNayan prototype screening report'},
            'subject': {'reference': f'Patient/{patient_id}'}, 'encounter': {'reference': f'Encounter/{encounter_id}'},
            'effectiveDateTime': effective or _now(), 'result': [{'reference': f'Observation/{observation_id}'}],
            'conclusion': PROTOTYPE_NOTE,
            'meta': {'tag': [{'system': 'urn:abhaynayan:tag', 'code': 'not-clinical-diagnostic', 'display': 'Not a clinical diagnosis'}]},
        }

    def generate_bundle(self, patient: dict[str, Any], result: dict[str, Any], worker: dict[str, Any] | None = None,
                        screening_id: str | None = None) -> dict[str, Any]:
        raw_sid = screening_id or str(uuid4())
        patient_resource = self.generate_patient(patient)
        encounter_id = _related_id('enc', raw_sid)
        observation_id = _related_id('obs', raw_sid)
        observation = self.generate_observation(result, patient_resource['id'], encounter_id, observation_id)
        encounter = self.generate_encounter(patient_resource['id'], encounter_id, worker, str(result.get('generated_at') or _now()))
        report_id = _related_id('report', raw_sid)
        report = self.generate_diagnostic_report(patient_resource['id'], encounter_id, observation['id'], report_id, str(result.get('generated_at') or _now()))
        resources = [patient_resource, encounter, observation, report]
        return {
            'resourceType': 'Bundle', 'id': str(uuid4()), 'type': 'collection', 'timestamp': _now(),
            'meta': {'tag': [{'system': 'urn:abhaynayan:tag', 'code': 'prototype', 'display': 'AbhayNayan hackathon prototype'}]},
            'entry': [{'fullUrl': f"https://fhir.abhaynayan.invalid/{resource['resourceType']}/{resource['id']}", 'resource': resource} for resource in resources],
        }
