"""Health information & navigation assistant: guards, retrieval and output validation (no clinical function).

Standard library only, so the same code runs in the API and in the stand-alone evaluation job
(scripts/assistant_eval). The flow for every question is:

1. `guard_question` refuses personal information, clinical requests (estimates, diagnosis, photos, medicines),
   emergencies (fixed urgent message) and instruction-injection attempts. Refused questions never leave the server.
2. `retrieve` matches the question against the curated knowledge base (`knowledge_base.json`). No match means
   "no approved answer": nothing is generated.
3. An optional provider (Agent37, see agent37.py) may reword the retrieved passages. `validate_provider_output`
   accepts its text only if it is well-formed JSON, cites retrieved entries, stays within length, contains no
   unsafe claim, and every number and URL in it appears in the cited passages. Anything else falls back to the
   approved passage text.

Questions and answers are never logged. See docs/build2026/assistant.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

KB_PATH = Path(__file__).with_name('knowledge_base.json')
MAX_QUESTION_CHARS = 500
MAX_ANSWER_CHARS = 1200
MAX_PASSAGES = 2
MIN_SCORE = 2

# Refusal codes (stable; part of API contract 1.4.0).
PERSONAL_INFORMATION = 'PERSONAL_INFORMATION'
CLINICAL_REQUEST = 'CLINICAL_REQUEST'
URGENT_HELP = 'URGENT_HELP'
OUT_OF_SCOPE = 'OUT_OF_SCOPE'
NO_APPROVED_ANSWER = 'NO_APPROVED_ANSWER'

REFUSAL_MESSAGES = {
    PERSONAL_INFORMATION: ('Please do not share names, phone numbers, email addresses, ID numbers or addresses here. '
                           'Your question was not sent anywhere. Ask a general question without personal details.'),
    CLINICAL_REQUEST: ('I cannot estimate hemoglobin or bilirubin, diagnose a condition, look at photos, or advise on '
                       'medicines. Only a qualified health worker or doctor, using appropriate tests, can assess a person. '
                       'If you are worried about someone\'s health, contact your local ASHA or ANM, or a doctor at a health centre.'),
    URGENT_HELP: ('If someone may be seriously ill, do not wait for an app. Call 112, India\'s national emergency number, '
                  'or go to the nearest health facility straight away.'),
    OUT_OF_SCOPE: ('I can only answer general questions about using AbhayNayan from approved information. '
                   'Please rephrase your question.'),
    NO_APPROVED_ANSWER: ('I do not have approved information to answer that. I can help with how AbhayNayan works, why a photo '
                         'may be rejected, what an outcome means, offline use, privacy, the Terms & Conditions and where to '
                         'find official health information. Answers are in English only for now.'),
}

_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_PHONE = re.compile(r'(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)')
_ID_NUMBER = re.compile(r'(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)')  # Aadhaar-like 12 digits
_LONG_NUMBER = re.compile(r'\d{9,}')
_NAME_INTRO = re.compile(r"\b(my name is|i am called|mera naam|meri beti ka naam|mere bete ka naam|patient name|patient's name)\b", re.I)
_ADDRESS = re.compile(r'\b(my address|i live at|house no|house number|village name is|pin ?code is)\b', re.I)

_PERSON = r'(?:my|our|the|this|her|his)\s+(?:baby|newborn|child|son|daughter|wife|husband|mother|father|sister|brother|patient|kid)'
_CLINICAL = [re.compile(p, re.I) for p in (
    r'\b(my|his|her|their|our|baby\'?s?|child\'?s?|wife\'?s?|mother\'?s?|patient\'?s?)\s+(hb|hgb|hemoglobin|haemoglobin|bilirubin|blood (?:count|level))\b',
    r'\b(estimate|calculate|measure|check|predict|tell me|what is|what\'s)\b.{0,40}\b(hb|hgb|hemoglobin|haemoglobin|bilirubin)\s*(level|value|count|is)?\b.{0,20}\b(my|his|her|this|the baby|the patient|from (?:this|my|the) (?:photo|image|picture))',
    rf'\b(do|does|did|am|is|are)\s+(i|he|she|they|we|{_PERSON})\s+(have|has|got)?\s*(an?\s+)?(anemi[ac]|anaemi[ac]|jaundice[d]?|anemia|anaemia|infection|disease|sick|ill)\b',
    rf'\b(am i|is (?:he|she|{_PERSON}))\s+(anemic|anaemic|jaundiced|healthy|normal|fine|ok|okay|safe|well)\b',
    r'\b(diagnos\w*)\b.{0,30}\b(me|my|him|her|baby|child|patient|this)\b',
    r'\b(look at|analy[sz]e|read|check|assess|review|interpret)\b.{0,25}\b(this|my|the|attached|uploaded)\s+(photo|image|picture|selfie|scan|eye|eyes)\b',
    r'\b(photo|image|picture)\b.{0,30}\b(anemi[ac]|anaemi[ac]|jaundice|hemoglobin|haemoglobin|bilirubin)\b.{0,30}\?',
    r'\d+(?:\.\d+)?\s*(g\s*/\s*d\s*l|gm\s*/\s*dl|g/dl|mg\s*/\s*d\s*l|mg/dl|gm%|g%)',
    r'\b(stop|start|change|reduce|increase|skip|double|quit|switch)\b.{0,30}\b(medicine|medication|tablet|tablets|pills?|iron|folic|syrup|dose|dosage|drug|treatment|injection|phototherapy)\b',
    r'\b(how much|how many|what dose|which dose|dosage of|dose of)\b.{0,30}\b(iron|folic|tablet|tablets|pills?|medicine|medication|syrup|mg)\b',
    r'\b(should i|should we|can i|can we)\s+(take|give|stop|skip|use)\b.{0,30}\b(medicine|medication|tablet|iron|syrup|drug|treatment)\b',
    r'\b(results?|value|reading|number|score)\b.{0,20}\b(mean|means|say|says)\b.{0,30}\b(about )?(my|his|her|the baby|the patient|anemia|anaemia|jaundice|health)\b',
)]

_URGENT = re.compile(r'\b(not breathing|stopped breathing|can\'?t breathe|cannot breathe|unconscious|unresponsive|fitting|seizures?|convulsions?|'
                     r'heavy bleeding|bleeding heavily|severe bleeding|very weak and|fainted|collapsed|chest pain|'
                     r'not feeding|stopped feeding|blue lips|turning blue|emergency now|dying)\b', re.I)
_INJECTION = re.compile(r'\b(ignore (?:all |the |your |any )?(?:previous|prior|above) (?:instructions|rules)|system prompt|developer message|'
                        r'you are now|act as|pretend to be|jailbreak|disregard (?:the|your) rules|reveal your (?:instructions|prompt)|'
                        r'run (?:a )?(?:shell|command)|execute (?:this|the) (?:code|command)|curl |wget |base64)\b', re.I)

# Output phrases that would turn an information answer into a clinical or reassurance claim.
_UNSAFE_OUTPUT = [re.compile(p, re.I) for p in (
    r'\byou (?:have|do not have|don\'t have|are|are not|aren\'t)\s+(?:an?\s+)?(?:anemi[ac]|anaemi[ac]|jaundice[d]?|healthy|normal|fine|well|sick|ill)\b',
    r'\b(?:your|the baby\'?s?|the patient\'?s?)\s+(?:hb|hemoglobin|haemoglobin|bilirubin)\s+(?:is|looks|seems|appears)\b',
    r'\b(?:is|are|looks|seems|appears)\s+(?:healthy|normal|fine|safe|nothing to worry)\b',
    r'\bno need to (?:see|visit|consult|go to)\b',
    r'\b(?:diagnosed with|diagnosis is|confirmed (?:anemia|anaemia|jaundice))\b',
    r'\b(?:take|give|stop|start|increase|reduce|double)\s+(?:\d+|the|your|an?)\s*\w*\s*(?:mg|tablets?|pills?|doses?|medicine|medication|iron|syrup)\b',
    r'\d+(?:\.\d+)?\s*(?:g\s*/\s*dl|mg\s*/\s*dl|gm%|g%|mg\b)',
    r'\b(?:prescribe|prescription|cure[ds]?)\b',
    r'\b(?:scheme|yojana|eligib\w*|entitle\w*|free treatment|insurance cover)\b',
)]
# A match preceded by one of these states what the app cannot say ("does not mean the person is healthy"); it is not a claim.
_NEGATED_CONTEXT = re.compile(r"(?:does not mean|doesn't mean|do not mean|not mean that|cannot tell you whether|cannot say whether|"
                              r"cannot tell whether|or say whether|not a sign that|or whether)\s+(?:that\s+)?[\w' ]{0,25}$", re.I)
_NUMBER = re.compile(r'(?<![\w.])\d+(?:[.,]\d+)?(?![\w.])')
_URL = re.compile(r'https?://[^\s<>"\')\]]+', re.I)


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    keywords: tuple[str, ...]
    answer: str
    sources: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class KnowledgeBase:
    kb_version: str
    review_status: str
    allowed_source_hosts: tuple[str, ...]
    entries: tuple[Entry, ...]
    sha256: str

    def by_id(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str


@dataclass
class Answer:
    mode: str  # 'AGENT37' | 'KNOWLEDGE_BASE' | 'REFUSED' | 'NO_ANSWER'
    answer: str
    sources: list[dict[str, str]] = field(default_factory=list)
    entry_ids: list[str] = field(default_factory=list)
    refusal_code: str | None = None
    fallback_reason: str | None = None
    related: list[dict[str, str]] = field(default_factory=list)


def load_kb(path: Path = KB_PATH) -> KnowledgeBase:
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8'))
    entries = tuple(Entry(e['id'], e['title'], tuple(e['keywords']), e['answer'], tuple(e['sources'])) for e in data['entries'])
    return KnowledgeBase(data['kb_version'], data['review_status'], tuple(data['allowed_source_hosts']), entries,
                         hashlib.sha256(raw).hexdigest())


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text or '')
    text = ''.join(ch for ch in text if unicodedata.category(ch)[0] != 'C' or ch in '\n\t')
    return re.sub(r'\s+', ' ', text).strip()


def guard_question(question: str) -> Refusal | None:
    """Returns a refusal for anything the assistant must not handle, before retrieval or any provider call."""
    q = normalize(question)
    if not q:
        return Refusal(OUT_OF_SCOPE, REFUSAL_MESSAGES[OUT_OF_SCOPE])
    if len(q) > MAX_QUESTION_CHARS:
        return Refusal(OUT_OF_SCOPE, f'Please ask a shorter question (at most {MAX_QUESTION_CHARS} characters).')
    if (_EMAIL.search(q) or _PHONE.search(q) or _ID_NUMBER.search(q) or _LONG_NUMBER.search(q)
            or _NAME_INTRO.search(q) or _ADDRESS.search(q)):
        return Refusal(PERSONAL_INFORMATION, REFUSAL_MESSAGES[PERSONAL_INFORMATION])
    if _URGENT.search(q):
        return Refusal(URGENT_HELP, REFUSAL_MESSAGES[URGENT_HELP])
    if _INJECTION.search(q):
        return Refusal(OUT_OF_SCOPE, REFUSAL_MESSAGES[OUT_OF_SCOPE])
    if any(p.search(q) for p in _CLINICAL):
        return Refusal(CLINICAL_REQUEST, REFUSAL_MESSAGES[CLINICAL_REQUEST])
    return None


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_']+", text.lower().replace('’', "'"))
    return [w[:-1] if len(w) > 4 and w.endswith('s') and not w.endswith('ss') else w for w in words]


def score(entry: Entry, question: str, shared: frozenset[str] = frozenset()) -> int:
    """Keyword score: a whole phrase counts 2 per word; a single word counts 2 if no other entry uses it, else 1."""
    q_text = ' ' + ' '.join(_tokens(question)) + ' '
    q_tokens = set(q_text.split())
    total = 0
    for keyword in entry.keywords:
        k_tokens = _tokens(keyword)
        if len(k_tokens) > 1 and f" {' '.join(k_tokens)} " in q_text:
            total += 2 * len(k_tokens)
        elif len(k_tokens) == 1 and k_tokens[0] in q_tokens:
            total += 1 if k_tokens[0] in shared else 2
    return total


def _shared_single_keywords(kb: KnowledgeBase) -> frozenset[str]:
    seen: dict[str, set[str]] = {}
    for e in kb.entries:
        for keyword in e.keywords:
            k_tokens = _tokens(keyword)
            if len(k_tokens) == 1:
                seen.setdefault(k_tokens[0], set()).add(e.id)
    return frozenset(word for word, ids in seen.items() if len(ids) > 1)


def retrieve(kb: KnowledgeBase, question: str, limit: int = MAX_PASSAGES) -> list[Entry]:
    shared = _shared_single_keywords(kb)
    ranked = sorted(((score(e, question, shared), i, e) for i, e in enumerate(kb.entries)), key=lambda t: (-t[0], t[1]))
    best = [e for s, _, e in ranked if s >= MIN_SCORE][:limit]
    return best


def knowledge_base_answer(entries: list[Entry], fallback_reason: str | None = None) -> Answer:
    primary = entries[0]
    return Answer('KNOWLEDGE_BASE', primary.answer, _unique_sources(entries[:1]), [primary.id], fallback_reason=fallback_reason,
                  related=[{'id': e.id, 'title': e.title} for e in entries[1:]])


def answer_without_provider(kb: KnowledgeBase, question: str, fallback_reason: str | None = None) -> tuple[Answer, list[Entry]]:
    """Guard + retrieval + approved text. Returns the retrieved entries for an optional provider call."""
    refusal = guard_question(question)
    if refusal is not None:
        return Answer('REFUSED', refusal.message, refusal_code=refusal.code), []
    entries = retrieve(kb, normalize(question))
    if not entries:
        return Answer('NO_ANSWER', REFUSAL_MESSAGES[NO_APPROVED_ANSWER], refusal_code=NO_APPROVED_ANSWER), []
    return knowledge_base_answer(entries, fallback_reason), entries


def build_provider_prompt(question: str, entries: list[Entry]) -> str:
    passages = '\n'.join(f'[{e.id}] {e.title}: {e.answer}' for e in entries)
    return (
        'You are the AbhayNayan help assistant, an information and navigation helper for a research prototype. '
        'Answer the QUESTION using ONLY the APPROVED PASSAGES below. Do not use tools, files, the web or your own knowledge. '
        'Never estimate hemoglobin or bilirubin, diagnose, interpret photos or results, advise on medicines, say anyone is '
        'healthy or unwell, or mention schemes, eligibility, clinics or statistics that are not in the passages. '
        'Use plain, short English sentences (at most 120 words). If the passages do not answer the question, set can_answer to false.\n'
        'Reply with exactly one JSON object and nothing else: '
        '{"can_answer": true or false, "answer": "<text>", "source_ids": ["<passage id>", ...]}\n\n'
        f'APPROVED PASSAGES:\n{passages}\n\nQUESTION: {normalize(question)}'
    )


def contains_unsafe_claim(text: str) -> bool:
    for pattern in _UNSAFE_OUTPUT:
        for match in pattern.finditer(text):
            if not _NEGATED_CONTEXT.search(text[max(0, match.start() - 60):match.start()]):
                return True
    return False


def _strip_fences(text: str) -> str:
    text = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.S)
    return fence.group(1) if fence else text


def validate_provider_output(text: Any, entries: list[Entry]) -> tuple[Answer | None, str | None]:
    """(answer, None) when the provider text is acceptable, else (None, reason code). Never raises."""
    if not isinstance(text, str) or not text.strip():
        return None, 'PROVIDER_EMPTY_OUTPUT'
    if len(text) > 8 * MAX_ANSWER_CHARS:
        return None, 'PROVIDER_OUTPUT_TOO_LONG'
    try:
        data = json.loads(_strip_fences(text))
    except (ValueError, TypeError):
        return None, 'PROVIDER_MALFORMED_OUTPUT'
    if not isinstance(data, dict) or not isinstance(data.get('can_answer'), bool):
        return None, 'PROVIDER_MALFORMED_OUTPUT'
    if data['can_answer'] is False:
        return Answer('NO_ANSWER', REFUSAL_MESSAGES[NO_APPROVED_ANSWER], refusal_code=NO_APPROVED_ANSWER), None
    answer, ids = data.get('answer'), data.get('source_ids')
    if not isinstance(answer, str) or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return None, 'PROVIDER_MALFORMED_OUTPUT'
    answer = normalize(answer)
    if not answer:
        return None, 'PROVIDER_EMPTY_OUTPUT'
    if len(answer) > MAX_ANSWER_CHARS:
        return None, 'PROVIDER_OUTPUT_TOO_LONG'
    by_id = {e.id: e for e in entries}
    cited = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
    if not ids or len(cited) != len(set(ids)):
        return None, 'PROVIDER_UNGROUNDED_OUTPUT'
    if contains_unsafe_claim(answer):
        return None, 'PROVIDER_UNSAFE_OUTPUT'
    passage_text = ' '.join(e.answer for e in cited)
    allowed_numbers = set(_NUMBER.findall(passage_text))
    if any(n not in allowed_numbers for n in _NUMBER.findall(answer)):
        return None, 'PROVIDER_UNGROUNDED_OUTPUT'
    allowed_urls = {u.rstrip('.,') for u in _URL.findall(passage_text)} | {s['url'] for e in cited for s in e.sources}
    if any(u.rstrip('.,') not in allowed_urls for u in _URL.findall(answer)):
        return None, 'PROVIDER_UNGROUNDED_OUTPUT'
    if re.search(r'[ऀ-ॿ]', answer):
        return None, 'PROVIDER_WRONG_LANGUAGE'
    return Answer('AGENT37', answer, _unique_sources(cited), [e.id for e in cited]), None


def _unique_sources(entries: list[Entry]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for e in entries:
        for s in e.sources:
            seen.setdefault(s['url'], {'title': s['title'], 'url': s['url']})
    return list(seen.values())


def validate_kb(kb: KnowledgeBase) -> list[str]:
    """Structural and safety checks of the curated content. Returns problem strings (empty means valid)."""
    problems: list[str] = []
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.\d+', kb.kb_version):
        problems.append('kb_version must look like YYYY-MM-DD.N')
    ids = [e.id for e in kb.entries]
    if len(ids) != len(set(ids)):
        problems.append('entry ids must be unique')
    if len(kb.entries) < 5:
        problems.append('knowledge base has fewer than 5 entries')
    for e in kb.entries:
        where = f'entry {e.id}'
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', e.id):
            problems.append(f'{where}: id must be kebab-case')
        if not e.title.strip() or not e.keywords or not e.answer.strip():
            problems.append(f'{where}: title, keywords and answer are required')
        if len(e.answer) > MAX_ANSWER_CHARS:
            problems.append(f'{where}: answer longer than {MAX_ANSWER_CHARS} characters')
        if contains_unsafe_claim(e.answer):
            problems.append(f'{where}: answer contains a phrase the output filter would block')
        if re.search(r'[ऀ-ॿ]', e.answer):
            problems.append(f'{where}: answers are English only until a reviewed translation exists')
        if not e.sources:
            problems.append(f'{where}: at least one source is required')
        for s in e.sources:
            url = s.get('url', '')
            if url.startswith('app:'):
                continue
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in kb.allowed_source_hosts or parsed.username or parsed.query:
                problems.append(f'{where}: source {url!r} is not an allowed https source')
        for url in _URL.findall(e.answer):
            parsed = urlparse(url.rstrip('.,'))
            if parsed.scheme != 'https' or parsed.hostname not in kb.allowed_source_hosts:
                problems.append(f'{where}: answer links to a host outside allowed_source_hosts')
    return problems
