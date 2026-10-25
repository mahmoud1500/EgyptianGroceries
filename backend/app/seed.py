"""Seed the database with demo vendors, the full Omar Caboose menu,
sample vendors, demo accounts, and a couple of demo orders.

Idempotent: adds only whatever is missing (safe to re-run).

Run (from the backend/ folder, VS Code terminal):
  $env:DATABASE_URL = "sqlite:///./app.db"
  python -m app.seed
"""
import json
from decimal import Decimal

from sqlalchemy import func, select, update

from . import auth, models
from .database import Base, SessionLocal, engine, ensure_schema
from .routers.orders import _completion_email, _log_event

# (name, description, price, category, featured)
OMAR_MENU: list[tuple[str, str, float, str, bool]] = [
    # ---- Salads ----
    ("Egyptian Baladi Salad", "Fresh tomatoes, cucumbers, red onion, and herbs", 6.99, "Salads", True),
    ("Tahini Salad", "Creamy tahini with lemon and fresh herbs", 6.99, "Salads", True),
    ("Baba Ghanoush", "Smoked eggplant blended with tahini and special spices", 7.99, "Salads", False),
    ("Hummus", "Chickpeas blended with tahini, lemon, and olive oil", 6.99, "Salads", True),
    ("Tabbouleh", "Fresh parsley, tomatoes, onions, bulgur, and lemon", 7.99, "Salads", False),
    ("Fattoush", "Mixed greens and vegetables with crispy pita and sumac dressing", 7.99, "Salads", False),
    ("Greek Salad", "Lettuce, tomatoes, cucumbers, red onion, feta, and olives", 8.99, "Salads", False),
    ("Caesar Salad", "Romaine, parmesan, and Caesar dressing", 8.99, "Salads", False),
    ("Chicken Caesar Salad", "Grilled chicken, romaine, parmesan, and Caesar dressing", 12.99, "Salads", False),
    ("Coleslaw", "Cabbage and carrots in creamy dressing", 5.99, "Salads", False),
    ("Cucumber Yogurt Salad", "Cucumbers, yogurt, garlic, and mint", 6.99, "Salads", False),
    ("Beet Salad", "Seasoned beets with herbs", 6.99, "Salads", False),
    ("Potato Salad", "Potatoes, herbs, and special dressing", 6.99, "Salads", False),
    ("Corn Salad", "Sweet corn, red & green peppers, and herbs", 6.99, "Salads", False),
    ("Pickled Eggplant", "Egyptian-style pickled eggplant", 7.99, "Salads", False),
    ("Egyptian Pickles", "Assorted Egyptian pickles", 5.99, "Salads", False),
    # ---- Soups ----
    ("Kaware' Broth (Cow Trotters Soup)", "Rich traditional Egyptian broth, slow-cooked with herbs and spices", 9.99, "Soups", False),
    ("Orzo Soup (Lisan Asfour)", "Traditional Egyptian orzo pasta soup", 7.99, "Soups", False),
    ("Egyptian Lentil Soup", "Red lentils, vegetables, and authentic spices", 7.99, "Soups", False),
    ("Vegetable Soup", "Fresh vegetables in homemade broth", 7.99, "Soups", False),
    ("Beef & Pasta Soup", "Tender beef, pasta, and vegetables in rich broth", 9.99, "Soups", False),
    # ---- Seafood: fish ----
    ("Whole Fried Fish", "Seasoned and fried to golden perfection", 16.00, "Seafood", False),
    ("Whole Grilled Fish", "Marinated and grilled to perfection", 18.00, "Seafood", True),
    ("Fish Fillet", "Fried or grilled — your choice", 15.00, "Seafood", False),
    # ---- Seafood: shrimp ----
    ("Fried Shrimp", "Crispy fried shrimp", 16.00, "Seafood", False),
    ("Grilled Shrimp", "Grilled shrimp", 17.00, "Seafood", False),
    ("Shrimp Sauteed", "Shrimp sauteed in garlic butter sauce", 18.00, "Seafood", False),
    ("Spicy Shrimp", "Shrimp in our special house sauce", 18.00, "Seafood", False),
    # ---- Seafood: calamari ----
    ("Fried Calamari", "Crispy fried calamari", 15.00, "Seafood", False),
    ("Grilled Calamari", "Char-grilled calamari", 16.00, "Seafood", False),
    # ---- Seafood: crab ----
    ("Blue Crab (Seasonal)", "Steamed or sauced", 22.00, "Seafood", False),
    ("King Crab Legs", "Steamed with butter — market price, confirmed at pickup", 0.00, "Seafood", False),
    # ---- Seafood: platters ----
    ("Mixed Seafood Platter", "Fish, shrimp, calamari and more", 28.00, "Seafood", True),
    ("Shrimp & Calamari Platter", "Shrimp and calamari platter", 24.00, "Seafood", False),
    ("Deluxe Platter", "Fish, shrimp, calamari, and crab — serves 2-3", 35.00, "Seafood", False),
    # ---- Seafood: rice ----
    ("Seafood Rice", "Our signature seasoned rice with mixed seafood", 18.00, "Seafood", False),
    ("Shrimp Rice", "Seasoned rice with shrimp", 16.00, "Seafood", False),
    ("Fish Rice", "Seasoned rice with fish", 16.00, "Seafood", False),
    # ---- Seafood: pasta ----
    ("Seafood Pasta", "Mixed seafood in creamy or red sauce", 18.00, "Seafood", False),
    ("Shrimp Pasta", "Shrimp in creamy or red sauce", 16.00, "Seafood", False),
    ("Calamari Pasta", "Calamari in creamy or red sauce", 16.00, "Seafood", False),
    # ---- Seafood: sides ----
    ("Seafood Soup", "Classic seafood soup", 8.00, "Seafood", False),
    ("Rice", "Steamed rice", 4.00, "Seafood", False),
    ("French Fries", "Crispy fries", 4.00, "Seafood", False),
    ("Garlic Bread", "Toasted garlic bread", 4.00, "Seafood", False),
    ("Extra Sauce", "Any extra sauce", 1.00, "Seafood", False),
    # ---- Grill ----
    ("Egyptian Kofta (Plate)", "Seasoned ground beef with Egyptian spices — served with rice, salad, bread", 18.99, "Grill", True),
    ("Egyptian Kofta (Sandwich)", "Seasoned ground beef in fresh bread", 10.99, "Grill", False),
    ("Alexandrian Liver (Plate)", "Sauteed liver with Alexandrian spices — served with rice, salad, bread", 17.99, "Grill", False),
    ("Alexandrian Liver (Sandwich)", "Sauteed liver in fresh bread", 9.99, "Grill", False),
    ("Charcoal-Grilled Sausage (Plate)", "Juicy grilled sausage — served with rice, salad, bread", 18.99, "Grill", False),
    ("Charcoal-Grilled Sausage (Sandwich)", "Juicy grilled sausage in fresh bread", 10.99, "Grill", False),
    ("Egyptian-Style Sausage (Plate)", "Sausage with a special spice blend — served with rice, salad, bread", 17.99, "Grill", False),
    ("Egyptian-Style Sausage (Sandwich)", "Sausage with special spice blend in fresh bread", 9.99, "Grill", False),
    ("Grilled Beef (Plate)", "Marinated beef, char-grilled — served with rice, salad, bread", 21.99, "Grill", False),
    ("Grilled Beef (Sandwich)", "Marinated char-grilled beef in fresh bread", 12.99, "Grill", False),
    ("Charcoal-Grilled Kebab (Plate)", "Marinated beef chunks grilled over charcoal — served with rice, salad, bread", 22.99, "Grill", False),
    ("Charcoal-Grilled Kebab (Sandwich)", "Marinated beef chunks in fresh bread", 12.99, "Grill", False),
    ("Chicken Pane (Plate)", "Crispy breaded chicken breast — served with rice, salad, bread", 17.99, "Grill", False),
    ("Chicken Pane (Sandwich)", "Crispy breaded chicken breast in fresh bread", 9.99, "Grill", False),
    ("Grilled Chicken (Plate)", "Marinated chicken, char-grilled — served with rice, salad, bread", 18.99, "Grill", False),
    ("Grilled Chicken (Sandwich)", "Marinated char-grilled chicken in fresh bread", 10.99, "Grill", False),
    ("Charcoal-Grilled Hawawshi (Plate)", "Egyptian stuffed bread with seasoned beef", 15.99, "Grill", True),
    # ---- Casseroles ----
    ("Cow Trotters Casserole (Kaware')", "Traditional Egyptian cow trotters casserole", 24.99, "Casseroles", False),
    ("Oxtail Casserole (Akawi)", "Slow-cooked oxtail casserole", 26.99, "Casseroles", False),
    ("Okra with Beef (Bamia)", "Okra cooked with tender beef", 21.99, "Casseroles", True),
    ("Egyptian Baked Rice with Lamb (Rice Ma'amar)", "Baked rice with lamb, Egyptian style", 22.99, "Casseroles", True),
    ("Egyptian Béchemel Pasta (Macarona Bechamel)", "Layered pasta with béchamel sauce", 17.99, "Casseroles", True),
    # ---- Mahshi ----
    ("Egyptian Mombar", "Stuffed with rice, herbs, and spices — priced per lb", 18.99, "Mahshi", False),
    ("Stuffed Grape Leaves (Half Tray)", "Half tray of stuffed grape leaves", 39.99, "Mahshi", False),
    ("Stuffed Grape Leaves (Full Tray)", "Full tray of stuffed grape leaves", 69.99, "Mahshi", False),
    ("Stuffed Cabbage Rolls (Half Tray)", "Half tray of stuffed cabbage rolls", 39.99, "Mahshi", False),
    ("Stuffed Cabbage Rolls (Full Tray)", "Full tray of stuffed cabbage rolls", 69.99, "Mahshi", False),
    ("Stuffed Eggplant (Half Tray)", "Half tray of stuffed eggplant", 39.99, "Mahshi", False),
    ("Stuffed Eggplant (Full Tray)", "Full tray of stuffed eggplant", 69.99, "Mahshi", False),
    ("Stuffed Zucchini (Half Tray)", "Half tray of stuffed zucchini", 42.99, "Mahshi", False),
    ("Stuffed Zucchini (Full Tray)", "Full tray of stuffed zucchini", 74.99, "Mahshi", False),
    ("Stuffed Tomatoes (Half Tray)", "Half tray of stuffed tomatoes", 42.99, "Mahshi", False),
    ("Stuffed Tomatoes (Full Tray)", "Full tray of stuffed tomatoes", 74.99, "Mahshi", False),
    ("Mixed Mahshi Tray (Half Tray)", "Grape leaves, cabbage, zucchini, eggplant, and tomatoes", 44.99, "Mahshi", True),
    ("Mixed Mahshi Tray (Full Tray)", "Grape leaves, cabbage, zucchini, eggplant, and tomatoes", 79.99, "Mahshi", False),
    # ---- Appetizers ----
    ("Dolma", "Stuffed grape leaves — price pending, call the vendor to confirm", 0.00, "Appetizers", False),
]

SAMPLE_VENDORS = [
    {
        "name": "Nile Bakery",
        "tagline": "Fresh baladi bread & pastries",
        "area": "Bellevue",
        "phone": "206-555-0111",
        "fulfillment": "both",
        "delivery_fee": 3.49,
        "dishes": [
            ("Baladi Bread (5 pc)", "Egyptian sourdough flatbread", 3.99, "Bakery", True),
            ("Feteer Meshaltet", "Layered Egyptian pastry", 12.99, "Bakery", False),
            ("Kahk", "Egyptian butter cookies", 8.99, "Desserts", False),
            ("Basbousa", "Semolina cake with syrup", 6.99, "Desserts", True),
        ],
    },
    {
        "name": "Mama Samia's Kitchen",
        "tagline": "Home-style classics like mom made",
        "area": "Seattle",
        "phone": "206-555-0222",
        "fulfillment": "pickup",
        "delivery_fee": 0.00,
        "dishes": [
            ("Molokhia with Chicken", "Molokhia stew with chicken, served with rice", 14.99, "Mains", True),
            ("Koshary", "Rice, lentils, pasta, chickpeas, and spicy tomato sauce", 9.99, "Mains", True),
            ("Fatta", "Layered bread, rice, and meat with garlic-vinegar sauce", 15.99, "Mains", True),
            ("Om Ali", "Egyptian bread pudding", 7.99, "Desserts", True),
            # === v50: Egypt best sellers the menu was missing ===
            ("Konafa", "Crispy shredded pastry layered with sweet cheese and cream, baked golden, soaked in syrup, and crowned with pistachio (كنافة)", 8.99, "Desserts", True),
            ("Qatayef", "Golden folded pancakes stuffed with nuts and cream, kissed with syrup — the Ramadan favorite (قطايف)", 7.99, "Desserts", True),
            ("Ta'ameya (Egyptian Falafel)", "Crisp fava-bean falafel with herbs — served with baladi bread, salad, and tahini (طعمية)", 9.99, "Mains", True),
        ],
    },
]

# (name, description, price, category, featured)
GROCERY_ITEMS: list[tuple[str, str, float, str, bool]] = [
    # ---- Pantry ----
    ("Fava Beans (Ful Medames) - 2 lb bag", "Egyptian fava beans, perfect for ful medames", 4.99, "Pantry", True),
    ("Egyptian Short-Grain Rice - 5 lb bag", "The rice for mahshi, fatta, and everyday cooking", 7.99, "Pantry", False),
    ("Red Lentils - 2 lb bag", "For Egyptian lentil soup (shorbet ads)", 3.99, "Pantry", False),
    ("Dried Chickpeas (Hummus) - 2 lb bag", "For hummus and koshary", 4.49, "Pantry", False),
    ("White Beans (Fasolia) - 2 lb bag", "For fasolia beida stew", 4.99, "Pantry", False),
    ("Dried Molokhia Leaves - 7 oz bag", "Dried molokhia for the classic stew", 5.99, "Pantry", True),
    ("Dried Okra (Bamia) - 7 oz bag", "Dried okra for bamia stew", 6.99, "Pantry", False),
    ("Macaroni Pasta - 1 lb", "For koshary and bechamel", 1.99, "Pantry", False),
    ("Grape Leaves Jar (for Mahshi) - 16 oz", "Brined grape leaves, ready to stuff", 6.99, "Pantry", False),
    ("Canned Ful Medames - 14 oz", "Ready-to-eat fava beans, Egyptian style", 2.49, "Pantry", False),
    ("Egyptian Pickles (Torshi) - 32 oz jar", "Assorted pickled vegetables, Egyptian style", 5.99, "Pantry", False),
    ("Green Olives - 16 oz jar", "Seasoned green olives", 5.99, "Pantry", False),
    # ---- Spices & Herbs ----
    ("Ground Cumin - 4 oz", "Freshly ground, the backbone of Egyptian cooking", 3.99, "Spices & Herbs", True),
    ("Ground Coriander - 4 oz", "For dukkah, ful, and stews", 3.49, "Spices & Herbs", False),
    ("Dukkah Spice Mix - 4 oz", "Nut and spice blend for bread dipping", 4.99, "Spices & Herbs", True),
    ("Baharat (7-Spice Blend) - 4 oz", "All-purpose Egyptian spice blend", 4.49, "Spices & Herbs", False),
    ("Black Seed (Habat El Baraka) - 4 oz", "Nigella seeds for bread and cheese", 5.99, "Spices & Herbs", False),
    ("Dried Mint - 2 oz", "For salads, ful, and tea", 2.99, "Spices & Herbs", False),
    ("Dried Hibiscus (Karkadeh) - 8 oz", "For hot or iced karkadeh drink", 5.99, "Spices & Herbs", False),
    ("Fenugreek Seeds (Helba) - 4 oz", "For helba tea and baking", 2.99, "Spices & Herbs", False),
    ("Ground Turmeric - 4 oz", "For rice and stews", 2.99, "Spices & Herbs", False),
    # ---- Frozen ----
    ("Frozen Molokhia - 14 oz", "Chopped frozen molokhia, ready to cook", 4.99, "Frozen", False),
    ("Frozen Okra - 14 oz", "Whole frozen okra for bamia", 3.99, "Frozen", False),
    ("Frozen Green Fava Beans - 14 oz", "For ful akhdar and stews", 4.49, "Frozen", False),
    # ---- Dairy & Cheese ----
    ("Egyptian White Cheese (Gibna Beida) - per lb", "Salty white cheese for breakfast", 8.99, "Dairy & Cheese", False),
    ("Aged Mish Cheese - 16 oz jar", "Traditional fermented mish", 9.99, "Dairy & Cheese", False),
    ("Karish Cheese - per lb", "Soft fresh karish cheese", 7.99, "Dairy & Cheese", False),
    # ---- Sweets ----
    ("Halva with Pistachio - 1 lb", "Sesame halva with pistachios", 8.99, "Sweets", True),
    ("Blackstrap Molasses (Asal Eswed) - 16 oz", "Sugarcane molasses with tahini — a classic", 5.99, "Sweets", False),
    ("Medjool Dates - 2 lb box", "Soft premium dates", 9.99, "Sweets", False),
    ("Qamar Al-Din (Apricot Paste) - 14 oz", "Dried apricot sheets for Ramadan drinks", 4.99, "Sweets", False),
    # ---- Beverages ----
    ("Egyptian Black Tea (El Arosa) - 100 bags", "The everyday Egyptian tea", 4.99, "Beverages", False),
    ("Sahlab Mix - 7 oz", "Hot orchid-root drink mix with cinnamon", 5.99, "Beverages", False),
]

GROCERY_VENDOR = {
    "name": "Lynnwood Groceries",
    "tagline": "Egyptian pantry staples, spices & sweets",
    "area": "Everett, WA",
    "phone": "206-555-0345",
    "fulfillment": "both",
    "delivery_fee": 3.99,
}

# === Alpha-T Grocery (Oct 2026 — Mediterranean grocery, Everett, WA) ===
# Vendor + grocery items from the store's public catalog (names + current
# prices only; no photos — groceries render emoji tiles; no copied
# descriptions — the short descriptors below are generic, written here.
# Sale prices were captured as the current price (no discount_percent),
# so the listing never shows a stale "was" price. The one out-of-stock
# item at capture time (Pocket Pita Bread - Sam's 4 Count) is omitted.
# Only-if-missing via _ensure_alpha_t() in fill_seed_data, so fresh and
# existing databases (including the live site) all pick it up.
ALPHA_T_VENDOR = {
    "name": "Alpha-T Grocery",
    "tagline": "Mediterranean & Egyptian grocery — Everett",
    "area": "Everett, WA",
    "phone": "",
    "fulfillment": "both",
    "delivery_fee": 3.99,
}

ALPHA_T_ITEMS: list[tuple[str, str, float, str, bool]] = [
    ("El Rashidi El Mizan Chocolate Halawa Spread, 300g", "Middle Eastern sweet — 300g", 7.99, "Sweets", False),
    ("El Rashidi El Mizan Molasses (Asal Eswed), 350g", "Middle Eastern sweet — 350g", 3.99, "Sweets", False),
    ("El Rashidi El Mizan Molasses (Asal Eswed), 650g", "Middle Eastern sweet — 650g", 7.49, "Sweets", False),
    ("Domty Istanbolly White Cheese", "Middle Eastern dairy / cheese", 11.99, "Dairy & Cheese", False),
    ("Bab El Sham Chunky Spicy Crispy Chicken Coating", "Middle Eastern pantry staple", 4.99, "Pantry", False),
    ("Bab El Sham 7 Spices Mix", "Middle Eastern spice / herb", 4.49, "Spices & Herbs", False),
    ("Bab El Sham Dried Basil", "Middle Eastern spice / herb", 3.99, "Spices & Herbs", False),
    ("Bab El Sham Curry Powder", "Middle Eastern spice / herb", 4.49, "Spices & Herbs", False),
    ("Bab El Sham Turmeric", "Middle Eastern spice / herb", 2.99, "Spices & Herbs", False),
    ("Bab El Sham Mixed Meat Spices", "Middle Eastern spice / herb", 3.99, "Spices & Herbs", False),
    ("Bab Elsham Egyptian Liver Spices", "Middle Eastern spice / herb", 2.99, "Spices & Herbs", False),
    ("Bab El Sham Seafood Spices", "Middle Eastern spice / herb", 3.99, "Spices & Herbs", False),
    ("Bab El Sham Potato Spices Mix", "Middle Eastern spice / herb", 3.49, "Spices & Herbs", False),
    ("Bab El Sham Perfect BBQ Blend", "Middle Eastern spice / herb", 2.99, "Spices & Herbs", False),
    ("Bab El Sham Ground Sumac", "Middle Eastern spice / herb", 2.99, "Spices & Herbs", False),
    ("Molto Magnum Chocolate & Hazelnut", "Middle Eastern sweet", 2.99, "Sweets", False),
    ("Baraka Cheese Feta 500g", "Middle Eastern dairy / cheese — 500g", 7.87, "Dairy & Cheese", False),
    ("Ziyad Whole Small Lentils 16oz (453g)", "Middle Eastern pantry staple", 3.8, "Pantry", False),
    ("Small Fava Beans Dried, Ziyad (16 oz)", "Middle Eastern pantry staple", 4.26, "Pantry", False),
    ("Butter Ghee, Ziyad (14 oz)", "Middle Eastern dairy / cheese", 14.99, "Dairy & Cheese", False),
    ("Bay Leaves - Botany 50g", "Middle Eastern spice / herb — 50g", 7.99, "Spices & Herbs", False),
    ("Kunefe with Syrup & Plate, Ipek (200g)", "Middle Eastern sweet", 9.99, "Sweets", False),
    ("Whipped Cream Powder - Basak 150g", "Middle Eastern dairy / cheese — 150g", 4.99, "Dairy & Cheese", False),
    ("Stuffed Grape Leaves - Tamek", "Middle Eastern pantry staple", 8.29, "Pantry", False),
    ("Sesame Seeds - Basak", "Middle Eastern pantry staple", 3.49, "Pantry", False),
    ("Basak - Baking Powder", "Middle Eastern pantry staple", 2.25, "Pantry", False),
    ("Honey with Nuts, Wild Garden (14 oz, 400g)", "Middle Eastern sweet", 7.99, "Sweets", False),
    ("Wild Garden Traditional Tahini Sauce & Dressing 9.9oz", "Middle Eastern pantry staple — 9.9oz", 6.99, "Pantry", False),
    ("Baraka Halva Plain 400g", "Middle Eastern sweet — 400g", 5.49, "Sweets", False),
    ("Seyidoglu Cotton Candy Pistachio 125g", "Middle Eastern sweet — 125g", 4.49, "Sweets", False),
    ("Seyidoglu Cotton Candy Plain 125g", "Middle Eastern sweet — 125g", 3.99, "Sweets", False),
    ("Wellmade Mango Juice 1L", "Middle Eastern drink — 1L", 3.99, "Beverages", False),
    ("Wellmade Mango Mini Juice - 250ml", "Middle Eastern drink — 250ml", 2.45, "Beverages", False),
    ("Rose Water, Baraka (8.45 fl oz / 250ml)", "Middle Eastern pantry staple", 2.99, "Pantry", False),
    ("Baraka Halva Pistachio - 400g", "Middle Eastern sweet — 400g", 6.99, "Sweets", False),
    ("Egyptian Baraka Spicy Pickled Onion 950g", "Middle Eastern pantry staple — 950g", 7.95, "Pantry", False),
    ("Egyptian Spicy Pickled Mixed Vegetables - 1300 g", "Middle Eastern pantry staple — 1300 g", 6.49, "Pantry", False),
    ("Baraka Frozen Minced Molokhia - 400g", "Frozen Middle Eastern grocery — 400g", 2.75, "Frozen", False),
    ("Royal Chef Vermicelli - 454g", "Middle Eastern pantry staple — 454g", 2.75, "Pantry", False),
    ("Baraka White Kidney Beans 850g", "Middle Eastern pantry staple — 850g", 4.99, "Pantry", False),
    ("Baraka Lupini Dry, 850g", "Middle Eastern pantry staple — 850g", 4.8, "Pantry", False),
    ("Baraka Brown Lentils, 908g", "Middle Eastern pantry staple — 908g", 4.19, "Pantry", False),
    ("Baraka Dry Chickpeas - 908g", "Middle Eastern pantry staple — 908g", 4.49, "Pantry", False),
    ("Baraka Small Whole Fava Beans - 908g", "Middle Eastern pantry staple — 908g", 4.4, "Pantry", False),
    ("Baraka Split Red Lentils - 908g", "Middle Eastern pantry staple — 908g", 4.49, "Pantry", False),
    ("Baraka Lupini - 600g jar", "Middle Eastern pantry staple — 600g jar", 4.99, "Pantry", False),
    ("Freez Tamarind", "Middle Eastern drink", 2.6, "Beverages", False),
    ("Freez Kiwi & Lime", "Middle Eastern drink", 2.6, "Beverages", False),
    ("Best Juice juava - (1L / 33.8 oz)", "Middle Eastern drink", 5.89, "Beverages", False),
    ("Best Juice Mango - 235ml", "Middle Eastern drink — 235ml", 1.99, "Beverages", False),
    ("Wild Garden Toum Garlic Aioli - 9.3 oz", "Middle Eastern pantry staple — 9.3 oz", 6.99, "Pantry", False),
    ("Ziyad Frozen Baby Okra - 14oz", "Frozen Middle Eastern grocery — 14oz", 4.49, "Frozen", False),
    ("Ziyad Kefta Spice Blend - 5.5oz", "Middle Eastern spice / herb — 5.5oz", 6.49, "Spices & Herbs", False),
    ("Ziyad Dried Zaatar Leaves - 100 g", "Middle Eastern spice / herb — 100 g", 5.99, "Spices & Herbs", False),
    ("Ziyad Halva Chocolate - 12.34 oz", "Middle Eastern sweet — 12.34 oz", 5.99, "Sweets", False),
    ("Barbican Malt Non-Alcoholic Drink - Halal", "Middle Eastern drink", 2.49, "Beverages", False),
    ("Barbican Apple Non-Alcoholic Drink - Halal", "Middle Eastern drink", 2.49, "Beverages", False),
    ("Halwani Maamoul Date Cookies 480g", "Middle Eastern sweet — 480g", 6.99, "Sweets", False),
    ("Al Afia Grape Leaves 32oz", "Middle Eastern pantry staple — 32oz", 11.9, "Pantry", False),
    ("Ziyad Freekeh 28oz", "Middle Eastern pantry staple — 28oz", 8.25, "Pantry", False),
    ("Ziyad Green Zaatar 16oz (453g)", "Middle Eastern spice / herb", 5.99, "Spices & Herbs", False),
    ("Baraka Husked Wheat 2lb", "Middle Eastern pantry staple — 2lb", 3.99, "Pantry", False),
    ("Baraka Whole Coriander 140 g", "Middle Eastern spice / herb — 140 g", 3.99, "Spices & Herbs", False),
    ("Baraka Sumac 300g", "Middle Eastern spice / herb — 300g", 4.49, "Spices & Herbs", False),
    ("Baraka Biryani Spice 7 oz", "Middle Eastern spice / herb — 7 oz", 5.99, "Spices & Herbs", False),
    ("Baraka Seven Spices 7.5 oz", "Middle Eastern spice / herb — 7.5 oz", 5.49, "Spices & Herbs", False),
    ("Baraka Tawook Spice 8 oz", "Middle Eastern spice / herb — 8 oz", 5.99, "Spices & Herbs", False),
    ("Baraka Grill & BBQ Spice 8 oz", "Middle Eastern spice / herb — 8 oz", 5.99, "Spices & Herbs", False),
    ("Baraka Kabseh Spice 8 oz", "Middle Eastern spice / herb — 8 oz", 5.99, "Spices & Herbs", False),
    ("Baraka Chicken Shawarma Spice 7.5 oz", "Middle Eastern spice / herb — 7.5 oz", 5.99, "Spices & Herbs", False),
    ("Cream Natural - Puck 6oz", "Middle Eastern dairy / cheese — 6oz", 3.99, "Dairy & Cheese", False),
    ("Baraka Meat Shawarma Spice 7.5 oz", "Middle Eastern spice / herb — 7.5 oz", 5.99, "Spices & Herbs", False),
    ("Baraka Bay Leaves 25 g", "Middle Eastern spice / herb — 25 g", 2.99, "Spices & Herbs", False),
    ("Baraka Frozen Taro (Coulcas) with Spices 400g", "Frozen Middle Eastern grocery — 400g", 3.25, "Frozen", False),
    ("Roomy Cheese", "Middle Eastern dairy / cheese", 9.99, "Dairy & Cheese", False),
    ("Merve Beef Soujouk Mild - 1LB", "Middle Eastern pantry staple — 1LB", 12.99, "Pantry", False),
    ("Sultan Sliced Basterma 10oz (0.66 Ib)", "Middle Eastern pantry staple", 16.99, "Pantry", False),
    ("Shamshiri Persian Tea, 250g", "Middle Eastern drink — 250g", 10.49, "Beverages", False),
    ("Shamshiri Earl Grey Tea, 250g", "Middle Eastern drink — 250g", 11.99, "Beverages", False),
    ("Shamshiri Green Tea, 250g", "Middle Eastern drink — 250g", 9.99, "Beverages", False),
    ("Crescent Premium Quality Pocket Pita Bread (Whole Wheat)", "Middle Eastern pantry staple", 2.49, "Pantry", False),
    ("Crescent Premium Quality Pocket Pita Bread (White)", "Middle Eastern pantry staple", 2.49, "Pantry", False),
    ("Crescent Turmeric, 7oz", "Middle Eastern spice / herb — 7oz", 5.49, "Spices & Herbs", False),
    ("Crescent Curry Powder Mild, 7oz", "Middle Eastern spice / herb — 7oz", 5.49, "Spices & Herbs", False),
    ("Crescent Paprika, 7oz", "Middle Eastern spice / herb — 7oz", 5.49, "Spices & Herbs", False),
    ("Abu Auf Lemon & Ginger, 12 bags", "Middle Eastern pantry staple — 12 bags", 1.49, "Pantry", False),
    ("Faiez Al Suhagy White Beans (Fasolia Beida), 400g", "Middle Eastern pantry staple — 400g", 2.99, "Pantry", False),
    ("Abu Auf Anise, 12 bags", "Middle Eastern pantry staple — 12 bags", 1.49, "Pantry", False),
    ("Safi Roasted Sesame Oil 16 Fl. Oz", "Middle Eastern pantry staple", 7.99, "Pantry", False),
    ("Crescent Sumac, 7oz", "Middle Eastern spice / herb — 7oz", 5.99, "Spices & Herbs", False),
    ("ARZ Labne Kefir Cheese, 16oz", "Middle Eastern dairy / cheese — 16oz", 4.99, "Dairy & Cheese", False),
    ("Turkish Labneh 400g", "Middle Eastern dairy / cheese — 400g", 5.99, "Dairy & Cheese", False),
    ("ARZ Original Ayran Yogurt Drink, 16 fl oz", "Middle Eastern dairy / cheese", 2.79, "Dairy & Cheese", False),
    ("Royal Palm Premium Date Paste 14.2oz (400g)", "Middle Eastern sweet", 3.99, "Sweets", False),
    ("Freez Pomegranate", "Middle Eastern drink", 2.6, "Beverages", False),
    ("Fillo Pastry Sheets - Kontos #4", "Middle Eastern pantry staple", 5.99, "Pantry", False),
    ("Molokhya Minced - Montana", "Frozen Middle Eastern grocery", 2.99, "Frozen", False),
    ("Pickled Turnips Sliced - Al Dayaa (1000g)", "Middle Eastern pantry staple", 5.99, "Pantry", False),
    ("Tahini - Al Dayaa (800g)", "Middle Eastern pantry staple", 10.99, "Pantry", False),
    ("Fava Beans, Egyptian Recipe - California Garden", "Middle Eastern pantry staple", 2.59, "Pantry", False),
    ("Fava Beans, Palestinian Recipe - California Garden", "Middle Eastern pantry staple", 2.19, "Pantry", False),
    ("Vacuumed Sukari Dates – 100% Natural Saudi Dates (2.2 lb / 1kg)", "Middle Eastern sweet", 8.99, "Sweets", False),
    ("Eggplant with Tahini(Baba Ganoush) - Four Seasons (400G)", "Middle Eastern pantry staple", 6.49, "Pantry", False),
    ("Grilled Eggplant - Four Seasons (2.9 lb)", "Middle Eastern pantry staple", 12.99, "Pantry", False),
    ("BaKe ROLZ - Ketchup Flavor", "Middle Eastern pantry staple", 2.99, "Pantry", False),
    ("BaKe ROLZ - Olive Flavor", "Middle Eastern pantry staple", 3.49, "Pantry", False),
    ("Maamoul with Dates – Traditional Date Filled Cookies", "Middle Eastern sweet", 1.89, "Sweets", False),
    ("Mandolin", "Middle Eastern sweet", 2.89, "Sweets", False),
    ("Pistachio Spreadable Cream", "Middle Eastern sweet", 9.99, "Sweets", False),
    ("Authentic Lebanese Pita Bread - Sam's", "Middle Eastern pantry staple", 2.99, "Pantry", False),
    ("100% Whole Wheat Pita Bread - Golden Mill", "Middle Eastern pantry staple", 2.99, "Pantry", False),
    ("Almond Halawa – El Rashidi El Mizan", "Middle Eastern sweet", 1.99, "Sweets", False),
    ("Plain Halawa – El Bawadi Traditional Sesame", "Middle Eastern sweet", 1.99, "Sweets", False),
    ("Sugar Cane Molasses – Nemah", "Middle Eastern sweet", 2.99, "Sweets", False),
    ("Ahmad Tea Special Blend – Black Tea Bags (100 Count)", "Middle Eastern drink", 7.99, "Beverages", False),
    ("Kharaz Yellow Label Black Tea – Lipton", "Middle Eastern drink", 5.99, "Beverages", False),
    ("Al Arosa - Black Tea", "Middle Eastern drink", 4.99, "Beverages", False),
    ("Red Split Lentils - Al Mazrah 2 LB", "Middle Eastern pantry staple — 2 LB", 4.49, "Pantry", False),
    ("Freekeh - Crescent", "Middle Eastern pantry staple", 6.5, "Pantry", False),
    ("Basil Seed Pomegranate Drink (6 Count)", "Middle Eastern drink", 10.8, "Beverages", False),
    ("Basil Seed Pomegranate Drink", "Middle Eastern drink", 1.99, "Beverages", False),
    ("Basil Seed Mango Drink (6 Count)", "Middle Eastern drink", 10.8, "Beverages", False),
    ("Basil Seed Mango Drink", "Middle Eastern drink", 1.99, "Beverages", False),
    ("Freez, Lemon & Mint (6 Count)", "Middle Eastern drink", 14.99, "Beverages", False),
    ("Freez, Lemon & Mint", "Middle Eastern drink", 2.6, "Beverages", False),
    ("Kalamata Olives - Sultan Garden (1kg)", "Middle Eastern pantry staple", 10.99, "Pantry", False),
    ("Blossom Water - Crescent", "Middle Eastern pantry staple", 3.75, "Pantry", False),
    ("Bechamel with Cheese Sauce Mix - Ebhar Food (50g)", "Middle Eastern pantry staple", 2.99, "Pantry", False),
    ("Split Fava Beans - Crescent", "Middle Eastern pantry staple", 3.75, "Pantry", False),
    ("Semolina - Crescent", "Middle Eastern pantry staple", 3.99, "Pantry", False),
    ("Farina - Crescent", "Middle Eastern pantry staple", 3.99, "Pantry", False),
    ("Halava Plain - Al Kanater (1 lb)", "Middle Eastern sweet", 5.99, "Sweets", False),
    ("Dried Apricots - Crescent", "Middle Eastern sweet", 7.99, "Sweets", False),
    ("Vanilla Orange Sugar - Dreem (4g)", "Middle Eastern pantry staple", 1.99, "Pantry", False),
    ("Vanilla Sugar - Dreem (4g)", "Middle Eastern pantry staple", 1.99, "Pantry", False),
    ("Whipping Cream (Sachet) - Dreem", "Middle Eastern dairy / cheese", 6.49, "Dairy & Cheese", False),
    ("Palm Dates - Royal", "Middle Eastern sweet", 9.99, "Sweets", False),
    ("Rose Water - Crescent", "Middle Eastern pantry staple", 3.99, "Pantry", False),
    ("PLAIN Fava Beans - California Garden", "Middle Eastern pantry staple", 2.25, "Pantry", False),
    ("Tahini - Al Mazrah 2 LB", "Middle Eastern pantry staple — 2 LB", 12.99, "Pantry", False),
    ("Fine Cut Vermicelli Noodles (Reshteh Or Sharya) - Sipa", "Middle Eastern pantry staple", 3.49, "Pantry", False),
    ("Taro & Spices - Silva", "Frozen Middle Eastern grocery", 2.99, "Frozen", False),
    ("Vimto Soft Drink - 330 ml", "Middle Eastern drink — 330 ml", 1.99, "Beverages", False),
    ("Mixed Pickles - Al Dayaa", "Middle Eastern pantry staple", 5.99, "Pantry", False),
    ("Shatta Hot Pepper Sauce - Al Dayaa", "Middle Eastern pantry staple", 4.49, "Pantry", False),
    ("Okra Zero - Silva", "Frozen Middle Eastern grocery", 3.99, "Frozen", False),
    ("Grape Leaves - Orlando", "Middle Eastern pantry staple", 9.49, "Pantry", False),
    ("Kataifi (Kadayif) Phyllo - Kontos", "Middle Eastern pantry staple", 6.99, "Pantry", False),
    ("Pomegranate Molasses - El Mazrah", "Middle Eastern pantry staple", 4.49, "Pantry", False),
]

def _ensure_alpha_t(db):
    """Create Alpha-T Grocery + its items only where missing (idempotent).
    Called from fill_seed_data on every startup, which is also the tail
    of seed(), so fresh and existing databases both get it."""
    vendor = _get_vendor(db, ALPHA_T_VENDOR["name"])
    if not vendor:
        vendor = models.Vendor(
            name=ALPHA_T_VENDOR["name"],
            tagline=ALPHA_T_VENDOR["tagline"],
            area=ALPHA_T_VENDOR["area"],
            phone=ALPHA_T_VENDOR["phone"],
            fulfillment=ALPHA_T_VENDOR["fulfillment"],
            delivery_fee=Decimal(str(ALPHA_T_VENDOR["delivery_fee"])),
        )
        db.add(vendor)
        db.flush()
        _add_dishes(db, vendor, ALPHA_T_ITEMS)
    else:
        _have = {
            d.name
            for d in db.scalars(
                select(models.Dish).where(models.Dish.vendor_id == vendor.id)
            )
        }
        _missing = [item for item in ALPHA_T_ITEMS if item[0] not in _have]
        if _missing:
            _add_dishes(db, vendor, _missing)
    db.flush()

# Um Sohaib's Kitchen (Oct 2026 — from the vendor's printed menu flyer).
# Location/phone were not on the flyer: left empty, the vendor edits them in the portal.
UM_SOHAIB_VENDOR = {
    "name": "Um Sohaib's Kitchen",
    "tagline": "Authentic Homemade Arabic Food · أكل عربي بيتي أصيل — "
               "All dishes prepared fresh to order · جميع الأكلات تُحضَّر طازجة حسب الطلب",
    "area": "",
    "phone": "",
    "fulfillment": "pickup",
    "delivery_fee": 0.00,
}

# (name, description [Arabic name first], price, category, featured, photo_file)
UM_SOHAIB_MENU: list[tuple[str, str, float, str, bool, str]] = [
    ("Mansaf", "المنسف · Traditional mansaf — choose a serving size", 50.00, "Mains", True, "um_mansaf.jpg"),
    ("Maqlouba", "المقلوبة · Upside-down rice — chicken or meat, serves 6", 65.00, "Mains", True, "um_maqlouba.jpg"),
    ("Musakhan", "المسخن · Sumac chicken over flatbread — whole tray", 45.00, "Mains", False, "um_musakhan.jpg"),
    ("Ouzi", "الأوزي · Fragrant spiced rice platter", 45.00, "Mains", False, "um_ouzi.jpg"),
    ("Biryani", "برياني · Spiced biryani rice", 45.00, "Mains", False, "um_biryani.jpg"),
    ("Shish Barak", "الشيشبرك · Meat dumplings in yogurt sauce", 50.00, "Mains", False, "um_shishbarak.jpg"),
    ("Freekeh with Chicken", "فريكة مع دجاج · Roasted green wheat with chicken", 45.00, "Mains", False, "um_freekeh.jpg"),
    ("Stuffed Cabbage Rolls", "ملفوف محشي · Stuffed cabbage leaves", 55.00, "Mains", False, ""),
    ("Stuffed Grape Leaves", "ورق عنب (دوالي) · Stuffed grape leaves — choose your pot", 60.00, "Mains", True, ""),
    ("Yalanji (Stuffed Vegetables)", "يالنجي · Stuffed vegetables (yalanji)", 50.00, "Mains", False, "um_yalanji.jpg"),
    ("Chicken Tray with Rice", "صينية دجاج مع رز · Roasted chicken tray with rice", 45.00, "Mains", False, "um_chicken_tray.jpg"),
    ("Kofta with Tahini & Rice", "صينية كفتة بالطحينية مع رز · Kofta tray with tahini sauce and rice", 55.00, "Mains", False, ""),
    ("Kibbeh", "الكبة · Crispy stuffed kibbeh — per piece / للحبة", 3.00, "Mains", False, "um_kibbeh.jpg"),
    ("Meat Sfiha", "صفيحة لحمة · Savory meat pastry — per piece / للحبة", 3.50, "Pastries", False, "um_sfiha.jpg"),
    ("Spinach Pastry", "سبانخ · Spinach-filled pastry — per piece / للحبة", 2.50, "Pastries", False, "um_spinach_pastry.jpg"),
    ("Cheese Pastry", "جبنة · Cheese-filled pastry — per piece / للحبة", 2.50, "Pastries", False, "um_cheese_pastry.jpg"),
    ("Mini Pizza", "ميني بيتزا · Mini pizza — per piece / للحبة", 2.50, "Pastries", True, "um_mini_pizza.jpg"),
    ("Salad", "السلطة · Fresh chopped salad — one size / حجم واحد", 25.00, "Salad", False, ""),
]
# Dishes with "" photo fall back to the existing PHOTO_RULES matches:
#   Stuffed Cabbage Rolls -> dolma.jpg, Stuffed Grape Leaves -> dolma.jpg,
#   Kofta with Tahini & Rice -> kofta.jpg, Salad -> meze.jpg (generic 'salad' rule).

# (dish_name, group_name, [(choice_label, price_delta), ...]) — single-select, required.
UM_SOHAIB_OPTIONS: list[tuple[str, str, list[tuple[str, float]]]] = [
    ("Mansaf", "Serving size", [("2 persons", 0), ("4 persons", 50), ("6 persons", 100)]),
    ("Maqlouba", "Protein", [("Chicken (serves 6)", 0), ("Meat (serves 6)", 15)]),
    ("Stuffed Grape Leaves", "Pot", [("Dawali with ground meat", 0), ("With meat & ribs", 20), ("With meat, ribs & kousa", 40)]),
]


# v53: Arabic dish descriptions (English description -> Arabic). Fills Dish.description_ar
# only when empty, same contract as ingredients/names — vendor edits win.
DISH_DESCRIPTIONS_AR: dict[str, str] = {
    "All-purpose Egyptian spice blend": "خلطة بهارات مصرية لكل الاستخدامات",
    "Any extra sauce": "أي صوص إضافي",
    "Assorted Egyptian pickles": "مخللات مصرية مشكلة",
    "Assorted pickled vegetables, Egyptian style": "خضار مخلل مشكل على الطريقة المصرية",
    "Baked rice with lamb, Egyptian style": "أرز بالفرن مع لحم الضأن على الطريقة المصرية",
    "Brined grape leaves, ready to stuff": "ورق عنب مملح جاهز للحشو",
    "Cabbage and carrots in creamy dressing": "كرنب وجزر بصوص كريمي",
    "Calamari in creamy or red sauce": "كاليماري بالصوص الكريمي أو الأحمر",
    "Char-grilled calamari": "كاليماري مشوي على الفحم",
    "Chickpeas blended with tahini, lemon, and olive oil": "حمص مهروس بالطحينة والليمون وزيت الزيتون",
    "Chopped frozen molokhia, ready to cook": "ملوخية مفرومة مجمدة جاهزة للطبخ",
    "Classic seafood soup": "شوربة مأكولات بحرية كلاسيكية",
    "Creamy tahini with lemon and fresh herbs": "طحينة كريمية بالليمون والأعشاب الطازجة",
    "Crispy breaded chicken breast in fresh bread": "صدر دجاج مقرمش بانيه في عيش طازج",
    "Crispy breaded chicken breast — served with rice, salad, bread": "صدر دجاج مقرمش بانيه — يقدم مع الأرز والسلطة والعيش",
    "Crispy fried calamari": "كاليماري مقلي مقرمش",
    "Crispy fried shrimp": "جمبري مقلي مقرمش",
    "Crispy fries": "بطاطس مقلية مقرمشة",
    "Cucumbers, yogurt, garlic, and mint": "خيار وزبادي وثوم ونعناع",
    "Dried apricot sheets for Ramadan drinks": "قمر الدين لمشروبات رمضان",
    "Dried molokhia for the classic stew": "ملوخية مجففة للطبخة الكلاسيكية",
    "Dried okra for bamia stew": "بامية مجففة لطبخ البامية",
    "Egyptian fava beans, perfect for ful medames": "فول مصري مثالي للفول المدمس",
    "Egyptian stuffed bread with seasoned beef": "حواوشي مصري محشي بلحم بقري متبل",
    "Egyptian-style pickled eggplant": "باذنجان مخلل على الطريقة المصرية",
    "Fish, shrimp, calamari and more": "سمك وجمبري وكاليماري وأكثر",
    "Fish, shrimp, calamari, and crab — serves 2-3": "سمك وجمبري وكاليماري وسلطعون — يكفي ٢-٣ أشخاص",
    "For Egyptian lentil soup (shorbet ads)": "لشوربة العدس المصرية",
    "For dukkah, ful, and stews": "للدقة والفول والطواجن",
    "For fasolia beida stew": "لطبخ الفاصوليا البيضاء",
    "For ful akhdar and stews": "للفول الأخضر والطواجن",
    "For helba tea and baking": "لشاي الحلبة والمخبوزات",
    "For hot or iced karkadeh drink": "لمشروب الكركديه الساخن أو المثلج",
    "For hummus and koshary": "للحمص والكشري",
    "For koshary and bechamel": "للكشري والبشاميل",
    "For rice and stews": "للأرز والطواجن",
    "For salads, ful, and tea": "للسلطات والفول والشاي",
    "Fresh parsley, tomatoes, onions, bulgur, and lemon": "بقدونس طازج وطماطم وبصل وبرغل وليمون",
    "Fresh tomatoes, cucumbers, red onion, and herbs": "طماطم وخيار طازج وبصل أحمر وأعشاب",
    "Fresh vegetables in homemade broth": "خضار طازج في مرق بيتي",
    "Freshly ground, the backbone of Egyptian cooking": "مطحون طازج، أساس الطبخ المصري",
    "Fried or grilled — your choice": "مقلي أو مشوي — على اختيارك",
    "Full tray of stuffed cabbage rolls": "صينية كاملة من الكرنب المحشي",
    "Full tray of stuffed eggplant": "صينية كاملة من الباذنجان المحشي",
    "Full tray of stuffed grape leaves": "صينية كاملة من ورق العنب المحشي",
    "Full tray of stuffed tomatoes": "صينية كاملة من الطماطم المحشية",
    "Full tray of stuffed zucchini": "صينية كاملة من الكوسة المحشية",
    "Grape leaves, cabbage, zucchini, eggplant, and tomatoes": "ورق عنب وكرنب وكوسة وباذنجان وطماطم",
    "Grilled chicken, romaine, parmesan, and Caesar dressing": "دجاج مشوي وخس روماني وبارميزان وصوص سيزر",
    "Grilled shrimp": "جمبري مشوي",
    "Half tray of stuffed cabbage rolls": "نصف صينية من الكرنب المحشي",
    "Half tray of stuffed eggplant": "نصف صينية من الباذنجان المحشي",
    "Half tray of stuffed grape leaves": "نصف صينية من ورق العنب المحشي",
    "Half tray of stuffed tomatoes": "نصف صينية من الطماطم المحشية",
    "Half tray of stuffed zucchini": "نصف صينية من الكوسة المحشية",
    "Hot orchid-root drink mix with cinnamon": "مشروب السحلب الساخن بالقرفة",
    "Juicy grilled sausage in fresh bread": "سجق مشوي طري في عيش طازج",
    "Juicy grilled sausage — served with rice, salad, bread": "سجق مشوي طري — يقدم مع الأرز والسلطة والعيش",
    "Layered pasta with béchamel sauce": "مكرونة بالبشاميل في طبقات",
    "Lettuce, tomatoes, cucumbers, red onion, feta, and olives": "خس وطماطم وخيار وبصل أحمر وجبنة فيتا وزيتون",
    "Marinated and grilled to perfection": "متبل ومشوي بإتقان",
    "Marinated beef chunks grilled over charcoal — served with rice, salad, bread": "قطع لحم بقري متبلة مشوية على الفحم — تقدم مع الأرز والسلطة والعيش",
    "Marinated beef chunks in fresh bread": "قطع لحم بقري متبلة في عيش طازج",
    "Marinated beef, char-grilled — served with rice, salad, bread": "لحم بقري متبل مشوي على الفحم — يقدم مع الأرز والسلطة والعيش",
    "Marinated char-grilled beef in fresh bread": "لحم بقري متبل مشوي على الفحم في عيش طازج",
    "Marinated char-grilled chicken in fresh bread": "دجاج متبل مشوي على الفحم في عيش طازج",
    "Marinated chicken, char-grilled — served with rice, salad, bread": "دجاج متبل مشوي على الفحم — يقدم مع الأرز والسلطة والعيش",
    "Mixed greens and vegetables with crispy pita and sumac dressing": "خضار وورقيات مشكلة مع خبز بيتا مقرمش وصوص السماق",
    "Mixed seafood in creamy or red sauce": "مأكولات بحرية مشكلة بالصوص الكريمي أو الأحمر",
    "Nigella seeds for bread and cheese": "حبة البركة للعيش والجبن",
    "Nut and spice blend for bread dipping": "خلطة المكسرات والبهارات لغمس العيش",
    "Okra cooked with tender beef": "بامية مطبوخة مع لحم بقري طري",
    "Our signature seasoned rice with mixed seafood": "أرزنا المتبل المميز مع المأكولات البحرية المشكلة",
    "Potatoes, herbs, and special dressing": "بطاطس وأعشاب وصوص خاص",
    "Ready-to-eat fava beans, Egyptian style": "فول مصري جاهز للأكل",
    "Red lentils, vegetables, and authentic spices": "عدس أحمر وخضار وبهارات أصيلة",
    "Rich traditional Egyptian broth, slow-cooked with herbs and spices": "مرق مصري تقليدي غني، مطهو ببطء بالأعشاب والبهارات",
    "Romaine, parmesan, and Caesar dressing": "خس روماني وبارميزان وصوص سيزر",
    "Salty white cheese for breakfast": "جبنة بيضاء مالحة للفطار",
    "Sausage with a special spice blend — served with rice, salad, bread": "سجق بخلطة بهارات خاصة — يقدم مع الأرز والسلطة والعيش",
    "Sausage with special spice blend in fresh bread": "سجق بخلطة بهارات خاصة في عيش طازج",
    "Sauteed liver in fresh bread": "كبدة سوتيه في عيش طازج",
    "Sauteed liver with Alexandrian spices — served with rice, salad, bread": "كبدة سوتيه ببهارات إسكندراني — تقدم مع الأرز والسلطة والعيش",
    "Seasoned and fried to golden perfection": "متبل ومقلي حتى يصبح ذهبياً",
    "Seasoned beets with herbs": "بنجر متبل بالأعشاب",
    "Seasoned green olives": "زيتون أخضر متبل",
    "Seasoned ground beef in fresh bread": "لحم بقري مفروم متبل في عيش طازج",
    "Seasoned ground beef with Egyptian spices — served with rice, salad, bread": "لحم بقري مفروم ببهارات مصرية — يقدم مع الأرز والسلطة والعيش",
    "Seasoned rice with fish": "أرز متبل مع السمك",
    "Seasoned rice with shrimp": "أرز متبل مع الجمبري",
    "Sesame halva with pistachios": "حلاوة طحينية بالفستق",
    "Shrimp and calamari platter": "طبق جمبري وكاليماري",
    "Shrimp in creamy or red sauce": "جمبري بالصوص الكريمي أو الأحمر",
    "Shrimp in our special house sauce": "جمبري بصوصنا الخاص",
    "Shrimp sauteed in garlic butter sauce": "جمبري سوتيه بصوص زبدة الثوم",
    "Slow-cooked oxtail casserole": "طاجن ذيل بقري مطهو ببطء",
    "Smoked eggplant blended with tahini and special spices": "باذنجان مشوي مهروس بالطحينة والبهارات الخاصة",
    "Soft fresh karish cheese": "جبنة قريش طرية طازجة",
    "Soft premium dates": "تمر طري فاخر",
    "Steamed or sauced": "على البخار أو بالصوص",
    "Steamed rice": "أرز مطهو على البخار",
    "Steamed with butter — market price, confirmed at pickup": "مطهو على البخار بالزبدة — السعر حسب السوق ويؤكد عند الاستلام",
    "Stuffed grape leaves — price pending, call the vendor to confirm": "ورق عنب محشي — السعر قيد التحديد، اتصل بالطباخ للتأكيد",
    "Stuffed with rice, herbs, and spices — priced per lb": "محشي بالأرز والأعشاب والبهارات — السعر للرطل",
    "Sugarcane molasses with tahini — a classic": "عسل أسود بالطحينة — كلاسيكية",
    "Sweet corn, red & green peppers, and herbs": "ذرة حلوة وفلفل أحمر وأخضر وأعشاب",
    "Tender beef, pasta, and vegetables in rich broth": "لحم بقري طري ومكرونة وخضار في مرق غني",
    "The everyday Egyptian tea": "الشاي المصري اليومي",
    "The rice for mahshi, fatta, and everyday cooking": "الأرز المناسب للمحشي والفتة والطبخ اليومي",
    "Toasted garlic bread": "عيش بالثوم محمص",
    "Traditional Egyptian cow trotters casserole": "طاجن كوارع بقري مصري تقليدي",
    "Traditional Egyptian orzo pasta soup": "شوربة لسان العصفور المصرية التقليدية",
    "Traditional fermented mish": "مش تقليدي مخمر",
    "Whole frozen okra for bamia": "بامية كاملة مجمدة",
    "Egyptian sourdough flatbread": "عيش بلدي مصري بالتخمير الطبيعي",
    "Layered Egyptian pastry": "فطير مصري بطبقات هشة",
    "Egyptian butter cookies": "كحك مصري بالسمنة",
    "Semolina cake with syrup": "بسبوسة بالسميد والشيرة",
    "Molokhia stew with chicken, served with rice": "ملوخية بالدجاج تقدم مع الأرز",
    "Rice, lentils, pasta, chickpeas, and spicy tomato sauce": "أرز وعدس ومكرونة وحمص مع صلصة طماطم حارة",
    "Layered bread, rice, and meat with garlic-vinegar sauce": "عيش وأرز ولحم في طبقات مع صلصة الثوم والخل",
    "Egyptian bread pudding": "بودينج العيش المصري",
    "Crispy shredded pastry layered with sweet cheese and cream, baked golden, soaked in syrup, and crowned with pistachio (كنافة)": "كنافة مقرمشة بطبقات من الجبنة الحلوة والقشطة، مخبوزة حتى تصبح ذهبية ومغمورة بالشيرة ومزينة بالفستق",
    "Golden folded pancakes stuffed with nuts and cream, kissed with syrup — the Ramadan favorite (قطايف)": "قطايف ذهبية محشوة بالمكسرات والقشطة ومغموسة بالشيرة — المفضلة في رمضان",
    "Crisp fava-bean falafel with herbs — served with baladi bread, salad, and tahini (طعمية)": "طعمية مقرمشة من الفول بالأعشاب — تقدم مع العيش البلدي والسلطة والطحينة",
    "الأوزي · Fragrant spiced rice platter": "الأوزي · طبق أرز متبل عطري",
    "السلطة · Fresh chopped salad — one size / حجم واحد": "السلطة · سلطة مفرومة طازجة — حجم واحد",
    "الشيشبرك · Meat dumplings in yogurt sauce": "الشيشبرك · عجائن محشوة باللحم في صلصة الزبادي",
    "الكبة · Crispy stuffed kibbeh — per piece / للحبة": "الكبة · كبة محشية مقرمشة — للحبة",
    "المسخن · Sumac chicken over flatbread — whole tray": "المسخن · دجاج بالسماق على خبز مسطح — صينية كاملة",
    "المقلوبة · Upside-down rice — chicken or meat, serves 6": "المقلوبة · أرز مقلوب — دجاج أو لحم، يكفي ٦ أشخاص",
    "المنسف · Traditional mansaf — choose a serving size": "المنسف · منسف تقليدي — اختر حجم الحصة",
    "برياني · Spiced biryani rice": "برياني · أرز برياني متبل",
    "جبنة · Cheese-filled pastry — per piece / للحبة": "جبنة · معجنات محشوة بالجبنة — للحبة",
    "سبانخ · Spinach-filled pastry — per piece / للحبة": "سبانخ · معجنات محشوة بالسبانخ — للحبة",
    "صفيحة لحمة · Savory meat pastry — per piece / للحبة": "صفيحة لحمة · معجنات باللحم — للحبة",
    "صينية دجاج مع رز · Roasted chicken tray with rice": "صينية دجاج مع رز · صينية دجاج محمر مع الأرز",
    "صينية كفتة بالطحينية مع رز · Kofta tray with tahini sauce and rice": "صينية كفتة بالطحينية مع رز · صينية كفتة بصلصة الطحينة والأرز",
    "فريكة مع دجاج · Roasted green wheat with chicken": "فريكة مع دجاج · قمح أخضر محمر مع الدجاج",
    "ملفوف محشي · Stuffed cabbage leaves": "ملفوف محشي · ورق كرنب محشي",
    "ميني بيتزا · Mini pizza — per piece / للحبة": "ميني بيتزا · بيتزا صغيرة — للحبة",
    "ورق عنب (دوالي) · Stuffed grape leaves — choose your pot": "ورق عنب (دوالي) · ورق عنب محشي — اختر نوع القدر",
    "يالنجي · Stuffed vegetables (yalanji)": "يالنجي · خضار محشي (يالنجي)",
}

# Arabic names for the seeded option groups and their choices.
OPTION_GROUPS_AR: dict[str, str] = {"Serving size": "حجم الحصة", "Protein": "نوع البروتين", "Pot": "نوع القدر"}
OPTION_CHOICES_AR: dict[str, str] = {
    "2 persons": "لشخصين", "4 persons": "لـ ٤ أشخاص", "6 persons": "لـ ٦ أشخاص",
    "Chicken (serves 6)": "دجاج (يكفي ٦)", "Meat (serves 6)": "لحم (يكفي ٦)",
    "Dawali with ground meat": "دوالي باللحم المفروم", "With meat & ribs": "باللحم والضلوع",
    "With meat, ribs & kousa": "باللحم والضلوع والكوسة",
}

# (dish_name -> ingredients text) — fills Dish.ingredients for the prepared-food
# dishes so the dish page "Ingredients" section has data. Only fills when
# empty, so vendor edits in the portal are never overwritten.
DISH_INGREDIENTS: dict[str, str] = {
    # --- Omar Caboose: salads & cold ---
    "Egyptian Baladi Salad": "Tomatoes, cucumbers, onions, parsley, lemon juice, olive oil",
    "Tahini Salad": "Tahini, lemon juice, garlic, cumin, olive oil, parsley",
    "Baba Ghanoush": "Roasted eggplant, tahini, lemon juice, garlic, olive oil",
    "Hummus": "Chickpeas, tahini, lemon juice, garlic, olive oil, paprika",
    "Tabbouleh": "Parsley, bulgur, tomatoes, mint, lemon juice, olive oil",
    "Fattoush": "Mixed greens, tomatoes, cucumbers, radish, toasted pita, sumac dressing",
    "Greek Salad": "Tomatoes, cucumbers, red onion, olives, feta cheese, olive oil",
    "Caesar Salad": "Romaine lettuce, parmesan, croutons, Caesar dressing",
    "Chicken Caesar Salad": "Grilled chicken, romaine lettuce, parmesan, croutons, Caesar dressing",
    "Coleslaw": "Cabbage, carrots, mayonnaise dressing",
    "Cucumber Yogurt Salad": "Cucumbers, yogurt, garlic, mint, olive oil",
    "Beet Salad": "Beets, garlic, lemon juice, olive oil, parsley",
    "Potato Salad": "Potatoes, mayonnaise, mustard, eggs, pickles",
    "Corn Salad": "Corn, peppers, mayonnaise, lemon juice",
    "Pickled Eggplant": "Baby eggplant, garlic, vinegar, chili, coriander",
    "Egyptian Pickles": "Mixed pickled vegetables, vinegar brine, chili",
    # --- Omar Caboose: soups ---
    "Kaware' Broth (Cow Trotters Soup)": "Cow trotters, garlic, vinegar, lemon, cumin",
    "Orzo Soup (Lisan Asfour)": "Orzo pasta, chicken broth, butter",
    "Egyptian Lentil Soup": "Red lentils, onions, carrots, cumin, lemon",
    "Vegetable Soup": "Mixed vegetables, tomato broth",
    "Beef & Pasta Soup": "Beef, pasta, mixed vegetables, broth",
    "Seafood Soup": "Mixed seafood, fish broth, garlic, lemon",
    # --- Omar Caboose: seafood ---
    "Whole Fried Fish": "Whole fish, flour, garlic, cumin, lemon",
    "Whole Grilled Fish": "Whole fish, garlic, lemon, olive oil, spices",
    "Fish Fillet": "Fish fillet, garlic, lemon, cumin",
    "Fried Shrimp": "Shrimp, flour, garlic, lemon",
    "Grilled Shrimp": "Shrimp, garlic, lemon, olive oil",
    "Shrimp Sauteed": "Shrimp, garlic, butter, lemon",
    "Spicy Shrimp": "Shrimp, chili, garlic, lemon",
    "Fried Calamari": "Calamari, flour, garlic, lemon",
    "Grilled Calamari": "Calamari, garlic, lemon, olive oil",
    "Blue Crab (Seasonal)": "Blue crab, garlic butter, lemon",
    "King Crab Legs": "King crab legs, garlic butter, lemon",
    "Mixed Seafood Platter": "Fish, shrimp, calamari, garlic, lemon",
    "Shrimp & Calamari Platter": "Shrimp, calamari, garlic, lemon",
    "Deluxe Platter": "Fish, shrimp, calamari, crab, garlic butter, lemon",
    "Seafood Rice": "Rice, mixed seafood, garlic, spices",
    "Shrimp Rice": "Rice, shrimp, garlic, spices",
    "Fish Rice": "Rice, fish, garlic, spices",
    "Seafood Pasta": "Pasta, mixed seafood, tomato sauce, garlic",
    "Shrimp Pasta": "Pasta, shrimp, tomato sauce, garlic",
    "Calamari Pasta": "Pasta, calamari, tomato sauce, garlic",
    # --- Omar Caboose: sides ---
    "Rice": "White rice, butter",
    "French Fries": "Potatoes, salt",
    "Garlic Bread": "Bread, garlic butter, parsley",
    "Extra Sauce": "House tahini garlic sauce",
    # --- Omar Caboose: grills (plate & sandwich share the filling) ---
    "Egyptian Kofta (Plate)": "Minced beef, onions, parsley, spices, served with rice and salad",
    "Egyptian Kofta (Sandwich)": "Minced beef, onions, parsley, spices, baladi bread, tahini",
    "Alexandrian Liver (Plate)": "Beef liver, garlic, chili, cumin, lemon, served with rice and salad",
    "Alexandrian Liver (Sandwich)": "Beef liver, garlic, chili, cumin, lemon, baladi bread",
    "Charcoal-Grilled Sausage (Plate)": "Charcoal-grilled sausage, served with rice and salad",
    "Charcoal-Grilled Sausage (Sandwich)": "Charcoal-grilled sausage, baladi bread, tahini",
    "Egyptian-Style Sausage (Plate)": "Egyptian sausage, peppers, onions, served with rice and salad",
    "Egyptian-Style Sausage (Sandwich)": "Egyptian sausage, peppers, onions, baladi bread",
    "Grilled Beef (Plate)": "Grilled beef, spices, served with rice and salad",
    "Grilled Beef (Sandwich)": "Grilled beef, spices, baladi bread, tahini",
    "Charcoal-Grilled Kebab (Plate)": "Charcoal-grilled kebab, onions, parsley, served with rice and salad",
    "Charcoal-Grilled Kebab (Sandwich)": "Charcoal-grilled kebab, onions, parsley, baladi bread",
    "Chicken Pane (Plate)": "Breaded chicken, served with rice and salad",
    "Chicken Pane (Sandwich)": "Breaded chicken, baladi bread, garlic sauce",
    "Grilled Chicken (Plate)": "Grilled chicken, garlic, lemon, spices, served with rice and salad",
    "Grilled Chicken (Sandwich)": "Grilled chicken, garlic, lemon, baladi bread",
    "Charcoal-Grilled Hawawshi (Plate)": "Baladi bread, minced beef, onions, bell peppers, tomatoes, parsley, hawawshi spices, ghee",
    # --- Omar Caboose: casseroles & baked ---
    "Cow Trotters Casserole (Kaware')": "Cow trotters, tomato sauce, onions, baked",
    "Oxtail Casserole (Akawi)": "Oxtail, onions, tomato sauce, baked",
    "Okra with Beef (Bamia)": "Okra, beef, tomato sauce",
    "Egyptian Baked Rice with Lamb (Rice Ma'amar)": "Rice, milk, cream, lamb, butter, baked",
    "Egyptian Béchemel Pasta (Macarona Bechamel)": "Pasta, minced beef, béchamel sauce, baked",
    "Egyptian Mombar": "Rice, herbs and tomato, stuffed and fried",
    # --- Omar Caboose: mahshi trays ---
    "Stuffed Grape Leaves (Half Tray)": "Grape leaves stuffed with rice, herbs and tomato",
    "Stuffed Grape Leaves (Full Tray)": "Grape leaves stuffed with rice, herbs and tomato",
    "Stuffed Cabbage Rolls (Half Tray)": "Cabbage stuffed with rice, herbs and tomato",
    "Stuffed Cabbage Rolls (Full Tray)": "Cabbage stuffed with rice, herbs and tomato",
    "Stuffed Eggplant (Half Tray)": "Eggplant stuffed with rice, herbs and tomato",
    "Stuffed Eggplant (Full Tray)": "Eggplant stuffed with rice, herbs and tomato",
    "Stuffed Zucchini (Half Tray)": "Zucchini stuffed with rice, herbs and tomato",
    "Stuffed Zucchini (Full Tray)": "Zucchini stuffed with rice, herbs and tomato",
    "Stuffed Tomatoes (Half Tray)": "Tomatoes stuffed with rice, herbs",
    "Stuffed Tomatoes (Full Tray)": "Tomatoes stuffed with rice, herbs",
    "Mixed Mahshi Tray (Half Tray)": "Mixed vegetables stuffed with rice, herbs and tomato",
    "Mixed Mahshi Tray (Full Tray)": "Mixed vegetables stuffed with rice, herbs and tomato",
    "Dolma": "Grape leaves stuffed with rice and minced meat",
    # --- Mama Samia's Kitchen ---
    "Molokhia with Chicken": "Molokhia leaves, chicken, chicken broth, garlic, ground coriander, rice, lemon",
    "Koshary": "Rice, brown lentils, macaroni pasta, chickpeas, crispy fried onions, spicy tomato sauce, garlic vinegar (da'ah), cumin",
    "Fatta": "Rice, baladi bread, beef, tomato sauce, garlic, vinegar, beef broth, ghee",
    "Om Ali": "Puff pastry, milk, cream, sugar, raisins, shredded coconut, almonds, pistachio, vanilla",
    # --- v50 additions (Mama Samia's Kitchen) ---
    "Konafa": "Shredded konafa pastry, sweet cheese, cream, ghee, syrup, pistachio",
    "Qatayef": "Pancake batter, walnuts, cream, syrup, pistachio",
    "Ta'ameya (Egyptian Falafel)": "Fava beans, leeks, herbs, coriander, sesame, baladi bread, tahini",
    # --- Nile Bakery ---
    "Baladi Bread (5 pc)": "Whole wheat flour, water, yeast, salt, wheat bran",
    "Feteer Meshaltet": "Flour, water, baladi ghee, salt, sugar",
    "Kahk": "Flour, ghee, powdered sugar, honey-nut filling (agameya), kahk spice (mahlab), sesame seeds, yeast",
    "Basbousa": "Semolina, yogurt, sugar syrup, shredded coconut, ghee, almonds, baking powder",
    # --- Um Sohaib's Kitchen ---
    "Mansaf": "Lamb, jameed yogurt sauce, shrak bread, rice, almonds",
    "Maqlouba": "Chicken or meat, rice, cauliflower, eggplant, potatoes",
    "Musakhan": "Chicken, sumac onions, taboon bread, olive oil",
    "Ouzi": "Lamb, rice, peas, carrots, nuts",
    "Biryani": "Chicken, basmati rice, biryani spices, yogurt",
    "Shish Barak": "Meat dumplings, yogurt sauce, garlic, mint",
    "Freekeh with Chicken": "Freekeh, chicken, broth, nuts",
    "Stuffed Cabbage Rolls": "Cabbage, rice, herbs, tomato",
    "Stuffed Grape Leaves": "Grape leaves, rice, meat, lemon",
    "Yalanji (Stuffed Vegetables)": "Vegetables, rice, olive oil, lemon (vegetarian)",
    "Chicken Tray with Rice": "Chicken, rice, potatoes, tomato",
    "Kofta with Tahini & Rice": "Kofta, tahini sauce, rice",
    "Kibbeh": "Bulgur, minced meat, onions, pine nuts",
    "Meat Sfiha": "Minced meat, tomatoes, onions, flatbread",
    "Spinach Pastry": "Spinach, onions, sumac, dough",
    "Cheese Pastry": "Cheese, dough",
    "Mini Pizza": "Pizza dough, tomato sauce, cheese",
    "Salad": "Tomatoes, cucumbers, lettuce, lemon juice, olive oil",
}


# (dish_name -> Arabic name) — v52: fills Dish.name_ar so the storefront
# can render dish names in Arabic mode (mirrors Bundle.name_ar). Source:
# hidden_files/builds/dish-names-ar.py (keys verified character-exact
# against the live dish names). Only fills when empty, so vendor edits
# in the portal are never overwritten.
DISH_NAMES_AR: dict[str, str] = {
    "Dolma": "دولمة",
    "Baladi Bread (5 pc)": "عيش بلدي (٥ قطع)",
    "Feteer Meshaltet": "فطير مشلتت",
    "Egyptian Black Tea (El Arosa) - 100 bags": "شاي أسود مصري (العروسة) - ١٠٠ كيس",
    "Sahlab Mix - 7 oz": "خلطة سحلب - ٧ أوقية",
    "Cow Trotters Casserole (Kaware')": "طاجن كوارع",
    "Egyptian Baked Rice with Lamb (Rice Ma'amar)": "رز معمر باللحمة الضاني",
    "Egyptian Béchemel Pasta (Macarona Bechamel)": "مكرونة بشاميل",
    "Okra with Beef (Bamia)": "بامية باللحمة",
    "Oxtail Casserole (Akawi)": "طاجن عكاوي",
    "Aged Mish Cheese - 16 oz jar": "جبنة مش معتقة - برطمان ١٦ أوقية",
    "Egyptian White Cheese (Gibna Beida) - per lb": "جبنة بيضاء مصرية - بالرطل",
    "Karish Cheese - per lb": "جبنة قريش - بالرطل",
    "Basbousa": "بسبوسة",
    "Kahk": "كحك",
    "Konafa": "كنافة",
    "Om Ali": "أم علي",
    "Qatayef": "قطايف",
    "Frozen Green Fava Beans - 14 oz": "فول أخضر مجمد - ١٤ أوقية",
    "Frozen Molokhia - 14 oz": "ملوخية مجمدة - ١٤ أوقية",
    "Frozen Okra - 14 oz": "بامية مجمدة - ١٤ أوقية",
    "Alexandrian Liver (Plate)": "كبدة إسكندراني (طبق)",
    "Alexandrian Liver (Sandwich)": "كبدة إسكندراني (ساندويتش)",
    "Charcoal-Grilled Hawawshi (Plate)": "حواوشي على الفحم (طبق)",
    "Charcoal-Grilled Kebab (Plate)": "كباب على الفحم (طبق)",
    "Charcoal-Grilled Kebab (Sandwich)": "كباب على الفحم (ساندويتش)",
    "Charcoal-Grilled Sausage (Plate)": "سجق على الفحم (طبق)",
    "Charcoal-Grilled Sausage (Sandwich)": "سجق على الفحم (ساندويتش)",
    "Chicken Pane (Plate)": "فراخ بانيه (طبق)",
    "Chicken Pane (Sandwich)": "فراخ بانيه (ساندويتش)",
    "Egyptian Kofta (Plate)": "كفتة مصرية (طبق)",
    "Egyptian Kofta (Sandwich)": "كفتة مصرية (ساندويتش)",
    "Egyptian-Style Sausage (Plate)": "سجق بلدي (طبق)",
    "Egyptian-Style Sausage (Sandwich)": "سجق بلدي (ساندويتش)",
    "Grilled Beef (Plate)": "لحمة مشوية (طبق)",
    "Grilled Beef (Sandwich)": "لحمة مشوية (ساندويتش)",
    "Grilled Chicken (Plate)": "فراخ مشوية (طبق)",
    "Grilled Chicken (Sandwich)": "فراخ مشوية (ساندويتش)",
    "Egyptian Mombar": "ممبار",
    "Mixed Mahshi Tray (Full Tray)": "محشي مشكل (صينية كاملة)",
    "Mixed Mahshi Tray (Half Tray)": "محشي مشكل (نص صينية)",
    "Stuffed Cabbage Rolls (Full Tray)": "محشي كرنب (صينية كاملة)",
    "Stuffed Cabbage Rolls (Half Tray)": "محشي كرنب (نص صينية)",
    "Stuffed Eggplant (Full Tray)": "محشي بتنجان (صينية كاملة)",
    "Stuffed Eggplant (Half Tray)": "محشي بتنجان (نص صينية)",
    "Stuffed Grape Leaves (Full Tray)": "محشي ورق عنب (صينية كاملة)",
    "Stuffed Grape Leaves (Half Tray)": "محشي ورق عنب (نص صينية)",
    "Stuffed Tomatoes (Full Tray)": "محشي طماطم (صينية كاملة)",
    "Stuffed Tomatoes (Half Tray)": "محشي طماطم (نص صينية)",
    "Stuffed Zucchini (Full Tray)": "محشي كوسة (صينية كاملة)",
    "Stuffed Zucchini (Half Tray)": "محشي كوسة (نص صينية)",
    "Biryani": "برياني",
    "Chicken Tray with Rice": "صينية فراخ بالرز",
    "Fatta": "فتة",
    "Freekeh with Chicken": "فريك بالفراخ",
    "Kibbeh": "كبة",
    "Kofta with Tahini & Rice": "كفتة بالطحينة والرز",
    "Koshary": "كشري",
    "Mansaf": "منسف",
    "Maqlouba": "مقلوبة",
    "Molokhia with Chicken": "ملوخية بالفراخ",
    "Musakhan": "مسخن",
    "Ouzi": "أوزي",
    "Shish Barak": "شيشبرك",
    "Stuffed Cabbage Rolls": "محشي كرنب",
    "Stuffed Grape Leaves": "محشي ورق عنب",
    "Ta'ameya (Egyptian Falafel)": "طعمية",
    "Yalanji (Stuffed Vegetables)": "يالنجي",
    "Canned Ful Medames - 14 oz": "فول مدمس معلب - ١٤ أوقية",
    "Dried Chickpeas (Hummus) - 2 lb bag": "حمص جاف - كيس ٢ رطل",
    "Dried Molokhia Leaves - 7 oz bag": "ورق ملوخية جاف - كيس ٧ أوقية",
    "Dried Okra (Bamia) - 7 oz bag": "بامية جافة - كيس ٧ أوقية",
    "Egyptian Pickles (Torshi) - 32 oz jar": "طرشي مصري - برطمان ٣٢ أوقية",
    "Egyptian Short-Grain Rice - 5 lb bag": "رز مصري - كيس ٥ رطل",
    "Fava Beans (Ful Medames) - 2 lb bag": "فول مدمس - كيس ٢ رطل",
    "Grape Leaves Jar (for Mahshi) - 16 oz": "ورق عنب للمحشي - برطمان ١٦ أوقية",
    "Green Olives - 16 oz jar": "زيتون أخضر - برطمان ١٦ أوقية",
    "Macaroni Pasta - 1 lb": "مكرونة - ١ رطل",
    "Red Lentils - 2 lb bag": "عدس أحمر - كيس ٢ رطل",
    "White Beans (Fasolia) - 2 lb bag": "فاصوليا بيضاء - كيس ٢ رطل",
    "Cheese Pastry": "فطاير جبنة",
    "Meat Sfiha": "صفيحة لحمة",
    "Mini Pizza": "ميني بيتزا",
    "Spinach Pastry": "فطاير سبانخ",
    "Salad": "سلطة",
    "Baba Ghanoush": "بابا غنوج",
    "Beet Salad": "سلطة بنجر",
    "Caesar Salad": "سلطة سيزر",
    "Chicken Caesar Salad": "سلطة سيزر بالفراخ",
    "Coleslaw": "سلطة كول سلو",
    "Corn Salad": "سلطة ذرة",
    "Cucumber Yogurt Salad": "سلطة خيار بالزبادي",
    "Egyptian Baladi Salad": "سلطة بلدي",
    "Egyptian Pickles": "مخلل مصري",
    "Fattoush": "فتوش",
    "Greek Salad": "سلطة يونانية",
    "Hummus": "حمص",
    "Pickled Eggplant": "بتنجان مخلل",
    "Potato Salad": "سلطة بطاطس",
    "Tabbouleh": "تبولة",
    "Tahini Salad": "سلطة طحينة",
    "Blue Crab (Seasonal)": "كابوريا (موسمي)",
    "Calamari Pasta": "مكرونة كاليماري",
    "Deluxe Platter": "صينية ديلوكس",
    "Extra Sauce": "صوص إضافي",
    "Fish Fillet": "فيليه سمك",
    "Fish Rice": "رز صيادية",
    "French Fries": "بطاطس مقلية",
    "Fried Calamari": "كاليماري مقلي",
    "Fried Shrimp": "جمبري مقلي",
    "Garlic Bread": "خبز بالثوم",
    "Grilled Calamari": "كاليماري مشوي",
    "Grilled Shrimp": "جمبري مشوي",
    "King Crab Legs": "أرجل كينج كراب",
    "Mixed Seafood Platter": "صينية سي فود مشكلة",
    "Rice": "رز أبيض",
    "Seafood Pasta": "مكرونة سي فود",
    "Seafood Rice": "رز سي فود",
    "Seafood Soup": "شوربة سي فود",
    "Shrimp & Calamari Platter": "صينية جمبري وكاليماري",
    "Shrimp Pasta": "مكرونة جمبري",
    "Shrimp Rice": "رز جمبري",
    "Shrimp Sauteed": "جمبري سوتيه",
    "Spicy Shrimp": "جمبري حار",
    "Whole Fried Fish": "سمكة كاملة مقلية",
    "Whole Grilled Fish": "سمكة كاملة مشوية",
    "Beef & Pasta Soup": "شوربة لحمة بالمكرونة",
    "Egyptian Lentil Soup": "شوربة عدس",
    "Kaware' Broth (Cow Trotters Soup)": "شوربة كوارع",
    "Orzo Soup (Lisan Asfour)": "شوربة لسان عصفور",
    "Vegetable Soup": "شوربة خضار",
    "Baharat (7-Spice Blend) - 4 oz": "بهارات (خلطة السبع بهارات) - ٤ أوقية",
    "Black Seed (Habat El Baraka) - 4 oz": "حبة البركة - ٤ أوقية",
    "Dried Hibiscus (Karkadeh) - 8 oz": "كركديه مجفف - ٨ أوقية",
    "Dried Mint - 2 oz": "نعناع مجفف - ٢ أوقية",
    "Dukkah Spice Mix - 4 oz": "خلطة دقة - ٤ أوقية",
    "Fenugreek Seeds (Helba) - 4 oz": "بذور الحلبة - ٤ أوقية",
    "Ground Coriander - 4 oz": "كزبرة مطحونة - ٤ أوقية",
    "Ground Cumin - 4 oz": "كمون مطحون - ٤ أوقية",
    "Ground Turmeric - 4 oz": "كركم مطحون - ٤ أوقية",
    "Blackstrap Molasses (Asal Eswed) - 16 oz": "عسل أسود - ١٦ أوقية",
    "Halva with Pistachio - 1 lb": "حلاوة بالفستق - ١ رطل",
    "Medjool Dates - 2 lb box": "تمر مجهول - علبة ٢ رطل",
    "Qamar Al-Din (Apricot Paste) - 14 oz": "قمر الدين - ١٤ أوقية",
}


# Default prep minutes by category (Oct 2026) — fills Dish.prep_minutes when
# blank; vendors can override per dish in the portal. Groceries = packing time.
CATEGORY_PREP: dict[str, int] = {
    "Salads": 10, "Salad": 10, "Appetizers": 10, "Sweets": 10, "Desserts": 10,
    "Soups": 15, "Pastries": 15, "Bakery": 15,
    "Grill": 20, "Seafood": 25, "Mains": 30,
    "Casseroles": 45, "Mahshi": 50,
    "Pantry": 5, "Dairy & Cheese": 5, "Frozen": 5, "Spices & Herbs": 5, "Beverages": 5,
}


def _get_vendor(db, name):
    return db.scalar(select(models.Vendor).where(models.Vendor.name == name))


def _add_dishes(db, vendor, items):
    for name, desc, price, category, featured in items:
        db.add(
            models.Dish(
                vendor_id=vendor.id,
                name=name,
                # v52: Arabic name at creation (fill_seed_data backstops).
                name_ar=DISH_NAMES_AR.get(name),
                description=desc,
                price=Decimal(str(price)),
                category=category,
                is_featured=featured,
            )
        )


# v50: Egypt's proven best sellers — these stay featured so they lead the
# home page (popular grid + photo marquee) on every database, including
# ones seeded before v50 (the seed lists alone can't reach those).
FEATURED_BEST_SELLERS: list[str] = [
    "Stuffed Grape Leaves",
    "Mixed Mahshi Tray (Half Tray)",
    "Molokhia with Chicken",
    "Egyptian Béchemel Pasta (Macarona Bechamel)",
    "Koshary",
    "Fatta",
    "Charcoal-Grilled Hawawshi (Plate)",
    "Egyptian Kofta (Plate)",
    "Okra with Beef (Bamia)",
    "Egyptian Baked Rice with Lamb (Rice Ma'amar)",
    "Om Ali",
    "Basbousa",
    "Konafa",
    "Qatayef",
    "Ta'ameya (Egyptian Falafel)",
]


# v53 remainder: Arabic ingredient lists (item-for-item parallel to
# DISH_INGREDIENTS — same keys, same split(", ") item counts, so AR
# checkout toggles map by INDEX to the EN canonical removal names)
# and Arabic vendor names. Copied verbatim from
# hidden_files/builds/dish-text-ar.py (Copywriter, 2026-10-23).
DISH_INGREDIENTS_AR: dict[str, str] = {
    "Dolma": "ورق عنب محشي رز ولحمة مفرومة",
    "Baladi Bread (5 pc)": "دقيق قمح كامل, ماء, خميرة, ملح, ردة قمح",
    "Feteer Meshaltet": "دقيق, ماء, سمن بلدي, ملح, سكر",
    "Cow Trotters Casserole (Kaware')": "كوارع, صوص طماطم, بصل, مخبوز",
    "Egyptian Baked Rice with Lamb (Rice Ma'amar)": "رز, لبن, قشطة, لحمة ضأن, زبدة, مخبوز",
    "Egyptian Béchemel Pasta (Macarona Bechamel)": "مكرونة, لحمة مفرومة, صوص بشاميل, مخبوز",
    "Okra with Beef (Bamia)": "بامية, لحمة, صوص طماطم",
    "Oxtail Casserole (Akawi)": "عكاوي, بصل, صوص طماطم, مخبوز",
    "Basbousa": "سميد, زبادي, شربات, جوز هند مبشور, سمن, لوز, بيكنج بودر",
    "Kahk": "دقيق, سمن, سكر بودرة, حشو عجمية بالعسل والمكسرات, ريحة كحك (محلب), سمسم, خميرة",
    "Konafa": "شعر كنافة, جبنة حلوة, قشطة, سمن, شربات, فستق",
    "Om Ali": "بف باستري, لبن, قشطة, سكر, زبيب, جوز هند مبشور, لوز, فستق, فانيليا",
    "Qatayef": "عجينة قطايف, جوز (عين جمل), قشطة, شربات, فستق",
    "Alexandrian Liver (Plate)": "كبدة بلدي, توم, شطة, كمون, ليمون, بتتقدم مع رز وسلطة",
    "Alexandrian Liver (Sandwich)": "كبدة بلدي, توم, شطة, كمون, ليمون, عيش بلدي",
    "Charcoal-Grilled Hawawshi (Plate)": "عيش بلدي, لحمة مفرومة, بصل, فلفل ألوان, طماطم, بقدونس, بهارات حواوشي, سمن",
    "Charcoal-Grilled Kebab (Plate)": "كباب مشوي على الفحم, بصل, بقدونس, بيتقدم مع رز وسلطة",
    "Charcoal-Grilled Kebab (Sandwich)": "كباب مشوي على الفحم, بصل, بقدونس, عيش بلدي",
    "Charcoal-Grilled Sausage (Plate)": "سجق مشوي على الفحم, بيتقدم مع رز وسلطة",
    "Charcoal-Grilled Sausage (Sandwich)": "سجق مشوي على الفحم, عيش بلدي, طحينة",
    "Chicken Pane (Plate)": "فراخ بانيه, بتتقدم مع رز وسلطة",
    "Chicken Pane (Sandwich)": "فراخ بانيه, عيش بلدي, صوص توم",
    "Egyptian Kofta (Plate)": "لحمة مفرومة, بصل, بقدونس, بهارات, بتتقدم مع رز وسلطة",
    "Egyptian Kofta (Sandwich)": "لحمة مفرومة, بصل, بقدونس, بهارات, عيش بلدي, طحينة",
    "Egyptian-Style Sausage (Plate)": "سجق مصري, فلفل, بصل, بيتقدم مع رز وسلطة",
    "Egyptian-Style Sausage (Sandwich)": "سجق مصري, فلفل, بصل, عيش بلدي",
    "Grilled Beef (Plate)": "لحمة مشوية, بهارات, بتتقدم مع رز وسلطة",
    "Grilled Beef (Sandwich)": "لحمة مشوية, بهارات, عيش بلدي, طحينة",
    "Grilled Chicken (Plate)": "فراخ مشوية, توم, ليمون, بهارات, بتتقدم مع رز وسلطة",
    "Grilled Chicken (Sandwich)": "فراخ مشوية, توم, ليمون, عيش بلدي",
    "Egyptian Mombar": "رز, خضرة وطماطم, محشي ومقلي",
    "Mixed Mahshi Tray (Full Tray)": "خضار مشكلة محشية رز, خضرة وطماطم",
    "Mixed Mahshi Tray (Half Tray)": "خضار مشكلة محشية رز, خضرة وطماطم",
    "Stuffed Cabbage Rolls (Full Tray)": "كرنب محشي رز, خضرة وطماطم",
    "Stuffed Cabbage Rolls (Half Tray)": "كرنب محشي رز, خضرة وطماطم",
    "Stuffed Eggplant (Full Tray)": "بتنجان محشي رز, خضرة وطماطم",
    "Stuffed Eggplant (Half Tray)": "بتنجان محشي رز, خضرة وطماطم",
    "Stuffed Grape Leaves (Full Tray)": "ورق عنب محشي رز, خضرة وطماطم",
    "Stuffed Grape Leaves (Half Tray)": "ورق عنب محشي رز, خضرة وطماطم",
    "Stuffed Tomatoes (Full Tray)": "طماطم محشية رز, خضرة",
    "Stuffed Tomatoes (Half Tray)": "طماطم محشية رز, خضرة",
    "Stuffed Zucchini (Full Tray)": "كوسة محشية رز, خضرة وطماطم",
    "Stuffed Zucchini (Half Tray)": "كوسة محشية رز, خضرة وطماطم",
    "Biryani": "فراخ, رز بسمتي, بهارات برياني, زبادي",
    "Chicken Tray with Rice": "فراخ, رز, بطاطس, طماطم",
    "Fatta": "رز, عيش بلدي, لحمة, صوص طماطم, توم, خل, شوربة لحمة, سمن",
    "Freekeh with Chicken": "فريكة, فراخ, شوربة, مكسرات",
    "Kibbeh": "برغل, لحمة مفرومة, بصل, صنوبر",
    "Kofta with Tahini & Rice": "كفتة, صوص طحينة, رز",
    "Koshary": "رز, عدس بني, مكرونة, حمص, بصل محمر مقرمش, صوص طماطم حامي, دقة خل وتوم (دقة), كمون",
    "Mansaf": "لحمة ضأن, صوص جميد, عيش شراك, رز, لوز",
    "Maqlouba": "فراخ أو لحمة, رز, قرنبيط, بتنجان, بطاطس",
    "Molokhia with Chicken": "ورق ملوخية, فراخ, شوربة فراخ, توم, كزبرة مطحونة, رز, ليمون",
    "Musakhan": "فراخ, بصل بالسماق, عيش طابون, زيت زيتون",
    "Ouzi": "لحمة ضأن, رز, بسلة, جزر, مكسرات",
    "Shish Barak": "شيشبرك لحمة, صوص زبادي, توم, نعناع",
    "Stuffed Cabbage Rolls": "كرنب, رز, خضرة, طماطم",
    "Stuffed Grape Leaves": "ورق عنب, رز, لحمة, ليمون",
    "Ta'ameya (Egyptian Falafel)": "فول, كرات, خضرة, كزبرة, سمسم, عيش بلدي, طحينة",
    "Yalanji (Stuffed Vegetables)": "خضار, رز, زيت زيتون, ليمون (نباتي)",
    "Cheese Pastry": "جبنة, عجينة",
    "Meat Sfiha": "لحمة مفرومة, طماطم, بصل, عيش مسطح",
    "Mini Pizza": "عجينة بيتزا, صوص طماطم, جبنة",
    "Spinach Pastry": "سبانخ, بصل, سماق, عجينة",
    "Salad": "طماطم, خيار, خس, عصير ليمون, زيت زيتون",
    "Baba Ghanoush": "بتنجان مشوي, طحينة, عصير ليمون, توم, زيت زيتون",
    "Beet Salad": "بنجر, توم, عصير ليمون, زيت زيتون, بقدونس",
    "Caesar Salad": "خس روماني, بارميزان, كروتون, صوص سيزر",
    "Chicken Caesar Salad": "فراخ مشوية, خس روماني, بارميزان, كروتون, صوص سيزر",
    "Coleslaw": "كرنب, جزر, صوص مايونيز",
    "Corn Salad": "ذرة, فلفل, مايونيز, عصير ليمون",
    "Cucumber Yogurt Salad": "خيار, زبادي, توم, نعناع, زيت زيتون",
    "Egyptian Baladi Salad": "طماطم, خيار, بصل, بقدونس, عصير ليمون, زيت زيتون",
    "Egyptian Pickles": "خضرة مخللة مشكلة, محلول خل, شطة",
    "Fattoush": "خضرة مشكلة, طماطم, خيار, فجل, عيش محمص, صوص سماق",
    "Greek Salad": "طماطم, خيار, بصل أحمر, زيتون, جبنة فيتا, زيت زيتون",
    "Hummus": "حمص, طحينة, عصير ليمون, توم, زيت زيتون, بابريكا",
    "Pickled Eggplant": "بتنجان صغير, توم, خل, شطة, كزبرة",
    "Potato Salad": "بطاطس, مايونيز, مستردة, بيض, مخلل",
    "Tabbouleh": "بقدونس, برغل, طماطم, نعناع, عصير ليمون, زيت زيتون",
    "Tahini Salad": "طحينة, عصير ليمون, توم, كمون, زيت زيتون, بقدونس",
    "Blue Crab (Seasonal)": "كابوريا زرقاء, زبدة توم, ليمون",
    "Calamari Pasta": "مكرونة, كاليماري, صوص طماطم, توم",
    "Deluxe Platter": "سمك, جمبري, كاليماري, كابوريا, زبدة توم, ليمون",
    "Extra Sauce": "صوص طحينة وتوم بيتي",
    "Fish Fillet": "فيليه سمك, توم, ليمون, كمون",
    "Fish Rice": "رز, سمك, توم, بهارات",
    "French Fries": "بطاطس, ملح",
    "Fried Calamari": "كاليماري, دقيق, توم, ليمون",
    "Fried Shrimp": "جمبري, دقيق, توم, ليمون",
    "Garlic Bread": "عيش, زبدة توم, بقدونس",
    "Grilled Calamari": "كاليماري, توم, ليمون, زيت زيتون",
    "Grilled Shrimp": "جمبري, توم, ليمون, زيت زيتون",
    "King Crab Legs": "أرجل كينج كراب, زبدة توم, ليمون",
    "Mixed Seafood Platter": "سمك, جمبري, كاليماري, توم, ليمون",
    "Rice": "رز أبيض, زبدة",
    "Seafood Pasta": "مكرونة, سي فود مشكل, صوص طماطم, توم",
    "Seafood Rice": "رز, سي فود مشكل, توم, بهارات",
    "Seafood Soup": "سي فود مشكل, شوربة سمك, توم, ليمون",
    "Shrimp & Calamari Platter": "جمبري, كاليماري, توم, ليمون",
    "Shrimp Pasta": "مكرونة, جمبري, صوص طماطم, توم",
    "Shrimp Rice": "رز, جمبري, توم, بهارات",
    "Shrimp Sauteed": "جمبري, توم, زبدة, ليمون",
    "Spicy Shrimp": "جمبري, شطة, توم, ليمون",
    "Whole Fried Fish": "سمكة كاملة, دقيق, توم, كمون, ليمون",
    "Whole Grilled Fish": "سمكة كاملة, توم, ليمون, زيت زيتون, بهارات",
    "Beef & Pasta Soup": "لحمة, مكرونة, خضار مشكلة, شوربة",
    "Egyptian Lentil Soup": "عدس أحمر, بصل, جزر, كمون, ليمون",
    "Kaware' Broth (Cow Trotters Soup)": "كوارع, توم, خل, ليمون, كمون",
    "Orzo Soup (Lisan Asfour)": "لسان عصفور, شوربة فراخ, زبدة",
    "Vegetable Soup": "خضار مشكلة, شوربة طماطم",
}

VENDOR_NAMES_AR: dict[str, str] = {
    "Mama Samia's Kitchen": "مطبخ ماما سامية",
    "Nile Bakery": "مخبز النيل",
    "Lynnwood Groceries": "بقالة لينوود",
    "Omar Caboose": "عمر كابوس",
    "Um Sohaib's Kitchen": "مطبخ أم صهيب",
}


def _rename_nile_to_lynnwood(db):
    """Rename "Nile Groceries" -> "Lynnwood Groceries" in place.

    name_ar follows only when it still holds the old Arabic name (or is
    empty) — a vendor's custom Arabic name is never overwritten.
    """
    _old = db.scalar(select(models.Vendor).where(models.Vendor.name == "Nile Groceries"))
    if _old is not None:
        _old.name = "Lynnwood Groceries"
        if not _old.name_ar or _old.name_ar == "بقالة النيل":
            _old.name_ar = "بقالة لينوود"


def _dedupe_vendors(db):
    """Merge vendor rows that share one name; keep the lowest id.

    Heals the v55 double-create (seed() created a second "Lynnwood
    Groceries" row before the rename ran). Vendor-level references move to
    the kept row; a duplicate dish with the same name as a kept dish has
    its references moved onto the kept dish and is then deleted, while a
    uniquely-named duplicate dish is reassigned to the kept vendor.
    Idempotent — a clean database is a no-op. Runs in a SAVEPOINT so a
    failure rolls back just the merge and never breaks startup.
    """
    try:
        with db.begin_nested():
            _dup_names = [
                r[0]
                for r in db.execute(
                    select(models.Vendor.name)
                    .group_by(models.Vendor.name)
                    .having(func.count(models.Vendor.id) > 1)
                )
            ]
            for _name in _dup_names:
                _vendors = (
                    db.scalars(
                        select(models.Vendor)
                        .where(models.Vendor.name == _name)
                        .order_by(models.Vendor.id)
                    ).all()
                )
                _kept, _dups = _vendors[0], _vendors[1:]
                _kept_dishes = {
                    d.name: d
                    for d in db.scalars(
                        select(models.Dish).where(models.Dish.vendor_id == _kept.id)
                    ).all()
                }
                for _dup in _dups:
                    for _model, _col in (
                        (models.Order, "vendor_id"),
                        (models.Order, "attributed_vendor_id"),
                        (models.VendorPayout, "vendor_id"),
                        (models.VendorSettlement, "vendor_id"),
                        (models.Review, "vendor_id"),
                        (models.DishAnnouncement, "vendor_id"),
                    ):
                        db.execute(
                            update(_model)
                            .where(getattr(_model, _col) == _dup.id)
                            .values({_col: _kept.id})
                        )
                    for _dish in list(
                        db.scalars(
                            select(models.Dish).where(models.Dish.vendor_id == _dup.id)
                        ).all()
                    ):
                        _target = _kept_dishes.get(_dish.name)
                        if _target is None:
                            _dish.vendor_id = _kept.id
                            _kept_dishes[_dish.name] = _dish
                            continue
                        db.execute(update(models.OrderItem).where(models.OrderItem.dish_id == _dish.id).values(dish_id=_target.id))
                        db.execute(update(models.Review).where(models.Review.dish_id == _dish.id).values(dish_id=_target.id))
                        db.execute(update(models.DishOption).where(models.DishOption.dish_id == _dish.id).values(dish_id=_target.id))
                        db.execute(update(models.DishIngredient).where(models.DishIngredient.dish_id == _dish.id).values(dish_id=_target.id))
                        for _fav in db.scalars(select(models.Favorite).where(models.Favorite.dish_id == _dish.id)).all():
                            _existing = db.scalar(select(models.Favorite).where(models.Favorite.user_id == _fav.user_id, models.Favorite.dish_id == _target.id))
                            if _existing is not None:
                                db.delete(_fav)
                            else:
                                _fav.dish_id = _target.id
                        for _ann in db.scalars(select(models.DishAnnouncement).where(models.DishAnnouncement.dish_id == _dish.id)).all():
                            _existing = db.scalar(select(models.DishAnnouncement).where(models.DishAnnouncement.dish_id == _target.id))
                            if _existing is not None:
                                db.delete(_ann)
                            else:
                                _ann.dish_id = _target.id
                        db.delete(_dish)
                    db.delete(_dup)
            db.flush()
    except Exception as exc:  # never break startup over a merge
        print(f"[seed] vendor dedupe skipped ({exc!r})")


def fill_seed_data(db):
    """Idempotent seed-*data* fills (not schema): ingredients text + category
    prep-minute defaults. Only fills blanks, so vendor edits in the portal are
    never overwritten. Safe to run on every startup — this is what keeps
    in-place zip upgrades (which never re-run `python -m app.seed`) current.
    """
    # Ingredients text for prepared-food dishes.
    for _name, _ing in DISH_INGREDIENTS.items():
        _d = db.scalar(select(models.Dish).where(models.Dish.name == _name))
        if _d is not None and not _d.ingredients:
            _d.ingredients = _ing
    # v52: Arabic dish names (see DISH_NAMES_AR). Only-when-empty, same
    # contract as ingredients — vendor edits in the portal win.
    for _name, _ar in DISH_NAMES_AR.items():
        _d = db.scalar(select(models.Dish).where(models.Dish.name == _name))
        if _d is not None and not _d.name_ar:
            _d.name_ar = _ar
    # v53 remainder: Arabic ingredient lists (only-when-empty — a vendor's
    # custom ingredients_ar in the portal always wins).
    for _name, _ar in DISH_INGREDIENTS_AR.items():
        _d = db.scalar(select(models.Dish).where(models.Dish.name == _name))
        if _d is not None and not _d.ingredients_ar:
            _d.ingredients_ar = _ar
    # Rename (Oct 2026): "Nile Groceries" -> "Lynnwood Groceries".
    # Runs on every startup, so existing databases are renamed in place.
    # NOTE (v56): this MUST run before any vendor creation in seed() — v55
    # created a second "Lynnwood Groceries" row because creation ran first
    # (lookup by the new name missed the old row) and the rename ran after.
    _rename_nile_to_lynnwood(db)
    # v56: merge any same-name vendor rows (heals the v55 double-create).
    _dedupe_vendors(db)

    # v53 remainder: Arabic vendor names (only-when-empty).
    for _name, _ar in VENDOR_NAMES_AR.items():
        _v = db.scalar(select(models.Vendor).where(models.Vendor.name == _name))
        if _v is not None and not _v.name_ar:
            _v.name_ar = _ar
    # v53: Arabic descriptions + option group/choice labels (only-when-empty).
    for _d in db.scalars(select(models.Dish).where(models.Dish.description_ar.is_(None))):
        _ar = DISH_DESCRIPTIONS_AR.get(_d.description)
        if _ar:
            _d.description_ar = _ar
    for _o in db.scalars(select(models.DishOption)):
        if not _o.name_ar and _o.name in OPTION_GROUPS_AR:
            _o.name_ar = OPTION_GROUPS_AR[_o.name]
        try:
            _choices = json.loads(_o.choices or "[]")
        except (TypeError, ValueError):
            continue
        _changed = False
        for _c in _choices:
            if isinstance(_c, dict) and not _c.get("label_ar") and _c.get("label") in OPTION_CHOICES_AR:
                _c["label_ar"] = OPTION_CHOICES_AR[_c["label"]]
                _changed = True
        if _changed:
            _o.choices = json.dumps(_choices, ensure_ascii=False)
    # Default prep minutes by category.
    for _d in db.scalars(select(models.Dish).where(models.Dish.prep_minutes.is_(None))):
        if _d.category in CATEGORY_PREP:
            _d.prep_minutes = CATEGORY_PREP[_d.category]
    # v50: best sellers stay featured (see FEATURED_BEST_SELLERS). Only
    # flips False -> True; idempotent and harmless when already set.
    for _d in db.scalars(
        select(models.Dish).where(models.Dish.name.in_(FEATURED_BEST_SELLERS))
    ):
        if not _d.is_featured:
            _d.is_featured = True
    # Alpha-T Grocery (Oct 2026): new vendor + items, only where missing.
    _ensure_alpha_t(db)
    db.commit()


def seed():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        # v56: rename BEFORE any vendor creation — otherwise the groceries
        # lookup below (by the new name) misses the old row, creates a
        # second vendor, and the later rename duplicates it (v55 live bug).
        _rename_nile_to_lynnwood(db)
        # Demo accounts (only if missing)
        customer = db.scalar(select(models.User).where(models.User.email == "customer@demo.com"))
        if not customer:
            customer = models.User(
                email="customer@demo.com",
                hashed_password=auth.hash_password("demo1234"),
                name="Demo Customer",
                role="customer",
            )
            db.add(customer)
        vendor_user = db.scalar(select(models.User).where(models.User.email == "vendor@demo.com"))
        if not vendor_user:
            vendor_user = models.User(
                email="vendor@demo.com",
                hashed_password=auth.hash_password("demo1234"),
                name="Omar",
                role="vendor",
            )
            db.add(vendor_user)
        admin_user = db.scalar(select(models.User).where(models.User.email == "admin@demo.com"))
        if not admin_user:
            admin_user = models.User(
                email="admin@demo.com",
                hashed_password=auth.hash_password("demo1234"),
                name="Site Admin",
                role="admin",
            )
            db.add(admin_user)
        db.flush()

        # Omar Caboose (only if missing)
        omar = _get_vendor(db, "Omar Caboose")
        if not omar:
            omar = models.Vendor(
                name="Omar Caboose",
                tagline="Good Food, Good Mood",
                area="Mill Creek, WA",
                phone="206-773-6068",
                fulfillment="pickup",
                delivery_fee=Decimal("0"),
                owner_id=vendor_user.id,
            )
            db.add(omar)
            db.flush()
            _add_dishes(db, omar, OMAR_MENU)

        # Lynnwood Groceries (only if missing)
        groceries = _get_vendor(db, GROCERY_VENDOR["name"])
        if not groceries:
            groceries = models.Vendor(
                name=GROCERY_VENDOR["name"],
                tagline=GROCERY_VENDOR["tagline"],
                area=GROCERY_VENDOR["area"],
                phone=GROCERY_VENDOR["phone"],
                fulfillment=GROCERY_VENDOR["fulfillment"],
                delivery_fee=Decimal(str(GROCERY_VENDOR["delivery_fee"])),
            )
            db.add(groceries)
            db.flush()
            _add_dishes(db, groceries, GROCERY_ITEMS)

        # Sample vendors (only if missing)
        for v in SAMPLE_VENDORS:
            vendor = _get_vendor(db, v["name"])
            if vendor:
                continue
            vendor = models.Vendor(
                name=v["name"],
                tagline=v["tagline"],
                area=v["area"],
                phone=v["phone"],
                fulfillment=v["fulfillment"],
                delivery_fee=Decimal(str(v["delivery_fee"])),
            )
            db.add(vendor)
            db.flush()
            _add_dishes(db, vendor, v["dishes"])
        db.flush()

        # === v50: top up dishes added to an existing vendor's menu ===
        # The loop above only seeds a vendor's dishes when the vendor is
        # first created, so dishes added to the seed lists later (Konafa,
        # Qatayef, Ta'ameya at Mama Samia's) would never reach databases
        # that already have the vendor — including the live site, which
        # runs seed on every boot. Add just the missing ones (idempotent).
        _ms = next(v for v in SAMPLE_VENDORS if v["name"] == "Mama Samia's Kitchen")
        _msv = _get_vendor(db, _ms["name"])
        if _msv is not None:
            _have = {
                d.name
                for d in db.scalars(
                    select(models.Dish).where(models.Dish.vendor_id == _msv.id)
                )
            }
            _new_dishes = [
                item
                for item in _ms["dishes"]
                if item[0] in ("Konafa", "Qatayef", "Ta'ameya (Egyptian Falafel)")
                and item[0] not in _have
            ]
            if _new_dishes:
                _add_dishes(db, _msv, _new_dishes)
                db.flush()
        # === END v50 top-up ===

        # Um Sohaib's Kitchen (only if missing) — dishes carry photo_url so the
        # web, vendor portal, and mobile app all show the same photo; the four
        # dishes without a dedicated photo resolve via PHOTO_RULES.
        um = _get_vendor(db, UM_SOHAIB_VENDOR["name"])
        if not um:
            um = models.Vendor(
                name=UM_SOHAIB_VENDOR["name"],
                tagline=UM_SOHAIB_VENDOR["tagline"],
                area=UM_SOHAIB_VENDOR["area"],
                phone=UM_SOHAIB_VENDOR["phone"],
                fulfillment=UM_SOHAIB_VENDOR["fulfillment"],
                delivery_fee=Decimal(str(UM_SOHAIB_VENDOR["delivery_fee"])),
            )
            db.add(um)
            db.flush()
            for name, desc, price, category, featured, photo in UM_SOHAIB_MENU:
                db.add(
                    models.Dish(
                        vendor_id=um.id,
                        name=name,
                        # v52: Arabic name at creation.
                        name_ar=DISH_NAMES_AR.get(name),
                        description=desc,
                        price=Decimal(str(price)),
                        category=category,
                        is_featured=featured,
                        photo_url=("/img/" + photo) if photo else "",
                    )
                )
            db.flush()
            for dish_name, group_name, choices in UM_SOHAIB_OPTIONS:
                dish = db.scalar(
                    select(models.Dish).where(
                        models.Dish.vendor_id == um.id,
                        models.Dish.name == dish_name,
                    )
                )
                if dish:
                    db.add(
                        models.DishOption(
                            dish_id=dish.id,
                            name=group_name,
                            selection_type="single",
                            min_select=1,
                            max_select=1,
                            choices=json.dumps(
                                [{"label": label, "delta": delta} for label, delta in choices]
                            ),
                        )
                    )
            db.flush()

        # A couple of demo orders so the vendor earnings dashboard has data
        # (only on a completely fresh database)
        if not db.scalar(select(models.Order).limit(1)):
            fish = db.scalar(select(models.Dish).where(models.Dish.name == "Whole Grilled Fish"))
            tahini = db.scalar(select(models.Dish).where(models.Dish.name == "Tahini Salad"))
            kofta = db.scalar(select(models.Dish).where(models.Dish.name == "Egyptian Kofta (Plate)"))

            def _order(dish_qtys, status, fulfillment="pickup", payment_method="cash"):
                items = []
                subtotal = Decimal("0")
                for dish, qty in dish_qtys:
                    price = Decimal(dish.price)
                    subtotal += price * qty
                    items.append(
                        models.OrderItem(
                            dish_id=dish.id, dish_name=dish.name,
                            # v52: Arabic name snapshot, same as checkout.
                            dish_name_ar=dish.name_ar,
                            unit_price=price, quantity=qty
                        )
                    )
                order = models.Order(
                    customer_id=customer.id,
                    vendor_id=omar.id,
                    status=status,
                    fulfillment=fulfillment,
                    payment_method=payment_method,
                    subtotal=subtotal,
                    delivery_fee=Decimal("0"),
                    total=subtotal,
                    items=items,
                )
                db.add(order)
                db.flush()
                return order

            o1 = _order([(fish, 2), (tahini, 1)], "completed", payment_method="zelle")
            _log_event(db, o1, "placed",
                       f"Order placed by {customer.name} — 2 item(s), pickup, paid via zelle (recorded only)",
                       {"fulfillment": "pickup", "payment_method": "zelle"})
            for prev, nxt in (("new", "preparing"), ("preparing", "ready"), ("ready", "completed")):
                _log_event(db, o1, "status", f"Status changed: {prev} → {nxt}",
                           {"from": prev, "to": nxt, "by": vendor_user.name})
            _log_event(db, o1, "email",
                       f"Completion email sent to {customer.email}",
                       {"subject": _completion_email(o1)[0],
                        "body": _completion_email(o1)[1],
                        "to": customer.email})
            o2 = _order([(kofta, 1)], "new", payment_method="cash")
            _log_event(db, o2, "placed",
                       f"Order placed by {customer.name} — 1 item(s), pickup, paid via cash (recorded only)",
                       {"fulfillment": "pickup", "payment_method": "cash"})

        db.commit()
        # === FEATURE 2: every vendor gets a unique referral share code ===
        # (idempotent — only vendors missing a code get one).
        from . import referrals as _referrals

        n = _referrals.ensure_referral_codes(db)
        if n:
            print(f"Backfilled {n} vendor referral code(s).")
        # Default referral rebate setting (display-only; the admin can change
        # it from the back-office site settings).
        if (
            db.scalar(
                select(models.Setting).where(
                    models.Setting.key == "referral_rebate_percent"
                )
            )
            is None
        ):
            db.add(models.Setting(key="referral_rebate_percent", value="2"))
            db.commit()
        # === END FEATURE 2 ===
        # Idempotent seed-data fills (ingredients text, prep defaults) — also
        # run on every app startup (see main.py) for in-place zip upgrades.
        fill_seed_data(db)
        print("Seeded OK: vendors, demo accounts, demo orders (added only what was missing).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
