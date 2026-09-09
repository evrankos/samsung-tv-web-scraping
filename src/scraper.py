import os
import re
import time
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .models import (
    SamsungProduct,
    parse_price,
    parse_rating,
    parse_rating_count,
    extract_screen_size,
    extract_storage_gb
)


def init_webdriver(headless: bool = True) -> webdriver.Chrome:
    """Initializes and returns an optimized Chrome WebDriver."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--log-level=3")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    # 1. Try built-in Selenium 4 manager
    try:
        return webdriver.Chrome(options=opts)
    except Exception:
        pass

    # 2. Fallback to webdriver-manager
    try:
        driver_path = ChromeDriverManager().install()
        if os.name == "nt" and not driver_path.endswith(".exe"):
            parent = os.path.dirname(driver_path)
            candidate = os.path.join(parent, "chromedriver.exe")
            if os.path.exists(candidate):
                driver_path = candidate
        return webdriver.Chrome(service=Service(driver_path), options=opts)
    except Exception:
        return webdriver.Chrome(options=opts)


def handle_cookie_consent(driver: webdriver.Chrome):
    """Dismisses cookie banners if present."""
    try:
        banner = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID, "truste-consent-track"))
        )
        btn = banner.find_element(By.XPATH, ".//button[contains(text(), 'Accept') or text()='Accept All']")
        btn.click()
        time.sleep(0.5)
    except Exception:
        pass

    try:
        onetrust_btn = driver.find_elements(By.ID, "onetrust-accept-btn-handler")
        if onetrust_btn:
            onetrust_btn[0].click()
            time.sleep(0.5)
    except Exception:
        pass


def click_view_more_if_available(driver: webdriver.Chrome):
    """Clicks 'View More' buttons to load dynamic products."""
    view_more_xpaths = [
        "//button[contains(@class, 'pd21-product-finder__view-more')]",
        "//button[contains(@class, 'js-pfv2-view-more')]",
        "//a[contains(@class, 'js-pfv2-view-more-cta')]",
        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'view more')]"
    ]
    for xpath in view_more_xpaths:
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            for b in buttons:
                if b.is_displayed():
                    driver.execute_script("arguments[0].click();", b)
                    time.sleep(1.5)
        except Exception:
            continue


def scroll_and_load_all_products(driver: webdriver.Chrome, max_scrolls: int = 10, scroll_delay: float = 2.0):
    """Scrolls down the category page and triggers lazy-loaded cards."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    while scroll_count < max_scrolls:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_delay)
        click_view_more_if_available(driver)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scroll_count += 1


def extract_product_urls(soup: BeautifulSoup, base_url: str = "https://www.samsung.com") -> List[str]:
    """Extracts unique product links across pd21, pd03, and general catalog templates."""
    product_links = []
    seen = set()

    cards = soup.find_all(lambda tag: tag.name in ['div', 'li', 'article'] and any(
        cls in tag.get('class', []) for cls in ['pd21-product-card__item', 'pd21-product-card', 'pd03-product-card', 'js-pfv2-product-card']
    ))

    for card in cards:
        link_tag = card.find('a', class_=lambda c: c and any(
            k in c for k in ['pd21-product-card__name', 'pd21-product-card__image-cta', 'pd03-product-card__product-image-link', 'js-pfv2-learn-more']
        )) or card.find('a', href=True)

        if link_tag and link_tag.get('href'):
            href = link_tag['href'].strip()
            if not href.startswith("http"):
                href = base_url + href
            if "/ca/" in href and "#" not in href and href not in seen:
                seen.add(href)
                product_links.append(href)

    if not product_links:
        for a in soup.find_all('a', href=True):
            classes = " ".join(a.get('class', []))
            if any(k in classes for k in ['pd21-product-card__name', 'pd21-product-card__image-cta', 'pd03-product-card__product-image-link']):
                href = a['href'].strip()
                if not href.startswith("http"):
                    href = base_url + href
                if "/ca/" in href and href not in seen:
                    seen.add(href)
                    product_links.append(href)

    return product_links


def extract_detailed_product(driver: webdriver.Chrome, product_url: str, category: str) -> SamsungProduct:
    """Visits a product page and extracts rich specifications, pricing, and discount details."""
    driver.get(product_url)
    time.sleep(1.2)
    handle_cookie_consent(driver)

    # Check if page is a splash/marketing page that redirects to a "Buy Now" CTA
    try:
        buy_btn = driver.find_elements(By.XPATH, "//a[contains(translate(text(), 'BUY NOW', 'buy now'), 'buy now') and @href]")
        if buy_btn and not product_url.endswith("/buy/"):
            buy_href = buy_btn[0].get_attribute("href")
            if buy_href and "/ca/" in buy_href and buy_href != product_url:
                driver.get(buy_href)
                time.sleep(1.2)
    except Exception:
        pass

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # 1. Product Name
    name = "Not Available"
    name_elem = (
        soup.find('h1', class_='pdd39-anchor-nav__headline') or
        soup.find('h1', class_='pd-header-navigation__title') or
        soup.find('h2', class_='pd-info__title') or
        soup.find('h1', class_='option-title') or
        soup.find('h1')
    )
    if name_elem:
        name = name_elem.get_text(strip=True)

    # 2. SKU Code
    sku_code = "Not Available"
    sku_elem = (
        soup.find('span', class_='pd-info__sku-code') or
        soup.find(class_='pdd39-anchor-nav__info-sku') or
        soup.find(class_='pd-header-navigation__sku') or
        soup.find('span', class_='option-title__sku')
    )
    if sku_elem:
        sku_code = sku_elem.get_text(strip=True)
    else:
        match = re.search(r'([A-Z0-9]{5,}(?:-[A-Z0-9]+)?)/?$', driver.current_url)
        if match:
            sku_code = match.group(1).upper()
        else:
            sku_code = f"SAMS-{abs(hash(product_url)) % 10000000}"

    # 3. Current Price
    curr_price = None
    price_elem = (
        soup.find('span', class_='pd-buying-price__new-price-currency') or
        soup.find(class_='pd-buying-price__new-price') or
        soup.find(class_='cost-price') or
        soup.find(class_='pd-buying-price__final-price')
    )
    price_formatted = "Not Available"
    if price_elem:
        curr_price = parse_price(price_elem.get_text(strip=True))
        if curr_price:
            price_formatted = f"${curr_price:,.2f}"

    # 4. Original / Regular Price & Discount
    orig_price = None
    orig_price_formatted = "Not Available"
    was_elem = soup.find(class_=re.compile(r'pd-buying-price__was-price|origin-price|cost-price-save|strike'))
    if was_elem:
        orig_price = parse_price(was_elem.get_text(strip=True))
        if orig_price:
            orig_price_formatted = f"${orig_price:,.2f}"

    # Check for "Save $X" badges
    save_match = re.search(r'Save\s+\$?([0-9,]+(?:\.[0-9]{2})?)', soup.text, re.IGNORECASE)
    if save_match and curr_price:
        savings = parse_price(save_match.group(1))
        if savings and savings > 0 and (orig_price is None or orig_price <= curr_price):
            orig_price = round(curr_price + savings, 2)
            orig_price_formatted = f"${orig_price:,.2f}"

    # 5. Financing Option
    fin_opt = "Not Applicable"
    mo_match = re.search(r'((?:From\s+)?\$\d+(?:\.\d{2})?/mo(?:\\s+for\s+\d+\s+mos)?)', soup.text)
    if mo_match:
        fin_opt = mo_match.group(1).strip()
    else:
        fin_elem = soup.find(class_=re.compile(r'finance-text|pd-buying-price__finance|installment'))
        if fin_elem and fin_elem.get_text(strip=True):
            fin_opt = fin_elem.get_text(strip=True)

    # 6. Rating & Reviews
    rating = None
    rating_count = 0
    rating_elem = (
        soup.find(class_='pdd39-anchor-nav__info-rating') or
        soup.find('strong', class_='rating__point') or
        soup.find(class_='pd-buying-price__rating')
    )
    if rating_elem:
        rating = parse_rating(rating_elem.get_text(strip=True))

    count_elem = soup.find('em', class_='rating__review-count') or soup.find(class_='bv_numRatings_component_container')
    if count_elem:
        rating_count = parse_rating_count(count_elem.get_text(strip=True))

    # 7. Specs Parsing
    specs: Dict[str, Any] = {}
    screen_size = extract_screen_size(name)
    if screen_size:
        specs["screen_size_inch"] = screen_size
    storage = extract_storage_gb(name)
    if storage:
        specs["storage_gb"] = storage

    text_lower = (name + " " + soup.text[:3000]).lower()
    if "neo qled" in text_lower:
        specs["display_tech"] = "Neo QLED"
    elif "oled" in text_lower:
        specs["display_tech"] = "OLED"
    elif "qled" in text_lower:
        specs["display_tech"] = "QLED"
    elif "crystal uhd" in text_lower:
        specs["display_tech"] = "Crystal UHD"

    if "8k" in text_lower:
        specs["resolution"] = "8K"
    elif "4k" in text_lower or "uhd" in text_lower:
        specs["resolution"] = "4K UHD"
    elif "fhd" in text_lower:
        specs["resolution"] = "1080p FHD"

    hz_match = re.search(r'\b(60|120|144|165|240)\s*Hz\b', soup.text, re.IGNORECASE)
    if hz_match:
        specs["refresh_rate"] = f"{hz_match.group(1)}Hz"

    return SamsungProduct(
        sku=sku_code,
        name=name,
        category=category,
        current_price=curr_price,
        original_price=orig_price,
        price_formatted=price_formatted,
        original_price_formatted=orig_price_formatted,
        financing_option=fin_opt,
        rating=rating,
        rating_count=rating_count,
        availability="In Stock",
        product_url=driver.current_url,
        specs=specs
    )


def scrape_category_deep(
    driver: webdriver.Chrome,
    category_name: str,
    category_url: str,
    max_products: Optional[int] = None
) -> List[SamsungProduct]:
    """Navigates category page and extracts rich details for all products."""
    print(f"\n[Scraper] Loading category: {category_name} -> {category_url}")
    driver.get(category_url)
    handle_cookie_consent(driver)
    scroll_and_load_all_products(driver)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    links = extract_product_urls(soup)
    print(f"[Scraper] Discovered {len(links)} products in {category_name}.")

    if max_products:
        links = links[:max_products]

    products = []
    for i, link in enumerate(links, 1):
        print(f"  ({i}/{len(links)}) Extracting: {link}")
        try:
            prod = extract_detailed_product(driver, link, category_name)
            products.append(prod)
        except Exception as e:
            print(f"    Failed on {link}: {e}")

    return products


def scrape_catalog_page_variants(
    driver: webdriver.Chrome,
    category_name: str,
    category_url: str,
    max_cards: Optional[int] = None
) -> List[SamsungProduct]:
    """
    Catalog-only card scraper.
    Extracts all product details and ALL color × storage/size variants directly
    from the category catalog page cards without loading individual product detail pages.
    Captures:
      - Model Name
      - Color Options
      - Storage / Capacity Options for each color
      - Variant SKU Code
      - Rating per variant / card
      - Exact Number of Ratings (capturing exact counts >9,999 from title/tooltip)
      - Current Price & Original Was-Price per variant
      - Financing Options ($X/mo for Y mos)
      - Offers (Badges, savings, promotions)
      - Stock Status ('In Stock' vs 'Notify Me' / 'Out of Stock')
      - Variant URL
    """
    print(f"\n[Catalog Scraper] Loading category: {category_name} -> {category_url}")
    driver.get(category_url)
    handle_cookie_consent(driver)
    scroll_and_load_all_products(driver)
    # In-browser asynchronous card extractor (operates on a single card index for speed & reliability)
    js_card_extractor = """
    var callback = arguments[arguments.length - 1];
    var cardIndex = arguments[0];

    (async function() {
        var allCards = Array.from(document.querySelectorAll('.pd21-product-card__item.js-pfv2-product-card, .pd21-product-card__item, .pd03-product-card'));
        if (cardIndex < 0 || cardIndex >= allCards.length) {
            callback([]);
            return;
        }

        var card = allCards[cardIndex];
        try {
            card.scrollIntoView({ behavior: 'instant', block: 'center' });
            await new Promise(function(r) { setTimeout(r, 200); });
        } catch(e) {}

        // 1. Model / Product Name
        var nameEl = card.querySelector('.pd21-product-card__name, [class*="product-card__name"], .product-name, h2, h3');
        var baseName = nameEl ? nameEl.innerText.trim() : '';
        if (!baseName) {
            await new Promise(function(r) { setTimeout(r, 300); });
            nameEl = card.querySelector('.pd21-product-card__name, [class*="product-card__name"], .product-name, h2, h3');
            baseName = nameEl ? nameEl.innerText.trim() : 'Unknown Product';
        }
        if (!baseName || baseName === 'Unknown Product') {
            callback([]);
            return;
        }

        var results = [];

        // 2. Rating & Exact Review Count
        var ratingEl = card.querySelector('.pd21-product-card__rating, [class*="rating"]');
        var ratingScore = null;
        var exactCount = 0;
        if (ratingEl) {
            var scoreEl = ratingEl.querySelector('strong span, .rating__point span:not(.hidden), strong');
            if (scoreEl) {
                var mScore = scoreEl.innerText.trim().match(/([0-5](?:\\.\\d+)?)/);
                if (mScore) ratingScore = parseFloat(mScore[1]);
            }

            // Check title attribute which contains exact count even for >9,999 reviews (e.g. title="4.8, (37185), Galaxy...")
            var titleText = ratingEl.getAttribute('title') || '';
            var mTitle = titleText.match(/\\(([0-9,]+)\\)/);
            if (mTitle) {
                exactCount = parseInt(mTitle[1].replace(/,/g, ''), 10);
            } else {
                var countEl = ratingEl.querySelector('em span:not(.hidden), em, [class*="review-count"]');
                if (countEl) {
                    var mCount = countEl.innerText.trim().match(/([0-9,]+)/);
                    if (mCount) exactCount = parseInt(mCount[1].replace(/,/g, ''), 10);
                }
            }
        }

        // 3. Badges / Tags (e.g. 'New', 'Online Exclusive')
        var badgeList = [];
        var badgeEls = card.querySelectorAll('.pd21-product-card__badge-wrap .badge-icon, .pd21-product-card__badge span, .badge-icon, .pd21-product-card__tag');
        badgeEls.forEach(function(b) {
            var bTxt = b.innerText.trim();
            if (bTxt && !badgeList.includes(bTxt)) badgeList.push(bTxt);
        });
        var badgeStr = badgeList.length > 0 ? badgeList.join(' | ') : 'None';

        // 4. Promotional Offers (e.g. Trade-in discounts, coupon codes, instant savings)
        var offersList = [];
        var tradeInEls = card.querySelectorAll('[class*="trade-in-message"], [class*="trade-in"], .seca-s26-fe-trade-in-message');
        tradeInEls.forEach(function(t) {
            var tTxt = t.innerText.trim().replace(/\\s+/g, ' ');
            if (tTxt && !offersList.includes(tTxt)) offersList.push(tTxt);
        });

        var couponEls = card.querySelectorAll('span[class*="-msg"], span[id*="COUPON"], [class*="promo-code"]');
        couponEls.forEach(function(c) {
            var cTxt = c.innerText.trim().replace(/\\s+/g, ' ');
            if (cTxt && !offersList.includes(cTxt)) offersList.push(cTxt);
        });

        var saveEl = card.querySelector('.price-ux__save, [class*="save"]');
        if (saveEl && saveEl.innerText.trim()) {
            var sTxt = saveEl.innerText.trim().replace(/\\s+/g, ' ');
            if (!offersList.includes(sTxt)) offersList.push(sTxt);
        }
        var origPriceEl = card.querySelector('.price-ux__price-original');
        if (origPriceEl) {
            var mSave = origPriceEl.innerText.match(/Save\\s+\\$[0-9,]+(?:\\.[0-9]{2})?/i);
            if (mSave && !offersList.includes(mSave[0])) {
                offersList.push(mSave[0]);
            }
        }

        var promoEl = card.querySelector('.pd21-product-card__promo, [class*="promo"]:not([class*="badge"])');
        if (promoEl && promoEl.innerText.trim()) {
            var pTxt = promoEl.innerText.trim().replace(/\\s+/g, ' ');
            if (!offersList.includes(pTxt)) offersList.push(pTxt);
        }
        var offersStr = offersList.length > 0 ? offersList.join(' | ') : 'None';

        // Helper to check if button is selected
        function isBtnSelected(btn) {
            if (!btn) return false;
            var blindText = btn.querySelector('.blind, .hidden')?.innerText || '';
            if (blindText.toLowerCase().includes('selected')) return true;
            if (btn.classList.contains('is-checked') || btn.classList.contains('active') || btn.classList.contains('selected')) return true;
            if (btn.parentElement && (btn.parentElement.classList.contains('is-checked') || btn.parentElement.classList.contains('active'))) return true;
            var parentSlide = btn.closest('.swiper-slide, li, div');
            if (parentSlide && (parentSlide.classList.contains('is-checked') || parentSlide.classList.contains('active'))) return true;
            return false;
        }

        // Helper to reliably trigger Samsung's custom web component event delegation
        function clickBtn(el) {
            if (!el) return;
            if (window.jQuery) {
                try { window.jQuery(el).trigger('click'); } catch(e){}
            }
            try {
                var rect = el.getBoundingClientRect();
                var x = rect.left + rect.width / 2;
                var y = rect.top + rect.height / 2;
                var opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, screenX: x, screenY: y };
                ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(evt) {
                    try { el.dispatchEvent(new MouseEvent(evt, opts)); } catch(e){}
                });
            } catch(e) {}
            try { el.click(); } catch(e2) {}
        }

        function getCleanText(el) {
            if (!el) return '';
            return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        }

        function getButtonLabel(btn) {
            if (!btn) return '';
            var clone = btn.cloneNode(true);
            var blind = clone.querySelectorAll('.blind, .hidden');
            blind.forEach(function(b) { b.remove(); });
            return getCleanText(clone);
        }

        // 5. Color and Storage / Size Swatches
        var initialColors = Array.from(card.querySelectorAll('.option-selector-v2__color, [data-chiptype="color"]'));
        var initialSizes = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));

        if (initialColors.length > 0) {
            for (var cIdx = 0; cIdx < initialColors.length; cIdx++) {
                var freshCBtns = Array.from(card.querySelectorAll('.option-selector-v2__color, [data-chiptype="color"]'));
                var cBtn = freshCBtns[cIdx];
                if (!cBtn) continue;

                var colorName = (
                    cBtn.getAttribute('an-la') ? cBtn.getAttribute('an-la').replace(/^color:/i, '').trim() : ''
                ) || (
                    cBtn.getAttribute('title') ? cBtn.getAttribute('title').trim() : ''
                ) || (
                    cBtn.getAttribute('aria-label') ? cBtn.getAttribute('aria-label').trim() : ''
                );
                if (!colorName) {
                    colorName = getButtonLabel(cBtn);
                }
                if (!colorName) {
                    colorName = 'Color ' + (cIdx + 1);
                }

                // Click color if not already selected
                var buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                if (!isBtnSelected(cBtn)) {
                    var prevSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                    clickBtn(cBtn);
                    
                    var elapsed = 0;
                    var retried = false;
                    while (elapsed < 600) {
                        await new Promise(function(r) { setTimeout(r, 50); });
                        elapsed += 50;
                        freshCBtns = Array.from(card.querySelectorAll('.option-selector-v2__color, [data-chiptype="color"]'));
                        var liveCBtn = freshCBtns[cIdx];
                        buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                        var currentSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                        if (isBtnSelected(liveCBtn) && (prevSku === null || currentSku !== prevSku || currentSku === liveCBtn?.getAttribute('data-modelcode'))) {
                            break;
                        }
                        if (elapsed >= 250 && !retried) {
                            retried = true;
                            clickBtn(liveCBtn || cBtn);
                        }
                    }
                    await new Promise(function(r) { setTimeout(r, 120); });
                }

                // Query fresh storage options for this color
                var curStorageBtns = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));
                if (curStorageBtns.length > 0) {
                    for (var sIdx = 0; sIdx < curStorageBtns.length; sIdx++) {
                        var freshSBtns = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));
                        var sBtn = freshSBtns[sIdx];
                        if (!sBtn) continue;

                        var isStorageDisabled = sBtn.hasAttribute('disabled') || sBtn.classList.contains('disabled');
                        var expectedCode = sBtn.getAttribute('data-modelcode');
                        var storageName = getButtonLabel(sBtn) || ('Option ' + (sIdx + 1));

                        buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');

                        if (!isStorageDisabled && !isBtnSelected(sBtn)) {
                            var prevSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                            clickBtn(sBtn);

                            var elapsed = 0;
                            var retried = false;
                            while (elapsed < 600) {
                                await new Promise(function(r) { setTimeout(r, 50); });
                                elapsed += 50;
                                freshSBtns = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));
                                var liveSBtn = freshSBtns[sIdx];
                                buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                                var currentSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                                if (isBtnSelected(liveSBtn) && (prevSku === null || currentSku !== prevSku || currentSku === liveSBtn?.getAttribute('data-modelcode'))) {
                                    break;
                                }
                                if (elapsed >= 250 && !retried) {
                                    retried = true;
                                    clickBtn(liveSBtn || sBtn);
                                }
                            }
                            await new Promise(function(r) { setTimeout(r, 100); });
                        }

                        // Prices
                        buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                        var priceWrap = card.querySelector('.pd21-product-card__price-main, .price-ux__wrap, .price-ux__price-current, .pd21-product-card__price, [class*="buying-price"]');
                        var priceRaw = priceWrap ? priceWrap.innerText.trim().replace(/\\s+/g, ' ') : '';
                        var wasEl = card.querySelector('.pd21-product-card__was-price, .price-ux__was-price, .price-ux__price-original, [class*="was-price"], [class*="origin-price"]');
                        var wasRaw = wasEl ? wasEl.innerText.trim() : '';

                        // Stock status
                        var notifyBtn = card.querySelector('.cta--notify, [class*="notify"]');
                        var stock = 'In Stock';
                        if (isStorageDisabled) {
                            stock = 'Out of Stock / Unavailable';
                        } else if (notifyBtn || (buyBtn && /notify/i.test(buyBtn.innerText))) {
                            stock = 'Notify Me';
                        } else if (buyBtn && (buyBtn.hasAttribute('disabled') || buyBtn.classList.contains('disabled'))) {
                            stock = 'Out of Stock';
                        }

                        // Model code / SKU - guaranteed by buyBtn active modelcode or expectedCode
                        var sku = (buyBtn ? buyBtn.getAttribute('data-modelcode') : '') ||
                                  expectedCode ||
                                  cBtn.getAttribute('data-modelcode') || '';

                        var learnMore = card.querySelector('a.js-pfv2-learn-more, a.pd21-product-card__name');
                        var itemUrl = (learnMore ? learnMore.getAttribute('href') : '') || (buyBtn ? buyBtn.getAttribute('href') : '');

                        results.push({
                            name: baseName,
                            color: colorName,
                            storage: storageName,
                            sku: sku,
                            price_raw: priceRaw,
                            was_raw: wasRaw,
                            badge: badgeStr,
                            offers: offersStr,
                            rating: ratingScore,
                            rating_count: exactCount,
                            stock: stock,
                            url: itemUrl
                        });
                    }
                } else {
                    // Color only, no storage chips
                    buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                    var priceWrap = card.querySelector('.pd21-product-card__price-main, .price-ux__wrap, .price-ux__price-current, .pd21-product-card__price, [class*="buying-price"]');
                    var priceRaw = priceWrap ? priceWrap.innerText.trim().replace(/\\s+/g, ' ') : '';
                    var wasEl = card.querySelector('.pd21-product-card__was-price, .price-ux__was-price, .price-ux__price-original, [class*="was-price"]');
                    var wasRaw = wasEl ? wasEl.innerText.trim() : '';

                    var notifyBtn = card.querySelector('.cta--notify, [class*="notify"]');
                    var stock = 'In Stock';
                    if (notifyBtn || (buyBtn && /notify/i.test(buyBtn.innerText))) {
                        stock = 'Notify Me';
                    } else if (buyBtn && (buyBtn.hasAttribute('disabled') || buyBtn.classList.contains('disabled'))) {
                        stock = 'Out of Stock';
                    }

                    var sku = (buyBtn ? buyBtn.getAttribute('data-modelcode') : '') ||
                              cBtn.getAttribute('data-modelcode') ||
                              (nameEl ? nameEl.getAttribute('data-modelcode') : '') || '';

                    var learnMore = card.querySelector('a.js-pfv2-learn-more, a.pd21-product-card__name');
                    var itemUrl = (learnMore ? learnMore.getAttribute('href') : '') || (buyBtn ? buyBtn.getAttribute('href') : '');

                    results.push({
                        name: baseName,
                        color: colorName,
                        storage: 'Default',
                        sku: sku,
                        price_raw: priceRaw,
                        was_raw: wasRaw,
                        badge: badgeStr,
                        offers: offersStr,
                        rating: ratingScore,
                        rating_count: exactCount,
                        stock: stock,
                        url: itemUrl
                    });
                }
            }
        } else if (initialSizes.length > 0) {
            // Storage/size chips without color chips (e.g. TVs or Monitors)
            for (var sIdx = 0; sIdx < initialSizes.length; sIdx++) {
                var freshSBtns = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));
                var sBtn = freshSBtns[sIdx];
                if (!sBtn) continue;

                var isStorageDisabled = sBtn.hasAttribute('disabled') || sBtn.classList.contains('disabled');
                var expectedCode = sBtn.getAttribute('data-modelcode');
                var storageName = getButtonLabel(sBtn) || ('Option ' + (sIdx + 1));

                var buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');

                if (!isStorageDisabled && !isBtnSelected(sBtn)) {
                    var prevSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                    clickBtn(sBtn);

                    var elapsed = 0;
                    var retried = false;
                    while (elapsed < 600) {
                        await new Promise(function(r) { setTimeout(r, 50); });
                        elapsed += 50;
                        freshSBtns = Array.from(card.querySelectorAll('.option-selector-v2__size, [data-chiptype="other"], [data-chiptype="size"]'));
                        var liveSBtn = freshSBtns[sIdx];
                        buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                        var currentSku = buyBtn ? buyBtn.getAttribute('data-modelcode') : null;
                        if (isBtnSelected(liveSBtn) && (prevSku === null || currentSku !== prevSku || currentSku === liveSBtn?.getAttribute('data-modelcode'))) {
                            break;
                        }
                        if (elapsed >= 250 && !retried) {
                            retried = true;
                            clickBtn(liveSBtn || sBtn);
                        }
                    }
                    await new Promise(function(r) { setTimeout(r, 100); });
                }

                buyBtn = card.querySelector('a.pd21-product-card__image-cta, a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
                var priceWrap = card.querySelector('.pd21-product-card__price-main, .price-ux__wrap, .price-ux__price-current, .pd21-product-card__price, [class*="buying-price"]');
                var priceRaw = priceWrap ? priceWrap.innerText.trim().replace(/\\s+/g, ' ') : '';
                var wasEl = card.querySelector('.pd21-product-card__was-price, .price-ux__was-price, .price-ux__price-original, [class*="was-price"]');
                var wasRaw = wasEl ? wasEl.innerText.trim() : '';

                var notifyBtn = card.querySelector('.cta--notify, [class*="notify"]');
                var stock = 'In Stock';
                if (isStorageDisabled) {
                    stock = 'Out of Stock / Unavailable';
                } else if (notifyBtn || (buyBtn && /notify/i.test(buyBtn.innerText))) {
                    stock = 'Notify Me';
                }

                var sku = (buyBtn ? buyBtn.getAttribute('data-modelcode') : '') ||
                          expectedCode ||
                          (nameEl ? nameEl.getAttribute('data-modelcode') : '') || '';

                var learnMore = card.querySelector('a.js-pfv2-learn-more, a.pd21-product-card__name');
                var itemUrl = (learnMore ? learnMore.getAttribute('href') : '') || (buyBtn ? buyBtn.getAttribute('href') : '');

                results.push({
                    name: baseName,
                    color: 'Default',
                    storage: storageName,
                    sku: sku,
                    price_raw: priceRaw,
                    was_raw: wasRaw,
                    badge: badgeStr,
                    offers: offersStr,
                    rating: ratingScore,
                    rating_count: exactCount,
                    stock: stock,
                    url: itemUrl
                });
            }
        } else {
            // Single variant product (no swatches)
            var priceWrap = card.querySelector('.pd21-product-card__price-main, .price-ux__wrap, .price-ux__price-current, .pd21-product-card__price, [class*="buying-price"]');
            var priceRaw = priceWrap ? priceWrap.innerText.trim().replace(/\\s+/g, ' ') : '';
            var wasEl = card.querySelector('.pd21-product-card__was-price, .price-ux__was-price, .price-ux__price-original, [class*="was-price"]');
            var wasRaw = wasEl ? wasEl.innerText.trim() : '';

            var buyBtn = card.querySelector('a.js-pfv2-buy-now, [class*="buy-now"], .cta--primary');
            var notifyBtn = card.querySelector('.cta--notify, [class*="notify"]');
            var stock = 'In Stock';
            if (notifyBtn || (buyBtn && /notify/i.test(buyBtn.innerText))) {
                stock = 'Notify Me';
            } else if (buyBtn && (buyBtn.hasAttribute('disabled') || buyBtn.classList.contains('disabled'))) {
                stock = 'Out of Stock';
            }

            var sku = (buyBtn ? buyBtn.getAttribute('data-modelcode') : '') ||
                      (nameEl ? nameEl.getAttribute('data-modelcode') : '') || '';

            var learnMore = card.querySelector('a.js-pfv2-learn-more, a.pd21-product-card__name');
            var itemUrl = (learnMore ? learnMore.getAttribute('href') : '') || (buyBtn ? buyBtn.getAttribute('href') : '');

            results.push({
                name: baseName,
                color: 'Default',
                storage: 'Default',
                sku: sku,
                price_raw: priceRaw,
                was_raw: wasRaw,
                badge: badgeStr,
                offers: offersStr,
                rating: ratingScore,
                rating_count: exactCount,
                stock: stock,
                url: itemUrl
            });
        }

        callback(results);
    })();
    """

    num_cards = driver.execute_script("""
        return document.querySelectorAll('.pd21-product-card__item.js-pfv2-product-card, .pd21-product-card__item, .pd03-product-card').length;
    """) or 0

    if max_cards and max_cards > 0:
        total_to_process = min(num_cards, max_cards)
    else:
        total_to_process = num_cards

    print(f"[Catalog Scraper] Found {num_cards} catalog cards. Extracting variants card by card...")

    driver.set_script_timeout(35)
    raw_results = []

    for c_idx in range(total_to_process):
        try:
            card_items = driver.execute_async_script(js_card_extractor, c_idx) or []
            if card_items:
                c_name = card_items[0].get("name", f"Card {c_idx + 1}")
                print(f"  [{c_idx + 1}/{total_to_process}] {c_name} -> {len(card_items)} variant(s)")
                raw_results.extend(card_items)
            else:
                print(f"  [{c_idx + 1}/{total_to_process}] Card {c_idx + 1} -> 0 variants")
        except Exception as e:
            print(f"  [{c_idx + 1}/{total_to_process}] Warning: Failed extracting card {c_idx + 1}: {e}")

    print(f"[Catalog Scraper] Completed! Extracted {len(raw_results)} total variant records.")

    products: List[SamsungProduct] = []
    seen_variants = set()

    for item in raw_results:
        name = item.get("name", "Unknown Product")
        color = item.get("color", "Default").strip()
        storage = item.get("storage", "Default").strip()
        sku = item.get("sku", "").strip().upper()
        if not sku:
            sku = f"SAMS-{abs(hash(name + color + storage)) % 10000000}"

        variant_key = (name, color, storage, sku)
        if variant_key in seen_variants:
            continue
        seen_variants.add(variant_key)

        price_raw = item.get("price_raw", "")
        was_raw = item.get("was_raw", "")

        # Current Price
        curr_price = None
        price_formatted = "Not Available"
        m_or = re.search(r'or\s+\$([0-9,]+\.?[0-9]*)', price_raw, re.IGNORECASE)
        if m_or:
            curr_price = parse_price(m_or.group(1))
        else:
            m_p = re.search(r'\$([0-9,]+\.[0-9]{2})', price_raw)
            if m_p:
                curr_price = parse_price(m_p.group(1))
            else:
                curr_price = parse_price(price_raw)

        if curr_price:
            price_formatted = f"${curr_price:,.2f}"

        # Original / Was Price
        orig_price = parse_price(was_raw)
        orig_price_formatted = f"${orig_price:,.2f}" if orig_price else "Not Available"

        # Financing Option
        fin_opt = "Not Applicable"
        m_fin = re.search(r'((?:From\s+)?\$[0-9,]+(?:\.[0-9]{2})?/mo(?:\s+for\s+\d+\s+mos)?)', price_raw, re.IGNORECASE)
        if m_fin:
            fin_opt = m_fin.group(1).strip()

        # Product URL
        p_url = item.get("url", "")
        if p_url and not p_url.startswith("http"):
            p_url = "https://www.samsung.com" + p_url

        prod = SamsungProduct(
            sku=sku,
            name=name,
            category=category_name,
            color=color,
            storage=storage,
            current_price=curr_price,
            original_price=orig_price,
            price_formatted=price_formatted,
            original_price_formatted=orig_price_formatted,
            financing_option=fin_opt,
            badge=item.get("badge", "None"),
            offers=item.get("offers", "None"),
            rating=item.get("rating"),
            rating_count=item.get("rating_count", 0),
            availability=item.get("stock", "In Stock"),
            product_url=p_url
        )
        products.append(prod)

    return products


def scrape_category_cards(
    driver: webdriver.Chrome,
    category_name: str,
    category_url: str,
    max_products: Optional[int] = None
) -> List[SamsungProduct]:
    """
    Alias / wrapper for scrape_catalog_page_variants.
    Extracts all product details (name, exact price, financing, ratings, reviews, SKU,
    colors, storage options, offers, stock status) directly from the category catalog cards.
    """
    return scrape_catalog_page_variants(driver, category_name, category_url, max_cards=max_products)

