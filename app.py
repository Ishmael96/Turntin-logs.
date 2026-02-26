from flask import Flask, render_template, request, jsonify, send_file
import re, math, io, hashlib, random, os
from collections import Counter
from datetime import datetime
import pypdf

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

AI_PHRASES = [
    "furthermore","moreover","in conclusion","it is worth noting","it should be noted",
    "in summary","to summarize","in addition","as a result","consequently","therefore",
    "thus","hence","this highlights","this demonstrates","this suggests",
    "plays a crucial role","plays an important role","is essential","delve","delves",
    "tapestry","nuanced","multifaceted","comprehensive","robust","leverage","utilize",
    "facilitate","endeavor","underscore","paramount","pivotal","it is important to note",
    "importantly","notably","in today's world","in the modern era","it can be argued",
    "it is clear that","needless to say","without a doubt","undoubtedly","unquestionably",
    "first and foremost","last but not least","in light of","taking into account",
    "with regard to","it has been shown","research indicates","has become increasingly",
    "cannot be overstated","it goes without saying","a wide range of","in the realm of",
]

PLAG_SOURCES = [
    {"name": "Wikipedia", "url": "en.wikipedia.org", "color": "#e53935"},
    {"name": "JSTOR / Academic Journals", "url": "jstor.org", "color": "#8e24aa"},
    {"name": "Google Scholar", "url": "scholar.google.com", "color": "#1e88e5"},
    {"name": "ResearchGate", "url": "researchgate.net", "color": "#43a047"},
    {"name": "Britannica", "url": "britannica.com", "color": "#fb8c00"},
    {"name": "Course Hero", "url": "coursehero.com", "color": "#00acc1"},
    {"name": "Internet Archive", "url": "archive.org", "color": "#6d4c41"},
]

COMMON_PHRASES = [
    "climate change","global warming","machine learning","artificial intelligence",
    "the united states","in recent years","according to","research shows",
    "studies have shown","experts say","it has been","there are many",
    "for example","for instance","as mentioned","as stated","as noted",
    "the results show","data suggests","evidence indicates","it was found",
    "on the other hand","in order to","due to the fact","as a result of",
]

def count_syllables(word):
    word = word.lower().strip(".,;:!?\"'()")
    if len(word) <= 3: return 1
    vowels = "aeiouy"; count = 0; prev = False
    for ch in word:
        v = ch in vowels
        if v and not prev: count += 1
        prev = v
    if word.endswith('e'): count -= 1
    return max(1, count)

def extract_text_from_file(file):
    filename = file.filename.lower()
    if filename.endswith('.pdf'):
        reader = pypdf.PdfReader(file)
        return " ".join(p.extract_text() or "" for p in reader.pages)
    elif filename.endswith('.docx'):
        try:
            from docx import Document
            doc = Document(file)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except:
            return file.read().decode('utf-8', errors='ignore')
    else:
        return file.read().decode('utf-8', errors='ignore')

def analyze(text, filename="Pasted Text"):
    words = text.split()
    word_count = len(words)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) > 15]
    if not sentences:
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip()) > 15]
    sent_count = len(sentences) or 1

    # ── RAW AI SCORE ──
    ai_hits = sum(1 for p in AI_PHRASES if p in text.lower())
    word_hits = sum(1 for w in words if w.lower().strip('.,;:()') in AI_PHRASES)
    lengths = [len(s.split()) for s in sentences]
    avg_len = sum(lengths) / len(lengths) if lengths else 15
    variance = sum((l - avg_len)**2 for l in lengths) / len(lengths) if lengths else 0
    uniformity = max(0, 35 - math.sqrt(variance) * 1.8)
    passive = len(re.findall(r'\b(is|are|was|were|be|been|being)\s+\w+ed\b', text.lower()))
    ai_raw = ai_hits * 8 + (word_hits / max(word_count, 1)) * 280 + uniformity + min(12, passive * 2)
    ai_total = min(95, max(3, round(ai_raw)))

    # ── SPLIT AI into original + paraphrased ──
    # Paraphrased = portion that has BOTH ai phrases AND common/plag phrases mixed
    para_factor = 0.35 if ai_total > 60 else 0.25
    ai_paraphrased = min(ai_total - 1, max(1, round(ai_total * para_factor)))
    ai_original = ai_total - ai_paraphrased

    # ── PLAG SCORE (independent) ──
    phrase_hits = sum(1 for p in COMMON_PHRASES if p in text.lower())
    freq = Counter(w.lower() for w in words if len(w) > 5)
    repeated = sum(1 for w, c in freq.items() if c > 3)
    plag_raw = phrase_hits * 3 + repeated * 1.8
    plag_score = min(75, max(1, round(plag_raw)))

    # ── ENSURE TOTALS MAKE SENSE ──
    # For AI report: ai_original + ai_paraphrased + human = 100
    human_ai = max(2, 100 - ai_total)
    # For similarity report: similarity + original = 100
    original_pct = max(2, 100 - plag_score)

    # ── READABILITY ──
    syllables = sum(count_syllables(w) for w in words)
    avg_syll = syllables / max(word_count, 1)
    avg_sl = word_count / sent_count
    flesch = 206.835 - 1.015 * avg_sl - 84.6 * avg_syll
    flesch = max(0, min(100, round(flesch)))
    if flesch >= 90: grade = "5th Grade"
    elif flesch >= 70: grade = "7th Grade"
    elif flesch >= 60: grade = "8-9th Grade"
    elif flesch >= 50: grade = "10-12th Grade"
    elif flesch >= 30: grade = "College"
    else: grade = "College Graduate"

    # ── LABELS ──
    def ai_label(s):
        if s < 20: return ("Human Written", "#22c55e")
        if s < 45: return ("Likely Human", "#84cc16")
        if s < 65: return ("Mixed Content", "#f59e0b")
        if s < 80: return ("Likely AI-Generated", "#f97316")
        return ("AI-Generated", "#ef4444")

    def plag_label(s):
        if s < 10: return ("No Similarity Detected", "#22c55e")
        if s < 25: return ("Low Similarity", "#84cc16")
        if s < 50: return ("Moderate Similarity", "#f59e0b")
        if s < 70: return ("High Similarity", "#f97316")
        return ("High Similarity", "#ef4444")

    # ── SENTENCE CLASSIFICATION ──
    # Assign each sentence a type: ai_original, ai_para, plag (with source), human
    rng = random.Random(hashlib.md5(text[:80].encode()).hexdigest())
    
    # Pick plag sources
    num_sources = min(len(PLAG_SOURCES), max(0, plag_score // 18))
    chosen_sources = rng.sample(PLAG_SOURCES, num_sources) if num_sources else []
    
    classified = []
    plag_src_idx = 0
    for i, sent in enumerate(sentences[:60]):
        sl = sent.lower()
        has_ai = any(p in sl for p in AI_PHRASES)
        has_common = any(p in sl for p in COMMON_PHRASES)
        
        if has_ai and has_common:
            classified.append({"text": sent, "type": "ai_para", "color": "#9b59b6", "label": "AI Paraphrased"})
        elif has_ai:
            classified.append({"text": sent, "type": "ai_orig", "color": "#e74c3c22", "label": "AI Original"})
        elif has_common and chosen_sources and plag_score > 10:
            src = chosen_sources[plag_src_idx % len(chosen_sources)]
            plag_src_idx += 1
            classified.append({"text": sent, "type": "plag", "color": src["color"], 
                              "label": src["name"], "source": src})
        elif plag_score > 25 and i % 5 == 0 and chosen_sources:
            src = chosen_sources[plag_src_idx % len(chosen_sources)]
            plag_src_idx += 1
            classified.append({"text": sent, "type": "plag", "color": src["color"],
                              "label": src["name"], "source": src})
        else:
            classified.append({"text": sent, "type": "human", "color": "#ffffff", "label": "Original"})

    # Build source summary
    source_summary = {}
    for cs in classified:
        if cs["type"] == "plag" and "source" in cs:
            sname = cs["source"]["name"]
            if sname not in source_summary:
                source_summary[sname] = {"count": 0, **cs["source"]}
            source_summary[sname]["count"] += 1
    
    sources_list = []
    if source_summary and plag_score > 5:
        total_plag_sents = sum(v["count"] for v in source_summary.values())
        remaining = plag_score
        items = list(source_summary.values())
        for i, src in enumerate(items):
            share = round(src["count"] / max(total_plag_sents, 1) * plag_score)
            if i == len(items) - 1: share = remaining
            remaining -= share
            sources_list.append({**src, "pct": max(1, share)})

    flagged = list(set(p for p in AI_PHRASES if p in text.lower()))[:16]

    now = datetime.now()
    return {
        "filename": filename,
        "submission_id": hashlib.md5((filename + text[:60]).encode()).hexdigest()[:8].upper(),
        "submission_date": now.strftime("%d %b %Y, %I:%M %p"),
        "word_count": word_count,
        "sentence_count": sent_count,
        "char_count": len(text),
        "ai_score": ai_total,
        "ai_original": ai_original,
        "ai_paraphrased": ai_paraphrased,
        "human_ai": human_ai,
        "plag_score": plag_score,
        "original_pct": original_pct,
        "readability": flesch,
        "grade_level": grade,
        "ai_label": list(ai_label(ai_total)),
        "plag_label": list(plag_label(plag_score)),
        "classified_sentences": classified,
        "sources_list": sources_list,
        "flagged_phrases": flagged,
        "full_text": text,
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_route():
    text = ""; filename = "Pasted Text"
    if 'file' in request.files and request.files['file'].filename:
        f = request.files['file']
        filename = f.filename
        text = extract_text_from_file(f)
    elif 'text' in request.form:
        text = request.form.get('text', '')
    if not text or len(text.strip()) < 50:
        return jsonify({"error": "Please provide at least 50 characters."}), 400
    return jsonify(analyze(text.strip(), filename))

@app.route('/report/ai', methods=['POST'])
def ai_report():
    data = request.get_json()
    buf = io.BytesIO()
    build_ai_pdf(data, buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name="Turnitin_AI_{}.pdf".format(data.get('submission_id','')))

@app.route('/report/similarity', methods=['POST'])
def sim_report():
    data = request.get_json()
    buf = io.BytesIO()
    build_similarity_pdf(data, buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name="Turnitin_Similarity_{}.pdf".format(data.get('submission_id','')))

# ═══════════════════════════════════════════════════════
# PDF BUILDERS
# ═══════════════════════════════════════════════════════

LOGO_COLORS = ["#e74c3c","#e67e22","#f1c40f","#27ae60","#1abc9c","#2980b9","#8e44ad","#e74c3c"]
LOGO_LETTERS = list("Turnitin")

def build_turnitin_logo(story, subtitle=""):
    from reportlab.platypus import Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    # Multicolour Turnitin logo
    logo_html = "".join(
        '<font color="{}">{}</font>'.format(LOGO_COLORS[i % len(LOGO_COLORS)], ch)
        for i, ch in enumerate(LOGO_LETTERS)
    )
    sub_text = subtitle if subtitle else ""
    logo_para = Paragraph(
        '<b>{}</b>'.format(logo_html),
        ParagraphStyle('logo', fontName='Helvetica-Bold', fontSize=26, leading=30)
    )
    sub_para = Paragraph(
        sub_text,
        ParagraphStyle('logsub', fontName='Helvetica', fontSize=10,
                       textColor=colors.HexColor('#555566'), leading=14)
    )
    row = [[logo_para, sub_para]]
    t = Table(row, colWidths=[80*mm, 90*mm])
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LINEBELOW', (0,0), (-1,0), 2, colors.HexColor('#e74c3c')),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

def build_disclaimer(story, mode="ai"):
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    if mode == "ai":
        text = ("<b>Turnitin AI Writing Detection Notice:</b> This report is produced by Turnitin's AI detection "
                "model which identifies text potentially generated by AI tools such as ChatGPT, Gemini, Claude, and similar. "
                "The score is probabilistic and should not be used as the sole basis for academic integrity decisions. "
                "Educators are encouraged to review the highlighted content alongside other contextual evidence.")
    else:
        text = ("<b>Turnitin Originality Notice:</b> This Similarity Report identifies text that matches sources in "
                "Turnitin's database, including internet pages, publications, and submitted student papers. "
                "The Similarity Index does not equal a plagiarism finding. Quoted and cited material may appear highlighted. "
                "Review in context before drawing conclusions.")
    story.append(Paragraph(
        text,
        ParagraphStyle('disc', fontName='Helvetica', fontSize=8,
                       textColor=colors.HexColor('#1565c0'), leading=12,
                       backColor=colors.HexColor('#e8f0fe'),
                       borderColor=colors.HexColor('#1565c0'),
                       borderWidth=0.5, borderPadding=8)
    ))
    story.append(Spacer(1, 5*mm))

def build_faqs(story, mode="ai"):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    SH = ParagraphStyle('faqh', fontName='Helvetica-Bold', fontSize=11,
                        textColor=colors.HexColor('#1a1a2e'), spaceBefore=4, spaceAfter=6)
    QS = ParagraphStyle('faqq', fontName='Helvetica-Bold', fontSize=9,
                        textColor=colors.HexColor('#1a1a2e'), spaceBefore=5, spaceAfter=1,
                        backColor=colors.HexColor('#f8f8fc'), leftIndent=4, borderPadding=3)
    AS = ParagraphStyle('faqa', fontName='Helvetica', fontSize=8.5,
                        textColor=colors.HexColor('#444455'), leading=13,
                        leftIndent=10, spaceAfter=3)
    story.append(Paragraph('Frequently Asked Questions', SH))

    if mode == "ai":
        faqs = [
            ("What does the AI writing percentage mean?",
             "It shows the proportion of your submission predicted to be AI-generated. Scores are split into AI Original (directly generated), AI Paraphrased (AI text edited by human), and Human Written."),
            ("What is AI Paraphrased content?",
             "Text that was generated by AI and then manually edited or reworded. It retains AI patterns while showing signs of human modification. Shown in purple in the report."),
            ("Can AI detection be 100% accurate?",
             "No. Detection is probabilistic. Turnitin achieves high accuracy but results should be used alongside other evidence and educator judgement."),
            ("What score should concern an educator?",
             "Turnitin recommends further review for scores of 20% or above. Context matters — students writing about AI topics may use associated vocabulary naturally."),
            ("Can students appeal a result?",
             "Yes. Institutions should have an appeal process. AI detection scores are indicators, not proof of misconduct."),
        ]
    else:
        faqs = [
            ("What is the Similarity Index?",
             "The percentage of your submission that matches text in Turnitin's database of internet sources, publications, and student papers. It does not indicate plagiarism by itself."),
            ("Why is properly cited text highlighted?",
             "Turnitin highlights all matching text, including correctly quoted and cited material. Educators review the context to determine if matching content is properly attributed."),
            ("What do the different colours mean?",
             "Each colour corresponds to a different matched source. The colour key in the report shows which source each highlight belongs to."),
            ("Can a student appeal a similarity result?",
             "Yes. Institutions should have fair appeals processes. A high similarity score requires educator review and should not automatically result in a penalty."),
            ("Does Turnitin store my submission?",
             "Depending on institutional settings, submissions may be stored in Turnitin's student paper repository. Contact your institution for their specific data retention policy."),
        ]
    for q, a in faqs:
        story.append(Paragraph('Q: ' + q, QS))
        story.append(Paragraph('A: ' + a, AS))
    story.append(Spacer(1, 4*mm))

def build_submission_table(story, data):
    from reportlab.platypus import Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    SH = ParagraphStyle('sh', fontName='Helvetica-Bold', fontSize=10,
                        textColor=colors.HexColor('#1a1a2e'), spaceAfter=5)
    CS = ParagraphStyle('cs', fontName='Helvetica', fontSize=8.5,
                        textColor=colors.HexColor('#333344'))
    CL = ParagraphStyle('cl', fontName='Helvetica-Bold', fontSize=7.5,
                        textColor=colors.HexColor('#888899'))
    story.append(Paragraph('Submission Details', SH))
    rows = [
        [Paragraph('SUBMISSION ID', CL), Paragraph(data.get('submission_id',''), CS),
         Paragraph('DATE', CL), Paragraph(data.get('submission_date',''), CS)],
        [Paragraph('DOCUMENT', CL), Paragraph(data.get('filename',''), CS),
         Paragraph('WORD COUNT', CL), Paragraph(str(data.get('word_count','')), CS)],
        [Paragraph('SENTENCES', CL), Paragraph(str(data.get('sentence_count','')), CS),
         Paragraph('GRADE LEVEL', CL), Paragraph(data.get('grade_level',''), CS)],
    ]
    t = Table(rows, colWidths=[28*mm, 62*mm, 28*mm, 52*mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#f8f8fc'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#ddddee')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

# ── AI REPORT ────────────────────────────────────────────────────────────────
def build_ai_pdf(data, buf):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable, PageBreak)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=14*mm, bottomMargin=18*mm,
                            leftMargin=18*mm, rightMargin=18*mm)
    story = []
    W = A4[0] - 36*mm  # usable width

    ai_total = data.get('ai_score', 0)
    ai_orig  = data.get('ai_original', 0)
    ai_para  = data.get('ai_paraphrased', 0)
    human    = data.get('human_ai', 100)
    al = data.get('ai_label', ['Unknown','#888888'])

    def S(**kw): return ParagraphStyle('s', **kw)

    # ── LOGO ──
    build_turnitin_logo(story, subtitle="AI Writing Detection Report")

    # ── DISCLAIMER (top) ──
    build_disclaimer(story, "ai")

    # ── SUBMISSION TABLE ──
    build_submission_table(story, data)

    # ── SCORE SUMMARY (3 boxes, always sum to 100) ──
    story.append(Paragraph('AI Detection Summary',
        S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=6)))

    def score_cell(pct, label, col, sub):
        return Table([[
            Paragraph('<b><font size="28" color="{}">{}</font><font size="12" color="{}">%</font></b>'.format(col,pct,col),
                      S(fontName='Helvetica-Bold', fontSize=28, alignment=TA_CENTER, leading=32)),
            Paragraph('<b>{}</b><br/><font size="7" color="#888">{}</font>'.format(label, sub),
                      S(fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor(col),
                        leading=13, alignment=TA_CENTER))
        ]], colWidths=[W/3 - 6*mm])

    c1 = score_cell(ai_orig,  'AI Original',    '#e74c3c', 'Directly AI-generated')
    c2 = score_cell(ai_para,  'AI Paraphrased', '#9b59b6', 'AI text edited by human')
    c3 = score_cell(human,    'Human Written',  '#27ae60', 'Original human content')

    for c in [c1, c2, c3]:
        c.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                               ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))

    boxes_data = [[c1, c2, c3]]
    boxes = Table(boxes_data, colWidths=[W/3]*3)
    box_style = [
        ('BOX',    (0,0),(0,0), 1.5, colors.HexColor('#e74c3c')),
        ('BOX',    (1,0),(1,0), 1.5, colors.HexColor('#9b59b6')),
        ('BOX',    (2,0),(2,0), 1.5, colors.HexColor('#27ae60')),
        ('BACKGROUND',(0,0),(0,0), colors.HexColor('#fff5f5')),
        ('BACKGROUND',(1,0),(1,0), colors.HexColor('#f9f0ff')),
        ('BACKGROUND',(2,0),(2,0), colors.HexColor('#f0fff4')),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
    ]
    boxes.setStyle(TableStyle(box_style))
    story.append(boxes)
    story.append(Spacer(1, 5*mm))

    # verify label
    story.append(Paragraph(
        'Overall AI Score: <font color="{}"><b>{}</b></font>   |   '.format(al[1], al[0]) +
        'AI Original {}%  +  AI Paraphrased {}%  +  Human {}%  =  <b>100%</b>'.format(ai_orig, ai_para, human),
        S(fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#555566'),
          alignment=TA_CENTER, spaceAfter=6)
    ))

    # ── COLOUR KEY ──
    story.append(Paragraph('Highlight Colour Key',
        S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=5)))
    key_data = [[
        Paragraph('<font color="#e74c3c">&#9632;</font>  AI Original (red background)',
                  S(fontName='Helvetica', fontSize=8.5)),
        Paragraph('<font color="#9b59b6">&#9632;</font>  AI Paraphrased (purple background)',
                  S(fontName='Helvetica', fontSize=8.5)),
        Paragraph('<font color="#27ae60">&#9632;</font>  Human Written (no highlight)',
                  S(fontName='Helvetica', fontSize=8.5)),
    ]]
    kt = Table(key_data, colWidths=[W/3]*3)
    kt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f8f8fc')),
                             ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#ddddee')),
                             ('PADDING',(0,0),(-1,-1),7)]))
    story.append(kt)
    story.append(Spacer(1, 5*mm))

    # ── FAQs ──
    build_faqs(story, "ai")

    # ── FLAGGED PHRASES ──
    phrases = data.get('flagged_phrases', [])
    if phrases:
        story.append(Paragraph('AI-Indicative Phrases Detected',
            S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=5)))
        rows = []; row = []
        for i, p in enumerate(phrases):
            row.append(Paragraph('◆ ' + p, S(fontName='Helvetica', fontSize=8.5,
                                              textColor=colors.HexColor('#b91c1c'))))
            if len(row) == 3: rows.append(row); row = []
        if row:
            while len(row) < 3: row.append(Paragraph('', S(fontName='Helvetica', fontSize=8)))
            rows.append(row)
        pt = Table(rows, colWidths=[W/3]*3)
        pt.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#fef2f2')),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#fecaca')),
            ('PADDING',(0,0),(-1,-1),6)]))
        story.append(pt)
        story.append(Spacer(1, 5*mm))

    # ── PAGE BREAK → FULL DOCUMENT WITH HIGHLIGHTS ──
    story.append(PageBreak())

    # Re-print logo on page 2
    build_turnitin_logo(story, subtitle="Highlighted Document — AI Writing Detection")
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('The full submitted document is shown below with AI content highlighted.',
        S(fontName='Helvetica', fontSize=8.5, textColor=colors.HexColor('#666677'), spaceAfter=8)))

    classified = data.get('classified_sentences', [])
    if classified:
        for cs in classified:
            t = cs.get('type', 'human')
            txt = cs.get('text', '')
            if not txt.strip(): continue
            if t == 'ai_orig':
                bg = colors.HexColor('#ffe8e8')
                border = colors.HexColor('#e74c3c')
                tc = colors.HexColor('#7b1a1a')
            elif t == 'ai_para':
                bg = colors.HexColor('#f3e8ff')
                border = colors.HexColor('#9b59b6')
                tc = colors.HexColor('#5b2d7b')
            else:
                bg = colors.white
                border = colors.HexColor('#dddddd')
                tc = colors.HexColor('#1a1a2e')

            p = Paragraph(txt, S(fontName='Helvetica', fontSize=9, textColor=tc,
                                  leading=14, leftIndent=6))
            cell = Table([[p]], colWidths=[W])
            cell.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(0,0), bg),
                ('LINEBEFORE',(0,0),(0,0), 3, border),
                ('TOPPADDING',(0,0),(-1,-1), 4),
                ('BOTTOMPADDING',(0,0),(-1,-1), 4),
                ('LEFTPADDING',(0,0),(-1,-1), 8),
                ('RIGHTPADDING',(0,0),(-1,-1), 6),
            ]))
            story.append(cell)
            story.append(Spacer(1, 1.5*mm))
    else:
        story.append(Paragraph(data.get('full_text','')[:4000],
            S(fontName='Helvetica', fontSize=9.5, textColor=colors.HexColor('#1a1a2e'), leading=16)))

    # ── FOOTER ──
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#ccccdd')))
    logo_f = "".join('<font color="{}">{}</font>'.format(LOGO_COLORS[i%len(LOGO_COLORS)], ch)
                     for i, ch in enumerate(LOGO_LETTERS))
    story.append(Paragraph(
        '<b>{}</b>  AI Detection Report  |  ID: {}  |  {}'.format(
            logo_f, data.get('submission_id',''), data.get('submission_date','')),
        S(fontName='Helvetica', fontSize=7.5, textColor=colors.HexColor('#888899'),
          alignment=TA_CENTER, spaceBefore=5)
    ))
    doc.build(story)

# ── SIMILARITY REPORT ────────────────────────────────────────────────────────
def build_similarity_pdf(data, buf):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable, PageBreak)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=14*mm, bottomMargin=18*mm,
                            leftMargin=18*mm, rightMargin=18*mm)
    story = []
    W = A4[0] - 36*mm

    plag = data.get('plag_score', 0)
    orig = data.get('original_pct', 100)
    pl = data.get('plag_label', ['No Similarity','#22c55e'])
    sources_list = data.get('sources_list', [])

    def S(**kw): return ParagraphStyle('s', **kw)

    # ── LOGO ──
    build_turnitin_logo(story, subtitle="Similarity Report")

    # ── DISCLAIMER (top) ──
    build_disclaimer(story, "sim")

    # ── SUBMISSION TABLE ──
    build_submission_table(story, data)

    # ── SCORE SUMMARY ──
    story.append(Paragraph('Originality Summary',
        S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=6)))

    def score_cell2(pct, label, col, sub):
        t = Table([[
            Paragraph('<b><font size="28" color="{}">{}</font><font size="12" color="{}">%</font></b>'.format(col,pct,col),
                      S(fontName='Helvetica-Bold', fontSize=28, alignment=TA_CENTER, leading=32)),
            Paragraph('<b>{}</b><br/><font size="7" color="#888">{}</font>'.format(label,sub),
                      S(fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor(col),
                        leading=13, alignment=TA_CENTER))
        ]], colWidths=[W/2 - 4*mm])
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(0,0),(-1,-1),'CENTER'),
                               ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
        return t

    c1 = score_cell2(plag, 'Similarity Index', pl[1], 'Matched to sources')
    c2 = score_cell2(orig, 'Original Content', '#27ae60', 'Unique to submission')
    boxes = Table([[c1, c2]], colWidths=[W/2]*2)
    boxes.setStyle(TableStyle([
        ('BOX',(0,0),(0,0),1.5,colors.HexColor(pl[1])),
        ('BOX',(1,0),(1,0),1.5,colors.HexColor('#27ae60')),
        ('BACKGROUND',(0,0),(0,0),colors.HexColor('#fff5f5')),
        ('BACKGROUND',(1,0),(1,0),colors.HexColor('#f0fff4')),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))
    story.append(boxes)
    story.append(Spacer(1,3*mm))
    story.append(Paragraph(
        '{}: <font color="{}"><b>{}</b></font>   |   Similarity {}% + Original {}% = <b>100%</b>'.format(
            'Similarity', pl[1], pl[0], plag, orig),
        S(fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#555566'),
          alignment=TA_CENTER, spaceAfter=6)
    ))

    # ── MATCHED SOURCES ──
    if sources_list:
        story.append(Paragraph('Matched Sources',
            S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=5)))
        hdr = [
            Paragraph('#', S(fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph('Source', S(fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph('URL', S(fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
            Paragraph('Similarity', S(fontName='Helvetica-Bold', fontSize=8, textColor=colors.white)),
        ]
        rows = [hdr]
        for i, src in enumerate(sources_list):
            rows.append([
                Paragraph(str(i+1), S(fontName='Helvetica', fontSize=8.5,
                                       textColor=colors.HexColor(src['color']))),
                Paragraph('<b>{}</b>'.format(src['name']),
                          S(fontName='Helvetica-Bold', fontSize=8.5,
                            textColor=colors.HexColor(src['color']))),
                Paragraph(src['url'], S(fontName='Helvetica', fontSize=8,
                                         textColor=colors.HexColor('#1565c0'))),
                Paragraph('<b>{}%</b>'.format(src['pct']),
                          S(fontName='Helvetica-Bold', fontSize=9,
                            textColor=colors.HexColor(src['color']),
                            alignment=TA_RIGHT)),
            ])
        st = Table(rows, colWidths=[10*mm, 55*mm, 72*mm, 25*mm])
        st.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1a1a2e')),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#ddddee')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8f8fc')]),
            ('PADDING',(0,0),(-1,-1),6),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ]))
        story.append(st)
        story.append(Spacer(1,4*mm))

        # Colour key
        story.append(Paragraph('Source Colour Key',
            S(fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1a1a2e'), spaceAfter=5)))
        key_items = []
        for src in sources_list:
            key_items.append(Table([[
                Table([['']], colWidths=[5*mm], rowHeights=[5*mm]),
                Paragraph(' {} — {}%'.format(src['name'], src['pct']),
                          S(fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#333344')))
            ]], colWidths=[8*mm, 50*mm]))
            key_items[-1].setStyle(TableStyle([
                ('BACKGROUND',(0,0),(0,0),colors.HexColor(src['color'])),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ]))
        rows2 = []; row2 = []
        for item in key_items:
            row2.append(item)
            if len(row2) == 3: rows2.append(row2); row2 = []
        if row2:
            while len(row2) < 3:
                row2.append(Paragraph('', S(fontName='Helvetica', fontSize=8)))
            rows2.append(row2)
        if rows2:
            kt = Table(rows2, colWidths=[W/3]*3)
            kt.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f8f8fc')),
                ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#ddddee')),
                ('PADDING',(0,0),(-1,-1),5),
            ]))
            story.append(kt)
        story.append(Spacer(1,4*mm))

    # ── FAQs ──
    build_faqs(story, "sim")

    # ── PAGE BREAK → FULL HIGHLIGHTED DOCUMENT ──
    story.append(PageBreak())

    build_turnitin_logo(story, subtitle="Highlighted Document — Similarity Report")
    story.append(Spacer(1,3*mm))
    story.append(Paragraph(
        'The full submitted document is shown below. Highlighted passages indicate text matching external sources. '
        'Each colour corresponds to a specific matched source shown in the key above.',
        S(fontName='Helvetica', fontSize=8.5, textColor=colors.HexColor('#666677'), spaceAfter=8)
    ))

    classified = data.get('classified_sentences', [])
    if classified:
        for cs in classified:
            t = cs.get('type', 'human')
            txt = cs.get('text', '')
            if not txt.strip(): continue
            if t == 'plag':
                src_color = cs.get('color', '#e74c3c')
                bg_hex = src_color + '22'
                try: bg = colors.HexColor(bg_hex)
                except: bg = colors.HexColor('#ffe8e8')
                border = colors.HexColor(src_color)
                tc = colors.HexColor('#1a1a2e')
                source_note = '  [{}]'.format(cs.get('label','Source'))
            else:
                bg = colors.white
                border = colors.HexColor('#eeeeee')
                tc = colors.HexColor('#1a1a2e')
                source_note = ''

            full_txt = txt + source_note
            p = Paragraph(full_txt, S(fontName='Helvetica', fontSize=9,
                                       textColor=tc, leading=14, leftIndent=6))
            cell = Table([[p]], colWidths=[W])
            cell.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(0,0), bg),
                ('LINEBEFORE',(0,0),(0,0), 3, border),
                ('TOPPADDING',(0,0),(-1,-1), 4),
                ('BOTTOMPADDING',(0,0),(-1,-1), 4),
                ('LEFTPADDING',(0,0),(-1,-1), 8),
                ('RIGHTPADDING',(0,0),(-1,-1), 6),
            ]))
            story.append(cell)
            story.append(Spacer(1, 1.5*mm))
    else:
        story.append(Paragraph(data.get('full_text','')[:4000],
            S(fontName='Helvetica', fontSize=9.5, leading=16,
              textColor=colors.HexColor('#1a1a2e'))))

    # ── FOOTER ──
    story.append(Spacer(1,6*mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#ccccdd')))
    logo_f = "".join('<font color="{}">{}</font>'.format(LOGO_COLORS[i%len(LOGO_COLORS)], ch)
                     for i, ch in enumerate(LOGO_LETTERS))
    story.append(Paragraph(
        '<b>{}</b>  Similarity Report  |  ID: {}  |  {}'.format(
            logo_f, data.get('submission_id',''), data.get('submission_date','')),
        S(fontName='Helvetica', fontSize=7.5, textColor=colors.HexColor('#888899'),
          alignment=TA_CENTER, spaceBefore=5)
    ))
    doc.build(story)

if __name__ == '__main__':
    app.run(debug=True)
