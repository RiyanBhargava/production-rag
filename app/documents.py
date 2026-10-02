import hashlib
import io
import re
import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\w]+(?:[-.][\w]+)*", text.lower())


def parse_chunks(data: bytes, filename: str, settings, category: str, version: str):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    elif suffix in {".txt", ".md"}:
        pages = [(1, data.decode("utf-8-sig"))]
    else:
        raise ValueError("Use PDF, UTF-8 TXT, or Markdown files")
    if sum(len(t) for _, t in pages) > settings.max_document_chars:
        raise ValueError("Extracted document is too large")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    seen = set()
    section = ""
    for page, text in pages:
        # Preserve page boundaries; Markdown headings and short uppercase lines supply sections.
        blocks = re.split(r"(?m)(?=^#{1,6} |^[A-Z][A-Z ]{3,70}$)", text)
        for block in blocks:
            first = block.strip().split("\n")[0] if block.strip() else ""
            if first.startswith("#") or (first.isupper() and len(first) < 72):
                section = first.lstrip("# ")
            for content in splitter.split_text(block):
                digest = hashlib.sha256(content.encode()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                chunks.append(
                    {
                        "id": str(uuid.uuid4()),
                        "text": content,
                        "page": page,
                        "section": section,
                        "category": category,
                        "version": version,
                        "filename": Path(filename).name,
                    }
                )
                if len(chunks) > settings.max_chunks:
                    raise ValueError("Document has too many chunks")
    if not chunks:
        raise ValueError("No text found. Scanned PDFs need OCR before uploading.")
    return chunks
