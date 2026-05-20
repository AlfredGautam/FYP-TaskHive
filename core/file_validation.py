"""
File upload validation utilities.
Enforces type and size limits on all uploaded files.
"""

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

ALLOWED_ATTACHMENT_TYPES = ALLOWED_IMAGE_TYPES | {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "application/x-rar-compressed",
    "text/plain",
    "text/csv",
}
ALLOWED_ATTACHMENT_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".txt", ".csv",
}

ALLOWED_CODE_EXTENSIONS = {
    ".py", ".js", ".html", ".css", ".java", ".c", ".cpp", ".h",
    ".json", ".xml", ".md", ".txt", ".sh", ".bat", ".sql",
    ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs", ".php",
}

MAX_IMAGE_SIZE = 5 * 1024 * 1024       # 5 MB
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_CODE_SIZE = 2 * 1024 * 1024        # 2 MB

import os


def _get_ext(filename):
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def validate_image(uploaded_file):
    """Validate an image upload (profile photo, cover). Returns error string or None."""
    if not uploaded_file:
        return "No file provided."

    ext = _get_ext(uploaded_file.name)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return f"Invalid image type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"

    content_type = getattr(uploaded_file, "content_type", "")
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        return f"Invalid image content type '{content_type}'."

    if uploaded_file.size > MAX_IMAGE_SIZE:
        mb = MAX_IMAGE_SIZE // (1024 * 1024)
        return f"Image too large. Maximum size is {mb} MB."

    return None


def validate_attachment(uploaded_file):
    """Validate a task/project attachment. Returns error string or None."""
    if not uploaded_file:
        return "No file provided."

    ext = _get_ext(uploaded_file.name)
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        return f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}"

    content_type = getattr(uploaded_file, "content_type", "")
    if content_type and content_type not in ALLOWED_ATTACHMENT_TYPES:
        return f"File content type '{content_type}' not allowed."

    if uploaded_file.size > MAX_ATTACHMENT_SIZE:
        mb = MAX_ATTACHMENT_SIZE // (1024 * 1024)
        return f"File too large. Maximum size is {mb} MB."

    return None


def validate_code_file(uploaded_file):
    """Validate a codespace file upload. Returns error string or None."""
    if not uploaded_file:
        return "No file provided."

    ext = _get_ext(uploaded_file.name)
    if ext not in ALLOWED_CODE_EXTENSIONS:
        return f"File type '{ext}' not allowed for code uploads."

    if uploaded_file.size > MAX_CODE_SIZE:
        mb = MAX_CODE_SIZE // (1024 * 1024)
        return f"Code file too large. Maximum size is {mb} MB."

    return None
