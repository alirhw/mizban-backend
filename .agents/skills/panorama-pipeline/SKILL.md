# Skill: Panorama Pipeline (TD-003 / ARCH-003)

## What it teaches
How a heavy 360° photo (often 15–40MB) becomes a fast web asset without
ever blocking a request: validated upload → Celery/Pillow conversion to a
4K WebP + tiny blur thumbnail → original deleted → status READY.

## Steps
1. Upload (`apps/panoramas` API/service): accept the file to temporary
   storage and validate by **magic bytes** (real image header, via
   `python-magic`) — never by extension or Content-Type. Enforce the
   design's size cap. Rename to a UUIDv4 filename immediately; the user's
   filename never reaches the filesystem path.
2. Create the `PanoramaImage` row with status `UPLOADED`, store under
   `media/panoramas/{venue_id}/{uuid}.<ext>`, return **202 Accepted**,
   and enqueue `process_panorama_image(image_id)` (Celery). The request
   is over — no image work in the request/response cycle (ARCH-003).
3. The Celery task: set status `PROCESSING`; open with Pillow; verify the
   equirectangular 2:1 aspect; resize to at most **4096×2048**; save WebP
   at **quality 82** as `{uuid}.webp`; generate the **512×256** thumbnail
   `{uuid}_thumb.webp` (~40KB, the instant first paint / LQIP).
4. On success: update paths, set status `READY`, and **delete the original
   heavy file** (disk protection, TR-002). On failure: status `FAILED`
   with a safe error summary; the venue owner sees "processing failed —
   re-upload", never a stack trace.
5. Delivery: Nginx serves `media/` directly with long-lived immutable
   cache headers; Django never streams panoramas. Pin coordinates
   (pitch/yaw floats) live on `TablePin` rows — image replacement keeps
   the same pins only if the design says the photo is the same space;
   otherwise the owner re-drops pins (Pannellum `mouseEventToCoords` in
   the owner editor, frontend phase).
6. Idempotency: re-running the task for the same image must produce the
   same outputs (overwrite same paths) and never duplicate rows.

## Example
```python
# apps/panoramas/tasks.py — shape of the worker
@shared_task
def process_panorama_image(image_id):
    img = PanoramaImage.objects.get(pk=image_id)
    img.status = "PROCESSING"; img.save(update_fields=["status"])
    with Image.open(img.original_path) as im:
        im = im.convert("RGB")
        im.thumbnail((4096, 2048))                 # cap, keep aspect
        im.save(webp_path, "WEBP", quality=82)
        thumb = im.resize((512, 256))
        thumb.save(thumb_path, "WEBP", quality=60)
    img.webp_path, img.thumb_path = webp_path, thumb_path
    img.status = "READY"; img.save(...)
    os.remove(img.original_path)                   # heavy original goes away
```

## Common mistakes
- Processing synchronously in the upload view (a 30MB conversion locks a
  web worker for seconds → 504s; this is the exact beginner trap TD-003
  calls out).
- Trusting the file extension (a renamed script in the media folder is a
  web-shell risk — magic bytes + UUID names + Nginx no-execution config).
- Multi-resolution tiling "for quality" — rejected for the MVP (TD-003);
  single 4K WebP is the budget, enforced by the Performance Engineer.
- Keeping originals "just in case" (disk fills; TR-002). Delete after
  successful conversion.
- Serving panoramas through Django views (loses Nginx caching and
  range performance).
