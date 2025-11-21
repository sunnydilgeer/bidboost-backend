#!/usr/bin/env python3
"""
FTS Scraper V2 - Broader scraping without stage filter
Key changes from V1:
- Removed stage=1 filter (was limiting to ~200 results)
- Scrapes ALL open tenders (108,860 available)
- Increased page limit to 500 (captures ~5,000 tenders)
- Adds deduplication for re-runs
- Output: fts_live_rich_v2.json
"""
import json
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

OUTFILE = "fts_live_rich_v2.json"  # V2 output file

def detect_page_format(page):
    """Detect which format the FTS page uses"""
    has_eu_sections = page.query_selector("text=/one\\.1\\)|two\\.1\\)|Section one/") is not None
    has_govuk = page.query_selector("h2.govuk-heading-m, h3.govuk-heading-s") is not None
    
    if has_eu_sections:
        return "eu_standard"
    elif has_govuk:
        return "govuk_design"
    else:
        return "unknown"

def extract_text_between(text, start_marker, end_markers):
    """Extract text between markers"""
    try:
        if start_marker not in text:
            return None
        
        start_idx = text.index(start_marker) + len(start_marker)
        end_idx = len(text)
        
        for end_marker in end_markers if isinstance(end_markers, list) else [end_markers]:
            if end_marker in text[start_idx:]:
                end_idx = min(end_idx, text.index(end_marker, start_idx))
        
        result = text[start_idx:end_idx].strip()
        return result if result else None
    except Exception:
        return None

def parse_eu_corrigendum_deadline(full_text):
    """Extract deadline from EU Standard correction notices (Section VII)"""
    deadline_pattern = r'Instead of[^\n]*Date[^\n]*(\d{1,2}.*?202\d)[^\n]*Read[^\n]*Date[^\n]*(\d{1,2}.*?202\d)'
    match = re.search(deadline_pattern, full_text, re.DOTALL)
    
    if match:
        return match.group(2).strip()
    
    fallback_patterns = [
        r'Time limit for receipt.*?(\d{1,2}\s+\w+\s+202\d,\s*\d{1,2}:\d{2}[ap]m)',
        r'Time limit for receipt.*?(\d{1,2}\s+\w+\s+202\d)',
        r'Deadline.*?(\d{1,2}\s+\w+\s+202\d,\s*\d{1,2}:\d{2}[ap]m)',
    ]
    
    for pattern in fallback_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return None

def parse_eu_standard_format(page):
    """Parse EU Standard Form format (numbered sections)"""
    full_text = page.locator("body").inner_text()
    
    data = {
        "title": None,
        "description": None,
        "cpv_codes": [],
        "supplier_name": None,
        "contract_value": None,
        "contract_value_text": None,
        "contract_dates": None,
        "award_date": None,
        "authority_name": None,
        "authority_email": None,
        "authority_website": None,
        "reference": None,
        "procedure_type": None,
        "suitable_for_sme": None,
        "region": None,
    }
    
    # Title
    data["title"] = (
        extract_text_between(full_text, "II.1.1) Title", ["II.1.2", "II.1.3", "Reference number"]) or
        extract_text_between(full_text, "two.1.1) Title", ["Reference number", "two.1.2"])
    )
    if not data["title"] or data["title"].startswith("II.") or data["title"].startswith("two."):
        title_elem = page.query_selector("h1")
        data["title"] = title_elem.inner_text().strip() if title_elem else "Untitled"
    
    # Reference
    data["reference"] = extract_text_between(full_text, "Reference number", ["two.1.2", "two.1.3"])
    
    # CPV codes
    cpv_pattern = r'(\d{8})\s*-\s*([^\n]+)'
    cpv_matches = re.findall(cpv_pattern, full_text)
    data["cpv_codes"] = [match[0] for match in cpv_matches]
    
    # Description
    desc = extract_text_between(full_text, "two.1.4) Short description", ["two.1.5", "two.1.6", "two.2"])
    if not desc or len(desc) < 20:
        desc = extract_text_between(full_text, "two.2.4) Description of the procurement", ["two.2.5", "two.2.6", "Section"])
    data["description"] = desc
    
    # Total value
    value_text = extract_text_between(full_text, "two.1.7) Total value", ["two.2", "Section"])
    if not value_text:
        value_text = extract_text_between(full_text, "Total value of the procurement", ["two.2", "Section"])
    if not value_text:
        value_match = re.search(r'Value[^\n]*[£€]\s*([\d,]+)', full_text)
        if value_match:
            value_text = value_match.group(0)
    
    if value_text:
        data["contract_value_text"] = value_text
        value_match = re.search(r'[£€]\s*([\d,]+)', value_text)
        if value_match:
            try:
                data["contract_value"] = float(value_match.group(1).replace(',', ''))
            except:
                pass
    
    # Check if award
    is_award = any([
        "Section five" in full_text,
        "Section V" in full_text,
        "V.2" in full_text,
        "five.2" in full_text
    ])
    
    if is_award:
        data["notice_type"] = "award"
        
        # Award date
        award_date = (
            extract_text_between(full_text, "V.2.1) Date of conclusion", ["V.2.2", "V.2.3"]) or
            extract_text_between(full_text, "five.2.1) Date of conclusion", ["five.2.2", "five.2.3"])
        )
        data["award_date"] = award_date
        
        # Supplier
        supplier_section = (
            extract_text_between(full_text, "V.2.3) Name and address of the contractor", ["Country", "NUTS", "V.2.4"]) or
            extract_text_between(full_text, "five.2.3) Name and address of the contractor", ["Country", "NUTS", "five.2.4"])
        )
        if supplier_section:
            lines = [l.strip() for l in supplier_section.split('\n') if l.strip()]
            data["supplier_name"] = lines[0] if lines else None
        
        # SME status
        if "The contractor is an SME" in full_text:
            sme_section = extract_text_between(full_text, "The contractor is an SME", ["V.2.4", "five.2.4", "Section"])
            data["suitable_for_sme"] = "Yes" in sme_section if sme_section else None
        
        # Contract value
        contract_value_section = (
            extract_text_between(full_text, "V.2.4) Information on value", ["Section", "V.2.5"]) or
            extract_text_between(full_text, "five.2.4) Information on value", ["Section six", "five.2.5"])
        )
        if contract_value_section:
            value_match = re.search(r'Total value[^\d]*([\d,]+)', contract_value_section)
            if value_match:
                try:
                    data["contract_value"] = float(value_match.group(1).replace(',', ''))
                    data["contract_value_text"] = f"£{value_match.group(1)}"
                except:
                    pass
    else:
        data["notice_type"] = "opportunity"
        
        # Deadline extraction
        deadline = (
            extract_text_between(full_text, "IV.2.2) Time limit for receipt of tenders", ["IV.2.3", "IV.2.4"]) or
            extract_text_between(full_text, "four.2.2) Time limit for receipt of tenders", ["four.2.3", "four.2.4"])
        )
        if not deadline:
            deadline = (
                extract_text_between(full_text, "IV.2.6) Minimum time frame", ["IV.2.7", "Section"]) or
                extract_text_between(full_text, "four.2.6) Minimum time frame", ["four.2.7", "Section"])
            )
        if not deadline:
            deadline = (
                extract_text_between(full_text, "IV.2.7) Conditions for opening", ["IV.2.8", "Section"]) or
                extract_text_between(full_text, "four.2.7) Conditions for opening", ["four.2.8", "Section"])
            )
        if not deadline:
            deadline_section = extract_text_between(full_text, "or requests to participate", ["Date", "Local time"])
            if deadline_section and "IV.2.2)" in deadline_section:
                date_match = re.search(r'Date\n\n(\d{1,2}\s+\w+\s+202\d)', full_text)
                time_match = re.search(r'Local time\n\n(\d{1,2}:\d{2}[ap]m)', full_text)
                if date_match:
                    deadline = date_match.group(1)
                    if time_match:
                        deadline += f", {time_match.group(1)}"
        if not deadline:
            deadline_match = re.search(r'Time limit[^\n]*:\s*([^\n]+)', full_text)
            if deadline_match:
                deadline = deadline_match.group(1)
        
        # Check for corrigendum
        if not deadline and any(["Section seven" in full_text, "Section VII" in full_text, "VII. Changes" in full_text]):
            deadline = parse_eu_corrigendum_deadline(full_text)
            if deadline:
                print(f"  ✅ Found deadline in CORRIGENDUM: {deadline}")
        
        data["deadline"] = deadline
    
    # Authority
    authority_section = (
        extract_text_between(full_text, "I.1) Name and addresses", ["Contact", "Country", "I.2"]) or
        extract_text_between(full_text, "one.1) Name and addresses", ["Contact", "Country", "one.2"])
    )
    if authority_section:
        lines = [l.strip() for l in authority_section.split('\n') if l.strip() and not l.startswith(('one.', 'I.'))]
        data["authority_name"] = lines[0] if lines else None
    
    # Authority email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', full_text)
    if email_match:
        data["authority_email"] = email_match.group(0)
    
    # Region
    nuts_match = re.search(r'(UK[A-Z0-9]{2,3})\s*-\s*([^\n]+)', full_text)
    if nuts_match:
        data["region"] = f"{nuts_match.group(1)} - {nuts_match.group(2)}"
    
    return data

def parse_govuk_design_format(page):
    """Parse GOV.UK Design System format"""
    
    def find_element_by_text(text_content):
        try:
            for tag in ['dt', 'h2', 'h3']:
                elements = page.query_selector_all(tag)
                for elem in elements:
                    elem_text = elem.inner_text().strip()
                    if text_content.lower() in elem_text.lower():
                        return elem
        except:
            pass
        return None
    
    def get_dt_dd_text(label):
        try:
            dt = find_element_by_text(label)
            if dt:
                dd = dt.evaluate_handle("el => el.nextElementSibling")
                if dd:
                    text = dd.inner_text().strip()
                    return text if text else None
        except:
            pass
        return None
    
    def get_dt_dd_list(label):
        try:
            dt = find_element_by_text(label)
            if dt:
                dd = dt.evaluate_handle("el => el.nextElementSibling")
                if dd:
                    items = dd.query_selector_all("li")
                    if items:
                        return [item.inner_text().strip() for item in items]
                    text = dd.inner_text().strip()
                    return [text] if text else []
        except:
            pass
        return []
    
    data = {"cpv_codes": []}
    
    # Title
    title_elem = page.query_selector("h1")
    data["title"] = title_elem.inner_text().strip() if title_elem else "Untitled"
    
    # Description
    desc = get_dt_dd_text("Description")
    if not desc or len(desc) < 10:
        desc_h3 = page.query_selector("h3:has-text('Description')")
        if desc_h3:
            next_elem = desc_h3.evaluate_handle("el => el.nextElementSibling")
            if next_elem:
                desc = next_elem.inner_text().strip()
    data["description"] = desc
    
    # CPV codes
    cpv_list = get_dt_dd_list("CPV classifications")
    if not cpv_list:
        page_text = page.locator("body").inner_text()
        cpv_pattern = r'(\d{8})\s*-\s*([^\n]+)'
        cpv_matches = re.findall(cpv_pattern, page_text)
        data["cpv_codes"] = [match[0] for match in cpv_matches[:5]]
    else:
        for item in cpv_list:
            match = re.search(r'(\d{8})', item)
            if match:
                data["cpv_codes"].append(match.group(1))
    
    # Detect notice type
    is_award = page.query_selector("h2:has-text('Supplier'), h3:has-text('Supplier')") is not None
    data["notice_type"] = "award" if is_award else "opportunity"
    
    if is_award:
        # Supplier
        supplier_heading = find_element_by_text("Supplier")
        if supplier_heading:
            supplier_section = supplier_heading.evaluate_handle("el => el.nextElementSibling || el.parentElement")
            if supplier_section:
                supplier_text = supplier_section.inner_text().strip()
                lines = [l.strip() for l in supplier_text.split('\n') if l.strip()]
                for line in lines:
                    if len(line) > 2 and "Supplier" not in line and "Contract" not in line:
                        data["supplier_name"] = line
                        break
        
        if not data.get("supplier_name"):
            data["supplier_name"] = None
        
        # Contract value
        contract_values = get_dt_dd_list("Contract value")
        if not contract_values:
            page_text = page.locator("body").inner_text()
            value_match = re.search(r'[£€]\s*([\d,]+)\s*(?:including|excluding|GBP)', page_text)
            if value_match:
                contract_values = [value_match.group(0)]
        
        data["contract_value_text"] = contract_values[0] if contract_values else None
        
        if data["contract_value_text"]:
            value_match = re.search(r'£\s*([\d,]+)', data["contract_value_text"])
            if value_match:
                try:
                    data["contract_value"] = float(value_match.group(1).replace(',', ''))
                except:
                    data["contract_value"] = None
        else:
            data["contract_value"] = None
        
        # Award date
        data["award_date"] = get_dt_dd_text("Date signed")
        
        # Contract dates
        data["contract_dates"] = get_dt_dd_list("Contract dates")
        
        # SME
        sme_elem = page.query_selector("text=Small or medium-sized enterprise (SME): Yes")
        data["suitable_for_sme"] = bool(sme_elem)
        
    else:
        # Opportunity fields
        data["supplier_name"] = None
        
        # Deadline
        data["deadline"] = (
            get_dt_dd_text("Deadline for requests to participate") or
            get_dt_dd_text("Deadline for receipt of tenders") or
            get_dt_dd_text("Time limit for receipt of tenders") or
            get_dt_dd_text("Closing date") or
            get_dt_dd_text("Deadline")
        )
        
        # Estimated value
        est_values = get_dt_dd_list("Total value (estimated)")
        if not est_values:
            est_values = get_dt_dd_list("Estimated value")
        if not est_values:
            est_values = get_dt_dd_list("Total value")
        if not est_values:
            est_values = get_dt_dd_list("Contract value")
        
        data["contract_value_text"] = est_values[0] if est_values else None
        
        if data["contract_value_text"]:
            value_match = re.search(r'£\s*([\d,]+)', data["contract_value_text"])
            if value_match:
                try:
                    data["contract_value"] = float(value_match.group(1).replace(',', ''))
                except:
                    data["contract_value"] = None
        else:
            data["contract_value"] = None
        
        # SME
        sme_elem = page.query_selector("text=Small and medium-sized enterprises (SME)")
        data["suitable_for_sme"] = bool(sme_elem)
    
    # Authority
    authority_heading = find_element_by_text("Contracting authority")
    if authority_heading:
        authority_section = authority_heading.evaluate_handle("el => el.parentElement || el.nextElementSibling")
        if authority_section:
            authority_text = authority_section.inner_text().strip()
            lines = [l.strip() for l in authority_text.split('\n') if l.strip()]
            for line in lines:
                if "Contracting authority" not in line and len(line) > 2:
                    data["authority_name"] = line
                    break
    
    if not data.get("authority_name"):
        data["authority_name"] = None
    
    # Authority email
    email_links = page.query_selector_all("a[href^='mailto:']")
    for link in email_links:
        href = link.get_attribute("href")
        if href and "mailto:" in href and "?subject=" not in href:
            data["authority_email"] = href.replace("mailto:", "").strip()
            break
    else:
        data["authority_email"] = None
    
    # Region
    region_elem = page.query_selector("text=/Region: UK[A-Z0-9]+/")
    data["region"] = region_elem.inner_text().replace("Region:", "").strip() if region_elem else None
    
    # Reference
    data["reference"] = get_dt_dd_text("Reference")
    
    return data

def scrape_notice(page, url):
    """Scrape a single FTS notice"""
    try:
        page.goto(url, timeout=60000)
        page.wait_for_selector("h1", timeout=20000)
        
        page_format = detect_page_format(page)
        print(f"  Format: {page_format}")
        
        if page_format == "eu_standard":
            data = parse_eu_standard_format(page)
        elif page_format == "govuk_design":
            data = parse_govuk_design_format(page)
        else:
            print(f"  [warning] Unknown format, using EU parser")
            data = parse_eu_standard_format(page)
        
        tender_id = url.split("/Notice/")[-1].split("?")[0]
        data["tender_id"] = tender_id
        data["url"] = url
        
        return data
        
    except PlaywrightTimeoutError:
        print(f"  [timeout] {url}")
        return None
    except Exception as e:
        print(f"  [error] {url}: {e}")
        return None

def scrape_fts():
    """Scrape FTS tenders - V2 with broader coverage"""
    data = []
    
    # Load existing data
    outfile_path = Path(OUTFILE)
    if outfile_path.exists() and outfile_path.stat().st_size > 0:
        try:
            with open(OUTFILE, "r") as f:
                data = json.load(f)
            print(f"[info] Loaded {len(data)} existing tenders")
        except json.JSONDecodeError:
            print("[warning] Existing JSON invalid, starting fresh")
            data = []
    
    # Build seen URLs set for deduplication
    seen_urls = set(d["url"] for d in data)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 🔥 KEY CHANGE: Removed stage=1 filter
        base_url = "https://www.find-tender.service.gov.uk/Search/Results?status=Open&page="
        
        # Increased page limit
        MAX_PAGES = 500
        page_no = 1
        
        print(f"\n{'='*60}")
        print(f"FTS SCRAPER V2 - Broader Coverage")
        print(f"URL: {base_url}X (no stage filter)")
        print(f"Page limit: {MAX_PAGES}")
        print(f"{'='*60}\n")
        
        while page_no <= MAX_PAGES:
            search_url = f"{base_url}{page_no}"
            print(f"\n{'='*60}")
            print(f"[page {page_no}/{MAX_PAGES}] {search_url}")
            print('='*60)
            
            try:
                page.goto(search_url, timeout=60000)
                page.wait_for_selector("a[href*='/Notice/']", timeout=20000)
            except PlaywrightTimeoutError:
                print(f"[timeout] search page {page_no}, stopping")
                break
            
            # Get notice links
            links = page.eval_on_selector_all(
                "a[href*='/Notice/']",
                "els => els.map(e => e.href)"
            )
            links = sorted(set(links))
            
            if not links:
                print(f"[✅] No more results")
                break
            
            print(f"Found {len(links)} tenders on this page\n")
            
            # Scrape each notice
            for idx, link in enumerate(links, 1):
                # Deduplication
                if link in seen_urls:
                    print(f"[{idx}/{len(links)}] ⏭️  Already scraped")
                    continue
                
                seen_urls.add(link)
                
                tender_id = link.split("/Notice/")[-1].split("?")[0]
                print(f"[{idx}/{len(links)}] {tender_id}")
                
                notice = scrape_notice(page, link)
                
                if notice:
                    print(f"  ✅ {notice.get('notice_type', 'unknown').upper()}: {notice.get('title', 'no title')[:50]}")
                    if notice.get('cpv_codes'):
                        print(f"  📋 CPV: {', '.join(notice['cpv_codes'][:3])}")
                    if notice.get('contract_value'):
                        print(f"  💰 Value: £{notice['contract_value']:,.0f}")
                    if notice.get('supplier_name'):
                        print(f"  🏢 Supplier: {notice['supplier_name'][:40]}")
                    if notice.get('deadline'):
                        print(f"  ⏰ Deadline: {notice['deadline']}")
                    
                    data.append(notice)
                    
                    # Progressive save
                    with open(OUTFILE, "w") as f:
                        json.dump(data, f, indent=2)
                else:
                    print(f"  ❌ Extraction failed")
                
                time.sleep(0.5)
            
            page_no += 1
            time.sleep(0.5)
        
        browser.close()
    
    print(f"\n{'='*60}")
    print(f"[✅] COMPLETE: Saved {len(data)} tenders to {OUTFILE}")
    print('='*60)

if __name__ == "__main__":
    scrape_fts()