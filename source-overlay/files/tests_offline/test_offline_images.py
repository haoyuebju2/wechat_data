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


def test_jpeg_with_appended_metadata_upgrades_preview_and_preserves_exact_bytes(local_images):
    seed_cache(local_images, image_bytes(120, 90))
    before = get_image(local_images, v=1)
    original = image_bytes(1000, 750, "JPEG") + b"synthetic appended metadata\n" * 357
    helpers = local_images[4]
    path = helpers._save_best_image_resource(local_images[1], "a" * 32, original)
    response = get_image(local_images, v=2, deep_scan=False, fetch_remote=False)
    assert response.status_code == 200
    assert response.content == original == path.read_bytes()
    assert dimensions(response.content) == (1000, 750)
    assert response.headers["etag"] != before.headers["etag"]
    seed_variant(local_images, "_t", image_bytes(120, 90))
    assert get_image(local_images, v=3).content == original


def test_invalid_jpeg_with_large_trailer_cannot_replace_valid_cache(local_images):
    import pytest
    helpers = local_images[4]
    original = image_bytes(1000, 750)
    seed_cache(local_images, original)
    invalid = b"\xff\xd8\xff\xe1broken image\xff\xd9" + b"synthetic metadata" * 600
    with pytest.raises(ValueError):
        helpers._save_best_image_resource(local_images[1], "a" * 32, invalid)
    assert get_image(local_images).content == original
