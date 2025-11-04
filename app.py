# app.py - Complete NutriGuard AI with Groq API + Smart Grocery List
import os
import re
import json
from typing import Dict, Any
from flask import Flask, render_template, request, jsonify
import requests
import traceback

# dotenv: load .env if present
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Enable debug mode to see full errors
app.config['DEBUG'] = True
app.config['PROPAGATE_EXCEPTIONS'] = True

# ----------------- API KEYS (from environment) -----------------
USDA_API_KEY = os.getenv("USDA_API_KEY", "DEMO_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

print("\n" + "="*60)
print("🔑 API KEY STATUS:")
print("="*60)
print(f"USDA_API_KEY: {'✅ SET' if USDA_API_KEY and USDA_API_KEY != 'DEMO_KEY' else '⚠️ USING DEMO'}")
print(f"WEATHER_API_KEY: {'✅ SET' if WEATHER_API_KEY else '❌ NOT SET'}")
print(f"GROQ_API_KEY: {'✅ SET' if GROQ_API_KEY else '❌ NOT SET'}")
print("="*60 + "\n")

if not WEATHER_API_KEY:
    print("⚠️ WARNING: WEATHER_API_KEY not set. Weather features will not work.")

if not GROQ_API_KEY:
    print("⚠️ WARNING: GROQ_API_KEY not set. Chat functionality will not work.")

# ----------------- GROQ SETTINGS -----------------
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# ----------------- WEATHER DATA -----------------
def get_weather(city: str):
    if not WEATHER_API_KEY:
        return {"condition": "Unknown", "temp": 25, "humidity": 50}
    
    try:
        url = "http://api.weatherapi.com/v1/current.json"
        params = {"key": WEATHER_API_KEY, "q": city, "aqi": "no"}
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        d = r.json()
        return {
            "condition": d["current"]["condition"]["text"],
            "temp": d["current"]["temp_c"],
            "humidity": d["current"]["humidity"],
        }
    except Exception as e:
        print(f"❌ Weather API error: {e}")
        return {"condition": "Unknown", "temp": 25, "humidity": 50}

# ----------------- NUTRIENTS FETCH -----------------
def get_food_nutrients(food: str) -> Dict[str, tuple]:
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {"api_key": USDA_API_KEY, "query": food, "pageSize": 1}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        nutrients = {}
        foods = data.get("foods", [])
        if not foods:
            return nutrients
        food_data = foods[0]
        for n in food_data.get("foodNutrients", []):
            name = n.get("nutrientName") or n.get("name")
            val = n.get("value")
            unit = n.get("unitName") or n.get("unit")
            if name and val is not None:
                try:
                    nutrients[name.strip()] = (float(val), unit or "")
                except Exception:
                    continue
        return nutrients
    except Exception as e:
        print(f"❌ USDA API error for {food}: {e}")
        return {}

def convert_to_mg(amount: float, unit: str) -> float:
    unit = (unit or "").lower()
    if unit in ("g", "gram", "grams"):
        return amount * 1000.0
    if unit in ("mg", "milligram", "milligrams"):
        return amount
    return amount

NUTRIENT_KEY_MAP = {
    "Protein": ["protein"],
    "Vitamin C": ["vitamin c", "ascorbic acid"],
    "Iron": ["iron"],
    "Calcium": ["calcium"],
    "Fiber": ["fiber", "dietary fiber"],
}

def calculate_deficiency(total_nutrients_mg: Dict[str,float], gender: str, height_cm: float, weight_kg: float):
    baseline = {
        "Protein_g": 50.0,
        "Vitamin C_mg": 90.0,
        "Iron_mg": 18.0 if gender.lower() == "female" else 8.0,
        "Calcium_mg": 1000.0,
        "Fiber_g": 30.0,
    }
    bmi = weight_kg / ((height_cm / 100.0) ** 2) if height_cm > 0 else 0
    if bmi and bmi < 18.5:
        for k in list(baseline.keys()):
            baseline[k] *= 1.10
    elif bmi and bmi > 25:
        for k in list(baseline.keys()):
            baseline[k] *= 0.90

    deficiencies = {}
    protein_mg = total_nutrients_mg.get("Protein", 0.0)
    fiber_mg = total_nutrients_mg.get("Fiber", 0.0)
    if protein_mg < (baseline["Protein_g"] * 1000.0) * 0.6:
        need_mg = baseline["Protein_g"] * 1000.0 - protein_mg
        deficiencies["Protein"] = f"{round(need_mg/1000.0, 2)} g"
    if fiber_mg < (baseline["Fiber_g"] * 1000.0) * 0.6:
        need_mg = baseline["Fiber_g"] * 1000.0 - fiber_mg
        deficiencies["Fiber"] = f"{round(need_mg/1000.0, 2)} g"

    for short_key, base_key in [("Vitamin C", "Vitamin C_mg"), ("Iron", "Iron_mg"), ("Calcium", "Calcium_mg")]:
        have = total_nutrients_mg.get(short_key, 0.0)
        need = baseline[base_key]
        if have < need * 0.6:
            need_more = need - have
            deficiencies[short_key] = f"{round(need_more, 2)} mg"
    return deficiencies

def recommend_foods(defic: Dict[str,str], weather: Dict[str,Any]):
    base = {
        "Protein": [("Chicken", "27 g"), ("Eggs", "13 g"), ("Paneer", "18 g")],
        "Iron": [("Spinach", "2.7 mg"), ("Liver", "6.5 mg"), ("Beans", "3.7 mg")],
        "Calcium": [("Milk", "120 mg"), ("Curd", "80 mg"), ("Almonds", "75 mg")],
        "Fiber": [("Oats", "10 g"), ("Apple", "4.5 g"), ("Carrots", "3 g")],
        "Vitamin C": [("Orange", "53 mg"), ("Guava", "200 mg"), ("Kiwi", "90 mg")],
    }
    temp_foods = ["Cucumber", "Yogurt"] if weather and weather.get("temp", 0) > 30 else ["Soup", "Eggs"]
    rec = []
    for n in defic.keys():
        rec.extend(base.get(n, []))
    for f in temp_foods:
        rec.append((f, "-", "-"))
    return rec[:10]

# ----------------- GROQ AI CHAT -----------------
def call_groq_chat(message: str, analysis: Dict[str, Any], lang: str = "en") -> str:
    """
    Calls Groq API for chat completion.
    """
    print("\n" + "="*60)
    print("🤖 GROQ CHAT FUNCTION CALLED")
    print("="*60)
    print(f"Message: {message}")
    print(f"Analysis keys: {list(analysis.keys()) if analysis else 'None'}")
    print(f"GROQ_API_KEY present: {bool(GROQ_API_KEY)}")
    
    if not GROQ_API_KEY:
        error_msg = "❌ Groq API key not configured. Please set GROQ_API_KEY in your .env file."
        print(error_msg)
        return error_msg
    
    # Build the system prompt with nutrition context
    system_prompt = "You are a helpful and friendly AI Dietician Assistant. Provide concise, practical nutrition advice.\n\n"
    
    if analysis:
        system_prompt += "--- NUTRITION ANALYSIS CONTEXT ---\n"
        
        if analysis.get("total_nutrients"):
            system_prompt += "\n[Total Nutrients]\n"
            for k, v in analysis["total_nutrients"].items():
                system_prompt += f"- {k}: {v}\n"
        
        if analysis.get("deficient"):
            system_prompt += "\n[Deficient Nutrients]\n"
            if len(analysis["deficient"]) > 0:
                for k, v in analysis["deficient"].items():
                    system_prompt += f"- {k}: need {v} more\n"
            else:
                system_prompt += "- No deficiencies detected\n"
        
        if analysis.get("weather"):
            system_prompt += f"\n[Weather Context]\n"
            system_prompt += f"- Condition: {analysis['weather'].get('condition', 'N/A')}\n"
            system_prompt += f"- Temperature: {analysis['weather'].get('temp', 'N/A')}°C\n"
        
        system_prompt += "\n--- END CONTEXT ---\n"
    
    system_prompt += "\nProvide helpful, concise responses (2-4 sentences)."
    
    if lang and lang != "en":
        system_prompt += f"\nRespond in: {lang}"
    
    print(f"System prompt length: {len(system_prompt)} chars")
    
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        print(f"📤 Sending request to Groq API...")
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        print(f"📥 Response status: {response.status_code}")
        
        response.raise_for_status()
        
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        
        print(f"✅ Got response from Groq (length: {len(reply)} chars)")
        print(f"Reply preview: {reply[:100]}...")
        return reply
        
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Groq API request error: {str(e)}"
        print(error_msg)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response text: {e.response.text}")
        return f"Sorry, I encountered an error connecting to the AI service: {str(e)}"
    except Exception as e:
        error_msg = f"❌ Unexpected error: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return f"Sorry, an unexpected error occurred: {str(e)}"

# ----------------- ROUTES -----------------
@app.route("/")
def home():
    return render_template("nutri.html")

@app.route("/smart_gross_list")
def smart_gross_list():
    return render_template("smart_gross_list.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    city = (data.get("city") or "").strip()
    items = data.get("items", [])
    gender = data.get("gender", "male")
    try:
        height = float(data.get("height") or 0)
    except Exception:
        height = 0.0
    try:
        weight = float(data.get("weight") or 0)
    except Exception:
        weight = 0.0

    if not city:
        return jsonify({"error": "City required"}), 400

    weather = get_weather(city)

    totals_mg = {}
    for it in items:
        name = (it.get("name") or "").strip()
        try:
            qty_g = float(it.get("qty") or 0)
        except Exception:
            qty_g = 0.0
        if not name or qty_g <= 0:
            continue
        nut = get_food_nutrients(name)
        for full_name, (val, unit) in nut.items():
            try:
                actual = float(val) * (qty_g / 100.0)
            except Exception:
                continue
            matched_key = None
            low = full_name.lower()
            for friendly, substrings in NUTRIENT_KEY_MAP.items():
                if any(s in low for s in substrings):
                    matched_key = friendly
                    break
            if not matched_key:
                continue
            amount_mg = convert_to_mg(actual, unit)
            totals_mg[matched_key] = totals_mg.get(matched_key, 0.0) + amount_mg

    defic = calculate_deficiency(totals_mg, gender, height, weight)
    rec = recommend_foods(defic, weather)

    human_totals = {}
    for k, v in totals_mg.items():
        if k in ("Protein", "Fiber"):
            human_totals[k] = f"{round(v/1000.0, 2)} g"
        else:
            human_totals[k] = f"{round(v, 2)} mg"

    return jsonify({
        "weather": weather,
        "total_nutrients": human_totals,
        "deficient": defic,
        "recommendations": rec
    })

@app.route("/chat", methods=["POST"])
def chat():
    """
    Chat endpoint for the AI Dietician Assistant using Groq API.
    """
    print("\n" + "="*60)
    print("🔵 /CHAT ENDPOINT HIT")
    print("="*60)
    
    try:
        data = request.get_json() or {}
        print(f"📦 Request data keys: {list(data.keys())}")
        
        message = data.get("message")
        analysis_data = data.get("analysis_data")
        lang = data.get("lang", "en")
        
        print(f"💬 Message: {message}")
        print(f"📊 Analysis data: {type(analysis_data)} - {bool(analysis_data)}")
        print(f"🌍 Language: {lang}")
        
        if not message:
            print("❌ No message provided")
            return jsonify({"ok": False, "error": "No message provided"}), 400

        if not GROQ_API_KEY:
            print("❌ GROQ_API_KEY not set")
            return jsonify({
                "ok": False, 
                "error": "GROQ_API_KEY not set in environment (.env file)."
            }), 500

        print("🚀 Calling call_groq_chat function...")
        chat_reply = call_groq_chat(message, analysis_data or {}, lang=lang)
        print(f"✅ Got reply from call_groq_chat")
        
        response_data = {"ok": True, "reply": chat_reply}
        print(f"📤 Sending response: {response_data}")
        return jsonify(response_data)
        
    except Exception as e:
        print("="*60)
        print("❌ EXCEPTION IN /CHAT ENDPOINT")
        print("="*60)
        print(traceback.format_exc())
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/generate_grocery_list", methods=["POST"])
def generate_grocery_list():
    """
    Generate a personalized grocery list using Groq AI based on health profile.
    """
    print("\n" + "="*60)
    print("🛒 /API/GENERATE_GROCERY_LIST ENDPOINT HIT")
    print("="*60)
    
    try:
        data = request.get_json() or {}
        print(f"📦 Request data: {data}")
        
        if not GROQ_API_KEY:
            print("❌ GROQ_API_KEY not set")
            return jsonify({
                "error": "GROQ_API_KEY not set in environment (.env file)."
            }), 500
        
        # Build a detailed prompt for Groq
        prompt = f"""Generate a personalized grocery list based on this health profile:

**Personal Information:**
- Age: {data.get('age')} years
- Gender: {data.get('gender')}
- Height: {data.get('height')} cm
- Weight: {data.get('weight')} kg
- Activity Level: {data.get('activityLevel')}

**Health Metrics:**
- Blood Pressure: {data.get('systolicBP')}/{data.get('diastolicBP')} mmHg
- Blood Sugar: {data.get('bloodSugar')} mg/dL
- Cholesterol: {data.get('cholesterol')} mg/dL

**Dietary Preferences:**
- Goals: {data.get('dietaryGoals')}
- Restrictions: {data.get('dietaryRestrictions', 'None')}
- Preferred Cuisines: {data.get('preferredCuisines', 'Any')}
- Budget Level: {data.get('budgetLevel')}
- Meal Plan Duration: {data.get('mealPlanDuration')} days

**Location Context:**
- Region: {data.get('region')}
- Weather: {data.get('weather')}

Please generate a comprehensive grocery list organized by categories.

Return ONLY a valid JSON array with this exact format (no markdown, no explanations):
[
  {{"category": "Fruits & Vegetables", "name": "Spinach", "quantity": "500g"}},
  {{"category": "Proteins", "name": "Chicken Breast", "quantity": "1kg"}},
  {{"category": "Grains & Cereals", "name": "Brown Rice", "quantity": "2kg"}},
  {{"category": "Dairy & Alternatives", "name": "Low-fat Milk", "quantity": "2L"}},
  {{"category": "Snacks & Beverages", "name": "Green Tea", "quantity": "100g"}},
  {{"category": "Spices & Condiments", "name": "Turmeric", "quantity": "50g"}}
]

Make the list:
- Tailored to their health conditions (BP, sugar, cholesterol)
- Appropriate for their dietary goals and restrictions
- Suitable for their region ({data.get('region')}) and weather ({data.get('weather')})
- Within their budget level ({data.get('budgetLevel')})
- Sufficient for {data.get('mealPlanDuration')} days
- Include 15-25 items with variety and balanced nutrition"""

        print("🚀 Calling Groq API...")
        
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are an expert nutritionist and meal planner. Generate practical, healthy grocery lists in valid JSON format ONLY. Return raw JSON array with no markdown formatting, no code blocks, no explanations - just pure JSON."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        print(f"📥 Response status: {response.status_code}")
        
        response.raise_for_status()
        
        result = response.json()
        ai_response = result["choices"][0]["message"]["content"].strip()
        
        print(f"✅ Got response from Groq")
        print(f"Response preview: {ai_response[:200]}...")
        
        # Try to extract JSON from the response
        try:
            # Remove markdown code blocks if present
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            grocery_list = json.loads(ai_response)
            
            # Validate structure
            if not isinstance(grocery_list, list):
                raise ValueError("Response is not a list")
            
            # Ensure each item has required fields
            for item in grocery_list:
                if not all(k in item for k in ["category", "name", "quantity"]):
                    raise ValueError("Missing required fields in grocery item")
            
            print(f"✅ Successfully parsed {len(grocery_list)} grocery items")
            return jsonify({"grocery_list": grocery_list})
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {e}")
            print(f"Raw response: {ai_response}")
            
            # Fallback: Create a basic grocery list
            fallback_list = [
                {"category": "Fruits & Vegetables", "name": "Spinach", "quantity": "500g"},
                {"category": "Fruits & Vegetables", "name": "Tomatoes", "quantity": "1kg"},
                {"category": "Proteins", "name": "Chicken Breast", "quantity": "1kg"},
                {"category": "Proteins", "name": "Eggs", "quantity": "12 pieces"},
                {"category": "Grains & Cereals", "name": "Brown Rice", "quantity": "2kg"},
                {"category": "Dairy & Alternatives", "name": "Low-fat Milk", "quantity": "2L"},
                {"category": "Snacks & Beverages", "name": "Green Tea", "quantity": "100g"},
            ]
            return jsonify({"grocery_list": fallback_list, "note": "Using fallback list due to AI response format issue"})
        
    except requests.exceptions.RequestException as e:
        print("="*60)
        print("❌ GROQ API REQUEST ERROR")
        print("="*60)
        print(traceback.format_exc())
        return jsonify({"error": f"AI service error: {str(e)}"}), 500
    except Exception as e:
        print("="*60)
        print("❌ EXCEPTION IN /API/GENERATE_GROCERY_LIST")
        print("="*60)
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 Starting NutriGuard AI Server with Groq")
    print("="*60)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
