"""
Unit tests for input sanitization and file validation utilities.
"""
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from core.sanitize import strip_tags, sanitize_text
from core.file_validation import validate_image, validate_attachment, validate_code_file


class StripTagsTests(TestCase):
    def test_removes_html(self):
        self.assertEqual(strip_tags("<b>bold</b>"), "bold")

    def test_removes_script(self):
        self.assertEqual(strip_tags('<script>alert(1)</script>hello'), "alert(1)hello")

    def test_none_returns_none(self):
        self.assertIsNone(strip_tags(None))

    def test_empty_string(self):
        self.assertEqual(strip_tags(""), "")

    def test_plain_text_unchanged(self):
        self.assertEqual(strip_tags("hello world"), "hello world")


class SanitizeTextTests(TestCase):
    def test_strips_tags_and_trims(self):
        self.assertEqual(sanitize_text("  <b>hi</b>  "), "hi")

    def test_removes_javascript_uri(self):
        result = sanitize_text("javascript:alert(1)")
        self.assertNotIn("javascript:", result)

    def test_removes_data_uri(self):
        result = sanitize_text("data:text/html,<script>")
        self.assertNotIn("data:", result)

    def test_max_length(self):
        result = sanitize_text("a" * 100, max_length=10)
        self.assertEqual(len(result), 10)

    def test_none_returns_none(self):
        self.assertIsNone(sanitize_text(None))


class ValidateImageTests(TestCase):
    def test_valid_jpeg(self):
        f = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff" + b"\x00" * 100, content_type="image/jpeg")
        self.assertIsNone(validate_image(f))

    def test_invalid_extension(self):
        f = SimpleUploadedFile("malware.exe", b"\x00" * 100, content_type="application/octet-stream")
        err = validate_image(f)
        self.assertIsNotNone(err)
        self.assertIn("Invalid image type", err)

    def test_oversized_image(self):
        f = SimpleUploadedFile("big.png", b"\x00" * (6 * 1024 * 1024), content_type="image/png")
        err = validate_image(f)
        self.assertIsNotNone(err)
        self.assertIn("too large", err)

    def test_none_file(self):
        err = validate_image(None)
        self.assertIsNotNone(err)


class ValidateAttachmentTests(TestCase):
    def test_valid_pdf(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-" + b"\x00" * 100, content_type="application/pdf")
        self.assertIsNone(validate_attachment(f))

    def test_invalid_type(self):
        f = SimpleUploadedFile("file.xyz", b"\x00" * 100, content_type="application/octet-stream")
        err = validate_attachment(f)
        self.assertIsNotNone(err)

    def test_oversized(self):
        f = SimpleUploadedFile("big.pdf", b"\x00" * (21 * 1024 * 1024), content_type="application/pdf")
        err = validate_attachment(f)
        self.assertIsNotNone(err)
        self.assertIn("too large", err)


class ValidateCodeFileTests(TestCase):
    def test_valid_python(self):
        f = SimpleUploadedFile("script.py", b"print('hello')", content_type="text/plain")
        self.assertIsNone(validate_code_file(f))

    def test_invalid_extension(self):
        f = SimpleUploadedFile("virus.exe", b"\x00" * 100, content_type="application/octet-stream")
        err = validate_code_file(f)
        self.assertIsNotNone(err)

    def test_oversized(self):
        f = SimpleUploadedFile("big.py", b"x" * (3 * 1024 * 1024), content_type="text/plain")
        err = validate_code_file(f)
        self.assertIsNotNone(err)
        self.assertIn("too large", err)
