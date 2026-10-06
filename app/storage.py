"""File storage: local disk for development, private S3 bucket in production.

Switch by setting S3_BUCKET. In S3 mode files are never public; the app hands out
short-lived presigned URLs, so only logged-in members can open them.
"""
import mimetypes
import os
import re
import uuid

from flask import current_app, url_for
from werkzeug.utils import secure_filename

KEY_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$")
_s3 = None


def _client():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config

        region = current_app.config["AWS_REGION"]
        _s3 = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _s3


def check_name(filename):
    """Return (ok, error, ext) for a file name."""
    name = secure_filename(filename or "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not name:
        return False, "No file selected.", None
    if ext not in current_app.config["ALLOWED_EXTENSIONS"]:
        return False, "That file type is not allowed.", None
    return True, None, ext


def limit_bytes(ext):
    """Biggest allowed upload for this file type: videos get MAX_VIDEO_MB, everything else MAX_UPLOAD_MB."""
    cfg = current_app.config
    mb = cfg["MAX_VIDEO_MB"] if ext in cfg["VIDEO_EXTENSIONS"] else cfg["MAX_UPLOAD_MB"]
    return mb * 1024 * 1024


def size_error(ext, size):
    """A friendly message if `size` is not acceptable for this file type, else None."""
    if isinstance(size, int) and 0 < size <= limit_bytes(ext):
        return None
    cfg = current_app.config
    return (f"File is too large or empty. Videos can be up to {cfg['MAX_VIDEO_MB']} MB; "
            f"photos and documents up to {cfg['MAX_UPLOAD_MB']} MB.")


def stream_size(file_storage):
    """Size in bytes of an uploaded file (without reading it into memory)."""
    stream = file_storage.stream
    pos = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(pos)
    return size


def validate(file_storage):
    """Return (ok, error, ext)."""
    if not file_storage or not file_storage.filename:
        return False, "No file selected.", None
    ok, err, ext = check_name(file_storage.filename)
    if not ok:
        return ok, err, ext
    stream = getattr(file_storage, "stream", None)
    if stream is not None and not _content_matches(ext, stream):
        return False, "The file content does not match its file type.", None
    return True, None, ext




def _content_matches(ext, stream):
    """Cheap signature checks to catch renamed executables and malformed uploads.
    Office OOXML files are ZIP containers; legacy Office files use OLE compound storage.
    Text-like formats are intentionally not sniffed because many valid encodings exist.
    """
    if not stream or not hasattr(stream, "read"):
        return True
    try:
        pos = stream.tell()
        head = stream.read(32)
        stream.seek(pos)
    except Exception:
        return False
    if ext == "png": return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {"jpg", "jpeg"}: return head.startswith(b"\xff\xd8\xff")
    if ext == "gif": return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == "webp": return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == "pdf": return head.startswith(b"%PDF-")
    if ext in {"docx", "xlsx", "pptx"}: return head.startswith(b"PK\x03\x04")
    if ext in {"doc", "xls", "ppt"}: return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext == "mp4": return len(head) >= 12 and head[4:8] == b"ftyp"
    return True


def mime_for(ext):
    return mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream"


# ---- uploads ----
def save_upload(file_storage, ext):
    """Store the file, return dict(key, name, mime)."""
    key = f"{uuid.uuid4().hex}.{ext}"
    mime = mime_for(ext)
    name = secure_filename(file_storage.filename)[:255]
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        _client().upload_fileobj(
            file_storage.stream, bucket, f"uploads/{key}", ExtraArgs={"ContentType": mime}
        )
    else:
        folder = current_app.config["UPLOAD_FOLDER"]
        os.makedirs(folder, exist_ok=True)
        file_storage.save(os.path.join(folder, key))
    return {"key": key, "name": name, "mime": mime}


def file_url(key, name=None, is_image=True):
    bucket = current_app.config["S3_BUCKET"]
    if bucket:
        params = {"Bucket": bucket, "Key": f"uploads/{key}"}
        if not is_image:
            params["ResponseContentDisposition"] = f'attachment; filename="{name or key}"'
        return _client().generate_presigned_url("get_object", Params=params, ExpiresIn=3600)
    return url_for("main.serve_file", key=key)


# ---- direct browser -> S3 uploads (keeps big files off the app servers) ----
def presign_upload(filename, ext):
    """S3 mode only. Returns (form_for_browser, meta). The browser POSTs the file straight to S3,
    so uploads never pass through (or slow down) the app servers."""
    key = f"{uuid.uuid4().hex}.{ext}"
    mime = mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream"
    max_bytes = limit_bytes(ext)
    form = _client().generate_presigned_post(
        Bucket=current_app.config["S3_BUCKET"],
        Key=f"uploads/{key}",
        Fields={"Content-Type": mime},
        Conditions=[{"Content-Type": mime}, ["content-length-range", 1, max_bytes]],
        ExpiresIn=600,
    )
    return form, {"key": key, "name": secure_filename(filename)[:255], "mime": mime}


def object_ok(key, max_bytes):
    """Validate an already-uploaded S3 object before it is attached to a message."""
    bucket = current_app.config["S3_BUCKET"]
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    try:
        head = _client().head_object(Bucket=bucket, Key=f"uploads/{key}")
        size = head["ContentLength"]
        if not size or size > max_bytes:
            _client().delete_object(Bucket=bucket, Key=f"uploads/{key}")
            return False
        body = _client().get_object(Bucket=bucket, Key=f"uploads/{key}", Range="bytes=0-31")["Body"]
        sample = body.read(32)
        import io
        if not _content_matches(ext, io.BytesIO(sample)):
            _client().delete_object(Bucket=bucket, Key=f"uploads/{key}")
            return False
        return True
    except Exception:
        return False


def object_size(key):
    """Size in bytes of an uploaded S3 object, or None if it is not there."""
    try:
        head = _client().head_object(Bucket=current_app.config["S3_BUCKET"], Key=f"uploads/{key}")
        return head["ContentLength"]
    except Exception:
        return None
