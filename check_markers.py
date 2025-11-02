import pdfplumber
from pathlib import Path

# Find most recent PDF
storage_path = Path("storage/documents")
pdf_files = list(storage_path.rglob("*.pdf"))

if not pdf_files:
    print("No PDFs found!")
else:
    latest_pdf = max(pdf_files, key=lambda p: p.stat().st_mtime)
    print(f"Checking: {latest_pdf}\n")
    
    # Extract text like document_processor does
    text_parts = []
    with pdfplumber.open(latest_pdf) as pdf:
        for page_num, page in enumerate(pdf.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
    
    full_text = "\n\n".join(text_parts)
    
    print("=== First 1000 characters ===")
    print(full_text[:1000])
    print("\n=== Page marker analysis ===")
    print(f"Total length: {len(full_text)}")
    print(f"Contains '[Page': {('[Page' in full_text)}")
    print(f"Count of [Page] markers: {full_text.count('[Page')}")
    
    import re
    page_matches = re.findall(r'\[Page (\d+)\]', full_text)
    print(f"Page numbers found: {page_matches[:15]}")
    print(f"Max page: {max(map(int, page_matches)) if page_matches else 0}")
