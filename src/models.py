import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def parse_price(price_str: Any) -> Optional[float]:
    """Parses a price string like '$1,499.99' or '1499.99' into a float."""
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)
    
    clean = str(price_str).replace(",", "").strip()
    match = re.search(r'\$?([0-9]+\.?[0-9]*)', clean)
    if match:
        try:
            return round(float(match.group(1)), 2)
        except ValueError:
            return None
    return None


def parse_rating(rating_val: Any) -> Optional[float]:
    """Parses rating values into float between 0 and 5."""
    if rating_val is None:
        return None
    if isinstance(rating_val, (int, float)):
        return float(rating_val)
    match = re.search(r'([0-5](?:\.\d+)?)', str(rating_val))
    if match:
        try:
            val = float(match.group(1))
            return val if 0.0 <= val <= 5.0 else None
        except ValueError:
            return None
    return None


def parse_rating_count(count_val: Any) -> int:
    """Parses review count into integer, correctly extracting exact count from title strings like '4.8, (37185), ...'."""
    if not count_val:
        return 0
    clean = str(count_val).replace(",", "").strip()
    paren_match = re.search(r'\((\d+)\)', clean)
    if paren_match:
        try:
            return int(paren_match.group(1))
        except ValueError:
            pass
    match = re.search(r'([0-9]+)', clean)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0


def extract_screen_size(name: str, specs: Optional[Dict[str, Any]] = None, sku: Optional[str] = None, storage: Optional[str] = None) -> Optional[float]:
    """Extracts screen size in inches from product title, specs, storage, or Samsung model SKU."""
    if specs and "screen_size_inch" in specs and specs["screen_size_inch"]:
        return float(specs["screen_size_inch"])
    
    # 1. Check storage attribute (e.g. '65"', '55"', '32"')
    if storage and storage != "Default":
        m_stor = re.search(r'(\d{2,3}(?:\.\d)?)\s*(?:"|”|\'\'|-inch|inch|in\b)', str(storage), re.IGNORECASE)
        if m_stor:
            try:
                val = float(m_stor.group(1))
                if 20 <= val <= 120:
                    return val
            except ValueError:
                pass

    # 2. Check for patterns like 55", 55-inch, 55” in name
    match = re.search(r'(\d{2,3}(?:\.\d)?)\s*(?:"|”|\'\'|-inch|inch|in\b)', name, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1))
            if 20 <= val <= 120:
                return val
        except ValueError:
            pass

    # 3. Check Samsung standard model SKU prefix (e.g. QN55S90C -> 55, UN43CU7000 -> 43, QN75LS03 -> 75)
    if sku:
        sku_match = re.search(r'^[A-Za-z]{2}(\d{2})[A-Za-z0-9]', sku)
        if sku_match:
            try:
                val = float(sku_match.group(1))
                if 24 <= val <= 115:
                    return val
            except ValueError:
                pass
    return None



def extract_storage_gb(name: str, specs: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Extracts storage capacity in GB from product title or specs."""
    if specs and "storage_gb" in specs and specs["storage_gb"]:
        return int(specs["storage_gb"])
    
    tb_match = re.search(r'(\d+)\s*TB\b', name, re.IGNORECASE)
    if tb_match:
        return int(tb_match.group(1)) * 1024
        
    gb_match = re.search(r'(\d{2,4})\s*GB\b', name, re.IGNORECASE)
    if gb_match:
        return int(gb_match.group(1))
    return None


@dataclass
class SamsungProduct:
    sku: str
    name: str
    category: str
    color: str = "Default"
    storage: str = "Default"
    current_price: Optional[float] = None
    original_price: Optional[float] = None
    discount_amount: Optional[float] = None
    discount_percentage: Optional[float] = None
    price_formatted: str = "Not Available"
    original_price_formatted: str = "Not Available"
    financing_option: str = "Not Applicable"
    badge: str = "None"
    offers: str = "None"
    rating: Optional[float] = None
    rating_count: int = 0
    availability: str = "In Stock"
    product_url: str = ""
    image_url: str = ""
    specs: Dict[str, Any] = field(default_factory=dict)
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        # Auto-compute discounts if both prices are present
        if self.current_price is not None and self.original_price is not None:
            if self.original_price > self.current_price:
                self.discount_amount = round(self.original_price - self.current_price, 2)
                self.discount_percentage = round((self.discount_amount / self.original_price) * 100, 1)
            elif self.discount_amount is None:
                self.discount_amount = 0.0
                self.discount_percentage = 0.0
        
        # Populate specs with derived metrics
        if "screen_size_inch" not in self.specs:
            size = extract_screen_size(self.name, self.specs, self.sku, self.storage)
            if size:
                self.specs["screen_size_inch"] = size
                if self.current_price and self.current_price > 0:
                    self.specs["price_per_inch"] = round(self.current_price / size, 2)
                    
        if "storage_gb" not in self.specs:
            storage = extract_storage_gb(self.storage if self.storage != "Default" else self.name, self.specs)
            if storage:
                self.specs["storage_gb"] = storage
                if self.current_price and self.current_price > 0:
                    self.specs["price_per_gb"] = round(self.current_price / storage, 2)

        if self.color and self.color != "Default" and "color" not in self.specs:
            self.specs["color"] = self.color
        if self.storage and self.storage != "Default" and "storage" not in self.specs:
            self.specs["storage"] = self.storage
        if self.badge and self.badge != "None" and "badge" not in self.specs:
            self.specs["badge"] = self.badge
        if self.offers and self.offers != "None" and "offers" not in self.specs:
            self.specs["offers"] = self.offers

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
