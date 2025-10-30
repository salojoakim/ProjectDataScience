# utils/gcs_storage.py
"""
Google Cloud Storage utilities for the ADK agent.
Replaces local file system operations with GCS bucket operations.

Required environment variables:
- GCS_BUCKET_NAME: Your GCS bucket name (e.g., "sms-pricing-data")
- GOOGLE_CLOUD_PROJECT: Your GCP project ID (optional, for ADC)

Authentication:
- Uses Application Default Credentials (ADC)
- In AgentSpace: automatically authenticated
- Locally: run `gcloud auth application-default login`
"""

from __future__ import annotations

import os
import io
import json
import tempfile
from typing import List, Dict, Optional, BinaryIO
from datetime import datetime, timedelta
from dotenv import load_dotenv

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("⚠️  google-cloud-storage not installed. Run: pip install google-cloud-storage")

load_dotenv()

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
USE_GCS = os.getenv("USE_GCS", "true").lower() in ("1", "true", "yes")

# Folder structure in bucket
EMAILS_PREFIX = "emails/"           # Raw .eml files
INBOX_PREFIX = "inbox_today/"       # Working folder for daily processing
LOGS_PREFIX = "logs/"               # Parsed data, diffs, snapshots
SUMMARIES_PREFIX = "summaries/"     # HTML summaries


class GCSStorage:
    """Wrapper for GCS operations with fallback to local storage."""
    
    def __init__(self, bucket_name: str = None, use_gcs: bool = None):
        self.bucket_name = bucket_name or BUCKET_NAME
        self.use_gcs = use_gcs if use_gcs is not None else USE_GCS
        self.client = None
        self.bucket = None
        
        if self.use_gcs and GCS_AVAILABLE and self.bucket_name:
            try:
                self.client = storage.Client()
                self.bucket = self.client.bucket(self.bucket_name)
                print(f"✅ GCS initialized: gs://{self.bucket_name}")
            except Exception as e:
                print(f"⚠️  GCS init failed: {e}. Falling back to local storage.")
                self.use_gcs = False
        elif self.use_gcs:
            print("⚠️  GCS not available (missing bucket name or library). Using local storage.")
            self.use_gcs = False
    
    def _local_path(self, blob_name: str) -> str:
        """Get local fallback path."""
        return os.path.join("data", blob_name)
    
    def list_files(self, prefix: str = "", suffix: str = "") -> List[str]:
        """
        List files in bucket with optional prefix and suffix filter.
        
        Returns:
            List of blob names (full paths in bucket)
        """
        if not self.use_gcs:
            # Local fallback
            local_dir = self._local_path(prefix)
            if not os.path.exists(local_dir):
                return []
            files = []
            for root, _, filenames in os.walk(local_dir):
                for fname in filenames:
                    if suffix and not fname.endswith(suffix):
                        continue
                    rel_path = os.path.relpath(os.path.join(root, fname), "data")
                    files.append(rel_path.replace("\\", "/"))
            return sorted(files)
        
        # GCS
        blobs = self.bucket.list_blobs(prefix=prefix)
        files = [blob.name for blob in blobs if not suffix or blob.name.endswith(suffix)]
        return sorted(files)
    
    def read_text(self, blob_name: str, encoding: str = "utf-8") -> str:
        """Read text file from GCS or local storage."""
        if not self.use_gcs:
            local_path = self._local_path(blob_name)
            if not os.path.exists(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")
            with open(local_path, "r", encoding=encoding) as f:
                return f.read()
        
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"Blob not found: gs://{self.bucket_name}/{blob_name}")
        return blob.download_as_text(encoding=encoding)
    
    def read_bytes(self, blob_name: str) -> bytes:
        """Read binary file from GCS or local storage."""
        if not self.use_gcs:
            local_path = self._local_path(blob_name)
            if not os.path.exists(local_path):
                raise FileNotFoundError(f"Local file not found: {local_path}")
            with open(local_path, "rb") as f:
                return f.read()
        
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"Blob not found: gs://{self.bucket_name}/{blob_name}")
        return blob.download_as_bytes()
    
    def read_json(self, blob_name: str) -> Dict:
        """Read and parse JSON file."""
        text = self.read_text(blob_name)
        return json.loads(text)
    
    def write_text(self, blob_name: str, content: str, encoding: str = "utf-8") -> str:
        """Write text file to GCS or local storage. Returns the blob_name/path."""
        if not self.use_gcs:
            local_path = self._local_path(blob_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "w", encoding=encoding) as f:
                f.write(content)
            return local_path
        
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content, content_type="text/plain")
        return f"gs://{self.bucket_name}/{blob_name}"
    
    def write_bytes(self, blob_name: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        """Write binary file to GCS or local storage. Returns the blob_name/path."""
        if not self.use_gcs:
            local_path = self._local_path(blob_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            return local_path
        
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content, content_type=content_type)
        return f"gs://{self.bucket_name}/{blob_name}"
    
    def write_json(self, blob_name: str, data: Dict) -> str:
        """Write JSON file to GCS or local storage. Returns the blob_name/path."""
        content = json.dumps(data, ensure_ascii=False, indent=2)
        if not self.use_gcs:
            return self.write_text(blob_name, content)
        
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content, content_type="application/json")
        return f"gs://{self.bucket_name}/{blob_name}"
    
    def download_to_tempfile(self, blob_name: str, suffix: str = "") -> str:
        """
        Download blob to a temporary file and return the temp file path.
        Useful for libraries that need file paths (e.g., pandas, email parser).
        """
        content = self.read_bytes(blob_name)
        
        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(content)
        except:
            os.close(fd)
            raise
        
        return temp_path
    
    def exists(self, blob_name: str) -> bool:
        """Check if file exists."""
        if not self.use_gcs:
            return os.path.exists(self._local_path(blob_name))
        
        blob = self.bucket.blob(blob_name)
        return blob.exists()
    
    def delete(self, blob_name: str) -> bool:
        """Delete a file. Returns True if successful."""
        if not self.use_gcs:
            local_path = self._local_path(blob_name)
            if os.path.exists(local_path):
                os.remove(local_path)
                return True
            return False
        
        blob = self.bucket.blob(blob_name)
        if blob.exists():
            blob.delete()
            return True
        return False
    
    def copy(self, source_blob: str, dest_blob: str) -> str:
        """Copy file within bucket. Returns dest path."""
        if not self.use_gcs:
            src_path = self._local_path(source_blob)
            dest_path = self._local_path(dest_blob)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            import shutil
            shutil.copy2(src_path, dest_path)
            return dest_path
        
        source = self.bucket.blob(source_blob)
        self.bucket.copy_blob(source, self.bucket, dest_blob)
        return f"gs://{self.bucket_name}/{dest_blob}"
    
    def get_public_url(self, blob_name: str, expiration: int = 3600) -> str:
        """
        Generate a signed URL for downloading the file.
        
        Args:
            blob_name: Path to file in bucket
            expiration: URL validity in seconds (default: 1 hour)
        
        Returns:
            Signed URL string
        """
        if not self.use_gcs:
            return f"file://{self._local_path(blob_name)}"
        
        blob = self.bucket.blob(blob_name)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiration),
            method="GET"
        )
        return url


# Global instance
_storage = None

def get_storage() -> GCSStorage:
    """Get or create global storage instance."""
    global _storage
    if _storage is None:
        _storage = GCSStorage()
    return _storage