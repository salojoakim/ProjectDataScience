# utils/email_reader_gcs.py
"""
Email reader that works with GCS storage.
Downloads .eml files from GCS bucket to temp files for parsing.
"""

from __future__ import annotations

import os
import tempfile
from email import policy
from email.parser import BytesParser
from typing import Dict, Generator

from utils.gcs_storage import get_storage


def _best_body(msg) -> str:
    """Extract email body, preferring HTML over plaintext."""
    if msg.is_multipart():
        html = None
        text = None
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/html" and html is None:
                try:
                    html = part.get_content()
                except Exception:
                    pass
            elif ctype == "text/plain" and text is None:
                try:
                    text = part.get_content()
                except Exception:
                    pass
        return html or (text or "")
    else:
        ctype = msg.get_content_type()
        try:
            return msg.get_content() if ctype in ("text/html", "text/plain") else ""
        except Exception:
            return ""


def _save_attachments_to_temp(msg) -> list[dict]:
    """
    Extract attachments from email and save to temp files.
    Returns list of dicts with filename and temp_path.
    """
    attachments = []
    for part in msg.walk():
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disp:
            continue
        
        filename = part.get_filename() or "attachment.bin"
        safe_name = "".join(ch for ch in filename if ch not in "\\/:*?\"<>|")
        
        try:
            content = part.get_payload(decode=True) or b""
            
            # Create temp file with appropriate suffix
            suffix = os.path.splitext(safe_name)[1]
            fd, temp_path = tempfile.mkstemp(suffix=suffix)
            try:
                with os.fdopen(fd, 'wb') as tmp:
                    tmp.write(content)
            except:
                os.close(fd)
                raise
            
            attachments.append({
                "filename": safe_name,
                "temp_path": temp_path
            })
        except Exception as e:
            print(f"Error saving attachment {safe_name}: {e}")
            continue
    
    return attachments


def iter_eml_messages_gcs(inbox_prefix: str) -> Generator[Dict, None, None]:
    """
    Iterate over .eml files in GCS bucket.
    
    Args:
        inbox_prefix: GCS prefix where .eml files are stored
        
    Yields:
        Dict with 'filename', 'body', and 'attachments' (each with temp_path)
    """
    storage = get_storage()
    
    # List all .eml files in the inbox prefix
    eml_files = storage.list_files(prefix=inbox_prefix, suffix=".eml")
    
    if not eml_files:
        print(f"No .eml files found in {inbox_prefix}")
        return
    
    for blob_name in sorted(eml_files):
        filename = os.path.basename(blob_name)
        
        try:
            # Download to temp file
            temp_eml_path = storage.download_to_tempfile(blob_name, suffix=".eml")
            
            # Parse email
            with open(temp_eml_path, "rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)
            
            # Extract body
            body = _best_body(msg) or ""
            
            # Extract attachments to temp files
            attachments = _save_attachments_to_temp(msg)
            
            yield {
                "filename": filename,
                "body": body,
                "attachments": attachments
            }
            
            # Cleanup temp eml file
            try:
                os.remove(temp_eml_path)
            except:
                pass
            
        except Exception as e:
            print(f"Error processing {filename}: {e}")
            continue