"""Seed the database with demo vendors, the full Omar Caboose menu,
sample vendors, demo accounts, and a couple of demo orders.

Idempotent: adds only whatever is missing (safe to re-run).

Run (from the backend/ folder, VS Code terminal):
  $env:DATABASE_URL = "sqlite:///./app.db"
  python -m app.seed
"""
import json
from decimal import Decimal

from sqlalchemy import select

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
    ("Charcoal-Grilled Hawawshi (Plate)", "Egyptian stuffed bread with seasoned beef", 15.99, "Grill", False),
    # ---- Casseroles ----
    ("Cow Trotters Casserole (Kaware')", "Traditional Egyptian cow trotters casserole", 24.99, "Casseroles", False),
    ("Oxtail Casserole (Akawi)", "Slow-cooked oxtail casserole", 26.99, "Casseroles", False),
    ("Okra with Beef (Bamia)", "Okra cooked with tender beef", 21.99, "Casseroles", False),
    ("Egyptian Baked Rice with Lamb (Rice Ma'amar)", "Baked rice with lamb, Egyptian style", 22.99, "Casseroles", False),
    ("Egyptian Béchemel Pasta (Macarona Bechamel)", "Layered pasta with béchamel sauce", 17.99, "Casseroles", False),
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
    ("Mixed Mahshi Tray (Half Tray)", "Grape leaves, cabbage, zucchini, eggplant, and tomatoes", 44.99, "Mahshi", False),
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
            ("Basbousa", "Semolina cake with syrup", 6.99, "Desserts", False),
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
            ("Molokhia with Chicken", "Molokhia stew with chicken, served with rice", 14.99, "Mains", False),
            ("Koshary", "Rice, lentils, pasta, chickpeas, and spicy tomato sauce", 9.99, "Mains", True),
            ("Fatta", "Layered bread, rice, and meat with garlic-vinegar sauce", 15.99, "Mains", False),
            ("Om Ali", "Egyptian bread pudding", 7.99, "Desserts", False),
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
    "name": "Nile Groceries",
    "tagline": "Egyptian pantry staples, spices & sweets",
    "area": "Everett, WA",
    "phone": "206-555-0345",
    "fulfillment": "both",
    "delivery_fee": 3.99,
}

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
    "Charcoal-Grilled Hawawshi": "Minced beef, onions, peppers, baked in baladi bread",
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
                description=desc,
                price=Decimal(str(price)),
                category=category,
                is_featured=featured,
            )
        )


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
    # Default prep minutes by category.
    for _d in db.scalars(select(models.Dish).where(models.Dish.prep_minutes.is_(None))):
        if _d.category in CATEGORY_PREP:
            _d.prep_minutes = CATEGORY_PREP[_d.category]
    db.commit()


def seed():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
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

        # Nile Groceries (only if missing)
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
                            dish_id=dish.id, dish_name=dish.name, unit_price=price, quantity=qty
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
