"""Document Studio: AI-generate résumés, CVs, cover letters, presentations,
reports, letters, proposals, READMEs, meeting minutes — and export each one as
.docx, .pptx, .pdf, .html, .md or .txt.

The model writes structured Markdown for the chosen document kind (with a solid
template fallback when no model is running); pure-Python renderers convert that
Markdown into real files — Office Open XML written directly with ``zipfile``
(no python-docx/pptx) and a minimal from-scratch PDF writer. Every generated
file is stored under the platform data dir and recorded in ``generated_docs``,
so your documents survive restarts and are always re-downloadable.

/render exports *your own* Markdown to any format — edit the AI draft, then
re-export, no regeneration needed.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core import db, llmutil

FORMATS = ("md", "txt", "html", "docx", "pptx", "pdf")

KINDS: Dict[str, Dict[str, str]] = {
    "resume": {
        "label": "Résumé (one page, ATS-friendly)",
        "prompt": "Write a complete one-page ATS-friendly résumé in Markdown: # Name, "
                  "contact line, ## Professional Summary, ## Core Skills, ## Experience "
                  "(quantified bullets), ## Projects, ## Education.",
    },
    "cv": {
        "label": "CV (detailed, academic/EU style)",
        "prompt": "Write a detailed multi-section CV in Markdown: # Name, contact line, "
                  "## Profile, ## Work Experience (full detail), ## Education, "
                  "## Publications/Projects, ## Skills, ## Languages, ## Certifications.",
    },
    "cover_letter": {
        "label": "Cover letter",
        "prompt": "Write a tailored 250-350 word cover letter in Markdown with a specific "
                  "opening hook (never 'I am writing to apply'), 2-3 achievements mapped "
                  "to the role, and a confident close.",
    },
    "presentation": {
        "label": "Presentation (slides)",
        "prompt": "Write a slide deck in Markdown: '# Deck Title' first, then each slide "
                  "as '## Slide Title' followed by 3-5 tight bullet points ('- '). "
                  "8-12 slides, one idea per slide, no walls of text.",
    },
    "report": {
        "label": "Report / analysis",
        "prompt": "Write a structured report in Markdown: # Title, ## Executive Summary, "
                  "## Background, ## Findings (with bullets), ## Recommendations, ## Next Steps.",
    },
    "letter": {
        "label": "Formal letter",
        "prompt": "Write a formal letter in Markdown: sender block, date, recipient block, "
                  "subject line in bold, respectful body, sign-off.",
    },
    "readme": {
        "label": "Project README",
        "prompt": "Write a GitHub README in Markdown: # Project, one-line pitch, badges "
                  "placeholder, ## Features, ## Quickstart (code blocks), ## Usage, "
                  "## Architecture, ## Contributing, ## License.",
    },
    "proposal": {
        "label": "Business/project proposal",
        "prompt": "Write a project proposal in Markdown: # Title, ## Problem, ## Proposed "
                  "Solution, ## Scope & Deliverables, ## Timeline, ## Budget, ## Risks.",
    },
    "meeting_minutes": {
        "label": "Meeting minutes",
        "prompt": "Write meeting minutes in Markdown: # Meeting, date/attendees lines, "
                  "## Agenda, ## Decisions, ## Action Items (owner + due date bullets).",
    },
    "ieee_paper": {
        "label": "IEEE research paper (use /api/docgen/paper for deep research)",
        "prompt": "Write a research paper in IEEE conference style, in Markdown: # Title, "
                  "authors line, ## Abstract (150-250 words), ## Index Terms, "
                  "## I. Introduction, ## II. Related Work, ## III. Methodology, "
                  "## IV. Results and Discussion, ## V. Conclusion, ## References "
                  "(IEEE numbered style [1], [2], ...).",
    },
    "custom": {
        "label": "Anything else (describe it)",
        "prompt": "Write the document the user describes, in clean structured Markdown "
                  "with a # title and ## sections.",
    },
}


# ------------------------- markdown → block model --------------------------- #
def parse_blocks(md: str) -> List[Dict[str, str]]:
    """[{type: h1|h2|h3|bullet|para, text}] — the shared input for all renderers."""
    blocks: List[Dict[str, str]] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append({"type": "h3", "text": line[4:].strip()})
        elif line.startswith("## "):
            blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("# "):
            blocks.append({"type": "h1", "text": line[2:].strip()})
        elif re.match(r"^\s*[-*•]\s+", line):
            blocks.append({"type": "bullet", "text": re.sub(r"^\s*[-*•]\s+", "", line)})
        else:
            blocks.append({"type": "para", "text": line.strip()})
    return blocks


def _plain(text: str) -> str:
    """Strip inline markdown (bold/italic/links/code) for non-rich formats."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[*_`]{1,3}([^*_`]*)[*_`]{1,3}", r"\1", text)


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


# ------------------------------- renderers ---------------------------------- #
def render_txt(md: str, title: str) -> bytes:
    lines = []
    for b in parse_blocks(md):
        t = _plain(b["text"])
        if b["type"] == "h1":
            lines += [t.upper(), "=" * len(t), ""]
        elif b["type"] in ("h2", "h3"):
            lines += ["", t, "-" * len(t)]
        elif b["type"] == "bullet":
            lines.append("  - " + t)
        else:
            lines.append(t)
    return "\n".join(lines).encode()


def render_html(md: str, title: str) -> bytes:
    body = []
    in_list = False
    for b in parse_blocks(md):
        if b["type"] == "bullet" and not in_list:
            body.append("<ul>")
            in_list = True
        elif b["type"] != "bullet" and in_list:
            body.append("</ul>")
            in_list = False
        t = _xml(_plain(b["text"]))
        if b["type"] in ("h1", "h2", "h3"):
            body.append(f"<{b['type']}>{t}</{b['type']}>")
        elif b["type"] == "bullet":
            body.append(f"<li>{t}</li>")
        else:
            body.append(f"<p>{t}</p>")
    if in_list:
        body.append("</ul>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_xml(title)}</title>"
            "<style>body{font:15px/1.6 Georgia,serif;max-width:760px;margin:3rem auto;"
            "padding:0 1rem;color:#222}h1{border-bottom:2px solid #e62429;padding-bottom:.3rem}"
            "h2{margin-top:1.6rem;color:#1a237e}li{margin:.25rem 0}</style></head><body>"
            + "\n".join(body) + "</body></html>").encode()


# -- DOCX: Office Open XML written directly (no python-docx) ------------------ #
def render_docx(md: str, title: str) -> bytes:
    paras = []
    for b in parse_blocks(md):
        t = _xml(_plain(b["text"]))
        if b["type"] == "h1":
            props, text = '<w:rPr><w:b/><w:sz w:val="40"/></w:rPr>', t
        elif b["type"] == "h2":
            props, text = '<w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="1A237E"/></w:rPr>', t
        elif b["type"] == "h3":
            props, text = '<w:rPr><w:b/><w:sz w:val="25"/></w:rPr>', t
        elif b["type"] == "bullet":
            props, text = '<w:rPr><w:sz w:val="22"/></w:rPr>', "•  " + t
        else:
            props, text = '<w:rPr><w:sz w:val="22"/></w:rPr>', t
        indent = '<w:pPr><w:ind w:left="360"/></w:pPr>' if b["type"] == "bullet" else ""
        paras.append(f'<w:p>{indent}<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{"".join(paras)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:bottom="1134" w:left="1134" w:right="1134"/></w:sectPr>'
                '</w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType='
                     '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument'
            '/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


# -- PPTX: minimal but valid deck, one slide per '## ' section ---------------- #
_PPT_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')


def _pptx_textbox(name: str, x: int, y: int, w: int, h: int,
                  paras: List[str], size: int, bold: bool, color: str) -> str:
    body = []
    for t in paras:
        body.append(
            f'<a:p><a:pPr/><a:r><a:rPr lang="en-US" sz="{size * 100}" b="{int(bold)}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr>'
            f'<a:t>{_xml(t)}</a:t></a:r></a:p>')
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{abs(hash(name)) % 9000 + 10}" name="{name}"/>'
            '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>'
            f'{"".join(body)}</p:txBody></p:sp>')


def _pptx_slide(title: str, bullets: List[str]) -> str:
    shapes = _pptx_textbox("Title", 685800, 457200, 10820400, 1143000, [title], 32, True, "1A237E")
    if bullets:
        shapes += _pptx_textbox("Body", 685800, 1828800, 10820400, 4114800,
                                ["•  " + b for b in bullets], 18, False, "222222")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sld {_PPT_NS}><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping bg1="lt1" tx1="dk1" '
            'bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
            'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
            'folHlink="folHlink"/></p:clrMapOvr></p:sld>')


_PPTX_THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Spidey">'
'<a:themeElements><a:clrScheme name="Spidey"><a:dk1><a:srgbClr val="111111"/></a:dk1>'
'<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1A237E"/></a:dk2>'
'<a:lt2><a:srgbClr val="EEEEEE"/></a:lt2><a:accent1><a:srgbClr val="E62429"/></a:accent1>'
'<a:accent2><a:srgbClr val="1A237E"/></a:accent2><a:accent3><a:srgbClr val="5B9BFF"/></a:accent3>'
'<a:accent4><a:srgbClr val="34D399"/></a:accent4><a:accent5><a:srgbClr val="FBBF24"/></a:accent5>'
'<a:accent6><a:srgbClr val="9A9AA8"/></a:accent6><a:hlink><a:srgbClr val="5B9BFF"/></a:hlink>'
'<a:folHlink><a:srgbClr val="9A9AA8"/></a:folHlink></a:clrScheme>'
'<a:fontScheme name="Spidey"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
'<a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
'<a:cs typeface=""/></a:minorFont></a:fontScheme>'
'<a:fmtScheme name="Spidey"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
'<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/>'
'</a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln><a:solidFill><a:schemeClr val="phClr"/>'
'</a:solidFill></a:ln><a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
'<a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
'<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/>'
'</a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
'<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill>'
'<a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
'</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')


def slides_from_markdown(md: str, title: str) -> List[Dict[str, Any]]:
    """'# Title' → title slide; each '## Heading' + bullets/paras → one slide."""
    slides: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    deck_title = title
    for b in parse_blocks(md):
        if b["type"] == "h1":
            deck_title = _plain(b["text"])
        elif b["type"] in ("h2", "h3"):
            current = {"title": _plain(b["text"]), "bullets": []}
            slides.append(current)
        else:
            if current is None:
                current = {"title": deck_title, "bullets": []}
                slides.append(current)
            current["bullets"].append(_plain(b["text"]))
    return [{"title": deck_title, "bullets": []}] + slides if slides else \
           [{"title": deck_title, "bullets": ["(empty document)"]}]


def render_pptx(md: str, title: str) -> bytes:
    slides = slides_from_markdown(md, title)
    n = len(slides)
    ct_slides = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, n + 1))
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f'{ct_slides}</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument'
        '/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
    slide_ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, n + 1))
    presentation = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation {_PPT_NS}>'
        f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{n + 1}"/></p:sldMasterIdLst>'
        f'<p:sldIdLst>{slide_ids}</p:sldIdLst>'
        '<p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        '</p:presentation>')
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pres_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="{rel_type}/slide" '
                  f'Target="slides/slide{i}.xml"/>' for i in range(1, n + 1))
        + f'<Relationship Id="rId{n + 1}" Type="{rel_type}/slideMaster" '
          'Target="slideMasters/slideMaster1.xml"/></Relationships>')
    master = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sldMaster {_PPT_NS}><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr/></p:spTree></p:cSld>'
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
        'hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        '</p:sldMaster>')
    master_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel_type}/theme" Target="../theme/theme1.xml"/>'
        '</Relationships>')
    layout = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sldLayout {_PPT_NS}><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr/></p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    layout_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}/slideMaster" '
        'Target="../slideMasters/slideMaster1.xml"/></Relationships>')
    slide_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel_type}/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("ppt/presentation.xml", presentation)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slideMasters/slideMaster1.xml", master)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels)
        z.writestr("ppt/theme/theme1.xml", _PPTX_THEME)
        for i, s in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", _pptx_slide(s["title"], s["bullets"]))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", slide_rels)
    return buf.getvalue()


# -- PDF: minimal from-scratch writer (Helvetica, A4, multi-page) -------------- #
def _pdf_escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            .encode("latin-1", "replace").decode("latin-1"))


def render_pdf(md: str, title: str) -> bytes:
    # Layout: (font_size, leading, wrap_chars, extra_space_before)
    styles = {"h1": (18, 24, 55, 10), "h2": (14, 20, 70, 8), "h3": (12, 17, 80, 6),
              "bullet": (10, 14, 92, 0), "para": (10, 14, 92, 0)}
    pages: List[List[str]] = [[]]
    y = 800.0
    for b in parse_blocks(md):
        size, leading, wrap, space = styles[b["type"]]
        text = _plain(b["text"])
        prefix = "-  " if b["type"] == "bullet" else ""
        words, line = text.split(), ""
        wrapped = []
        for w in words:
            if len(line) + len(w) + 1 > wrap:
                wrapped.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        wrapped.append(line)
        y -= space
        for j, ln in enumerate(wrapped):
            if y < 60:
                pages.append([])
                y = 800.0
            indent = 50 if not prefix or j == 0 else 62
            pages[-1].append(f"BT /F1 {size} Tf {indent} {y:.0f} Td "
                             f"({_pdf_escape((prefix if j == 0 else '') + ln)}) Tj ET")
            y -= leading

    objects: List[bytes] = []
    n_pages = len(pages)
    page_obj_ids = [4 + i * 2 for i in range(n_pages)]
    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")                       # 1
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())  # 2
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
    for i, cmds in enumerate(pages):
        stream = "\n".join(cmds).encode("latin-1", "replace")
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                        f"/Resources << /Font << /F1 3 0 R >> >> "
                        f"/Contents {page_obj_ids[i] + 1} 0 R >>").encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                       + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF").encode()
    return bytes(out)


RENDERERS = {"md": lambda md, t: md.encode(), "txt": render_txt, "html": render_html,
             "docx": render_docx, "pptx": render_pptx, "pdf": render_pdf}
MEDIA_TYPES = {
    "md": "text/markdown", "txt": "text/plain", "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    # generated media (Media Studio) reuse the same download endpoint
    "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
    "mp3": "audio/mpeg", "wav": "audio/wav", "mp4": "video/mp4"}


# ------------------------------ generation ----------------------------------- #
def generate_markdown(kind: str, prompt: str, details: str) -> Dict[str, str]:
    spec = KINDS[kind]
    llm = llmutil.ask(
        f"{spec['prompt']}\n\nUSER BRIEF:\n{prompt}\n\n"
        + (f"SOURCE MATERIAL (use only true facts from here):\n{details[:5000]}\n\n" if details else "")
        + "Output clean Markdown only — no code fences, no commentary.",
        system="You are a professional document writer. Never invent facts about the user; "
               "work from the brief and source material only.")
    if llm:
        return {"markdown": re.sub(r"^```(?:markdown)?|```$", "", llm.strip(), flags=re.M).strip(),
                "mode": "llm"}
    # Template fallback: honest skeleton the user can fill in / re-export later.
    sections = {
        "resume": ["Professional Summary", "Core Skills", "Experience", "Projects", "Education"],
        "cv": ["Profile", "Work Experience", "Education", "Projects", "Skills", "Languages"],
        "presentation": ["Why this matters", "The problem", "The approach", "Results", "Next steps"],
        "report": ["Executive Summary", "Background", "Findings", "Recommendations"],
    }.get(kind, ["Overview", "Details", "Next Steps"])
    body = "\n\n".join(f"## {s}\n- {prompt[:120] or 'fill this in'}" for s in sections)
    return {"markdown": f"# {prompt[:60] or KINDS[kind]['label']}\n\n{body}\n\n"
                        f"> Template mode — start a model (`spidey up`) for full AI writing.",
            "mode": "template"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or "document"


def create_document(kind: str, fmt: str, title: str, prompt: str, details: str) -> Dict[str, Any]:
    gen = generate_markdown(kind, prompt, details)
    payload = RENDERERS[fmt](gen["markdown"], title)
    out_dir = db.data_dir() / "generated"
    out_dir.mkdir(exist_ok=True)
    doc_id = db.execute(
        "INSERT INTO generated_docs(kind, title, format, path, size, prompt, markdown,"
        " mode, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (kind, title, fmt, "", len(payload), prompt[:1000], gen["markdown"], gen["mode"], db.now()))
    path = out_dir / f"{doc_id:04d}-{_slug(title)}.{fmt}"
    path.write_bytes(payload)
    db.execute("UPDATE generated_docs SET path=? WHERE id=?", (str(path), doc_id))
    return {"id": doc_id, "title": title, "kind": kind, "format": fmt,
            "size": len(payload), "mode": gen["mode"], "markdown": gen["markdown"],
            "download_url": f"/api/docgen/files/{doc_id}/download"}


# --------------------- deep-research IEEE paper pipeline --------------------- #
PAPER_SECTIONS = [
    ("Abstract", "Write the Abstract (150-250 words): problem, approach, key findings."),
    ("I. Introduction", "Write the Introduction: motivation, problem statement, "
                        "contributions as a bulleted list, paper organization."),
    ("II. Related Work", "Write Related Work: survey the area, cite the provided "
                         "sources as [n] matching the reference list."),
    ("III. Methodology", "Write the Methodology: the approach/system/algorithm in "
                         "technical depth; describe architecture and design choices."),
    ("IV. Results and Discussion", "Write Results and Discussion: expected/observed "
                                   "outcomes, comparisons, limitations. Be honest "
                                   "about what is analysis vs. measurement."),
    ("V. Conclusion", "Write the Conclusion: findings, implications, future work."),
]


def _fetch_sources(topic: str) -> List[Dict[str, str]]:
    """Real references: Crossref (academic, with DOIs) + Wikipedia summary.
    Free APIs, no keys; failures just mean fewer sources."""
    import requests
    sources: List[Dict[str, str]] = []
    try:
        r = requests.get("https://api.crossref.org/works",
                         params={"query": topic, "rows": 6, "select": "title,author,DOI,"
                                 "container-title,issued"}, timeout=15)
        for item in r.json().get("message", {}).get("items", []):
            title = (item.get("title") or ["?"])[0]
            authors = ", ".join(f"{a.get('family', '')}" for a in (item.get("author") or [])[:3])
            year = str((item.get("issued", {}).get("date-parts") or [[""]])[0][0])
            venue = (item.get("container-title") or [""])[0]
            sources.append({"ref": f"{authors}, \"{title},\" {venue}, {year}.",
                            "doi": item.get("DOI", ""),
                            "summary": ""})
    except Exception:
        pass
    try:
        r = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                         + topic.replace(" ", "_"), timeout=10,
                         headers={"User-Agent": "SpideyPlatform/1.0"})
        if r.ok:
            j = r.json()
            if j.get("extract"):
                sources.append({"ref": f"Wikipedia contributors, \"{j.get('title', topic)},\" "
                                       "Wikipedia, The Free Encyclopedia.",
                                "doi": "", "summary": j["extract"][:1500]})
    except Exception:
        pass
    return sources


def _paper_progress(run_id: int, status: str, stage: str, done: List[str]) -> None:
    db.execute("UPDATE paper_runs SET status=?, progress=? WHERE id=?",
               (status, db.json_dumps({"stage": stage, "sections_done": done}), run_id))


def _job_research_paper(payload: Dict[str, Any]) -> Dict[str, Any]:
    run_id, topic, fmt = payload["run_id"], payload["topic"], payload.get("format", "pdf")
    try:
        _paper_progress(run_id, "researching", "fetching sources (Crossref + Wikipedia)", [])
        sources = _fetch_sources(topic)
        db.execute("UPDATE paper_runs SET sources=? WHERE id=?",
                   (db.json_dumps(sources), run_id))
        refs_block = "\n".join(f"[{i}] {s['ref']}" + (f" doi:{s['doi']}" if s["doi"] else "")
                               for i, s in enumerate(sources, 1)) or "[1] (no sources reachable)"
        background = "\n\n".join(s["summary"] for s in sources if s["summary"])

        parts = [f"# {topic}", "", "*Generated by Spidey Document Studio — draft for review*", ""]
        done: List[str] = []
        for name, instruction in PAPER_SECTIONS:
            _paper_progress(run_id, "writing", f"writing {name}", done)
            section = llmutil.ask(
                f"TOPIC: {topic}\n\nAVAILABLE REFERENCES (cite as [n]):\n{refs_block}\n\n"
                + (f"BACKGROUND MATERIAL:\n{background[:2500]}\n\n" if background else "")
                + (f"PAPER SO FAR (for continuity):\n{chr(10).join(parts)[-2500:]}\n\n")
                + f"{instruction}\nOutput Markdown for this section only, starting with "
                  f"'## {name}'. Dense, technical, no fluff.",
                system="You are an experienced IEEE conference paper author. Rigorous, "
                       "precise, honest about limitations. Never fabricate citations — "
                       "only cite the provided reference list.")
            if section is None:
                raise RuntimeError("deep research needs a model — start Ollama (`spidey up`)")
            if not section.lstrip().startswith("##"):
                section = f"## {name}\n\n{section}"
            parts += [section.strip(), ""]
            done.append(name)
        parts += ["## References", ""] + [f"[{i}] {s['ref']}" for i, s in enumerate(sources, 1)]
        markdown = "\n".join(parts)

        _paper_progress(run_id, "writing", f"rendering .{fmt}", done)
        payload_bytes = RENDERERS[fmt](markdown, topic)
        out_dir = db.data_dir() / "generated"
        out_dir.mkdir(exist_ok=True)
        doc_id = db.execute(
            "INSERT INTO generated_docs(kind, title, format, path, size, prompt, markdown,"
            " mode, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("ieee_paper", topic, fmt, "", len(payload_bytes), topic, markdown, "llm", db.now()))
        path = out_dir / f"{doc_id:04d}-{_slug(topic)}.{fmt}"
        path.write_bytes(payload_bytes)
        db.execute("UPDATE generated_docs SET path=? WHERE id=?", (str(path), doc_id))
        db.execute("UPDATE paper_runs SET status='done', doc_id=?, finished_at=? WHERE id=?",
                   (doc_id, db.now(), run_id))
        return {"doc_id": doc_id, "sections": len(done), "references": len(sources)}
    except Exception as e:
        db.execute("UPDATE paper_runs SET status='failed', error=?, finished_at=? WHERE id=?",
                   (str(e), db.now(), run_id))
        raise


def register_jobs(queue) -> None:
    queue.register("docgen.paper", _job_research_paper)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/docgen", tags=["Documents"])


class CreateIn(BaseModel):
    kind: str
    format: str = "docx"
    title: str = ""
    prompt: str
    details: str = ""   # source material: resume text, notes, data — facts only


class RenderIn(BaseModel):
    markdown: str
    format: str = "docx"
    title: str = "document"


@router.get("/kinds")
def kinds() -> dict:
    return {"kinds": [{"kind": k, "label": v["label"]} for k, v in KINDS.items()],
            "formats": list(FORMATS)}


@router.post("/create")
def api_create(body: CreateIn) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {list(KINDS)}")
    if body.format not in FORMATS:
        raise HTTPException(422, f"format must be one of {FORMATS}")
    if not body.prompt.strip():
        raise HTTPException(422, "prompt is required — describe the document you want")
    title = body.title.strip() or f"{KINDS[body.kind]['label']}"
    return create_document(body.kind, body.format, title, body.prompt, body.details)


@router.post("/render")
def api_render(body: RenderIn) -> dict:
    """Export YOUR markdown (e.g. the edited AI draft) to any format."""
    if body.format not in FORMATS:
        raise HTTPException(422, f"format must be one of {FORMATS}")
    payload = RENDERERS[body.format](body.markdown, body.title)
    out_dir = db.data_dir() / "generated"
    out_dir.mkdir(exist_ok=True)
    doc_id = db.execute(
        "INSERT INTO generated_docs(kind, title, format, path, size, prompt, markdown,"
        " mode, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("custom", body.title, body.format, "", len(payload), "", body.markdown,
         "render", db.now()))
    path = out_dir / f"{doc_id:04d}-{_slug(body.title)}.{body.format}"
    path.write_bytes(payload)
    db.execute("UPDATE generated_docs SET path=? WHERE id=?", (str(path), doc_id))
    return {"id": doc_id, "size": len(payload),
            "download_url": f"/api/docgen/files/{doc_id}/download"}


class PaperIn(BaseModel):
    topic: str
    format: str = "pdf"


@router.post("/paper")
def start_paper(body: PaperIn) -> dict:
    """Deep-research an IEEE-style paper: fetch real references (Crossref +
    Wikipedia), then draft section by section on the job queue. Poll
    GET /api/docgen/paper/{id} to watch progress; the finished file lands in
    /api/docgen/files. Needs a running model."""
    if not body.topic.strip():
        raise HTTPException(422, "topic is required")
    if body.format not in FORMATS:
        raise HTTPException(422, f"format must be one of {FORMATS}")
    run_id = db.execute("INSERT INTO paper_runs(topic, created_at) VALUES(?,?)",
                        (body.topic.strip(), db.now()))
    from ..core.queue import default_queue
    default_queue().enqueue("docgen.paper", {"run_id": run_id, "topic": body.topic.strip(),
                                             "format": body.format}, max_attempts=1)
    return {"id": run_id, "status": "queued",
            "note": "poll GET /api/docgen/paper/{id} — sections appear as they're written"}


@router.get("/paper/{run_id}")
def paper_status(run_id: int) -> dict:
    row = db.one("SELECT * FROM paper_runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(404, "paper run not found")
    row["progress"] = db.json_loads(row["progress"], {})
    row["sources"] = db.json_loads(row["sources"], [])
    if row["doc_id"]:
        row["download_url"] = f"/api/docgen/files/{row['doc_id']}/download"
        doc = db.one("SELECT markdown FROM generated_docs WHERE id=?", (row["doc_id"],))
        row["markdown"] = doc["markdown"] if doc else None
    return row


@router.get("/papers")
def list_papers(limit: int = 20) -> list:
    return db.query("SELECT id, topic, status, created_at, finished_at, doc_id FROM"
                    " paper_runs ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/files")
def list_generated(limit: int = 50) -> list:
    return db.query("SELECT id, kind, title, format, size, mode, created_at FROM"
                    " generated_docs ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/files/{doc_id}")
def get_generated(doc_id: int) -> dict:
    row = db.one("SELECT * FROM generated_docs WHERE id=?", (doc_id,))
    if not row:
        raise HTTPException(404, "document not found")
    return row


@router.get("/files/{doc_id}/download")
def download(doc_id: int):
    row = db.one("SELECT * FROM generated_docs WHERE id=?", (doc_id,))
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "document not found (or its file was cleaned up)")
    filename = Path(row["path"]).name.split("-", 1)[-1]
    return FileResponse(row["path"], media_type=MEDIA_TYPES[row["format"]],
                        filename=filename)
