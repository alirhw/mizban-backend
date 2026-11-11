"""Celery tasks for panorama processing (Architecture Spec section 20).

process_panorama_image: open the original with Pillow, resize to at most
4096x2048, compress to WebP (quality 82), generate a 512x256 thumbnail,
mark the record READY and delete the heavy original file (ARCH-003).
"""
from celery import shared_task


@shared_task(name="panoramas.process_panorama_image")
def process_panorama_image(image_id: int) -> None:
    raise NotImplementedError("Implemented together with the PanoramaImage model task.")
