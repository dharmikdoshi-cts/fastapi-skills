---
name: fastapi-file-uploads
description: >
  Implement secure file upload patterns for FastAPI: streaming UploadFile,
  size limits enforced by middleware, MIME-type and magic-byte validation,
  virus scanning hooks (ClamAV), local + S3/MinIO storage abstraction,
  presigned URL uploads (direct-to-S3), chunked/multipart uploads, image
  processing safety, and download streaming with range requests. Use this
  skill whenever the user asks about file uploads, multipart, UploadFile,
  S3, MinIO, presigned URLs, image upload, attachment, "how to upload a
  file", or "where to store user files". Python 3.12+, async, FE-friendly
  responses.
---

# FastAPI File Uploads Skill

Secure, streamed, validated uploads with pluggable storage. Python 3.12+.

---

## Decision: Server-Proxy vs Presigned-Direct

| Pattern | When | Pros | Cons |
|---------|------|------|------|
| **Server proxy** (`UploadFile`) | < 25 MB, need server-side processing | Simple, full control, easy auth | Server bandwidth + memory pressure |
| **Presigned URL** (S3/MinIO direct) | > 25 MB, image/video, no transform | Scales, no server bandwidth | Two-step flow, harder validation |

ERP rule of thumb: invoices/receipts/avatars → server proxy. Bulk imports / media → presigned.

---

## Server-Proxy Upload (Streamed)

```python
# app/api/uploads.py
from typing import Annotated
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.uploads import UploadService

router = APIRouter(prefix="/files", tags=["files"])

MAX_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "application/pdf"}


@router.post("", status_code=201)
async def upload_file(
    file: Annotated[UploadFile, File(...)],
    svc: Annotated[UploadService, Depends()],
):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(415, f"Unsupported type: {file.content_type}")

    saved = await svc.save_streaming(file, max_bytes=MAX_BYTES)
    return {"id": saved.id, "url": saved.url, "size": saved.size}
```

### Streaming save (no full-file in RAM)

```python
# app/services/uploads.py
import hashlib
import aiofiles
from fastapi import HTTPException, UploadFile

CHUNK = 1024 * 1024  # 1 MB

async def save_streaming(file: UploadFile, *, max_bytes: int) -> SavedFile:
    sha = hashlib.sha256()
    total = 0
    async with aiofiles.open(dest_path, "wb") as out:
        while chunk := await file.read(CHUNK):
            total += len(chunk)
            if total > max_bytes:
                # delete partial, fail
                await out.close()
                Path(dest_path).unlink(missing_ok=True)
                raise HTTPException(413, "File too large")
            sha.update(chunk)
            await out.write(chunk)
    return SavedFile(id=..., size=total, sha256=sha.hexdigest(), ...)
```

`UploadFile.read()` is async and chunked. Never call `.read()` with no argument on untrusted input — that loads everything into memory.

---

## Hard Size Limit at Middleware

`Content-Length` can lie. Enforce in middleware **before** routing:

```python
# app/middleware/body_size.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > self.max_bytes:
            return JSONResponse({"success": False, "code": 413, "message": "Payload too large"}, status_code=413)
        return await call_next(request)
```

Also configure your reverse proxy (nginx `client_max_body_size`, ALB body size).

---

## Magic-Byte Validation (Don't Trust MIME)

Clients can lie about `Content-Type`. Sniff actual bytes:

```python
import magic  # python-magic

async def detect_real_mime(path: str) -> str:
    mime = magic.Magic(mime=True)
    return mime.from_file(path)

# After save:
real = await detect_real_mime(dest_path)
if real not in ALLOWED_MIME:
    Path(dest_path).unlink()
    raise HTTPException(415, f"Sniffed type {real} not allowed")
```

For images, also verify with Pillow:
```python
from PIL import Image, UnidentifiedImageError
try:
    with Image.open(dest_path) as im:
        im.verify()
except UnidentifiedImageError:
    raise HTTPException(415, "Not a valid image")
```

---

## Filename Hygiene

Never use the client's filename for storage. Generate server-side:

```python
import secrets, mimetypes
from datetime import datetime

ext = mimetypes.guess_extension(file.content_type) or ""
key = f"{datetime.utcnow():%Y/%m/%d}/{secrets.token_urlsafe(16)}{ext}"
```

Sanitize the **display** name (strip path components, control chars):
```python
import re
display = re.sub(r"[^\w\-. ]", "_", file.filename or "file").strip()[:200]
```

---

## Virus Scanning (ClamAV)

```python
import asyncio

async def scan_clamav(path: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "clamdscan", "--no-summary", "--stdout", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0  # 0 clean, 1 infected, 2 error
```

Run scan **after** save, **before** marking the file as available. If infected, delete and 422.

For high throughput, scan via Celery (see `fastapi-background-task`).

---

## Storage Abstraction (Protocol)

```python
# app/storage/base.py
from typing import Protocol, BinaryIO

class FileStorage(Protocol):
    async def put(self, key: str, data: BinaryIO, *, content_type: str) -> str: ...
    async def get_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...
    async def delete(self, key: str) -> None: ...
```

Implementations: `LocalFileStorage`, `S3FileStorage`. Service depends on the protocol, not the impl.

### S3/MinIO impl (boto3)

```python
import aioboto3
from app.config.settings import settings

class S3FileStorage:
    def __init__(self):
        self.session = aioboto3.Session()

    async def put(self, key, data, *, content_type):
        async with self.session.client("s3", endpoint_url=settings.S3_ENDPOINT) as s3:
            await s3.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=content_type)
        return key

    async def get_url(self, key, *, expires_seconds=3600):
        async with self.session.client("s3", endpoint_url=settings.S3_ENDPOINT) as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET, "Key": key},
                ExpiresIn=expires_seconds,
            )
```

---

## Presigned-Direct Upload (Recommended for > 25 MB)

```python
@router.post("/presign")
async def presign_upload(
    body: PresignReq,
    storage: Annotated[FileStorage, Depends(get_storage)],
):
    if body.content_type not in ALLOWED_MIME:
        raise HTTPException(415)
    if body.size_bytes > MAX_BYTES:
        raise HTTPException(413)

    key = generate_key(body.content_type)
    url = await storage.generate_presigned_put(
        key, content_type=body.content_type, expires_seconds=300, max_bytes=body.size_bytes
    )
    # Persist a pending File row; client confirms after upload completes
    await repo.create_pending(key=key, owner_id=user.id, size=body.size_bytes)
    return {"upload_url": url, "key": key}


@router.post("/confirm")
async def confirm_upload(body: ConfirmReq, ...):
    # Verify object exists, sniff MIME, mark file as ready
    ...
```

Use S3 **conditions** (`Content-Length-Range`, `Content-Type`) so a malicious client can't upload 10 GB through your presigned URL.

---

## Image Processing Safety

User images are dangerous. Decompression bombs, polyglots, EXIF leaks.

```python
from PIL import Image

Image.MAX_IMAGE_PIXELS = 50_000_000  # ~50 MP cap

with Image.open(path) as im:
    im.load()                          # forces full decode
    im = im.convert("RGB")             # strips EXIF, alpha
    im.thumbnail((2000, 2000))         # downscale
    im.save(out_path, format="JPEG", quality=85, optimize=True)
```

Always **re-encode**, don't pass through bytes. Strip EXIF (location data!).

Run image processing in a worker with a memory limit, not the request.

---

## Download Streaming + Range

```python
from fastapi.responses import StreamingResponse

@router.get("/{file_id}")
async def download(file_id: int, ...):
    meta = await repo.get(file_id)
    # Authorize first!
    stream = storage.open_stream(meta.key)
    return StreamingResponse(
        stream,
        media_type=meta.content_type,
        headers={"Content-Disposition": f'attachment; filename="{meta.display_name}"'},
    )
```

For video/audio supporting seek, implement HTTP Range with `starlette.responses.FileResponse` or proxy to S3.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| `await file.read()` (no chunk size) | Loads entire file into memory |
| Save with client-supplied filename | Path traversal, overwrite, encoding |
| Trust `Content-Type` header | Easily forged, sniff with `python-magic` |
| Serve uploaded HTML/SVG with original MIME | XSS via uploaded file |
| Store keys without random component | Enumeration, collisions |
| Skip virus scan because "it's just PDFs" | PDF/Office formats carry malware |
| Return error including original filename unsanitized | Log injection, XSS in error UIs |
| Store files in DB as bytea | Bloats DB; use object storage |

---

## Verification Checklist

- [ ] Body-size middleware active and < proxy limit
- [ ] MIME sniffed via `python-magic`, not trusted from header
- [ ] Filenames generated server-side, display name sanitized
- [ ] Storage behind a `Protocol`; service unaware of S3 vs local
- [ ] Presigned uploads use size + type conditions
- [ ] Images re-encoded, EXIF stripped, max pixels capped
- [ ] Virus scan integrated (or explicitly waived per data-sensitivity review)
- [ ] Downloads authorized before streaming
- [ ] Tests cover: oversize, wrong MIME, magic-byte mismatch, traversal attempt, unauthorized download
