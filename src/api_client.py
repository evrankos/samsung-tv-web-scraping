import json
import re
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from .models import (
    SamsungProduct,
    parse_price,
    parse_rating,
    parse_rating_count,
    extract_screen_size,
    extract_storage_gb
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.samsung.com/ca/",
}


class SamsungApiClient:
    """
    Rapid ingestion client for Samsung products.
    Uses direct HTTP requests, Schema.org JSON-LD parsing, internal search APIs,
    and meta tags without requiring a heavyweight headless browser.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_product_from_url(self, url: str, category: str = "General") -> Optional[SamsungProduct]:
        """
        Extracts product details from a direct Samsung product page using
        Schema.org JSON-LD, meta tags, and structured HTML elements.
        """
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            return self.parse_product_page(soup, url, category)
        except Exception as e:
            print(f"Error fetching product from {url}: {e}")
            return None

    def parse_product_page(self, soup: BeautifulSoup, url: str, category: str) -> SamsungProduct:
        """Parses a Samsung page soup for rich specs, pricing, and ratings."""
        # 1. Try to extract Schema.org JSON-LD
        json_ld_data = self._extract_json_ld(soup)
        
        # 2. Extract Product Name
        name = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content") and "Samsung" in og_title.get("content"):
            name = og_title["content"].replace(" | Samsung Canada", "").replace(" | Samsung CA", "").strip()

        if not name or "Explore" in name:
            if json_ld_data.get("name") and "Explore" not in json_ld_data["name"]:
                name = json_ld_data["name"]
            else:
                h1 = soup.find("h1")
                if h1 and "Explore" not in h1.get_text():
                    name = h1.get_text(strip=True)

        if not name or "Explore" in name:
            # Fallback to URL slug
            slug_match = re.search(r'/([^/]+)/?$', url.rstrip('/'))
            if slug_match:
                name = slug_match.group(1).replace("-", " ").title()
            else:
                name = "Samsung Product"

        # 3. Extract SKU
        sku = json_ld_data.get("sku") or ""
        if not sku:
            meta_sku = soup.find("meta", property="product:retailer_item_id")
            if meta_sku and meta_sku.get("content"):
                sku = meta_sku["content"].strip().upper()
            else:
                sku_tag = soup.find(class_=lambda c: c and any(k in c.lower() for k in ['pd-info__sku-code', 'nav__info-sku', 'navigation__sku', 'option-title__sku']))
                if sku_tag and sku_tag.get_text(strip=True):
                    sku = sku_tag.get_text(strip=True).upper()
                
                if not sku:
                    # Look for model codes in URL (e.g. qn55s90cafxzc or sm-s928wzkaxac)
                    match = re.search(r'[-/]([a-zA-Z0-9]{6,}(?:-[a-zA-Z0-9]+)?)/?$', url)
                    if match:
                        sku = match.group(1).upper()
                    else:
                        sku = f"SAMS-{abs(hash(url)) % 10000000}"

        # 4. Extract Pricing (Current & Original / Discount)
        current_price = None
        orig_price = None
        price_str = "Not Available"
        orig_price_str = "Not Available"

        # Check JSON-LD offers
        offers = json_ld_data.get("offers", {})
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict) and "price" in offers:
            current_price = parse_price(offers.get("price"))

        # Check OpenGraph / Meta price tags
        if current_price is None:
            og_price = soup.find("meta", property="og:price:amount") or soup.find("meta", property="product:price:amount")
            if og_price and og_price.get("content"):
                current_price = parse_price(og_price["content"])

        # Check DOM price elements
        if current_price is None:
            curr_elem = (
                soup.find(class_=re.compile(r'pd-buying-price__new-price|final-price|cost-price')) or
                soup.find("span", class_="pd-buying-price__new-price-currency")
            )
            if curr_elem:
                current_price = parse_price(curr_elem.get_text(strip=True))

        if current_price:
            price_str = f"${current_price:,.2f}"

        # Look for Original Price / Was Price
        was_elem = soup.find(class_=re.compile(r'origin-price|old-price|was-price|before-discount|regular-price'))
        if was_elem:
            orig_price = parse_price(was_elem.get_text(strip=True))
            if orig_price:
                orig_price_str = f"${orig_price:,.2f}"
        
        # Check for promo text (e.g. "Save $200")
        save_match = re.search(r'Save\s+\$?([0-9,]+(?:\.[0-9]{2})?)', soup.text, re.IGNORECASE)
        if save_match and current_price:
            savings = parse_price(save_match.group(1))
            if savings and savings > 0 and (orig_price is None or orig_price <= current_price):
                orig_price = round(current_price + savings, 2)
                orig_price_str = f"${orig_price:,.2f}"

        # 5. Financing Option
        fin_text = "Not Applicable"
        mo_match = re.search(r'((?:From\s+)?\$\d+(?:\.\d{2})?/mo(?:\s+for\s+\d+\s+mos)?)', soup.text)
        if mo_match:
            fin_text = mo_match.group(1).strip()

        # 6. Rating & Review Count
        rating = None
        rating_count = 0
        agg_rating = json_ld_data.get("aggregateRating", {})
        if isinstance(agg_rating, dict):
            rating = parse_rating(agg_rating.get("ratingValue"))
            rating_count = parse_rating_count(agg_rating.get("reviewCount") or agg_rating.get("ratingCount"))

        if rating is None:
            rating_elem = soup.find(class_=re.compile(r'rating__point|info-rating|buying-price__rating'))
            if rating_elem:
                rating = parse_rating(rating_elem.get_text(strip=True))

        if rating_count == 0:
            count_elem = soup.find(class_=re.compile(r'review-count|numRatings'))
            if count_elem:
                rating_count = parse_rating_count(count_elem.get_text(strip=True))

        # 7. Image URL
        image_url = ""
        if json_ld_data.get("image"):
            img = json_ld_data["image"]
            image_url = img[0] if isinstance(img, list) else str(img)
        else:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                image_url = og_img["content"]

        # 8. Detailed Technical Specs
        specs = self._extract_specs(soup, name, category)

        return SamsungProduct(
            sku=sku,
            name=name,
            category=category,
            current_price=current_price,
            original_price=orig_price,
            price_formatted=price_str,
            original_price_formatted=orig_price_str,
            financing_option=fin_text,
            rating=rating,
            rating_count=rating_count,
            availability="In Stock",
            product_url=url,
            image_url=image_url,
            specs=specs
        )

    def _extract_json_ld(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Finds and parses Schema.org Product JSON-LD."""
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            try:
                data = json.loads(s.string or "{}")
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif isinstance(data, dict):
                    if data.get("@type") == "Product":
                        return data
                    if "@graph" in data:
                        for item in data["@graph"]:
                            if item.get("@type") == "Product":
                                return item
            except Exception:
                continue
        return {}

    def _extract_specs(self, soup: BeautifulSoup, name: str, category: str) -> Dict[str, Any]:
        """Extracts category-specific technical specifications."""
        specs: Dict[str, Any] = {}

        # Screen Size for Displays / TVs / Monitors / Phones
        screen_size = extract_screen_size(name)
        if screen_size:
            specs["screen_size_inch"] = screen_size

        # Storage capacity for Phones / Tablets / Laptops
        storage = extract_storage_gb(name)
        if storage:
            specs["storage_gb"] = storage

        # Display technology detection
        text_lower = (name + " " + soup.text[:2000]).lower()
        if "neo qled" in text_lower:
            specs["display_tech"] = "Neo QLED"
        elif "oled" in text_lower:
            specs["display_tech"] = "OLED"
        elif "qled" in text_lower:
            specs["display_tech"] = "QLED"
        elif "crystal uhd" in text_lower:
            specs["display_tech"] = "Crystal UHD"
        elif "amoled" in text_lower:
            specs["display_tech"] = "Dynamic AMOLED 2X"

        # Resolution detection
        if "8k" in text_lower:
            specs["resolution"] = "8K (7680 x 4320)"
        elif "4k" in text_lower or "uhd" in text_lower:
            specs["resolution"] = "4K UHD (3840 x 2160)"
        elif "fhd" in text_lower or "1080p" in text_lower:
            specs["resolution"] = "Full HD (1920 x 1080)"

        # Refresh Rate
        hz_match = re.search(r'\b(60|120|144|165|240)\s*Hz\b', soup.text, re.IGNORECASE)
        if hz_match:
            specs["refresh_rate"] = f"{hz_match.group(1)}Hz"

        # Energy Star / Color
        color_match = re.search(r'\b(Titanium Black|Titanium Gray|Titanium Yellow|Titanium Violet|Onyx Black|Marble Gray|Cobalt Violet|Amber Yellow|Phantom Black|Graphite|Silver|White|Cream|Lavender|Mint)\b', name, re.IGNORECASE)
        if color_match:
            specs["color"] = color_match.group(1).title()

        return specs
