"""Synthetic local media only; no user images or remote servers."""
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_chat_image_local_quality import local_images, seed_cache, seed_variant, image_bytes, dimensions, get_image


def test_preview_upgrades_when_local_original_arrives_without_remote_or_broad_scan(local_images):
    seed_cache(local_images, image_bytes(120, 120))
    helpers, router = local_images[4], local_images[5]
    with patch.object(router.cdn_image_service, "download_original_image", AsyncMock(side_effect=AssertionError("No CDN"))), patch.object(
        helpers, "_fallback_search_media_by_md5", side_effect=AssertionError("No account-wide scan")
    ):
        assert dimensions(get_image(local_images, v=1, deep_scan=False, fetch_remote=False).content) == (120, 120)
        seed_variant(local_images, "_h", image_bytes(1000, 800))
        response = get_image(local_images, v=2, deep_scan=False, fetch_remote=False)
        assert response.status_code == 200
        assert dimensions(response.content) == (1000, 800)


def test_legacy_remote_flag_cannot_read_cdn_credentials_or_break_existing_thumbnail(local_images):
    seed_cache(local_images, image_bytes(120, 120))
    router = local_images[5]
    with patch.object(router, "_lookup_image_cdn_download_info", side_effect=AssertionError("No CDN metadata")), patch.object(
        router.cdn_image_service, "is_cdn_download_enabled", side_effect=AssertionError("No CDN settings")
    ), patch.object(router.cdn_image_service, "download_original_image", AsyncMock(side_effect=AssertionError("No CDN"))):
        response = get_image(local_images, server_id=123, fetch_remote=True)
        assert response.status_code == 200
        assert dimensions(response.content) == (120, 120)
