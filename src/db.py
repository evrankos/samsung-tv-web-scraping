import os
import json
import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import pandas as pd

from .models import SamsungProduct, parse_price, parse_rating, parse_rating_count

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "samsung_tracker.db")


class SamsungDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        """Initializes tables and indexes if they do not exist."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                
                # Products Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        sku TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        product_url TEXT,
                        image_url TEXT,
                        specs_json TEXT,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                """)

                # Price History Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS price_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sku TEXT NOT NULL,
                        current_price REAL,
                        original_price REAL,
                        discount_amount REAL,
                        discount_percentage REAL,
                        price_formatted TEXT,
                        original_price_formatted TEXT,
                        financing_option TEXT,
                        rating REAL,
                        rating_count INTEGER,
                        availability TEXT,
                        scraped_at TIMESTAMP NOT NULL,
                        FOREIGN KEY (sku) REFERENCES products(sku)
                    )
                """)

                # Indexes for high performance querying
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_sku ON price_history(sku)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_scraped_at ON price_history(scraped_at)")
        finally:
            conn.close()

    def clear_database(self):
        """Clears all records from products and price_history tables for clean re-sync."""
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM price_history")
                cursor.execute("DELETE FROM products")
        finally:
            conn.close()

    def upsert_product(self, product: SamsungProduct, conn: Optional[sqlite3.Connection] = None):
        """Inserts or updates the master product entry."""
        close_conn = False
        if conn is None:
            conn = self.get_connection()
            close_conn = True

        try:
            cursor = conn.cursor()
            specs_json = json.dumps(product.specs)
            now = datetime.now(timezone.utc).isoformat()
            
            cursor.execute("""
                INSERT INTO products (sku, name, category, product_url, image_url, specs_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    product_url = excluded.product_url,
                    image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE products.image_url END,
                    specs_json = excluded.specs_json,
                    updated_at = excluded.updated_at
            """, (
                product.sku,
                product.name,
                product.category,
                product.product_url,
                product.image_url,
                specs_json,
                now,
                now
            ))
            if close_conn:
                conn.commit()
        finally:
            if close_conn:
                conn.close()

    def record_price_snapshot(self, product: SamsungProduct, conn: Optional[sqlite3.Connection] = None):
        """Records a timestamped price and stock snapshot."""
        close_conn = False
        if conn is None:
            conn = self.get_connection()
            close_conn = True

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO price_history (
                    sku, current_price, original_price, discount_amount, discount_percentage,
                    price_formatted, original_price_formatted, financing_option,
                    rating, rating_count, availability, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product.sku,
                product.current_price,
                product.original_price,
                product.discount_amount,
                product.discount_percentage,
                product.price_formatted,
                product.original_price_formatted,
                product.financing_option,
                product.rating,
                product.rating_count,
                product.availability,
                product.scraped_at
            ))
            if close_conn:
                conn.commit()
        finally:
            if close_conn:
                conn.close()

    def save_products(self, products: List[SamsungProduct]):
        """Batch saves a list of SamsungProduct objects."""
        if not products:
            return
        conn = self.get_connection()
        try:
            with conn:
                for p in products:
                    self.upsert_product(p, conn=conn)
                    self.record_price_snapshot(p, conn=conn)
        finally:
            conn.close()

    def get_latest_products_df(self) -> pd.DataFrame:
        """Retrieves the latest snapshot of each product joined with its metadata."""
        query = """
            SELECT 
                p.sku,
                p.name,
                p.category,
                p.product_url,
                p.image_url,
                p.specs_json,
                h.current_price,
                h.original_price,
                h.discount_amount,
                h.discount_percentage,
                h.price_formatted,
                h.original_price_formatted,
                h.financing_option,
                h.rating,
                h.rating_count,
                h.availability,
                h.scraped_at
            FROM products p
            INNER JOIN price_history h ON p.sku = h.sku
            WHERE h.id IN (
                SELECT MAX(id) FROM price_history GROUP BY sku
            )
            ORDER BY p.category, p.name
        """
        conn = self.get_connection()
        try:
            df = pd.read_sql_query(query, conn)
        finally:
            conn.close()
            
        # Parse specs_json columns into pandas columns
        if not df.empty and "specs_json" in df.columns:
            specs_list = []
            for item in df["specs_json"]:
                try:
                    specs_list.append(json.loads(item) if item else {})
                except Exception:
                    specs_list.append({})
            specs_df = pd.DataFrame(specs_list)
            for col in specs_df.columns:
                if col not in df.columns:
                    df[col] = specs_df[col]
        return df

    def get_price_history_df(self, sku: str) -> pd.DataFrame:
        """Retrieves the full chronological price history for a given SKU."""
        query = """
            SELECT 
                scraped_at,
                current_price,
                original_price,
                discount_amount,
                discount_percentage,
                rating,
                rating_count
            FROM price_history
            WHERE sku = ?
            ORDER BY scraped_at ASC
        """
        conn = self.get_connection()
        try:
            return pd.read_sql_query(query, conn, params=(sku,))
        finally:
            conn.close()

    def get_all_price_history_df(self) -> pd.DataFrame:
        """Returns entire price history table joined with product info."""
        query = """
            SELECT 
                p.sku,
                p.name,
                p.category,
                h.current_price,
                h.original_price,
                h.discount_amount,
                h.discount_percentage,
                h.rating,
                h.rating_count,
                h.scraped_at
            FROM price_history h
            JOIN products p ON h.sku = p.sku
            ORDER BY h.scraped_at ASC
        """
        conn = self.get_connection()
        try:
            return pd.read_sql_query(query, conn)
        finally:
            conn.close()

    def import_legacy_csv(self, csv_path: str, category_name: str) -> int:
        """Imports historical records from existing project CSVs into the SQLite DB."""
        if not os.path.exists(csv_path):
            return 0
        df = pd.read_csv(csv_path)
        count = 0
        products = []
        
        # Standardize column names
        cols = {c.strip(): c for c in df.columns}
        name_col = cols.get("Product Name", cols.get("Model Name", cols.get("name", "Product Name")))
        price_col = cols.get("Product Price", cols.get("Current Price", cols.get("price", "Product Price")))
        orig_price_col = cols.get("Original Price", cols.get("Was Price", cols.get("orig_price", None)))
        fin_col = cols.get("Financing Option", cols.get("financing", "Financing Option"))
        rating_col = cols.get("Product Rating", cols.get("rating", "Product Rating"))
        count_col = cols.get("Number of Ratings", cols.get("ratings_count", "Number of Ratings"))
        sku_col = cols.get("SKU Code", cols.get("sku", "SKU Code"))
        url_col = cols.get("Product URL", cols.get("url", "Product URL"))
        color_col = cols.get("Color", cols.get("color", None))
        storage_col = cols.get("Storage", cols.get("storage", None))
        badge_col = cols.get("Badge", cols.get("badge", cols.get("Tag", None)))
        offers_col = cols.get("Offers", cols.get("offers", None))
        stock_col = cols.get("Stock Status", cols.get("availability", None))

        for _, row in df.iterrows():
            name = str(row.get(name_col, "Unknown Product")).strip()
            if not name or name == "nan" or name == "Error":
                continue
            
            raw_sku = str(row.get(sku_col, "")).strip()
            if not raw_sku or raw_sku in ["nan", "Not Available", "N/A"]:
                # Generate synthetic SKU from name slug if missing
                raw_sku = f"GEN-{abs(hash(name)) % (10 ** 8)}"

            price_val = parse_price(row.get(price_col))
            price_str = str(row.get(price_col, "Not Available"))
            
            orig_price_val = parse_price(row.get(orig_price_col)) if orig_price_col else None
            orig_price_str = str(row.get(orig_price_col, "Not Available")) if orig_price_col else "Not Available"
            
            fin_str = str(row.get(fin_col, "Not Applicable"))
            rating_val = parse_rating(row.get(rating_col))
            rcount_val = parse_rating_count(row.get(count_col))
            url_str = str(row.get(url_col, ""))
            color_str = str(row.get(color_col, "Default")) if color_col else "Default"
            storage_str = str(row.get(storage_col, "Default")) if storage_col else "Default"
            badge_str = str(row.get(badge_col, "None")) if badge_col else "None"
            offers_str = str(row.get(offers_col, "None")) if offers_col else "None"
            stock_str = str(row.get(stock_col, "In Stock")) if stock_col else "In Stock"

            # Handle unpriced / retail partner products accurately
            if price_val is None or price_val <= 0:
                if stock_str in ["In Stock", "Default", "nan", ""]:
                    stock_str = "Where to Buy (Dealer Only)"
                price_str = "Where to Buy"
                orig_price_str = "—"
            elif orig_price_val is None and price_val and price_val > 0:
                orig_price_val = price_val

            prod = SamsungProduct(
                sku=raw_sku,
                name=name,
                category=category_name,
                color=color_str,
                storage=storage_str,
                current_price=price_val,
                original_price=orig_price_val,
                price_formatted=price_str,
                original_price_formatted=orig_price_str,
                financing_option=fin_str,
                badge=badge_str,
                offers=offers_str,
                rating=rating_val,
                rating_count=rcount_val,
                availability=stock_str,
                product_url=url_str
            )
            products.append(prod)

        self.save_products(products)
        return len(products)
