import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app import photo_uploads


class PhotoUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name)
        self.upload_dir_patch = patch.object(photo_uploads, "UPLOAD_DIR", self.upload_dir)
        self.upload_dir_patch.start()
        self.addCleanup(self.upload_dir_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    @staticmethod
    def upload(data: bytes, *, filename="photo.jpg", content_type="image/jpeg"):
        return UploadFile(
            filename=filename,
            file=io.BytesIO(data),
            headers=Headers({"content-type": content_type}),
        )

    @staticmethod
    def jpeg_bytes(*, exif=None, size=(32, 24)):
        image = Image.new("RGB", size, color=(80, 120, 160))
        output = io.BytesIO()
        image.save(output, format="JPEG", exif=exif or b"")
        return output.getvalue()

    def test_reencodes_photo_without_source_exif_metadata(self):
        exif = Image.Exif()
        exif[270] = "private source metadata"
        upload = self.upload(self.jpeg_bytes(exif=exif))

        url = photo_uploads.save_uploaded_photo(upload)

        self.assertTrue(url.startswith("/img/uploads/"))
        saved_path = self.upload_dir / Path(url).name
        self.assertTrue(saved_path.is_file())
        with Image.open(saved_path) as saved:
            self.assertEqual(saved.size, (32, 24))
            self.assertEqual(dict(saved.getexif()), {})

    def test_rejects_content_type_not_on_allowlist(self):
        upload = self.upload(self.jpeg_bytes(), content_type="text/plain")

        with self.assertRaises(HTTPException) as raised:
            photo_uploads.save_uploaded_photo(upload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Only JPG", raised.exception.detail)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_rejects_oversized_photo_before_decoding(self):
        upload = self.upload(b"x" * (photo_uploads.MAX_PHOTO_BYTES + 1))

        with self.assertRaises(HTTPException) as raised:
            photo_uploads.save_uploaded_photo(upload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("5 MB or smaller", raised.exception.detail)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_rejects_non_image_payload(self):
        upload = self.upload(b"this is not an image")

        with self.assertRaises(HTTPException) as raised:
            photo_uploads.save_uploaded_photo(upload)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("valid image", raised.exception.detail)
        self.assertEqual(list(self.upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
