from __future__ import annotations

import os
from datetime import datetime, timezone
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from pathlib import Path
from xml.sax.saxutils import escape

# Devanagari-capable fonts first (Hindi/Bhojpuri counselling text), then DejaVu, then built-in Helvetica.
FONT_CANDIDATES = [
    (os.getenv('ABHAYNAYAN_PDF_FONT', ''), os.getenv('ABHAYNAYAN_PDF_FONT_BOLD', '')),
    ('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf', '/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf'),
    ('C:/Windows/Fonts/Nirmala.ttf', 'C:/Windows/Fonts/NirmalaB.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
]
BODY_FONT = 'Helvetica'
BOLD_FONT = 'Helvetica-Bold'
for _regular, _bold in FONT_CANDIDATES:
    try:
        if _regular and _bold and Path(_regular).exists() and Path(_bold).exists():
            pdfmetrics.registerFont(TTFont('AN', _regular))
            pdfmetrics.registerFont(TTFont('AN-Bold', _bold))
            pdfmetrics.registerFontFamily('AN', normal='AN', bold='AN-Bold', italic='AN', boldItalic='AN-Bold')
            BODY_FONT, BOLD_FONT = 'AN', 'AN-Bold'
            break
    except Exception:
        continue

NAVY = colors.HexColor('#123642')
TEAL = colors.HexColor('#0b817d')
BODY = colors.HexColor('#526a70')
PALE = colors.HexColor('#eff8f6')
LINE = colors.HexColor('#dce7e8')
SAFETY = ('Prototype / synthetic screening estimate only — not a diagnosis or validated clinical measurement. '
          'Confirm with appropriate clinical testing and follow local protocol.')


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('ANTitle', parent=base['Title'], fontName=BOLD_FONT, fontSize=19, leading=23, textColor=NAVY, alignment=0, spaceAfter=5),
        'body': ParagraphStyle('ANBody', parent=base['BodyText'], fontName=BODY_FONT, fontSize=9, leading=13, textColor=BODY, spaceAfter=4),
        'label': ParagraphStyle('ANLabel', parent=base['BodyText'], fontName=BODY_FONT, fontSize=7.4, leading=10, textColor=BODY),
        'value': ParagraphStyle('ANValue', parent=base['BodyText'], fontName=BOLD_FONT, fontSize=8.3, leading=11, textColor=NAVY),
        'safety': ParagraphStyle('ANSafety', parent=base['BodyText'], fontName=BOLD_FONT, fontSize=8, leading=11.5, textColor=colors.HexColor('#704d1f')),
    }


def _esc(value) -> str:
    return escape(str(value if value is not None else ''))


def build_referral_pdf(data: dict) -> bytes:
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title='AbhayNayan Prototype Referral Brief', author='AbhayNayan Demo')
    s = _styles()
    screening = data.get('screening', {})
    result = screening.get('result', {})
    stype = result.get('screening_type', 'maternal_anemia')
    provenance = result.get('provenance') or 'DEMO_SYNTHETIC'
    measure = {'DEMO_SYNTHETIC': 'Synthetic demo value (not measured)',
               'EXPERIMENTAL_RESEARCH_ONLY': 'Experimental research estimate (not validated)'}.get(
        provenance, 'Estimated Hb screening value' if stype == 'maternal_anemia' else 'Estimated bilirubin screening value')
    context = screening.get('context') or {}
    confidence = result.get('confidence')
    quality = result.get('quality_score')
    rows = [
        [Paragraph('Patient ID', s['label']), Paragraph(_esc(screening.get('patient', {}).get('patient_id', 'Not supplied')), s['value'])],
        [Paragraph('Screening type', s['label']), Paragraph(_esc('Maternal anemia' if stype == 'maternal_anemia' else 'Neonatal jaundice'), s['value'])],
        [Paragraph('Date / time', s['label']), Paragraph(_esc(screening.get('created_at', 'Not recorded')), s['value'])],
        [Paragraph('Worker / PHC', s['label']), Paragraph(_esc(f"{data.get('worker_name','Demo ASHA Worker')} · {screening.get('phc','Demo PHC')}"), s['value'])],
        [Paragraph(measure, s['label']), Paragraph(_esc(f"{result.get('estimate','—')} {result.get('unit','')}"), s['value'])],
        [Paragraph('Prototype tag', s['label']), Paragraph(_esc(result.get('risk_category','DEMO_ONLY')), s['value'])],
        [Paragraph('Confidence / image quality', s['label']), Paragraph(_esc(
            f"{'Not available' if confidence is None else f'{float(confidence) * 100:.0f}%'} / "
            f"{'Not measured' if quality is None else f'{float(quality) * 100:.0f}%'}"), s['value'])],
        [Paragraph('Result provenance', s['label']), Paragraph(_esc(f"{provenance} · mode {result.get('model_mode', 'DEMO')} · {result.get('model_version') or 'no model version'}"), s['value'])],
        [Paragraph('Result generated (UTC)', s['label']), Paragraph(_esc(result.get('generated_at', 'Not recorded')), s['value'])],
        [Paragraph('Referral reason', s['label']), Paragraph(_esc(str(data.get('reason', 'SCREENING_CONFIRMATION')).replace('_', ' ').capitalize()), s['value'])],
        [Paragraph('Counselling source', s['label']), Paragraph(_esc(
            'Optional Gemini wording (safety text from reviewed local copy)' if data.get('counselling_mode') == 'GEMINI'
            else 'Reviewed deterministic local copy'), s['value'])],
        [Paragraph('Brief generated (UTC)', s['label']), Paragraph(_esc(data.get('generated_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')), s['value'])],
    ]
    if context.get('infant_age_hours') is not None:
        rows.insert(3, [Paragraph('Newborn age (hours)', s['label']), Paragraph(_esc(context['infant_age_hours']), s['value'])])
    if context.get('gestational_week') is not None:
        rows.insert(3, [Paragraph('Gestational week', s['label']), Paragraph(_esc(context['gestational_week']), s['value'])])
    table = Table(rows, colWidths=[54*mm, 110*mm], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.white), ('GRID',(0,0),(-1,-1),.45,LINE),
        ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('BACKGROUND',(0,0),(0,-1),PALE),
    ]))
    story = [
        Paragraph('ABHAYNAYAN · SCREENING REFERRAL BRIEF', s['title']),
        Paragraph('Prototype-generated summary for clinician review · not a diagnosis', s['body']),
        Spacer(1, 7), table, Spacer(1, 14),
        Paragraph('Recommended next step', ParagraphStyle('ANSection', fontName=BOLD_FONT, fontSize=10, leading=13, textColor=NAVY, spaceAfter=5)),
        Paragraph(_esc(data.get('next_step') or 'Confirm with appropriate clinical testing and follow local clinical protocol.'), s['body']),
        Paragraph('Counselling summary', ParagraphStyle('ANSection2', fontName=BOLD_FONT, fontSize=10, leading=13, textColor=NAVY, spaceBefore=6, spaceAfter=5)),
        Paragraph(_esc(data.get('counselling') or 'No counseling text provided.'), s['body']),
        Spacer(1, 10),
    ]
    safety_box = Table([[Paragraph(SAFETY, s['safety'])]], colWidths=[doc.width])
    safety_box.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#fff7e8')), ('BOX',(0,0),(-1,-1),.7,colors.HexColor('#e5c98f')),
        ('LINEBEFORE',(0,0),(0,0),3,TEAL), ('LEFTPADDING',(0,0),(-1,-1),10), ('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),9), ('BOTTOMPADDING',(0,0),(-1,-1),9),
    ]))
    story.append(safety_box)
    doc.build(story)
    return out.getvalue()
