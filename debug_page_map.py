from app.services.document_processor import DocumentProcessor
from pathlib import Path

processor = DocumentProcessor()

# Get the PDF
latest_pdf = max(Path("storage/documents").rglob("*.pdf"), key=lambda p: p.stat().st_mtime)

with open(latest_pdf, 'rb') as f:
    content = f.read()

text = processor._extract_pdf(content)

# Build page map like the chunker does
import re
page_pattern = re.compile(r'\[Page (\d+)\]')
page_map = {}

for match in page_pattern.finditer(text):
    page_num = int(match.group(1))
    position = match.start()
    page_map[position] = page_num

print("=== Page Map Contents ===")
print(f"Total entries: {len(page_map)}")
for pos in sorted(page_map.keys())[:10]:
    print(f"  Position {pos}: Page {page_map[pos]}")

# Test the lookup for clause 1 position
test_position = 1317
relevant_positions = [pos for pos in page_map.keys() if pos <= test_position]
if relevant_positions:
    last_marker = max(relevant_positions)
    page = page_map[last_marker]
    print(f"\nTest: Position {test_position} (Clause 1)")
    print(f"  Last marker before: {last_marker}")
    print(f"  Resolved to page: {page}")
else:
    print(f"\nTest: Position {test_position} → No markers before it!")
