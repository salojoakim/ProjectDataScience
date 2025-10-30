# utils/attachment_parser.py
"""
Attachment parser that works with file paths (including temp files from GCS).
"""

from __future__ import annotations

import os
from typing import Union
from bs4 import BeautifulSoup  # pip install beautifulsoup4

def parse_attachments(file_path: Union[str, dict]) -> str:
    """
    Parse non-tabular attachments to text.
    
    Args:
        file_path: Can be a string path or a dict with 'path'/'temp_path' key
    
    Returns:
        Text content of the attachment
    """
    path = None
    
    # Handle both string paths and dict structures
    if isinstance(file_path, str):
        path = file_path
    elif isinstance(file_path, dict):
        # Try different key names
        for k in ("temp_path", "path", "filepath", "file_path"):
            if k in file_path and file_path[k]:
                path = str(file_path[k])
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
        
        # For text files, just read them
        if ext in (".txt", ".text"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        
        # For PDFs/DOCs, you can integrate pdfminer/docx later if needed
        # For now, return empty string for unsupported types
        
    except Exception as e:
        print(f"Error parsing attachment {path}: {e}")

    return ""