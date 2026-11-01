from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class PDFContent:
    full_text: str
    pages: int
    title_guess: str
    abstract: str
    references_raw: list[str]


def extract_pdf(pdf_path: str | Path) -> PDFContent:
    doc = pymupdf.open(str(pdf_path))
    pages = len(doc)

    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    full_text = "\n".join(text_parts)
    doc.close()

    title_guess = _guess_title(full_text, str(pdf_path))
    abstract = _extract_abstract(full_text)
    references_raw = _extract_references(full_text)

    return PDFContent(
        full_text=full_text,
        pages=pages,
        title_guess=title_guess,
        abstract=abstract,
        references_raw=references_raw,
    )


def _guess_title(text: str, filename: str) -> str:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines[:10]:
        if len(line) > 15 and len(line) < 300 and not re.match(r"^(abstract|keywords|introduction|\d)", line, re.I):
            if not re.match(r"^(arxiv|doi|http|www)", line, re.I):
                return line
    return Path(filename).stem


def _extract_abstract(text: str) -> str:
    patterns = [
        r"(?i)abstract\s*[-—:]\s*\n?(.*?)(?=\n\s*(?:keywords|introduction|1[\.\s]|I\.\s))",
        r"(?i)abstract\s*[-—:]\s*\n?(.*?)(?=\n\n)",
        r"(?i)abstract\s*[-—:]\s*\n?(.{50,500})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return ""


def _extract_references(text: str) -> list[str]:
    patterns = [
        r"(?i)(?:references|bibliography)\s*\n(.*?)(?=\n\s*(?:appendix|acknowledgment|$))",
        r"(?i)(?:references|bibliography)\s*\n(.*)",
    ]
    ref_section = ""
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            ref_section = m.group(1).strip()
            break

    if not ref_section:
        return []

    refs = re.split(r"\n\s*(?=\[\d+\]|\(\d{4}\)|^\d+[\.\)])", ref_section)
    return [r.strip() for r in refs if r.strip() and len(r.strip()) > 10]


def split_paper_text(text: str) -> dict[str, str]:
    sections = {}
    section_names = ["introduction", "method", "approach", "model", "experiment", "result", "discussion", "conclusion", "related work"]

    current_section = "preamble"
    current_text = []

    for line in text.split("\n"):
        matched = False
        for name in section_names:
            if re.match(rf"^(?:\d+[\.\s]*|I+I*[\.\s]*)?{name}", line.strip(), re.I):
                if current_text:
                    sections[current_section] = "\n".join(current_text)
                current_section = name
                current_text = [line]
                matched = True
                break
        if not matched:
            current_text.append(line)

    if current_text:
        sections[current_section] = "\n".join(current_text)

    return sections
