"""Build/update stock_names.json from TDX server via pytdx.

Usage: python stock_names_builder.py
Output: dragon_eye/_cache/stock_names.json (all A-share stocks)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from pytdx.hq import TdxHq_API
except ImportError:
    print("[ERROR] pytdx not installed. Run: pip install pytdx")
    sys.exit(1)

TDX_HOSTS = [
    ("119.147.212.81", 7709),
    ("120.76.152.2", 7709),
    ("47.103.48.45", 7709),
    ("124.70.133.119", 7709),
    ("218.108.50.178", 7709),
]


def get_all_stocks() -> dict[str, str]:
    """Connect to TDX and retrieve complete A-share stock code→name map."""
    api = TdxHq_API()
    all_names: dict[str, str] = {}

    for host, port in TDX_HOSTS:
        try:
            api.connect(host, port)
            print(f"  Connected to {host}:{port}")
            break
        except Exception:
            print(f"  Failed {host}:{port}")
            continue
    else:
        print("[ERROR] All TDX hosts failed")
        return {}

    try:
        # SH market (1): 60xxxx, 68xxxx
        print("  Fetching SH stocks (market=1)...")
        cnt = api.get_security_count(1)
        print(f"    Count: {cnt}")
        stocks = api.get_security_list(1, 0)
        if stocks:
            for s in stocks:
                code = s.get("code", "")
                name = s.get("name", "").strip()
                if code and name:
                    all_names[code] = name
        print(f"    Got {len(all_names)} stocks")

        # SZ market (0): 00xxxx, 30xxxx
        print("  Fetching SZ stocks (market=0)...")
        stocks = api.get_security_list(0, 0)
        if stocks:
            sz_total = len(all_names)
            for s in stocks:
                code = s.get("code", "")
                name = s.get("name", "").strip()
                if code and name:
                    all_names[code] = name
            print(f"    Added {len(all_names) - sz_total} SZ stocks")

        # BJ market (2): 83xxxx, 87xxxx, 43xxxx
        try:
            print("  Fetching BJ stocks (market=2)...")
            stocks = api.get_security_list(2, 0)
            if stocks:
                bj_start = len(all_names)
                for s in stocks:
                    code = s.get("code", "")
                    name = s.get("name", "").strip()
                    if code and name:
                        all_names[code] = name
                print(f"    Added {len(all_names) - bj_start} BJ stocks")
        except Exception:
            print("    BJ market skip (may not be supported)")

    finally:
        api.disconnect()

    return all_names


def main():
    cache_dir = os.path.join(os.path.dirname(__file__), "dragon_eye", "_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "stock_names.json")

    # Load existing
    existing: dict[str, str] = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"Existing cache: {len(existing)} stocks")

    # Fetch from TDX
    print("Fetching from TDX servers...")
    t0 = time.time()
    new_names = get_all_stocks()
    elapsed = time.time() - t0

    if not new_names:
        print("[ERROR] No stocks retrieved")
        return 1

    print(f"\nRetrieved: {len(new_names)} stocks in {elapsed:.1f}s")

    # Merge: new data preferred, but keep existing for any missing
    merged = dict(existing)
    merged.update(new_names)

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Saved: {len(merged)} stocks → {cache_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
