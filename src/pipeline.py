import os
import sys
import argparse
import pandas as pd
from typing import List, Optional
from datetime import datetime, timezone

# Ensure stdout and stderr handle unicode safely on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .models import SamsungProduct
from .db import SamsungDB
from .alerts import PriceAlertEngine
from .api_client import SamsungApiClient
from .scraper import init_webdriver, scrape_category_deep, scrape_catalog_page_variants

CATEGORY_CONFIGS = {
    "Smartphones": {
        "url": "https://www.samsung.com/ca/smartphones/all-smartphones/",
        "folder": os.path.join("scraped_data", "Smartphones"),
        "filename": "samsung_smartphones.csv",
        "display_name": "Smartphones"
    },
    "Tablets": {
        "url": "https://www.samsung.com/ca/tablets/all-tablets/",
        "folder": os.path.join("scraped_data", "Tablets"),
        "filename": "samsung_tablets.csv",
        "display_name": "Tablets"
    },
    "Watches": {
        "url": "https://www.samsung.com/ca/watches/all-watches/",
        "folder": os.path.join("scraped_data", "Watches"),
        "filename": "samsung_watches.csv",
        "display_name": "Watches"
    },
    "Audio_and_Buds": {
        "url": "https://www.samsung.com/ca/audio-sound/all-audio-sound/",
        "folder": os.path.join("scraped_data", "Audio_and_Buds"),
        "filename": "samsung_audio_and_buds.csv",
        "display_name": "Audio & Buds"
    },
    "TVs": {
        "url": "https://www.samsung.com/ca/tvs/all-tvs/",
        "folder": os.path.join("scraped_data", "TVs"),
        "filename": "samsung_tvs.csv",
        "display_name": "TVs"
    },
    "Sound_Devices": {
        "url": "https://www.samsung.com/ca/audio-devices/all-audio-devices/",
        "folder": os.path.join("scraped_data", "Sound_Devices"),
        "filename": "samsung_sound_devices.csv",
        "display_name": "Sound Devices"
    },
    "Refrigerators": {
        "url": "https://www.samsung.com/ca/refrigerators/all-refrigerators/",
        "folder": os.path.join("scraped_data", "Refrigerators"),
        "filename": "samsung_refrigerators.csv",
        "display_name": "Refrigerators"
    },
    "Laundry": {
        "url": "https://www.samsung.com/ca/laundry/all-laundry/",
        "folder": os.path.join("scraped_data", "Laundry"),
        "filename": "samsung_laundry.csv",
        "display_name": "Laundry"
    },
    "Cooking_Appliances": {
        "url": "https://www.samsung.com/ca/cooking-appliances/all-cooking-appliances/",
        "folder": os.path.join("scraped_data", "Cooking_Appliances"),
        "filename": "samsung_cooking_appliances.csv",
        "display_name": "Cooking Appliances"
    },
    "Monitors": {
        "url": "https://www.samsung.com/ca/monitors/all-monitors/",
        "folder": os.path.join("scraped_data", "Monitors"),
        "filename": "samsung_monitors.csv",
        "display_name": "Monitors"
    },
    "Computers": {
        "url": "https://www.samsung.com/ca/computers/all-computers/",
        "folder": os.path.join("scraped_data", "Computers"),
        "filename": "samsung_computers.csv",
        "display_name": "Computers"
    }
}

CATEGORIES_MAP = {k: v["url"] for k, v in CATEGORY_CONFIGS.items()}

CATEGORY_DATASETS = [
    (k, os.path.join(v["folder"], v["filename"]), v["display_name"])
    for k, v in CATEGORY_CONFIGS.items()
]


class SamsungPipeline:
    def __init__(self, db: Optional[SamsungDB] = None):
        self.db = db or SamsungDB()
        self.alert_engine = PriceAlertEngine(self.db)
        self.api_client = SamsungApiClient()

    def seed_all_data(self, project_root: str, reset: bool = True):
        """Seeds SQLite database from all latest scraped category CSVs in scraped_data/."""
        if reset:
            print("[Pipeline] Resetting database tables for fresh, clean ingestion...")
            self.db.clear_database()

        print("[Pipeline] Seeding SQLite database from all 11 category CSV datasets...")
        total_seeded = 0

        for raw_cat, rel_path, display_name in CATEGORY_DATASETS:
            csv_path = os.path.join(project_root, rel_path)
            if os.path.exists(csv_path):
                n = self.db.import_legacy_csv(csv_path, display_name)
                print(f"  • Seeded {n} {display_name} products from {rel_path}")
                total_seeded += n
            else:
                print(f"  ⚠️ Warning: CSV not found at {rel_path}")

        print(f"[Pipeline] Database seeding complete! Total: {total_seeded} products stored across all categories.\n")
        return total_seeded

    def seed_legacy_data(self, project_root: str, reset: bool = True):
        """Backward-compatible alias for seed_all_data."""
        return self.seed_all_data(project_root, reset=reset)

    def scrape_and_update_all(
        self,
        project_root: str,
        max_cards: Optional[int] = None,
        headless: bool = True,
        categories: Optional[List[str]] = None
    ) -> int:
        """
        Executes automated scraping across product categories,
        updates individual CSV files in scraped_data/, and ingests
        records into the SQLite database with timestamped snapshots.
        """
        print("\n" + "=" * 70)
        print("SAMSUNG E-COMMERCE SCHEDULED SCRAPING & DATABASE UPDATE PIPELINE")
        print(f"Timestamp:  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Headless:   {headless}")
        print(f"Max Cards:  {max_cards if max_cards else 'All available'}")
        print("=" * 70)

        target_cats = categories or list(CATEGORY_CONFIGS.keys())
        driver = init_webdriver(headless=headless)
        total_scraped = 0

        try:
            for cat_key in target_cats:
                if cat_key not in CATEGORY_CONFIGS:
                    print(f"[!] Warning: Unknown category '{cat_key}', skipping.")
                    continue

                cfg = CATEGORY_CONFIGS[cat_key]
                cat_url = cfg["url"]
                display_name = cfg["display_name"]
                csv_rel_path = os.path.join(cfg["folder"], cfg["filename"])
                full_csv_path = os.path.join(project_root, csv_rel_path)

                print(f"\n--> Starting scraping for: {display_name}")
                print(f"  URL:         {cat_url}")
                print(f"  Destination: {full_csv_path}")

                try:
                    prods = scrape_catalog_page_variants(
                        driver,
                        category_name=display_name,
                        category_url=cat_url,
                        max_cards=max_cards
                    )

                    if prods:
                        # 1. Update CSV file
                        csv_rows = []
                        for p in prods:
                            csv_rows.append({
                                'Model Name': p.name,
                                'Color': p.color,
                                'Storage': p.storage,
                                'SKU Code': p.sku,
                                'Product Price': p.price_formatted,
                                'Original Price': p.original_price_formatted,
                                'Financing Option': p.financing_option,
                                'Badge': p.badge,
                                'Offers': p.offers,
                                'Product Rating': p.rating if p.rating is not None else 'Not Rated',
                                'Number of Ratings': p.rating_count,
                                'Stock Status': p.availability,
                                'Product URL': p.product_url
                            })

                        df_cat = pd.DataFrame(csv_rows)
                        os.makedirs(os.path.dirname(full_csv_path), exist_ok=True)
                        df_cat.to_csv(full_csv_path, index=False, encoding='utf-8-sig')
                        print(f"  [OK] Saved {len(df_cat)} records to CSV: {csv_rel_path}")

                        # 2. Persist into SQLite DB
                        self.db.save_products(prods)
                        print(f"  [OK] Ingested {len(prods)} products & price snapshots into SQLite DB")
                        total_scraped += len(prods)
                    else:
                        print(f"  [!] No products returned for {display_name}")

                except Exception as cat_err:
                    print(f"  [ERROR] Error scraping {display_name}: {cat_err}")
                    continue

        finally:
            try:
                driver.quit()
            except Exception:
                pass

        print("\n" + "=" * 70)
        print(f"SCRAPING COMPLETE: Total {total_scraped} product variants processed & updated in DB.")
        print("=" * 70 + "\n")

        # Run alert checks after fresh ingestion
        self.run_alerts()
        return total_scraped

    def simulate_price_drop_snapshot(self, sku: str, discount_pct: float = 20.0):
        """
        Helper for testing: Inserts a lower price snapshot for a SKU to demonstrate
        the price drop alert system in action.
        """
        df = self.db.get_latest_products_df()
        matches = df[df["sku"] == sku]
        if matches.empty:
            matches = df[df["current_price"].notna()]
            if matches.empty:
                print("No products found to simulate price drop.")
                return
            sku = matches.iloc[0]["sku"]

        row = df[df["sku"] == sku].iloc[0]
        curr_price = float(row["current_price"])
        new_price = round(curr_price * (1.0 - (discount_pct / 100.0)), 2)
        orig_price = row.get("original_price") or curr_price

        new_prod = SamsungProduct(
            sku=sku,
            name=row["name"],
            category=row["category"],
            current_price=new_price,
            original_price=orig_price,
            price_formatted=f"${new_price:,.2f}",
            original_price_formatted=f"${orig_price:,.2f}",
            financing_option=row.get("financing_option", "Not Applicable"),
            rating=row.get("rating"),
            rating_count=int(row.get("rating_count", 0)),
            availability="In Stock",
            product_url=row.get("product_url", ""),
            scraped_at=datetime.now(timezone.utc).isoformat()
        )
        self.db.record_price_snapshot(new_prod)
        print(f"[Pipeline] Simulated price drop for {row['name']} ({sku}): ${curr_price:,.2f} -> ${new_price:,.2f} (-{discount_pct}%)")

    def run_alerts(self):
        """Runs the price drop & all-time low alert engine."""
        print("[Pipeline] Running Price & Deal Alert Engine...")
        alerts = self.alert_engine.check_alerts()
        drops = alerts["price_drops"]
        lows = alerts["all_time_lows"]
        discounts = alerts["steep_discounts"]

        print(f"  • Price Drops Detected: {len(drops)}")
        print(f"  • All-Time Lows:        {len(lows)}")
        print(f"  • Steep Discounts:      {len(discounts)}")
        return alerts


def main():
    parser = argparse.ArgumentParser(description="Samsung Scraping, Price Tracking & Alert Pipeline")
    parser.add_argument("--scrape-all", action="store_true", help="Scrape all categories, update CSVs and SQLite DB")
    parser.add_argument("--categories", nargs="+", default=None, help="Specific categories to scrape (e.g. TVs Smartphones)")
    parser.add_argument("--max-cards", type=int, default=None, help="Max cards per category (useful for quick dry runs)")
    parser.add_argument("--no-headless", action="store_true", help="Run browser with visible UI instead of headless")
    parser.add_argument("--seed", action="store_true", help="Seed database from existing project CSVs")
    parser.add_argument("--alerts", action="store_true", help="Check and generate price drop alerts")
    parser.add_argument("--simulate-drop", type=str, default="", help="Simulate a price drop on a SKU to test alerts")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pipeline = SamsungPipeline()

    if args.seed:
        pipeline.seed_legacy_data(project_root)

    if args.scrape_all:
        pipeline.scrape_and_update_all(
            project_root=project_root,
            max_cards=args.max_cards,
            headless=not args.no_headless,
            categories=args.categories
        )

    if args.simulate_drop:
        pipeline.simulate_price_drop_snapshot(args.simulate_drop)

    if args.alerts and not args.scrape_all:
        pipeline.run_alerts()


if __name__ == "__main__":
    main()
