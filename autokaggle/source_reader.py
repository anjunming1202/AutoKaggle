"""Bounded subprocess entry point for imported PDF text. Never runs source code."""
import io
import json
import sys


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read(16 * 1024 * 1024 + 1)), strict=False)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF")
    parts, length = [], 0
    for page in list(reader.pages)[:30]:
        text = page.extract_text() or ""
        parts.append(text[:40000 - length])
        length += len(parts[-1])
        if length >= 40000:
            break
    print(json.dumps({"text": "\n".join(parts), "pages_total": len(reader.pages),
                      "truncated": len(reader.pages) > 30 or length >= 40000}))


if __name__ == "__main__":
    main()
