# utils/attachment_parser.py
from __future__ import annotations

import os
from typing import Union
from bs4 import BeautifulSoup  # pip install beautifulsoup4

def parse_attachments(att: Union[str, dict]) -> str:
    """
    For non-tabular attachments, return a text rendering.
    - HTML: strip tags to text (keeps table text but not structure; your tools.py does direct table parsing).
    - Others: best-effort (empty string ok; tools.py uses direct CSV/XLSX parsing).
    """
    path = None
    if isinstance(att, str):
        path = att
    elif isinstance(att, dict):
        for k in ("path", "filepath", "file_path"):
            if k in att and att[k]:
                path = str(att[k])
                break
    if not path or not os.path.exists(path):
        return ""

    ext = os.path.splitext(path.lower())[1]
    try:
        if ext in (".html", ".htm"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
            soup = BeautifulSoup(html, "html.parser")
            return soup.get_text(" ", strip=True)
        # For PDFs/DOCs/etc you can integrate pdfminer/docx later if needed.
    except Exception:
        pass

    return ""
