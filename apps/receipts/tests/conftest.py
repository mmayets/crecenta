import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def upload(content=PNG, name="foto.png", content_type="image/png"):
    return SimpleUploadedFile(name, content, content_type=content_type)
