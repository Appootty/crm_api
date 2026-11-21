"""Where dumps and database versions live: a Google Cloud Storage bucket in the cloud,
or a plain folder on your computer for testing. Chosen by environment variables:
  DUMPS_BUCKET / VERSIONS_BUCKET   (cloud)      DUMPS_DIR / VERSIONS_DIR   (local test)"""
import os
import shutil
from pathlib import Path


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self, prefix=""):
        out = []
        for p in self.root.rglob("*"):
            if p.is_file():
                name = p.relative_to(self.root).as_posix()
                if name.startswith(prefix):
                    out.append((name, p.stat().st_mtime))
        return sorted(out, key=lambda x: x[1])

    def download(self, name, dest):
        shutil.copy(self.root / name, dest)

    def upload(self, src, name):
        dest = self.root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)

    def read_text(self, name):
        p = self.root / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_text(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def delete(self, name):
        (self.root / name).unlink(missing_ok=True)


class GcsStore:
    def __init__(self, bucket):
        from google.cloud import storage  # only needed in the cloud
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket)

    def list(self, prefix=""):
        return sorted(((b.name, b.updated.timestamp()) for b in self.client.list_blobs(self.bucket, prefix=prefix)),
                      key=lambda x: x[1])

    def download(self, name, dest):
        self.bucket.blob(name).download_to_filename(str(dest))

    def upload(self, src, name):
        self.bucket.blob(name).upload_from_filename(str(src))

    def read_text(self, name):
        blob = self.bucket.blob(name)
        return blob.download_as_text() if blob.exists() else None

    def write_text(self, name, text):
        self.bucket.blob(name).upload_from_string(text, content_type="application/json")

    def delete(self, name):
        blob = self.bucket.blob(name)
        if blob.exists():
            blob.delete()


def configured(kind):
    return bool(os.environ.get(f"{kind}_BUCKET") or os.environ.get(f"{kind}_DIR"))


def open_store(kind):
    """kind is 'DUMPS' or 'VERSIONS'."""
    bucket = os.environ.get(f"{kind}_BUCKET")
    if bucket:
        return GcsStore(bucket)
    folder = os.environ.get(f"{kind}_DIR")
    if folder:
        return LocalStore(folder)
    raise RuntimeError(f"Set {kind}_BUCKET (cloud) or {kind}_DIR (local test)")
