import os
import json
import base64
import random
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Load .env from project root
load_dotenv()

app = FastAPI(title="AI Visual Product Reviewer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5176", "http://127.0.0.1:5176"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ────────────────────────────────────────────────────────────────────

FIXED_PLATFORMS = [
    {"name": "Amazon",   "search_url": "https://www.amazon.com/s?k={q}"},
    {"name": "Best Buy", "search_url": "https://www.bestbuy.com/site/searchpage.jsp?st={q}"},
    {"name": "Walmart",  "search_url": "https://www.walmart.com/search?q={q}"},
    {"name": "Target",   "search_url": "https://www.target.com/s?searchTerm={q}"},
]


def build_platform_url(platform_name: str, product_name: str) -> str:
    q = urllib.parse.quote_plus(product_name)
    for p in FIXED_PLATFORMS:
        if p["name"].lower() == platform_name.lower():
            return p["search_url"].format(q=q)
    return f"https://www.google.com/search?q={q}+buy+site:{platform_name.lower().replace(' ', '')}.com"


def generate_realistic_price_history(base_price: float, product_name: str):
    seed = sum(ord(c) for c in product_name.lower())
    rng = random.Random(seed)
    today = datetime.today()
    months, prices = [], []

    current = base_price * rng.uniform(1.12, 1.30)

    for i in range(11, 0, -1):
        month_dt = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        label = month_dt.strftime("%Y-%m")
        month_num = month_dt.month

        seasonal = 0.0
        if month_num == 11:   seasonal =  base_price * 0.06
        elif month_num == 12: seasonal =  base_price * 0.04
        elif month_num == 7:  seasonal = -base_price * 0.05
        elif month_num == 8:  seasonal = -base_price * 0.07

        drift = (base_price - current) * 0.20
        noise = rng.uniform(-base_price * 0.04, base_price * 0.04)
        current = round(max(base_price * 0.70, min(base_price * 1.40, current + drift + seasonal + noise)), 2)
        months.append(label)
        prices.append(current)

    months.append(today.replace(day=1).strftime("%Y-%m"))
    prices.append(round(base_price, 2))

    price_range = max(prices) - min(prices)
    if price_range < base_price * 0.08:
        prices[0] = round(base_price * rng.uniform(1.15, 1.30), 2)

    return [{"date": m, "price": p} for m, p in zip(months, prices)]


def get_gemini_model():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash")


BASE_PROMPT = """Analyze the product based on the provided input (image, text, or both) and provide a comprehensive review in JSON format matching exactly this structure:
{
    "product_name": "Name of the product",
    "category": "Product category",
    "specific_answer": "Directly answer the user's specific request or question. If no specific question was asked, briefly summarize the product's value proposition.",
    "build_and_features": {
        "build_quality": "High-level summary of construction quality",
        "materials": ["Material 1", "Material 2"],
        "special_details": "Unique features or technical highlights"
    },
    "key_features": ["Feature 1", "Feature 2", "Feature 3"],
    "pros": ["Pro 1", "Pro 2", "Pro 3"],
    "cons": ["Con 1", "Con 2"],
    "rating": 4.5,
    "worth_buying": true,
    "average_price": 199.99,
    "reviews": [
        {"user": "User1", "platform": "Amazon", "text": "Detailed review text.", "rating": 5},
        {"user": "User2", "platform": "BestBuy", "text": "Detailed review text.", "rating": 4}
    ],
    "platforms": [
        {"name": "Amazon",   "trust_score": 9.5, "price": 199.99},
        {"name": "Best Buy", "trust_score": 9.0, "price": 199.99},
        {"name": "Walmart",  "trust_score": 8.5, "price": 189.99},
        {"name": "Target",   "trust_score": 8.8, "price": 195.99}
    ],
    "price_history": [{"date": "2023-01", "price": 249.99}],
    "frequently_bought_together": [{"name": "Accessory A", "reason": "Protects the product"}],
    "better_alternatives": [
        {
            "name": "Alternative Name",
            "brand": "Brand Name",
            "brand_domain": "brand.com",
            "price": 179.99,
            "url": "https://www.amazon.com/s?k=alternative+name",
            "reason": "Direct comparison or value proposition."
        }
    ],
    "review_authenticity": {
        "genuine_count": 3,
        "fake_count": 1,
        "confidence_score": 75,
        "summary": "Most reviews appear genuine; one review shows signs of being fabricated.",
        "key_signals": [
            "Consistent sentiment across multiple platforms",
            "High percentage of verified purchase indicators",
            "Natural language variations in positive feedback",
            "Detection of suspicious templated language in 1 review"
        ],
        "per_review": [
            {"user": "User1", "platform": "Amazon", "verdict": "genuine", "text": "Great product, works as expected.", "reason": "Specific product details mentioned, balanced tone."},
            {"user": "User2", "platform": "BestBuy", "verdict": "fake", "text": "AMAZING!!! BEST EVER!!!", "reason": "Overly promotional, no critical feedback, suspiciously short."}
        ]
    },
    "is_new_product": true
}

Return ONLY valid JSON.
If an image is provided, use it as the primary source of truth.
If text is provided, determine if it is a follow-up question about the product in the image or a completely NEW product search.
Set "is_new_product" to true if the user is asking about a different product than what is shown/previously discussed, or if no image is provided.
Set "is_new_product" to false if the user is asking a refinement or follow-up question about the product in the image.
For platforms, ALWAYS return EXACTLY these 4 stores: Amazon, Best Buy, Walmart, Target. Do NOT include URLs. Ensure at least 4 reviews. Provide 12 months of mock price_history.
For better_alternatives, provide at least 3 options with brand, brand_domain, price, url, and reason.
For platform names, use standard recognizable names like Amazon, Best Buy, Walmart, Target, eBay, B&H Photo, Newegg, Flipkart, etc.
For review_authenticity, analyze each review and classify as 'genuine' or 'fake' with a reason. Provide genuine_count, fake_count, and confidence_score (0-100)."""


# Mock product data for when APIs are unavailable
MOCK_PRODUCTS = [
    {
        "product_name": "Wireless Bluetooth Headphones Pro",
        "category": "Audio Equipment",
        "build_quality": "Premium aluminum construction with soft ear cushions",
        "materials": ["Aluminum", "Silicone", "Stainless Steel"],
        "special_details": "Active Noise Cancellation, 40-hour battery life",
        "key_features": ["ANC Technology", "40h Battery", "Bluetooth 5.0"],
        "pros": ["Excellent sound quality", "Long battery life", "Comfortable fit"],
        "cons": ["Slightly bulky", "Premium pricing"],
        "rating": 4.7,
        "worth_buying": True,
        "average_price": 299.99,
    },
    {
        "product_name": "USB-C Fast Charging Cable",
        "category": "Electronics Accessories",
        "build_quality": "Durable nylon braided design",
        "materials": ["Nylon Braid", "Copper Wire", "Aluminum Connectors"],
        "special_details": "100W Power Delivery, 6ft length, reinforced connectors",
        "key_features": ["100W PD Support", "6ft Length", "Fast Charging"],
        "pros": ["Very durable", "Fast charging", "Good value"],
        "cons": ["Slightly stiff initially", "Expensive for a cable"],
        "rating": 4.5,
        "worth_buying": True,
        "average_price": 19.99,
    },
    {
        "product_name": "Portable External SSD 2TB",
        "category": "Storage Devices",
        "build_quality": "Rugged metal casing with shock protection",
        "materials": ["Aluminum", "Rubber Padding", "NAND Flash"],
        "special_details": "550MB/s read speed, USB 3.1, waterproof up to 3ft",
        "key_features": ["2TB Storage", "550MB/s Speed", "Waterproof"],
        "pros": ["Very fast", "Reliable", "Compact size"],
        "cons": ["Premium price", "Gets warm under load"],
        "rating": 4.6,
        "worth_buying": True,
        "average_price": 249.99,
    },
]

def generate_mock_result(text_prompt: Optional[str]) -> dict:
    """Generate mock product review when API is unavailable."""
    rng = random.Random()
    base_product = rng.choice(MOCK_PRODUCTS)
    product_name = base_product["product_name"]
    category = base_product["category"]
    base_price = base_product["average_price"]
    
    platform_prices = [
        base_price * rng.uniform(0.95, 1.05),
        base_price * rng.uniform(0.92, 1.08),
        base_price * rng.uniform(0.90, 1.10),
        base_price * rng.uniform(0.93, 1.07),
    ]
    
    return {
        "product_name": product_name,
        "category": category,
        "specific_answer": f"This product offers excellent value and performance.",
        "build_and_features": {
            "build_quality": base_product.get("build_quality", "High quality construction"),
            "materials": base_product.get("materials", ["Premium Materials"]),
            "special_details": base_product.get("special_details", "Well-engineered product"),
        },
        "key_features": base_product.get("key_features", ["Feature 1", "Feature 2", "Feature 3"]),
        "pros": base_product.get("pros", ["Excellent quality", "Good value", "Reliable"]),
        "cons": base_product.get("cons", ["Premium pricing", "Availability issues"]),
        "rating": base_product.get("rating", 4.5),
        "worth_buying": base_product.get("worth_buying", True),
        "average_price": round(base_price, 2),
        "reviews": [
            {"user": "John D.", "platform": "Amazon", "text": "Great product, exceeded expectations.", "rating": 5},
            {"user": "Sarah M.", "platform": "Best Buy", "text": "Good quality, fast shipping.", "rating": 4},
            {"user": "Mike R.", "platform": "Walmart", "text": "Very satisfied with this purchase.", "rating": 5},
            {"user": "Lisa P.", "platform": "Target", "text": "Solid product at a fair price.", "rating": 4},
        ],
        "platforms": [
            {"name": "Amazon", "trust_score": 9.5, "price": round(platform_prices[0], 2)},
            {"name": "Best Buy", "trust_score": 9.0, "price": round(platform_prices[1], 2)},
            {"name": "Walmart", "trust_score": 8.5, "price": round(platform_prices[2], 2)},
            {"name": "Target", "trust_score": 8.8, "price": round(platform_prices[3], 2)},
        ],
        "price_history": [],
        "frequently_bought_together": [{"name": "Protective Case", "reason": "Protects the product from damage"}],
        "better_alternatives": [
            {
                "name": "Alternative Brand Premium",
                "brand": "TechBrand",
                "brand_domain": "techbrand.com",
                "price": round(base_price * 1.2, 2),
                "url": "https://www.amazon.com/s",
                "reason": "Similar features with better build quality.",
            },
            {
                "name": "Budget Alternative",
                "brand": "ValueBrand",
                "brand_domain": "valuebrand.com",
                "price": round(base_price * 0.7, 2),
                "url": "https://www.amazon.com/s",
                "reason": "Good alternative for budget buyers.",
            },
            {
                "name": "Premium Upgrade",
                "brand": "LuxeBrand",
                "brand_domain": "luxebrand.com",
                "price": round(base_price * 1.5, 2),
                "url": "https://www.amazon.com/s",
                "reason": "Top-tier option with advanced features.",
            },
        ],
        "review_authenticity": {
            "genuine_count": 3,
            "fake_count": 1,
            "confidence_score": 82,
            "summary": "Most reviews appear genuine with consistent positive feedback.",
            "key_signals": ["Consistent sentiment", "Verified purchases", "Natural language"],
            "per_review": [
                {"user": "John D.", "platform": "Amazon", "verdict": "genuine", "text": "Great product.", "reason": "Specific details mentioned."},
            ],
        },
        "is_new_product": False,
    }

def call_gemini_api(image_bytes: Optional[bytes], format_str: Optional[str], text_prompt: Optional[str]) -> dict:
    model = get_gemini_model()
    
    # Build the message content for Gemini
    message_parts = []
    
    # Add image if provided
    if image_bytes:
        # Gemini accepts PIL images or base64 encoded images
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        message_parts.append(img)
    
    # Add the prompt
    final_text = BASE_PROMPT
    if text_prompt:
        final_text = f"USER REQUEST: {text_prompt}\n\nINSTRUCTIONS: {BASE_PROMPT}"
    
    message_parts.append(final_text)
    
    # Call Gemini API with vision
    response = model.generate_content(
        message_parts,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=4096,
        )
    )

    output_text = response.text
    output_text = output_text.strip()
    if output_text.startswith("```json"):
        output_text = output_text[7:]
    elif output_text.startswith("```"):
        output_text = output_text[3:]
    if output_text.endswith("```"):
        output_text = output_text[:-3]
    return json.loads(output_text.strip())


# ── Route ──────────────────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze(
    prompt: str = Form(default=""),
    image: Optional[UploadFile] = File(default=None),
):
    img_bytes = None
    fmt = None
    if image and image.filename:
        img_bytes = await image.read()
        ext = image.filename.rsplit(".", 1)[-1].lower()
        fmt = "jpeg" if ext == "jpg" else ext

    try:
        result = call_gemini_api(img_bytes, fmt, prompt or None)
    except Exception as e:
        # API failed - use mock data instead
        print(f"API Error: {str(e)[:100]}... Using mock data instead.")
        result = generate_mock_result(prompt or None)

    # Enrich platforms with generated search URLs
    product_name = result.get("product_name", "product")
    for p in result.get("platforms", []):
        p["url"] = build_platform_url(p.get("name", ""), product_name)

    # Replace AI price history with our deterministic one
    platforms = result.get("platforms", [])
    base_price = 99.99
    if platforms:
        try:
            base_price = float(min(p.get("price", 9999) for p in platforms))
        except Exception:
            pass
    result["average_price"] = base_price
    result["price_history"] = generate_realistic_price_history(base_price, product_name)

    # Dynamic image sync: Use a high-quality product placeholder based on category
    if result.get("is_new_product") or not img_bytes:
        category = result.get("category", "product")
        # Add "product" to the category search to get more relevant images
        search_term = f"{category},product"
        safe_term = urllib.parse.quote_plus(search_term)
        # loremflickr is a reliable alternative for generic placeholders by category
        result["product_image_url"] = f"https://loremflickr.com/800/600/{safe_term}"
    else:
        result["product_image_url"] = None

    return result
