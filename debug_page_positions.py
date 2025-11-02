import pdfplumber
from pathlib import Path
import re

latest_pdf = max(Path("storage/documents").rglob("*.pdf"), key=lambda p: p.stat().st_mtime)

text_parts = []
with pdfplumber.open(latest_pdf) as pdf:
    for page_num, page in enumerate(pdf.pages):
        page_text = page.extract_text()
        if page_text and page_text.strip():
            text_parts.append(f"[Page {page_num + 1}]\n{page_text}")

full_text = "\n\n".join(text_parts)

# Find where each clause starts
clause_pattern = re.compile(r'^\s*(\d+)\.\s+([A-Z][a-z]+)', re.MULTILINE)
page_pattern = re.compile(r'\[Page (\d+)\]')

print("=== Clause and Page Marker Positions ===\n")

# Find all page markers
page_markers = [(m.start(), int(m.group(1))) for m in page_pattern.finditer(full_text)]
print("Page markers:")
for pos, page_num in page_markers[:5]:
    print(f"  Position {pos}: [Page {page_num}]")

print("\nFirst 10 clauses:")
for match in list(clause_pattern.finditer(full_text))[:10]:
    clause_num = match.group(1)
    clause_name = match.group(2)
    position = match.start()
    
    # Find which page this is on
    page_for_clause = 1
    for marker_pos, page_num in page_markers:
        if marker_pos <= position:
            page_for_clause = page_num
    
    print(f"  Clause {clause_num} ({clause_name}) at position {position} → Page {page_for_clause}")
