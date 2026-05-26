"""
Script 1: Million Dollar Drawing - Data Scraper
================================================
1. Downloads the canvas snapshot (.bin.gz) from CloudFront.
2. Reads each byte — if NOT 0xFF, that pixel has content:
       x = (n - 1) % 1000      (horizontal scan, x advances first)
       y = (n - 1) // 1000
   The byte value is looked up in the colour palette to get the hex colour.
3. Fetches only those coordinates from the API.
4. Saves results to data_archive_painting.csv.
5. After the main pass, reconciles requested coords vs saved rows and
   retries missing ones (up to MAX_RECONCILE_PASSES times).

Output columns:
  x, y, color_hex, owner_id, owner_name, legacy_message, rank, made_at
"""

import csv
import asyncio
import aiohttp
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────
BIN_URL              = "https://d34w1vc7uzb89c.cloudfront.net/canvas/snapshot/latest.bin.gz"
BASE_URL             = "https://api.themilliondollardrawing.com/pixels/{x}/{y}"
OUTPUT_FILE          = "data_archive_painting.csv"
MAX_WORKERS          = 1000      # concurrent API requests
TIMEOUT_SEC          = 10      # per-request timeout (seconds)
RETRY_COUNT          = 0       # retries on transient network error per attempt
ISNOT_COMPLETE       = True    #makes sure that it gets elbiting
MAX_RECONCILE_PASSES = 3       # reconciliation passes before giving up
# ───────────────────────────────────────────────────────────────────────────────

# Colour palette: byte value -> (R, G, B)
PALETTE: dict[int, tuple[int, int, int]] = {
    0x00: (198,  40,  40),
    0x01: (229,  57,  53),
    0x02: (251, 140,   0),
    0x03: (255, 112,  67),
    0x04: (255, 179,   0),
    0x05: (253, 216,  53),
    0x06: (192, 202,  51),
    0x07: ( 67, 160,  71),
    0x08: ( 27,  94,  32),
    0x09: (  0, 137, 123),
    0x0A: (  0, 172, 193),
    0x0B: ( 38, 198, 218),
    0x0C: ( 41, 182, 246),
    0x0D: ( 30, 136, 229),
    0x0E: ( 13,  71, 161),
    0x0F: (142,  36, 170),
    0x10: (216,  27,  96),
    0x11: (109,  76,  65),
    0x12: (255, 255, 255),
    0x13: (122, 122, 122),
    0x14: ( 47,  47,  47),
    0x15: ( 17,  17,  17),
}

PRIMARY_COLS = [
    "x", "y", "color_hex",
    "owner_id", "owner_name", "legacy_message", "rank", "made_at",
]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# ── Helpers ────────────────────────────────────────────────────────────────────

async def download_bin(session: aiohttp.ClientSession) -> bytes:
    """Download and decompress the canvas snapshot."""
    print(f"[{datetime.now():%H:%M:%S}] Downloading canvas snapshot ...")
    async with session.get(BIN_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        resp.raise_for_status()
        raw = await resp.read()
    print(f"  {len(raw):,} bytes acquired.")
    return raw


def extract_coords(raw: bytes) -> list[tuple[int, int, str]]:
    """
    Return (x, y, color_hex) for every byte that is NOT 0xFF.
    x = (n - 1) % 1000   (horizontal scan)
    y = (n - 1) // 1000
    color_hex is derived from the palette using the byte value.
    """
    coords = []
    for n_minus1, byte in enumerate(raw):
        if byte != 0xFF:
            x         = n_minus1 % 1000
            y         = n_minus1 // 1000
            rgb       = PALETTE.get(byte, (128, 128, 128))  # grey fallback
            color_hex = rgb_to_hex(rgb)
            coords.append((x, y, color_hex))
    return coords


async def fetch_pixel(
    session: aiohttp.ClientSession,
    x: int, y: int, color_hex: str,
) -> dict | None:
    """Fetch one pixel from the API. Returns a flat dict on success, None to skip."""
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
                # Require at least one meaningful API field to confirm a real response
                if not data.get("ownerId") and not data.get("madeAt"):
                    return None
                return {
                    "x":             x,
                    "y":             y,
                    "color_hex":     color_hex,          # from palette, not API
                    "owner_id":      data.get("ownerId"),
                    "owner_name":    data.get("ownerName"),
                    "legacy_message":data.get("legacyMessage"),
                    "rank":          data.get("rank"),
                    "made_at":       data.get("madeAt"),
                }
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
            if attempt < RETRY_COUNT:
                await asyncio.sleep(0.5 * (attempt + 1))
    return None
    
    if total == rows:
        ISNOT_COMPLETE = False
    
    return rows, failed


async def fetch_batch(
    session: aiohttp.ClientSession,
    coords: list[tuple[int, int, str]],
    label: str = "Fetching",
) -> tuple[list[dict], set[tuple[int, int]]]:
    """
    Fetch all coords in batches of MAX_WORKERS.
    Returns:
      rows   — list of successfully fetched dicts
      failed — set of (x, y) that returned None
    """
    total  = len(coords)
    done   = 0
    rows   = []
    failed: set[tuple[int, int]] = set()

    print(f"[{datetime.now():%H:%M:%S}] {label}: {total:,} coords "
          f"({MAX_WORKERS} concurrent) ...")

    for batch_start in range(0, total, MAX_WORKERS):
        batch   = coords[batch_start : batch_start + MAX_WORKERS]
        tasks   = [fetch_pixel(session, x, y, c) for x, y, c in batch]
        results = await asyncio.gather(*tasks)

        for (x, y, _), result in zip(batch, results):
            if result is not None:
                rows.append(result)
            else:
                failed.add((x, y))

        done += len(batch)
        if done % 5_000 == 0 or done == total:
            pct = done / total * 100
            print(f"  [{datetime.now():%H:%M:%S}] "
                  f"{done:>7,}/{total:,} ({pct:5.1f}%)  saved so far={len(rows):,}")

    return rows, failed


def load_saved_coords(filepath: str) -> set[tuple[int, int]]:
    """Read the CSV and return a set of (x, y) already saved."""
    saved = set()
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    saved.add((int(row["x"]), int(row["y"])))
                except (KeyError, ValueError):
                    pass
    except FileNotFoundError:
        pass
    return saved


def append_rows(filepath: str, rows: list[dict]) -> None:
    """Append rows to an existing CSV."""
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PRIMARY_COLS, extrasaction="ignore")
        writer.writerows(rows)


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    connector = aiohttp.TCPConnector(limit=MAX_WORKERS, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:

        # 1. Download snapshot and extract coords + colours from palette
        raw    = await download_bin(session)
        coords = extract_coords(raw)          # list of (x, y, color_hex)
        total  = len(coords)
        print(f"  {total:,} non-FF pixels to query "
              f"(skipped {len(raw) - total:,} empty slots)\n")

        if total == 0:
            print("Nothing to fetch. Exiting.")
            return

        requested: dict[tuple[int, int], str] = {
            (x, y): c for x, y, c in coords
        }

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
        final_saved   = load_saved_coords(OUTPUT_FILE)
        truly_missing = set(requested.keys()) - final_saved
        print(f"\n{'='*55}")
        print(f"  Requested coords : {len(requested):,}")
        print(f"  Rows in CSV      : {len(final_saved):,}")
        if truly_missing:
            print(f"  Still missing    : {len(truly_missing):,}  "
                  "(API returned no content — normal for unsold/blank pixels)")
        else:
            print(f"  All requested coords accounted for.")
        print(f"  Output file      : {OUTPUT_FILE}")
        print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
