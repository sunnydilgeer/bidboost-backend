from app.services.document_processor import DocumentProcessor
from pathlib import Path

processor = DocumentProcessor()

# Get the PDF
latest_pdf = max(Path("storage/documents").rglob("*.pdf"), key=lambda p: p.stat().st_mtime)

# Read and extract
with open(latest_pdf, 'rb') as f:
    content = f.read()

import io
text = processor._extract_pdf(content)

print("=== Step 1: After _extract_pdf ===")
print(f"Page markers in extracted text: {text.count('[Page')}")

# Now chunk it
metadata = {"filename": "test.pdf", "document_id": "test-123"}
chunks = processor.chunk_text(text, metadata)

print(f"\n=== Step 2: After chunk_text ===")
print(f"Total chunks created: {len(chunks)}")

# Check first 5 chunks
for i, chunk in enumerate(chunks[:5], 1):
    chunk_text = chunk['text']
    chunk_page = chunk['metadata'].get('page', 'MISSING')
    has_marker = '[Page' in chunk_text
    print(f"\nChunk {i}:")
    print(f"  Metadata page: {chunk_page}")
    print(f"  Has [Page marker: {has_marker}")
    print(f"  Text preview: {chunk_text[:100]}...")

# Check for page variety
all_pages = [c['metadata'].get('page', 1) for c in chunks]
print(f"\n=== Summary ===")
print(f"Unique pages in chunks: {set(all_pages)}")
print(f"Problem: All page 1? {'YES' if set(all_pages) == {1} else 'NO'}")
