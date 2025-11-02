from app.services.legal_chunker import LegalDocumentChunker
from pathlib import Path

# Get PDF text
import pdfplumber
latest_pdf = max(Path("storage/documents").rglob("*.pdf"), key=lambda p: p.stat().st_mtime)

text_parts = []
with pdfplumber.open(latest_pdf) as pdf:
    for page_num, page in enumerate(pdf.pages):
        page_text = page.extract_text()
        if page_text and page_text.strip():
            text_parts.append(f"[Page {page_num + 1}]\n{page_text}")

full_text = "\n\n".join(text_parts)

# Create chunker and chunk
chunker = LegalDocumentChunker()
page_map = chunker._build_page_map(full_text)

print("=== Page Map Check ===")
print(f"Page map has {len(page_map)} entries")
print(f"First few: {dict(list(page_map.items())[:3])}")

# Find clause boundaries like the chunker does
import re
clause_matches = list(chunker.PATTERNS['numbered_clause'].finditer(full_text))

print(f"\n=== First 5 Clause Boundaries ===")
for i, match in enumerate(clause_matches[:5]):
    start_pos = match.start()
clear    page = chunker._get_page_for_position(start_pos, page_map)
rgwrehge    preview = full_text[start_pos:start_pos+50].replace('\n', ' ')
    print(f"Clause at position {start_pos}: Page {page}")
    print(f"  Preview: {preview}...")
