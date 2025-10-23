# utils/email_reader.py
from __future__ import annotations

import os
from email import policy
from email.parser import BytesParser
from typing import Dict, Generator

def _best_body(msg) -> str:
    # Prefer HTML, then plaintext
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
        # single-part message
        ctype = msg.get_content_type()
        try:
            return msg.get_content() if ctype in ("text/html", "text/plain") else ""
        except Exception:
            return ""

def _save_attachments(msg, dest_dir: str) -> list[dict]:
    out = []
    for part in msg.walk():
        disp = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disp:
            continue
        filename = part.get_filename() or "attachment.bin"
        safe = "".join(ch for ch in filename if ch not in "\\/:*?\"<>|")
        path = os.path.join(dest_dir, safe)
        try:
            with open(path, "wb") as f:
                f.write(part.get_payload(decode=True) or b"")
            out.append({"name": safe, "filename": safe, "path": path})
        except Exception:
            # ignore broken parts
            pass
    return out

def iter_eml_messages(inbox_dir: str) -> Generator[Dict, None, None]:
    """
    Yields: {"filename": <eml name>, "body": <html or text>, "attachments": [ {name, path}, ... ]}
    """
    if not os.path.isdir(inbox_dir):
        return
    for name in sorted(os.listdir(inbox_dir)):
        if not name.lower().endswith(".eml"):
            continue
        fpath = os.path.join(inbox_dir, name)
        try:
            with open(fpath, "rb") as f:
                msg = BytesParser(policy=policy.default).parse(f)
        except Exception:
            continue

        # per-message temp folder for attachments
        att_dir = os.path.join(inbox_dir, f"_{os.path.splitext(name)[0]}_atts")
        os.makedirs(att_dir, exist_ok=True)
        attachments = _save_attachments(msg, att_dir)
        body = _best_body(msg) or ""
        yield {"filename": name, "body": body, "attachments": attachments}
