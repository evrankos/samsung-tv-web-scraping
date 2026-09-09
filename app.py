import os
import sys
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.db import SamsungDB
from src.alerts import PriceAlertEngine
from src.pipeline import SamsungPipeline

st.set_page_config(
    page_title="Samsung Product Intelligence & Price Tracker",
    page_icon="📺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for rich modern aesthetics
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #181c24 0%, #232936 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.18);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .metric-card:hover {
        border-color: rgba(0, 114, 206, 0.4);
        transform: translateY(-2px);
    }
    .metric-val {
        font-size: 26px;
        font-weight: 700;
        color: #00f2fe;
        margin-top: 4px;
        letter-spacing: -0.5px;
    }
    .metric-label {
        font-size: 12px;
        color: #9aa0a6;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        font-weight: 600;
    }
    .badge-deal {
        background-color: #00e676;
        color: #000;
        padding: 2px 7px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 11px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0px 0px;
        padding: 10px 18px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

CATEGORY_ICONS = {
    "All Categories": "🌐",
    "TVs": "📺",
    "Smartphones": "📱",
    "Tablets": "📟",
    "Watches": "⌚",
    "Audio & Buds": "🎧",
    "Monitors": "🖥️",
    "Computers": "💻",
    "Refrigerators": "🧊",
    "Cooking Appliances": "🍳",
    "Laundry": "🧺",
    "Sound Devices": "🔊"
}


def load_database():
    """Initializes and returns the database and pipeline with dynamic module reload."""
    import importlib
    import src.db
    import src.pipeline
    importlib.reload(src.db)
    importlib.reload(src.pipeline)
    from src.db import SamsungDB
    from src.pipeline import SamsungPipeline

    db = SamsungDB()
    pipeline = SamsungPipeline(db)
    df = db.get_latest_products_df()
    
    # Auto-seed if database is empty or has only a few categories from legacy runs
    if df.empty or len(df["category"].unique()) < 5:
        if hasattr(pipeline, "seed_all_data"):
            pipeline.seed_all_data(os.path.dirname(os.path.abspath(__file__)), reset=True)
        else:
            pipeline.seed_legacy_data(os.path.dirname(os.path.abspath(__file__)), reset=True)
        df = db.get_latest_products_df()
        
    return db, pipeline, df


db, pipeline, df = load_database()

# -------------------------------------------------------------
# SIDEBAR CONTROLS & FILTERS
# -------------------------------------------------------------
st.sidebar.title("📺 Samsung Intelligence")
st.sidebar.caption("E-Commerce Catalog, Time-Series Tracker & Deals")

# Catalog Sync & Automated Schedule Indicator
if not df.empty and "scraped_at" in df.columns:
    try:
        latest_ts = pd.to_datetime(df["scraped_at"]).max()
        formatted_date = latest_ts.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        formatted_date = "Recently Synchronized"

    st.sidebar.markdown(f"""
    <div style="background: rgba(0, 114, 206, 0.12); border: 1px solid rgba(0, 114, 206, 0.3); border-radius: 8px; padding: 10px 12px; margin: 10px 0 14px 0;">
        <div style="font-size: 11px; color: #9aa0a6; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Last Scraped Snapshot</div>
        <div style="font-size: 13px; color: #00f2fe; font-weight: 700; margin-top: 2px;">⚡ {formatted_date}</div>
        <div style="font-size: 11px; color: #81c784; margin-top: 4px;">● Auto-scrapes every 7 days (Sundays)</div>
    </div>
    """, unsafe_allow_html=True)

# Refresh / Resync Action
if st.sidebar.button("🔄 Reload Latest Scraped Data into DB"):
    try:
        with st.spinner("Reloading all 11 category datasets into SQLite..."):
            import importlib
            import src.db
            import src.pipeline
            importlib.reload(src.db)
            importlib.reload(src.pipeline)
            from src.db import SamsungDB
            from src.pipeline import SamsungPipeline
            
            fresh_db = SamsungDB()
            fresh_pipeline = SamsungPipeline(fresh_db)
            if hasattr(fresh_pipeline, "seed_all_data"):
                fresh_pipeline.seed_all_data(os.path.dirname(os.path.abspath(__file__)), reset=True)
            elif hasattr(fresh_pipeline, "seed_legacy_data"):
                fresh_pipeline.seed_legacy_data(os.path.dirname(os.path.abspath(__file__)), reset=True)
            st.cache_data.clear()
            st.cache_resource.clear()
        st.sidebar.success("Database successfully reloaded with fresh scraped data!")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Error reloading database: {e}")

st.sidebar.markdown("---")

# Category Selector with Live Counts
if not df.empty:
    cat_counts = df["category"].value_counts().to_dict()
    category_choices = ["All Categories"] + sorted(list(cat_counts.keys()))
    
    def format_category_label(cat):
        icon = CATEGORY_ICONS.get(cat, "📦")
        count = len(df) if cat == "All Categories" else cat_counts.get(cat, 0)
        return f"{icon} {cat} ({count})"

    selected_cat = st.sidebar.selectbox(
        "Select Category",
        category_choices,
        format_func=format_category_label
    )
else:
    selected_cat = "All Categories"

# Search Keyword
search_term = st.sidebar.text_input("🔍 Search Products", placeholder="e.g. OLED, S25, 65-inch, 512GB...")

# Price Range Slider
if not df.empty and df["current_price"].notna().any():
    min_p = float(df["current_price"].dropna().min())
    max_p = float(df["current_price"].dropna().max())
    price_range = st.sidebar.slider(
        "Price Range (CAD)",
        min_value=0.0,
        max_value=max_p,
        value=(0.0, max_p),
        step=50.0,
        format="$%.0f"
    )
else:
    price_range = (0.0, 100000.0)

# Toggles for Deals and Stock
only_deals = st.sidebar.checkbox("🏷️ Only Discounted / On-Sale", value=False)
only_in_stock = st.sidebar.checkbox("📦 Only Purchasable In-Stock", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ Quick Actions")

if st.sidebar.button("🔔 Check Deal Alerts"):
    alerts = pipeline.run_alerts()
    st.sidebar.success(f"Discounts: {len(alerts['steep_discounts'])} | Drops: {len(alerts['price_drops'])}")

if st.sidebar.button("🧪 Simulate Price Drop Demo"):
    pipeline.simulate_price_drop_snapshot("QN55S90CAFXZC", discount_pct=25.0)
    st.sidebar.success("Simulated 25% price drop on 55\" OLED S90C!")
    st.rerun()

# -------------------------------------------------------------
# FILTERING PIPELINE
# -------------------------------------------------------------
filtered_df = df.copy()

if selected_cat != "All Categories":
    filtered_df = filtered_df[filtered_df["category"] == selected_cat]

if search_term:
    term_lower = search_term.lower()
    filtered_df = filtered_df[
        filtered_df["name"].astype(str).str.lower().str.contains(term_lower, na=False) |
        filtered_df["sku"].astype(str).str.lower().str.contains(term_lower, na=False) |
        filtered_df["color"].astype(str).str.lower().str.contains(term_lower, na=False) |
        filtered_df["storage"].astype(str).str.lower().str.contains(term_lower, na=False)
    ]

# Apply price filter (unpriced items retained unless filtering below min or using only_in_stock)
if "current_price" in filtered_df.columns:
    filtered_df = filtered_df[
        (filtered_df["current_price"].isna()) |
        ((filtered_df["current_price"] >= price_range[0]) & (filtered_df["current_price"] <= price_range[1]))
    ]

# Apply deals filter
if only_deals and "discount_percentage" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["discount_percentage"] > 0]

# Apply stock filter: strictly in-stock with confirmed retail price
if only_in_stock and "availability" in filtered_df.columns:
    filtered_df = filtered_df[
        (filtered_df["availability"] == "In Stock") &
        (filtered_df["current_price"].notna()) &
        (filtered_df["current_price"] > 0)
    ]


# -------------------------------------------------------------
# HEADER & EXECUTIVE METRICS
# -------------------------------------------------------------
header_title = f"{CATEGORY_ICONS.get(selected_cat, '📦')} {selected_cat}" if selected_cat != "All Categories" else "🌐 All Samsung Categories"
st.title(f"{header_title} Intelligence")
st.caption(f"Real-time catalog analytics, price history tracking, and deal discovery across Samsung Canada.")

col1, col2, col3, col4, col5 = st.columns(5)

total_items = len(filtered_df)
avg_price = filtered_df["current_price"].dropna().mean() if not filtered_df.empty else 0.0
median_price = filtered_df["current_price"].dropna().median() if not filtered_df.empty else 0.0
avg_rating = filtered_df["rating"].dropna().mean() if not filtered_df.empty and filtered_df["rating"].notna().any() else 0.0
deals_count = len(filtered_df[filtered_df["discount_percentage"] > 0]) if "discount_percentage" in filtered_df.columns else 0

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Products Visible</div>
        <div class="metric-val">{total_items:,}</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Average Price</div>
        <div class="metric-val">${avg_price:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Median Price</div>
        <div class="metric-val">${median_price:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Active Promotions</div>
        <div class="metric-val" style="color:#00e676;">{deals_count} Deals</div>
    </div>
    """, unsafe_allow_html=True)

with col5:
    rating_display = f"⭐ {avg_rating:.2f} / 5" if avg_rating > 0 else "N/A"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Average Rating</div>
        <div class="metric-val" style="color:#ffb300;">{rating_display}</div>
    </div>
    """, unsafe_allow_html=True)

# -------------------------------------------------------------
# MAIN NAVIGATION TABS
# -------------------------------------------------------------
tab_catalog, tab_history, tab_value, tab_deals, tab_compare = st.tabs([
    "📋 Product Catalog",
    "📈 Price History Tracker",
    "💎 Value-for-Money Analytics",
    "🔥 Live Deals & Alerts",
    "⚖️ Side-by-Side Comparison"
])

# -------------------------------------------------------------
# TAB 1: Product Catalog
# -------------------------------------------------------------
with tab_catalog:
    st.subheader(f"Current Catalog: {selected_cat} ({len(filtered_df)} items)")
    
    if filtered_df.empty:
        st.warning("No products match the selected criteria and filters.")
    else:
        # Download button
        csv_data = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Filtered Products as CSV",
            data=csv_data,
            file_name=f"samsung_{selected_cat.lower().replace(' ', '_')}_filtered.csv",
            mime="text/csv"
        )
        
        # Prepare clean display dataframe with formatted values (no raw None)
        view_df = pd.DataFrame()
        view_df["Product Name"] = filtered_df["name"].astype(str)
        view_df["Category"] = filtered_df["category"].astype(str)
        view_df["Price (CAD)"] = filtered_df["current_price"].apply(
            lambda p: f"${p:,.2f}" if pd.notna(p) and p > 0 else "Where to Buy"
        )
        view_df["Was Price (CAD)"] = filtered_df["original_price"].apply(
            lambda p: f"${p:,.2f}" if pd.notna(p) and p > 0 else "—"
        )
        view_df["Discount"] = filtered_df["discount_percentage"].apply(
            lambda d: f"{d:.1f}%" if pd.notna(d) and d > 0 else "—"
        )
        view_df["Color"] = filtered_df.get("color", pd.Series(["Default"] * len(filtered_df))).fillna("Default").astype(str)
        view_df["Storage / Size"] = filtered_df.get("storage", pd.Series(["Default"] * len(filtered_df))).fillna("Default").astype(str)
        view_df["Rating"] = filtered_df["rating"].apply(
            lambda r: f"{r:.1f} ⭐" if pd.notna(r) and r > 0 else "Not Rated"
        )
        view_df["Reviews"] = filtered_df["rating_count"].fillna(0).astype(int)
        view_df["Stock Status"] = filtered_df["availability"].fillna("Where to Buy (Dealer Only)").astype(str)
        view_df["Financing Terms"] = filtered_df["financing_option"].fillna("Not Applicable").astype(str)
        view_df["SKU Code"] = filtered_df["sku"].astype(str)
        view_df["Product URL"] = filtered_df["product_url"].astype(str)
        
        st.dataframe(
            view_df,
            use_container_width=True,
            column_config={
                "Product URL": st.column_config.LinkColumn(display_text="View on Samsung.ca")
            },
            height=540
        )

# -------------------------------------------------------------
# TAB 2: Price History Tracker
# -------------------------------------------------------------
with tab_history:
    st.subheader("Historical Price Movements & All-Time Lows")
    st.caption("Select any product to inspect its longitudinal price trajectory and all-time low recorded in the SQLite database.")

    if not df.empty:
        # Filter products by category for quick lookup
        hist_cat = st.selectbox(
            "Category Scope for Inspection",
            ["All Categories"] + sorted(df["category"].dropna().unique().tolist()),
            index=0 if selected_cat == "All Categories" else (["All Categories"] + sorted(df["category"].dropna().unique().tolist())).index(selected_cat)
        )
        
        hist_pool = df.copy()
        if hist_cat != "All Categories":
            hist_pool = hist_pool[hist_pool["category"] == hist_cat]
            
        if not hist_pool.empty:
            sku_options = hist_pool["sku"].tolist()
            name_map = dict(zip(hist_pool["sku"], hist_pool["name"] + " [" + hist_pool["sku"] + "]"))
            selected_sku = st.selectbox(
                "Select Product to Inspect",
                sku_options,
                format_func=lambda s: name_map.get(s, s)
            )
            
            history_df = db.get_price_history_df(selected_sku)
            
            if not history_df.empty:
                c1, c2, c3, c4 = st.columns(4)
                latest_p = history_df.iloc[-1]["current_price"]
                min_p = history_df["current_price"].min()
                max_p = history_df["current_price"].max()
                price_changes = len(history_df)
                
                c1.metric("Current Price", f"${latest_p:,.2f}" if latest_p else "N/A")
                c2.metric("All-Time Low (ATL)", f"${min_p:,.2f}" if min_p else "N/A")
                c3.metric("Highest Seen", f"${max_p:,.2f}" if max_p else "N/A")
                c4.metric("Snapshots Logged", f"{price_changes} Records")
                
                fig = px.line(
                    history_df,
                    x="scraped_at",
                    y="current_price",
                    markers=True,
                    title=f"Price Trajectory: {name_map.get(selected_sku, selected_sku)}",
                    labels={"scraped_at": "Timestamp", "current_price": "Price (CAD)"}
                )
                fig.update_traces(line_color="#00f2fe", line_width=3, marker_size=8)
                fig.update_layout(template="plotly_dark", hovermode="x unified", margin=dict(t=40, b=20, l=40, r=20))
                st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("📄 View Detailed Price Snapshot Records"):
                    st.dataframe(history_df, use_container_width=True)
            else:
                st.info("No historical snapshots logged for this SKU yet.")
        else:
            st.info("No products found in this category.")

# -------------------------------------------------------------
# TAB 3: Value-for-Money Analytics
# -------------------------------------------------------------
with tab_value:
    st.subheader("Value-for-Money, Specs & Market Efficiency Modeling")
    st.caption("Cross-sectional econometric analysis of price vs screen dimensions, storage capacity, and customer satisfaction.")
    
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("#### 📺 Display Tech: Screen Size vs. Price")
        st.caption("Bubble size corresponds to Cost per Inch ($/in). Larger bubbles = higher cost per diagonal inch.")
        
        display_data = df[df["category"].isin(["TVs", "Monitors"])].copy()
        if not display_data.empty and "screen_size_inch" in display_data.columns:
            valid_screens = display_data[display_data["screen_size_inch"].notna() & display_data["current_price"].notna()].copy()
            if not valid_screens.empty:
                valid_screens["Cost Per Inch ($)"] = valid_screens["current_price"] / valid_screens["screen_size_inch"]
                
                fig_disp = px.scatter(
                    valid_screens,
                    x="screen_size_inch",
                    y="current_price",
                    size="Cost Per Inch ($)",
                    color="category",
                    hover_name="name",
                    title="Screen Dimensions vs. Retail Price (Bubble = Cost/Inch)",
                    labels={"screen_size_inch": "Screen Size (Inches)", "current_price": "Price (CAD)"}
                )
                fig_disp.update_layout(template="plotly_dark", margin=dict(t=40, b=20, l=40, r=20))
                st.plotly_chart(fig_disp, use_container_width=True)
            else:
                st.info("No display screen size data available.")
        else:
            st.info("No display data available.")

    with col_chart2:
        st.markdown("#### 📱 Mobile & Computing: Storage Tier Premium")
        st.caption("Analyzes the incremental step-up cost from 128GB to 1TB across devices.")
        
        storage_data = df[df["category"].isin(["Smartphones", "Tablets", "Computers"])].copy()
        if not storage_data.empty and "storage_gb" in storage_data.columns:
            valid_storage = storage_data[storage_data["storage_gb"].notna() & storage_data["current_price"].notna()].copy()
            if not valid_storage.empty:
                fig_stor = px.scatter(
                    valid_storage,
                    x="storage_gb",
                    y="current_price",
                    color="category",
                    hover_name="name",
                    title="Storage Capacity (GB) vs. Device Price",
                    labels={"storage_gb": "Internal Storage (GB)", "current_price": "Price (CAD)"}
                )
                fig_stor.update_layout(template="plotly_dark", margin=dict(t=40, b=20, l=40, r=20))
                st.plotly_chart(fig_stor, use_container_width=True)
            else:
                st.info("No storage capacity data available.")
        else:
            st.info("No mobile device data available.")

    col_chart3, col_chart4 = st.columns(2)

    with col_chart3:
        st.markdown("#### 📊 Price Distribution Across All 11 Categories")
        st.caption("Distribution box-plots showing price spread, medians, and outliers per category.")
        
        valid_prices = df[df["current_price"].notna() & (df["current_price"] > 0)].copy()
        if not valid_prices.empty:
            fig_box = px.box(
                valid_prices,
                x="category",
                y="current_price",
                color="category",
                title="Category Price Spread & Median Benchmarks",
                labels={"category": "Hardware Category", "current_price": "Price (CAD)"}
            )
            fig_box.update_layout(template="plotly_dark", showlegend=False, margin=dict(t=40, b=40, l=40, r=20))
            st.plotly_chart(fig_box, use_container_width=True)

    with col_chart4:
        st.markdown("#### ⭐ Customer Rating vs. Price Distribution")
        st.caption("Correlation between customer review ratings and hardware retail price.")
        
        valid_rat = df[df["rating"].notna() & df["current_price"].notna()].copy()
        if not valid_rat.empty:
            fig_rat = px.scatter(
                valid_rat,
                x="current_price",
                y="rating",
                color="category",
                hover_name="name",
                title="Consumer Rating vs. Hardware Price",
                labels={"current_price": "Price (CAD)", "rating": "Customer Rating (out of 5)"}
            )
            fig_rat.update_layout(template="plotly_dark", margin=dict(t=40, b=20, l=40, r=20))
            st.plotly_chart(fig_rat, use_container_width=True)

# -------------------------------------------------------------
# TAB 4: Live Deals & Alerts
# -------------------------------------------------------------
with tab_deals:
    st.subheader("🔥 Promotional Deals, Price Drops & Special Offers")
    
    alert_engine = PriceAlertEngine(db)
    alerts = alert_engine.check_alerts()
    
    deal_c1, deal_c2 = st.columns(2)
    
    with deal_c1:
        st.markdown("### 🔻 Detected Price Drops & All-Time Lows")
        drops = alerts["price_drops"]
        if drops:
            for drop in drops:
                st.success(
                    f"**{drop['name']}** dropped from **${drop['old_price']:,.2f}** to "
                    f"**${drop['new_price']:,.2f}** (-${drop['drop_amount']:,.2f} | -{drop['drop_percentage']}%)"
                )
        else:
            st.info("No sudden price drops between successive runs yet. Use 'Simulate Price Drop Demo' on the sidebar to test this feature!")

    with deal_c2:
        st.markdown("### 🏷️ Top Steep Discounts (>15% Off)")
        discounts = alerts["steep_discounts"]
        if discounts:
            for dc in discounts[:8]:
                st.warning(
                    f"**{dc['name']}**: **${dc['current_price']:,.2f}** "
                    f"(Was: ${dc['original_price']:,.2f} | Save {dc['discount_percentage']}%)"
                )
        else:
            st.info("No products currently above the steep discount threshold.")

    st.markdown("---")
    st.subheader("🏆 Top 10 Best Deals in Catalog (Ranked by Discount %)")
    if not df.empty and "discount_percentage" in df.columns:
        deals_df = df[df["discount_percentage"] > 0].sort_values(by="discount_percentage", ascending=False).head(10)
        if not deals_df.empty:
            deal_cols = ["name", "category", "current_price", "original_price", "discount_percentage", "discount_amount", "availability", "product_url"]
            d_view = deals_df[[c for c in deal_cols if c in deals_df.columns]].copy()
            d_view.rename(columns={
                "name": "Product Name",
                "category": "Category",
                "current_price": "Price (CAD)",
                "original_price": "MSRP (CAD)",
                "discount_percentage": "Discount (%)",
                "discount_amount": "Total Savings ($)",
                "availability": "Stock",
                "product_url": "Link"
            }, inplace=True)
            st.dataframe(
                d_view,
                use_container_width=True,
                column_config={
                    "Price (CAD)": st.column_config.NumberColumn(format="$%.2f"),
                    "MSRP (CAD)": st.column_config.NumberColumn(format="$%.2f"),
                    "Total Savings ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Discount (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Link": st.column_config.LinkColumn(display_text="View Deal")
                }
            )
        else:
            st.info("No promotional discounts found in the catalog.")

# -------------------------------------------------------------
# TAB 5: Side-by-Side Comparison
# -------------------------------------------------------------
with tab_compare:
    st.subheader("⚖️ Side-by-Side Hardware Comparison")
    st.caption("Select a category and compare up to 4 models side-by-side on pricing, specifications, and savings.")

    if not df.empty:
        cmp_cat = st.selectbox(
            "Filter Products by Category for Comparison",
            sorted(df["category"].dropna().unique().tolist()),
            key="compare_cat_selector"
        )
        
        cat_pool = df[df["category"] == cmp_cat]
        if not cat_pool.empty:
            sku_list = cat_pool["sku"].tolist()
            name_dict = dict(zip(cat_pool["sku"], cat_pool["name"] + " (" + cat_pool["sku"] + ")"))
            
            selected_skus = st.multiselect(
                "Choose 2 to 4 products to compare",
                options=sku_list,
                default=sku_list[:2] if len(sku_list) >= 2 else sku_list,
                format_func=lambda s: name_dict.get(s, s),
                max_selections=4
            )
            
            if selected_skus:
                comparison_subset = cat_pool[cat_pool["sku"].isin(selected_skus)].copy()
                
                # Build unique display label per item (combining name, color/storage, and SKU)
                comparison_subset["Product Header"] = comparison_subset.apply(
                    lambda r: f"{r['name']} - {r['color'] if r.get('color') and str(r.get('color')) != 'Default' else ''} [{r['sku']}]".replace(" -  [", " ["),
                    axis=1
                )
                
                fields_to_show = [
                    "current_price", "original_price", "discount_percentage",
                    "color", "storage", "rating", "rating_count", "availability",
                    "financing_option", "sku", "product_url"
                ]
                cols_present = [c for c in fields_to_show if c in comparison_subset.columns]
                subset = comparison_subset[cols_present + ["Product Header"]].drop_duplicates(subset=["Product Header"]).set_index("Product Header").T
                subset.rename(index={
                    "current_price": "Price (CAD)",
                    "original_price": "MSRP (CAD)",
                    "discount_percentage": "Discount (%)",
                    "color": "Color",
                    "storage": "Storage / Size",
                    "rating": "Customer Rating",
                    "rating_count": "Total Reviews",
                    "availability": "Stock Status",
                    "financing_option": "Financing Terms",
                    "sku": "SKU Identifier",
                    "product_url": "Product URL"
                }, inplace=True)
                
                st.table(subset.fillna("N/A"))
        else:
            st.info("No products found in this category.")

# -------------------------------------------------------------
# DASHBOARD FOOTER
# -------------------------------------------------------------
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #8a99a8; font-size: 13px; padding: 15px 0 30px 0;">
    <strong>Samsung Product Intelligence & Deal Tracker</strong> • Automated 7-Day Scraping Cycle via GitHub Actions • Deployed on Streamlit Cloud
</div>
""", unsafe_allow_html=True)
