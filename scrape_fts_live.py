#!/usr/bin/env python3
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

OUTFILE = "fts_live_rich.json"

def scrape_notice(page, url):
    """Scrape a single FTS notice page for rich data."""
    try:
        page.goto(url, timeout=60000)
        page.wait_for_selector("h1.govuk-heading-l", timeout=20000)

        def get_text(selector, default="Unknown"):
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else default

        def get_next_sibling_text(label_text, tag="p", default="Unknown"):
            el = page.query_selector(f"h3:has-text('{label_text}')")
            if el:
                sibling = el.evaluate_handle("el => el.nextElementSibling")
                return sibling.inner_text().strip() if sibling else default
            return default

        def get_next_sibling_list(label_text):
            el = page.query_selector(f"h3:has-text('{label_text}')")
            items = []
            if el:
                sibling = el.evaluate_handle("el => el.nextElementSibling")
                if sibling:
                    lis = sibling.query_selector_all("li")
                    items = [li.inner_text().strip() for li in lis]
            return items

        # Main fields
        title = get_text("h1.govuk-heading-l", "Untitled")
        publishing_authority = get_text("div.govuk-grid-column-three-quarters > ul.govuk-list > li", "Unknown")
        notice_id = get_next_sibling_text("Notice identifier:", "p", "")
        published_date = get_next_sibling_text("Published", "p", "")
        reference = get_next_sibling_text("Reference", "p", "")
        description = get_next_sibling_text("Description", "div", "")

        # Contract details
        contract_value = get_next_sibling_list("Contract value")
        award_decision_date = get_next_sibling_text("Award decision date")
        contract_dates = get_next_sibling_list("Contract dates (estimated)")

        # Supplier
        supplier_name = get_text("h3#supplier_or_tenderer_0", "Unknown")
        supplier_block = page.query_selector("h3#supplier_or_tenderer_0 + div.govuk-body")
        supplier_address = [p.inner_text().strip() for p in supplier_block.query_selector_all("p")] if supplier_block else []
        supplier_email_el = supplier_block.query_selector("a[href^='mailto:']") if supplier_block else None
        supplier_email = supplier_email_el.get_attribute("href").replace("mailto:", "").strip() if supplier_email_el else "Unknown"

        # Contracting authority
        authority_name = get_text("h3#contracting_authority_0", "Unknown")
        authority_block = page.query_selector("h3#contracting_authority_0 + div.govuk-body")
        authority_address = [p.inner_text().strip() for p in authority_block.query_selector_all("p")] if authority_block else []
        authority_email_el = authority_block.query_selector("a[href^='mailto:']") if authority_block else None
        authority_email = authority_email_el.get_attribute("href").replace("mailto:", "").strip() if authority_email_el else "Unknown"
        authority_website_el = authority_block.query_selector("a[href^='http']") if authority_block else None
        authority_website = authority_website_el.get_attribute("href").strip() if authority_website_el else "Unknown"

        tender_id = url.split("/Notice/")[-1].split("?")[0]

        return {
            "url": url,
            "tender_id": tender_id,
            "title": title,
            "publishing_authority": publishing_authority,
            "notice_id": notice_id,
            "published_date": published_date,
            "reference": reference,
            "description": description,
            "contract_value": contract_value,
            "award_decision_date": award_decision_date,
            "contract_dates": contract_dates,
            "supplier_name": supplier_name,
            "supplier_address": supplier_address or ["Unknown"],
            "supplier_email": supplier_email,
            "authority_name": authority_name,
            "authority_address": authority_address or ["Unknown"],
            "authority_email": authority_email,
            "authority_website": authority_website
        }

    except PlaywrightTimeoutError:
        print(f"[timeout] {url}")
        return None
    except Exception as e:
        print(f"[error] {url}: {e}")
        return None

def scrape_fts():
    """Scrape all open tenders and save progressively to JSON."""
    data = []

    # Load existing data if present
    outfile_path = Path(OUTFILE)
    if outfile_path.exists() and outfile_path.stat().st_size > 0:
        try:
            with open(OUTFILE, "r") as f:
                data = json.load(f)
            print(f"[info] Loaded {len(data)} existing tenders")
        except json.JSONDecodeError:
            print("[warning] Existing JSON file is invalid, starting fresh")
            data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        base_url = "https://www.find-tender.service.gov.uk/Search/Results?stage=1&status=Open&page="
        page_no = 1

        while True:
            search_url = f"{base_url}{page_no}"
            print(f"[page {page_no}] Navigating to {search_url}")
            try:
                page.goto(search_url, timeout=60000)
                page.wait_for_selector("a[href*='/Notice/']", timeout=20000)
            except PlaywrightTimeoutError:
                print(f"[timeout] search page {page_no}, skipping")
                page_no += 1
                continue

            links = page.eval_on_selector_all("a[href*='/Notice/']", "els => els.map(e => e.href)")
            links = sorted(set(links))

            if not links:
                print(f"[✅] No more results after page {page_no}")
                break

            print(f"[page {page_no}] found {len(links)} tenders")
            for link in links:
                if any(d["url"] == link for d in data):
                    continue  # skip already scraped
                notice = scrape_notice(page, link)
                if notice:
                    data.append(notice)
                    # save progressively
                    with open(OUTFILE, "w") as f:
                        json.dump(data, f, indent=2)
                    time.sleep(1)  # polite pacing

            page_no += 1
            time.sleep(1)  # page transition delay

        browser.close()
    print(f"[✅] Done. Saved {len(data)} tenders to {OUTFILE}")

if __name__ == "__main__":
    scrape_fts()
