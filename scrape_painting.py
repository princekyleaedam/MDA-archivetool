"""
Script 1: Million Dollar Drawing - Data Scraper
================================================
1. Downloads the canvas snapshot (.bin.gz) from CloudFront.
2. Reads each byte — if NOT 0xFF, that pixel has content:
       x = (n - 1) // 1000
       y = (n - 1) %  1000
3. Fetches only those coordinates from the API.
4. Saves results to data_archive_painting.csv.
5. After the main pass, compares requested coords vs saved rows.
   Any coord that was requested but not saved is retried (up to
   MAX_RECONCILE_PASSES times) until the counts match or no new
   rows are recovered.

Output columns:
  x, y, username, 
  current_content_color_hex, current_content_created_at,
  legacy_message
"""

import csv
import asyncio
import aiohttp
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────
BIN_URL     = "https://d34w1vc7uzb89c.cloudfront.net/canvas/snapshot/latest.bin.gz"
BASE_URL    = "https://api.themilliondollardrawing.com/pixels/{x}/{y}"
now = datetime.now()

formatted_time = now.strftime("%B %d, %Y, %H_%M_%S %p")
formatted_time += " UTC+08"
OUTPUT_FILE = "data_archive_painting " + formatted_time + ".csv"
COORD_RANGE = range(0, 1000)          # 0 to 999 inclusive
MAX_WORKERS = 1000                    # concurrent requests
TIMEOUT_SEC = 5                     # per-request timeout
RETRY_COUNT = 1                       # retries on network error
ISNOT_COMPLETE = True                #makes sure that it gets elbiting
DELAY_BETWEEN_BATCHES = 0.05       # seconds between launching batches
pass_num = 1
# ───────────────────────────────────────────────────────────────────────────────

PRIMARY_COLS = ["x", "y", "username", "current_content_color_hex", "legacy_message", "current_content_created_at", ]


# ── Helpers ────────────────────────────────────────────────────────────────────

async def download_bin(session: aiohttp.ClientSession) -> bytes:
    """Download and decompress the canvas snapshot."""
    print(f"[{datetime.now():%H:%M:%S}] Downloading canvas snapshot ...")
    async with session.get(BIN_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        resp.raise_for_status()
        compressed = await resp.read()
    raw = compressed
    return raw


def extract_coords(raw: bytes) -> list[tuple[int, int]]:
    """Return (x, y) for every byte that is NOT 0xFF."""
    coords = []
    for n_minus1, byte in enumerate(raw):
        if byte != 0xFF:
            coords.append((n_minus1 % 1000, n_minus1 // 1000))
    return coords


async def fetch_pixel(session: aiohttp.ClientSession, x: int, y: int) -> dict | None:
    """Fetch one pixel. Returns a flat dict on success, None to skip."""
    url = BASE_URL.format(x=x, y=y)
    for attempt in range(RETRY_COUNT + 1):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if not isinstance(data, dict):
                    return None
                content = data.get("current_content")
                return {
                    "x":                          data.get("x", x),
                    "y":                          data.get("y", y),
                    "status":                     data.get("status"),
                    "base_price":                 data.get("base_price"),
                    "owner_id":                   data.get("owner_id"),
                    "username":                   data.get("owner").get("username"),
                    "email":                   data.get("owner").get("email"),
                    "role":                   data.get("owner").get("role"),
                    "isverified":                   data.get("owner").get("isverified"),
                    "googleId":                   data.get("owner").get("googleId"),
                    "created_at":                   data.get("owner").get("created_at"),
                    "owner_status":                   data.get("owner").get("status"),
                    "restricted_until":                   data.get("owner").get("restricted_until"),
                    "violation_count":                   data.get("owner").get("violation_count"),
                    "avatar_s3_key":                   data.get("owner").get("avatar_s3_key"),
                    "current_content_id":         data.get("current_content_id"),
                    "content_type":               content.get("content_type"),
                    "current_content_color_hex":  content.get("color_hex"),
                    "s3_key":  content.get("s3_key"),
                    "moderation_status":  content.get("moderation_status"),
                    "rejection_reason":  content.get("rejection_reason"),
                    
                    
                    
                    "legacy_message":             content.get("legacy_message"),
                    "current_content_created_at": content.get("created_at"),
                    "is_active":                  content.get("is_active"),
                }
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
            if attempt < RETRY_COUNT:
                await asyncio.sleep(0.5 * (attempt + 1))
    return None


async def fetch_batch(
    session: aiohttp.ClientSession,
    coords: list[tuple[int, int]],
    label: str = "Fetching",
) -> tuple[list[dict], set[tuple[int, int]]]:
    """
    Fetch all coords in batches of MAX_WORKERS.
    Returns:
      rows       — list of successfully fetched dicts
      failed     — set of (x, y) that returned None (no data / no content)
    """
    total  = len(coords)
    done   = 0
    rows   = []
    failed : set[tuple[int, int]] = set()

    print(f"[{datetime.now():%H:%M:%S}] {label}: {total:,} coords ({MAX_WORKERS} concurrent) ...")

    for batch_start in range(0, total, MAX_WORKERS):
        batch   = coords[batch_start : batch_start + MAX_WORKERS]
        tasks   = [fetch_pixel(session, x, y) for x, y in batch]
        results = await asyncio.gather(*tasks)

        for (x, y), result in zip(batch, results):
            if result is not None:
                rows.append(result)
            else:
                failed.add((x, y))

        done += len(batch)
        if done % MAX_WORKERS == 0 or done == total:
            pct = done / total * 100
            print(f"  [{datetime.now():%H:%M:%S}] "
                  f"{done:>7,}/{total:,} ({pct:5.1f}%)  saved so far={len(rows):,}")
    
    if total == rows:
        ISNOT_COMPLETE = False
    
    return rows, failed


def load_saved_coords(filepath: str) -> set[tuple[int, int]]:
    """Read the CSV and return a set of (x, y) already saved."""
    saved = set()
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    saved.add((int(row["x"]), int(row["y"])))
                except (KeyError, ValueError):
                    pass
    except FileNotFoundError:
        pass
    return saved


def append_rows(filepath: str, rows: list[dict]) -> None:
    """Append rows to the CSV (file must already exist with a header)."""
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PRIMARY_COLS, extrasaction="ignore")
        writer.writerows(rows)


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    connector = aiohttp.TCPConnector(limit=MAX_WORKERS, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        pass_num = 1
        
        
        # 1. Get the list of coords to query from the .bin snapshot
        raw    = await download_bin(session)
        coords = extract_coords(raw)
        total  = len(coords)
        print(f"  {total:,} non-FF pixels to query "
              f"(skipped {len(raw) - total:,} empty slots)\n")

        if total == 0:
            print("Nothing to fetch. Exiting.")
            return

        requested: set[tuple[int, int]] = set(coords)

        # 2. Main fetch pass — write fresh CSV
        rows, _ = await fetch_batch(session, coords, label="Main pass")

        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PRIMARY_COLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        # 3. Reconciliation loop
        while ISNOT_COMPLETE:
            saved_coords  = load_saved_coords(OUTPUT_FILE)
            missing       = requested - saved_coords
            saved_count   = len(saved_coords)
 
            print(f"\n── Reconciliation check (pass {pass_num}) ──────────────────")
            print(f"  Requested : {len(requested):,}")
            print(f"  Saved     : {saved_count:,}")
            print(f"  Missing   : {len(missing):,}")
 
            if not missing:
                print("  ✓ Counts match — no missing rows.")
                break
 
            print(f"  Retrying {len(missing):,} missing coords ...")
            retry_coords        = sorted(missing)   # deterministic order
            recovered_rows, _   = await fetch_batch(
                session, retry_coords,
                label=f"Reconciliation pass {pass_num}"
            )
 
            if not recovered_rows:
                print(f"  No new rows recovered in pass {pass_num}. "
                      "Remaining coords likely have no content on the API.")
                break
 
            append_rows(OUTPUT_FILE, recovered_rows)
            print(f"  Appended {len(recovered_rows):,} recovered rows.")

        # 4. Final report
        final_saved = load_saved_coords(OUTPUT_FILE)
        truly_missing = requested - final_saved
        print(f"\n{'='*55}")
        print(f"  Requested coords : {len(requested):,}")
        print(f"  Rows in CSV      : {len(final_saved):,}")
        if truly_missing:
            print(f"  Still missing    : {len(truly_missing):,}  "
                  "(API returned no content for these — normal for unsold/blank pixels)")
        else:
            print(f"  All requested coords accounted for.")
        print(f"  Output file      : {OUTPUT_FILE}")
        print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())