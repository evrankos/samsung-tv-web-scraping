import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import pandas as pd
from .db import SamsungDB


class PriceAlertEngine:
    def __init__(self, db: SamsungDB, discount_threshold: float = 15.0):
        self.db = db
        self.discount_threshold = discount_threshold
        self.alerts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alerts")
        os.makedirs(self.alerts_dir, exist_ok=True)

    def check_alerts(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Analyzes recent price history to find:
        1. Price Drops: products whose current price is lower than the previous recorded price.
        2. All-Time Lows: products currently at their lowest recorded price in the database.
        3. Steep Discounts: products with discount percentage >= discount_threshold.
        """
        history_df = self.db.get_all_price_history_df()
        if history_df.empty:
            return {"price_drops": [], "all_time_lows": [], "steep_discounts": []}

        price_drops = []
        all_time_lows = []
        steep_discounts = []

        grouped = history_df.groupby("sku")

        for sku, group in grouped:
            if len(group) == 0:
                continue
            
            # Sort chronologically
            sorted_group = group.sort_values("scraped_at")
            latest = sorted_group.iloc[-1]
            
            curr_price = latest.get("current_price")
            if curr_price is None or pd.isna(curr_price) or curr_price <= 0:
                continue

            name = latest.get("name", sku)
            cat = latest.get("category", "General")
            orig_price = latest.get("original_price")
            disc_pct = latest.get("discount_percentage", 0.0) or 0.0

            # 1. Check for Price Drop compared to previous snapshot
            if len(sorted_group) > 1:
                prev = sorted_group.iloc[-2]
                prev_price = prev.get("current_price")
                if prev_price and not pd.isna(prev_price) and curr_price < prev_price:
                    diff = round(prev_price - curr_price, 2)
                    drop_pct = round((diff / prev_price) * 100, 1)
                    price_drops.append({
                        "sku": sku,
                        "name": name,
                        "category": cat,
                        "old_price": prev_price,
                        "new_price": curr_price,
                        "drop_amount": diff,
                        "drop_percentage": drop_pct,
                        "timestamp": latest.get("scraped_at")
                    })

            # 2. Check for All-Time Low
            min_historic = sorted_group["current_price"].dropna().min()
            if curr_price <= min_historic and len(sorted_group) > 1:
                all_time_lows.append({
                    "sku": sku,
                    "name": name,
                    "category": cat,
                    "price": curr_price,
                    "timestamp": latest.get("scraped_at")
                })

            # 3. Check for Steep Discount (>= discount_threshold %)
            if disc_pct >= self.discount_threshold:
                savings = latest.get("discount_amount", 0.0) or 0.0
                steep_discounts.append({
                    "sku": sku,
                    "name": name,
                    "category": cat,
                    "current_price": curr_price,
                    "original_price": orig_price,
                    "discount_amount": savings,
                    "discount_percentage": disc_pct,
                    "timestamp": latest.get("scraped_at")
                })

        # Save alert log report
        self._save_alert_log(price_drops, all_time_lows, steep_discounts)

        return {
            "price_drops": price_drops,
            "all_time_lows": all_time_lows,
            "steep_discounts": steep_discounts
        }

    def _save_alert_log(self, drops: List[Dict], lows: List[Dict], discounts: List[Dict]):
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_path = os.path.join(self.alerts_dir, f"price_alerts_{today_str}.txt")
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write(f"SAMSUNG PRODUCT PRICE INTELLIGENCE REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")

            f.write(f"1. PRICE DROPS DETECTED: {len(drops)}\n")
            f.write("-" * 50 + "\n")
            for d in drops:
                f.write(f" • [{d['category']}] {d['name']} ({d['sku']})\n")
                f.write(f"   Dropped from ${d['old_price']:,.2f} -> ${d['new_price']:,.2f} (-${d['drop_amount']:,.2f} | -{d['drop_percentage']}%)\n")
            f.write("\n")

            f.write(f"2. ALL-TIME LOW PRICES: {len(lows)}\n")
            f.write("-" * 50 + "\n")
            for l in lows:
                f.write(f" • [{l['category']}] {l['name']} is at an ALL-TIME LOW: ${l['price']:,.2f}\n")
            f.write("\n")

            f.write(f"3. STEEP DISCOUNTS (>= {self.discount_threshold}% OFF): {len(discounts)}\n")
            f.write("-" * 50 + "\n")
            for dc in discounts:
                f.write(f" • [{dc['category']}] {dc['name']}: ${dc['current_price']:,.2f} (Was ${dc['original_price']:,.2f} | Save ${dc['discount_amount']:,.2f} / {dc['discount_percentage']}%)\n")
            f.write("\n" + "=" * 70 + "\n")
