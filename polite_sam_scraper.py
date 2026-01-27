"""
Polite SAM.gov attachment scraper for production use.
Implements respectful rate limiting, business-hours gating, caching, and robust
attachment filtering (skip external links / missing resourceIds / non-public / non-existent).

Key fixes vs prior version:
- Hard-skip attachments with missing/invalid resourceId (prevents most HTTP 400s)
- Treat fileExists/deletedFlag as truthy values (robust across response variants)
- Skip non-public attachments (accessLevel != public)
- Sanitize filenames (safe cache paths)
- Validate download response (avoid saving HTML/error payloads)
- Add per-notice filter stats + richer error logs (including 400 body snippet)
- Retry with exponential backoff on transient errors (429/5xx/timeouts)
"""

import time
import random
import re
import httpx
import logging
from pathlib import Path
from datetime import datetime, time as dt_time
import pytz
from typing import List, Dict, Optional, Tuple


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PoliteSAMScraper:
    """Polite SAM.gov scraper with rate limiting, caching, and robust filtering."""

    API_BASE = "https://sam.gov/api/prod/opps/v3/opportunities"

    # US Eastern Time business hours
    BUSINESS_HOURS_START = dt_time(9, 0)   # 9 AM ET
    BUSINESS_HOURS_END = dt_time(17, 0)    # 5 PM ET

    # Rate limiting
    MIN_DELAY_SECONDS = 5
    MAX_DELAY_SECONDS = 10

    # Retries
    MAX_RETRIES = 4
    BACKOFF_BASE_SECONDS = 2.0
    BACKOFF_JITTER_SECONDS = 0.8

    # US Federal Holidays 2026 (don't run on these days)
    FEDERAL_HOLIDAYS_2026 = [
        "2026-01-01",  # New Year's Day
        "2026-01-19",  # MLK Day
        "2026-02-16",  # Presidents' Day
        "2026-05-25",  # Memorial Day
        "2026-07-03",  # Independence Day (observed)
        "2026-09-07",  # Labor Day
        "2026-10-12",  # Columbus Day
        "2026-11-11",  # Veterans Day
        "2026-11-26",  # Thanksgiving
        "2026-12-25",  # Christmas
    ]

    def __init__(self, cache_dir: Path = None, contact_email: str = "your-email@example.com"):
        """
        Args:
            cache_dir: Directory to cache downloaded files
            contact_email: Your contact email for User-Agent (recommended)
        """
        self.cache_dir = cache_dir or Path("./sam_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Browser-like headers (often helps)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://sam.gov/",
            "Origin": "https://sam.gov",
        }

        # If you want to include contact email in UA, you can do it here safely
        # (Some sites prefer a contact; but keep it simple)
        if contact_email and contact_email != "your-email@example.com":
            self.headers["User-Agent"] += f" (contact: {contact_email})"

        self.client = httpx.Client(
            headers=self.headers,
            timeout=60.0,
            follow_redirects=True,
        )

    # ---------------------------
    # Utilities
    # ---------------------------

    @staticmethod
    def _is_truthy(v) -> bool:
        """Robust truthiness for SAM flags that may be '1'/1/true/'true'/etc."""
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "y", "t")

    @staticmethod
    def _safe_filename(name: Optional[str], default: str) -> str:
        """Make filename safe for filesystem usage."""
        if not name or str(name).strip().lower() == "none":
            return default
        name = str(name).strip()

        # Replace path separators
        name = name.replace("\\", "_").replace("/", "_")

        # Remove odd characters
        name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)

        # Prevent empty
        if not name:
            return default

        # Cap to avoid path length issues
        return name[:180]

    def is_business_hours(self) -> bool:
        """Check if current time is during US business hours (US/Eastern)."""
        eastern = pytz.timezone("US/Eastern")
        now = datetime.now(eastern)

        # weekend
        if now.weekday() >= 5:
            logger.warning("It's the weekend - skipping to respect US federal working hours")
            return False

        # federal holiday
        today = now.strftime("%Y-%m-%d")
        if today in self.FEDERAL_HOLIDAYS_2026:
            logger.warning(f"It's a US federal holiday ({today}) - skipping")
            return False

        # business hours
        current_time = now.time()
        if current_time < self.BUSINESS_HOURS_START or current_time > self.BUSINESS_HOURS_END:
            logger.warning(f"Outside business hours (9 AM - 5 PM ET) - current time: {current_time}")
            return False

        return True

    def polite_delay(self):
        """Add a polite random delay between requests."""
        delay = random.uniform(self.MIN_DELAY_SECONDS, self.MAX_DELAY_SECONDS)
        logger.info(f"⏸️  Polite delay: {delay:.1f} seconds")
        time.sleep(delay)

    def _backoff_sleep(self, attempt: int):
        """Exponential backoff with jitter."""
        base = self.BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0, self.BACKOFF_JITTER_SECONDS)
        delay = base + jitter
        logger.warning(f"⏳ Backing off for {delay:.1f}s (attempt {attempt}/{self.MAX_RETRIES})")
        time.sleep(delay)

    def _request_with_retries(self, method: str, url: str) -> httpx.Response:
        """
        Retry on transient errors:
        - 429 (rate limit)
        - 5xx
        - timeouts / network errors
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                resp = self.client.request(method, url)
                # Retry on 429 and 5xx
                if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                    logger.warning(f"⚠️  HTTP {resp.status_code} for {url}")
                    if attempt < self.MAX_RETRIES:
                        self._backoff_sleep(attempt)
                        continue
                resp.raise_for_status()
                return resp

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                logger.warning(f"⚠️  Network/timeout error for {url}: {e}")
                if attempt < self.MAX_RETRIES:
                    self._backoff_sleep(attempt)
                    continue
                raise

            except httpx.HTTPStatusError as e:
                last_exc = e
                # For non-retryable status codes, just raise
                status = e.response.status_code if e.response is not None else None
                if status in (429,) or (status is not None and 500 <= status <= 599):
                    if attempt < self.MAX_RETRIES:
                        self._backoff_sleep(attempt)
                        continue
                raise

        # Should never hit, but just in case:
        if last_exc:
            raise last_exc
        raise RuntimeError("Request failed without exception (unexpected).")

    def get_cached_filepath(self, resource_id: str, filename: str) -> Optional[Path]:
        """Return cached file path if exists."""
        filename = self._safe_filename(filename, f"attachment_{resource_id}.bin")
        filepath = self.cache_dir / f"{resource_id}_{filename}"
        if filepath.exists():
            logger.info(f"✅ Found in cache: {filepath.name}")
            return filepath
        return None

    # ---------------------------
    # Core functionality
    # ---------------------------

    def get_attachments(self, notice_id: str) -> Tuple[List[Dict], Dict]:
        """
        Get downloadable attachments for a notice.

        Returns:
            (attachments, stats)
        """
        api_url = f"{self.API_BASE}/{notice_id}/resources"
        logger.info(f"🔍 Fetching attachments for: {notice_id}")

        response = self._request_with_retries("GET", api_url)
        data = response.json()

        attachments: List[Dict] = []
        opp_list = data.get("_embedded", {}).get("opportunityAttachmentList", [])

        stats = {
            "total": 0,
            "deleted": 0,
            "not_file": 0,
            "missing_resource": 0,
            "not_exists": 0,
            "not_public": 0,
            "kept": 0,
        }

        for opp in opp_list:
            for att in opp.get("attachments", []):
                stats["total"] += 1

                # Skip deleted
                if self._is_truthy(att.get("deletedFlag")):
                    stats["deleted"] += 1
                    continue

                # Only SAM-hosted files
                att_type = (att.get('type') or "").lower()
                if att_type not in ("file", "link"):
                    stats["not_file"] += 1
                    continue

                # Only public
                access = (att.get("accessLevel") or "").lower()
                if access and access != "public":
                    stats["not_public"] += 1
                    continue

                # Must have real resourceId (prevents most 400s)
                rid = att.get("resourceId")
                if not rid or str(rid).strip().lower() == "none":
                    stats["missing_resource"] += 1
                    continue

                # Must exist
                if not self._is_truthy(att.get("fileExists")):
                    stats["not_exists"] += 1
                    continue

                filename = att.get("name")
                if not filename or str(filename).strip().lower() == "none":
                    # Try description field
                    filename = att.get("description", "").split("/")[-1]  # Get last part of URL
                    if not filename or len(filename) > 100:
                        filename = f"attachment_{rid}.pdf"

                attachments.append({
                    "filename": filename,
                    "resource_id": str(rid),
                    "size": att.get("size"),
                    "mime_type": att.get("mimeType"),
                    "posted_date": att.get("postedDate"),
                })
                stats["kept"] += 1

        logger.info(f"   Found {len(attachments)} downloadable file(s)")
        logger.info(f"   Filter stats: {stats}")
        return attachments, stats

    def download_attachment(self, resource_id: str, filename: Optional[str], use_cache: bool = True) -> Optional[Path]:
        """
        Download a single attachment.

        Returns:
            Path to downloaded file or None if failed.
        """
        if not resource_id or str(resource_id).strip().lower() == "none":
            logger.warning("⚠️  Missing resource_id; cannot download.")
            return None

        safe_name = self._safe_filename(filename, f"attachment_{resource_id}.pdf")

        # Cache
        if use_cache:
            cached = self.get_cached_filepath(resource_id, safe_name)
            if cached:
                return cached

        download_url = f"{self.API_BASE}/resources/files/{resource_id}/download"
        logger.info(f"📥 Downloading: {safe_name}")

        try:
            response = self._request_with_retries("GET", download_url)

            # Validate response content looks like a file (avoid saving HTML error pages)
            ct = (response.headers.get("content-type") or "").lower()
            if "text/html" in ct:
                logger.warning("   ⚠️  Got HTML instead of a file; skipping save")
                return None
            if len(response.content) < 500:
                logger.warning("   ⚠️  Response too small to be a real attachment; skipping")
                return None

            filepath = self.cache_dir / f"{resource_id}_{safe_name}"
            with open(filepath, "wb") as f:
                f.write(response.content)

            size_kb = len(response.content) / 1024
            logger.info(f"   ✅ Saved: {filepath.name} ({size_kb:.1f} KB)")
            return filepath

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 400:
                body = ""
                try:
                    body = (e.response.text or "")[:300] if e.response is not None else ""
                except Exception:
                    body = ""
                logger.warning(f"   ⚠️  HTTP 400 - likely invalid resource ID / not downloadable")
                if body:
                    logger.warning(f"   Body: {body}")
            elif status == 429:
                logger.error("⚠️  Rate limited during download (429).")
            else:
                logger.error(f"   ❌ HTTP {status} during download")
            return None

        except Exception as e:
            logger.error(f"   ❌ Download failed: {e}")
            return None

    def process_batch(self, notice_ids: List[str], respect_business_hours: bool = True) -> List[Dict]:
        """
        Process a batch of notice IDs with polite rate limiting.

        Returns:
            List of results for each notice
        """
        results: List[Dict] = []

        for i, notice_id in enumerate(notice_ids, 1):
            if respect_business_hours and not self.is_business_hours():
                logger.warning("⏸️  Outside business hours - stopping batch")
                break

            logger.info(f"Processing {i}/{len(notice_ids)}: {notice_id}")

            try:
                attachments, stats = self.get_attachments(notice_id)

                downloaded = []
                for j, att in enumerate(attachments, 1):
                    filepath = self.download_attachment(
                        resource_id=att["resource_id"],
                        filename=att["filename"],
                        use_cache=True,
                    )

                    if filepath:
                        downloaded.append({
                            "filename": self._safe_filename(att["filename"], f"attachment_{att['resource_id']}.pdf"),
                            "filepath": str(filepath),
                            "size": att.get("size"),
                            "mime_type": att.get("mime_type"),
                        })

                    # Polite delay between downloads (if multiple)
                    if j < len(attachments):
                        self.polite_delay()

                results.append({
                    "notice_id": notice_id,
                    "success": True,
                    "attachments": downloaded,
                    "attachment_filter_stats": stats,
                })

            except Exception as e:
                logger.error(f"❌ Failed {notice_id}: {e}")
                results.append({
                    "notice_id": notice_id,
                    "success": False,
                    "error": str(e),
                })

            # Polite delay before next notice
            if i < len(notice_ids):
                self.polite_delay()

        return results

    def close(self):
        """Close HTTP client."""
        self.client.close()


# ---------------------------
# Example usage / smoke test
# ---------------------------
if __name__ == "__main__":
    scraper = PoliteSAMScraper(
        cache_dir=Path("./sam_cache"),
        contact_email="your-email@yourcompany.com",  # UPDATE THIS
    )

    notice_ids = [
        "12c167468aff46b4a22e5b3c38fb9a2e",
        "d2768f1e963b4b0e900ff9548e506a68",
        "4ca81557b47e422ba6198e2928dbed0b",
        "ee733f5add42404badb3c8f7b5436cb1",
        "c05f595f974d4ea09d508c475b3f8e86",
        "7680b6389764de4aedc16ddbb1858b1",
        "ee3e18514d2b4ab0bb6a9110c88d8084",
    ]

    print(f"Testing with {len(notice_ids)} contracts...\n")

    results = scraper.process_batch(
        notice_ids=notice_ids,
        respect_business_hours=False,  # set True in production
    )

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    success_count = 0
    total_files = 0

    for result in results:
        if result["success"]:
            files = len(result["attachments"])
            print(f"✅ {result['notice_id']}: {files} file(s) downloaded")
            print(f"   filter stats: {result.get('attachment_filter_stats')}")
            success_count += 1
            total_files += files
        else:
            print(f"❌ {result['notice_id']}: {result['error']}")

    print(f"\nSummary: {success_count}/{len(results)} notices processed, {total_files} total files downloaded")

    scraper.close()