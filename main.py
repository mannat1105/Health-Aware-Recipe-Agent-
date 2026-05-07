import requests
import json
import time

# ============================================================
#  API KEYS
# ============================================================
GROQ_API_KEY = "Insert key here"  
USDA_API_KEY = "Insert key here"   

# ============================================================
#  SHARED STATE : accumulates results across all steps
# ============================================================
state = {
    "user_input":     "",
    "parsed_data":    {},
    "filtered_data":  {},
    "recipe":         {},
    "nutrition":      {},
    "final_output":   {},
    "human_response": "",
    "chat_history":   []
}

# ============================================================
#  GROQ LLM CALL 
# ============================================================
def call_llm(prompt, expect_json=True):
    """
    Sends a prompt to Groq (Llama 3.1) and returns the reply as a string.
    Automatically retries up to 3 times if rate limited (429).
    Waits 2 seconds between every call to stay under free tier limits.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    system_msg = "You are a helpful food and nutrition assistant."
    if expect_json:
        system_msg = (
            "You are a food and nutrition assistant. "
            "You ONLY return valid JSON. No explanation, no markdown, no backticks."
        )

    messages = [{"role": "system", "content": system_msg}]
    messages += state["chat_history"]
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "llama-3.1-8b-instant",
        "messages": messages
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            time.sleep(2)
            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 429:
                wait_time = 10 * (attempt + 1)
                print(f"  Rate limited — waiting {wait_time}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

            state["chat_history"].append({"role": "user",      "content": prompt})
            state["chat_history"].append({"role": "assistant", "content": reply})
            state["chat_history"] = state["chat_history"][-10:]

            return reply

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"     Groq API error (attempt {attempt+1}): {e} — retrying...")
                time.sleep(5)
            else:
                print(f"    Groq API error after {max_retries} attempts: {e}")
                raise

    raise Exception("Groq API failed after all retries")


# ============================================================
#  SAFE JSON PARSER
# ============================================================
def safe_json_load(output):
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        try:
            start = output.find("{")
            end   = output.rfind("}") + 1
            return json.loads(output[start:end])
        except json.JSONDecodeError:
            print("\n Could not parse JSON from LLM output:\n", output)
            raise


# ============================================================
#  STEP 1 — LLM: Parse user input into structured data
# ============================================================
def step1_parse():
    """
    INPUT : raw user text (state["user_input"])
    OUTPUT: state["parsed_data"] — intent, ingredients, dish_name,
            dietary_condition, meal_type, diet_type, cuisine
    WHY SEPARATE: every downstream step depends on this structure;
                  the raw string is useless to Steps 2-6.
    NEW: now extracts diet_type (veg/nonveg) and cuisine (Indian/any).
    """
    print("\n [Step 1 — LLM] Parsing user input...")

    prompt = f"""
 Read the user query and extract information into JSON.

User query: "{state["user_input"]}"

Rules:
- "intent" must be exactly one of: get_recipe, get_suggestions, general_question
  * get_recipe — user wants to cook something or asks how to make a dish
  * get_suggestions — user wants food ideas without a specific dish in mind
  * general_question — anything else

- "ingredients" — list of raw ingredients the user says they HAVE.
  If the user asks HOW TO MAKE a dish but does not list ingredients they own, return [].

- "dish_name" — name of dish the user wants to make (e.g. "butter chicken").
  If no dish mentioned, return "".

- "dietary_condition" must be exactly one of: diabetes, hypertension, weight_loss, none

- "meal_type" must be exactly one of: breakfast, lunch, dinner, snack, any

- "diet_type" — whether the user wants vegetarian or non-vegetarian food.
  Must be exactly one of: vegetarian, non-vegetarian, any
  * Use "vegetarian" if user says veg, vegetarian, no meat, plant-based
  * Use "non-vegetarian" if user says non-veg, chicken, meat, fish, egg, etc.
  * Use "any" if not mentioned

- "cuisine" — the cultural style of cooking the user prefers.
  Must be exactly one of: indian, western, any
  * Use "indian" if user mentions Indian dishes, masala, curry, roti, dal, etc.
  * Use "western" if user mentions pasta, sandwich, salad, burger, etc.
  * Use "any" if not mentioned

Return ONLY a JSON object. Example:
{{"intent": "get_recipe", "ingredients": [], "dish_name": "dal tadka", "dietary_condition": "none", "meal_type": "lunch", "diet_type": "vegetarian", "cuisine": "indian"}}
"""
    output = call_llm(prompt, expect_json=True)
    state["parsed_data"] = safe_json_load(output)
    print(f"   Parsed: {state['parsed_data']}")


# ============================================================
#  STEP 2 — TOOL: USDA FoodData Central API
# ============================================================

USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

CONDITION_THRESHOLDS = {
    "diabetes":     {"sugars": 5.0,    "carbohydrates": 20.0},
    "hypertension": {"sodium": 140.0},
    "weight_loss":  {"calories": 150.0, "fat": 10.0},
}

# Ingredients that contain meat/fish/egg used to enforce veg filter
NON_VEG_KEYWORDS = [
    "chicken", "mutton", "beef", "pork", "lamb", "fish", "prawn",
    "shrimp", "egg", "meat", "bacon", "turkey", "tuna", "salmon",
    "anchovy", "crab", "lobster", "squid"
]

def fetch_nutrition(ingredient: str) -> dict:
    """
    Calls USDA API for one ingredient.
    Returns dict with nutrient values per 100g, or {} on failure.
    """
    try:
        params = {
            "query":    ingredient,
            "pageSize": 1,
            "api_key":  USDA_API_KEY
        }
        response = requests.get(USDA_BASE_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        foods = data.get("foods", [])
        if not foods:
            return {}

        food      = foods[0]
        nutrients = {}

        for n in food.get("foodNutrients", []):
            name  = n.get("nutrientName", "").lower()
            value = n.get("value", 0)

            if "energy" in name:
                nutrients["calories"]      = value
            elif "sugar" in name:
                nutrients["sugars"]        = value
            elif "sodium" in name:
                nutrients["sodium"]        = value
            elif "carbohydrate" in name:
                nutrients["carbohydrates"] = value
            elif "total lipid" in name or name == "fat":
                nutrients["fat"]           = value

        return {
            "name":      food.get("description", ingredient),
            "nutrients": nutrients
        }

    except requests.exceptions.RequestException as e:
        print(f"       USDA API failed for '{ingredient}': {e} — treating as safe")
        return {}


def is_non_veg(ingredient: str) -> bool:
    """Returns True if ingredient contains meat/fish/egg."""
    ingredient_lower = ingredient.lower()
    return any(kw in ingredient_lower for kw in NON_VEG_KEYWORDS)


def check_ingredient_safety(nutrition_data: dict, condition: str, diet_type: str, ingredient: str):
    """
    Returns (is_safe: bool, reason: str) for one ingredient.
    Checks both nutritional thresholds AND veg/nonveg filter.
    """
    # Veg filter — remove non-veg ingredients if user wants vegetarian
    if diet_type == "vegetarian" and is_non_veg(ingredient):
        return False, "contains meat/fish/egg — removed for vegetarian diet"

    # Nutritional filter
    if not nutrition_data or not condition or condition == "none":
        return True, "no condition specified"

    thresholds = CONDITION_THRESHOLDS.get(condition.lower(), {})
    if not thresholds:
        return True, "condition not in threshold list"

    nutrients = nutrition_data.get("nutrients", {})
    for nutrient, limit in thresholds.items():
        actual = nutrients.get(nutrient, 0)
        if actual > limit:
            return False, f"too high in {nutrient} ({actual:.1f}/100g, limit {limit})"

    return True, "within safe limits"


def step2_filter():
    """
    INPUT : state["parsed_data"] — ingredients, dietary_condition, diet_type
    OUTPUT: state["filtered_data"] — safe_ingredients, removed, USDA nutrition data
    WHY TOOL: LLMs hallucinate nutrition facts; real values come from USDA.
    WHY SEPARATE: Step 3 must only see safe ingredients; this gate enforces that.
    NEW: also filters out non-veg ingredients if user is vegetarian.
    """
    ingredients = state["parsed_data"].get("ingredients", [])
    condition   = state["parsed_data"].get("dietary_condition", "")
    diet_type   = state["parsed_data"].get("diet_type", "any")

    print(f"\n [Step 2 — USDA Tool] Checking {len(ingredients)} ingredient(s) | condition: '{condition}' | diet: '{diet_type}'...")

    safe     = []
    removed  = []
    api_data = {}

    for ingredient in ingredients:
        print(f"   → Fetching nutrition: {ingredient}")
        nutrition = fetch_nutrition(ingredient)
        api_data[ingredient] = nutrition

        is_safe, reason = check_ingredient_safety(nutrition, condition, diet_type, ingredient)

        if is_safe:
            safe.append(ingredient)
            print(f"       Safe — {reason}")
        else:
            removed.append(ingredient)
            print(f"       Removed — {reason}")

    state["filtered_data"] = {
        "safe_ingredients":  safe,
        "removed":           removed,
        "usda_nutrition":    api_data,
        "condition_checked": condition,
        "diet_type":         diet_type
    }

    print(f"    Safe ingredients: {safe}")
    print(f"    Removed: {removed}")


# ============================================================
#  STEP 3 — LLM: Generate recipe
# ============================================================
def step3_recipe():
    """
    INPUT : safe ingredients OR dish name + diet_type + cuisine from state
    OUTPUT: state["recipe"] — recipe name, ingredients WITH quantities, steps
    WHY SEPARATE: recipe must be built AFTER filtering so only safe
                  ingredients are used; handles dish-by-name requests too.
    NEW: passes diet_type and cuisine to the LLM so it respects
         veg/nonveg preference and Indian vs western cooking style.
         Explicitly asks for quantities (grams/cups/tsp) in ingredients.
    """
    print("\n [Step 3 — LLM] Generating recipe...")

    dish_name        = state["parsed_data"].get("dish_name", "")
    safe_ingredients = state["filtered_data"].get("safe_ingredients", [])
    condition        = state["parsed_data"].get("dietary_condition", "none")
    meal_type        = state["parsed_data"].get("meal_type", "any")
    diet_type        = state["parsed_data"].get("diet_type", "any")
    cuisine          = state["parsed_data"].get("cuisine", "any")

    # Build cuisine + diet context string for the prompt
    context = f"Diet preference: {diet_type}. Cuisine style: {cuisine}. Health condition: {condition}. Meal type: {meal_type}."

    # Case A — user asked for a specific dish by name
    if dish_name:
        prompt = f"""
You are a recipe assistant. Provide a complete recipe for: {dish_name}

{context}

Important instructions:
- Respect the diet preference strictly. If diet is "vegetarian", do NOT include any meat, fish, or eggs.
- If cuisine is "indian", use Indian spices and cooking methods (e.g. tadka, masala, roti, dal).
- If cuisine is "western", use western cooking methods (e.g. bake, saute, pasta, sandwich).
- Every ingredient MUST include a specific quantity (e.g. "200g chicken", "2 cups flour", "1 tsp cumin").

Return ONLY this JSON:
{{
  "recipe_name": "{dish_name}",
  "ingredients_used": ["200g ingredient", "2 cups ingredient", "1 tsp spice"],
  "steps": ["Step 1: ...", "Step 2: ...", "Step 3: ...", "Step 4: ...", "Step 5: ..."],
  "note": "any health or dietary tip"
}}
"""

    # Case B — no safe ingredients left after filtering
    elif not safe_ingredients:
        prompt = f"""
All provided ingredients were flagged as unsafe or removed due to dietary restrictions.
{context}

Suggest a simple healthy recipe suitable for these preferences using common safe ingredients.

Important:
- Respect the diet preference strictly. If diet is "vegetarian", use NO meat, fish, or eggs.
- If cuisine is "indian", use Indian style cooking.
- Every ingredient MUST have a specific quantity (e.g. "1 cup oats", "2 tbsp olive oil").

Return ONLY this JSON:
{{
  "recipe_name": "name of the dish",
  "ingredients_used": ["1 cup ingredient", "2 tbsp ingredient"],
  "steps": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
  "note": "why this is suitable"
}}
"""

    # Case C — user provided ingredients, some are safe
    else:
        prompt = f"""
You are a recipe assistant. Create a recipe using ONLY these ingredients:
{safe_ingredients}

{context}

Important instructions:
- Respect the diet preference strictly. If diet is "vegetarian", do NOT use meat, fish, or eggs even if available.
- If cuisine is "indian", use Indian cooking style (e.g. add tadka, use masala, make roti or sabzi).
- If cuisine is "western", use western style (e.g. saute, bake, make a salad or pasta).
- Every ingredient MUST include a specific quantity (e.g. "2 medium tomatoes", "1 cup spinach", "1/2 tsp turmeric").

Return ONLY this JSON:
{{
  "recipe_name": "name of the dish",
  "ingredients_used": ["quantity + ingredient", "quantity + ingredient"],
  "steps": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
  "note": ""
}}
"""

    output = call_llm(prompt, expect_json=True)
    state["recipe"] = safe_json_load(output)
    print(f"   Recipe: {state['recipe'].get('recipe_name', '(unnamed)')}")


# ============================================================
#  STEP 4 — LLM: Nutrition analysis
# ============================================================
def step4_nutrition():
    """
    INPUT : state["recipe"] + dietary_condition + USDA data
    OUTPUT: state["nutrition"] — safety flag, calories, health note
    WHY SEPARATE: recipe must exist before it can be analysed;
                  this step adds a health lens the recipe step doesn't provide.
    """
    print("\n [Step 4 — LLM] Analysing nutrition...")

    prompt = f"""
You are a nutrition advisor. Analyse this recipe for a user with the following profile:
- Health condition: {state["parsed_data"].get("dietary_condition", "none")}
- Diet type: {state["parsed_data"].get("diet_type", "any")}
- Cuisine preference: {state["parsed_data"].get("cuisine", "any")}

Recipe: {json.dumps(state["recipe"])}

Real USDA nutritional data for checked ingredients:
{json.dumps(state["filtered_data"].get("usda_nutrition", {}))}

Return ONLY this JSON:
{{
  "estimated_calories_per_serving": "number only e.g. 320",
  "portion_size": "e.g. 1 bowl (250g)",
  "is_safe_for_condition": "yes or no or caution",
  "health_note": "one sentence explaining suitability",
  "improvement_suggestion": "one concrete tip to make it healthier"
}}
"""
    output = call_llm(prompt, expect_json=True)
    state["nutrition"] = safe_json_load(output)
    print(f"   Safe for condition: {state['nutrition'].get('is_safe_for_condition', '?')}")


# ============================================================
#  STEP 5 — LLM: Compile structured final output
# ============================================================
def step5_final():
    """
    INPUT : all previous state fields
    OUTPUT: state["final_output"] — single clean structured report
    WHY SEPARATE: earlier steps produce partial data; this synthesises
                  everything into one coherent object the user can act on.
    """
    print("\n [Step 5 — LLM] Compiling final structured output...")

    for attempt in range(2):
        try:
            prompt = f"""
Combine all information below into one clean JSON summary.

Parsed intent:        {json.dumps(state["parsed_data"])}
Filtered ingredients: {json.dumps(state["filtered_data"])}
Recipe:               {json.dumps(state["recipe"])}
Nutrition:            {json.dumps(state["nutrition"])}

Return ONLY this JSON:
{{
  "final_recipe_name":      "",
  "diet_type":              "",
  "cuisine":                "",
  "ingredients_used":       [],
  "removed_ingredients":    [],
  "cooking_steps":          [],
  "portion_size":           "",
  "estimated_calories":     "",
  "is_safe_for_user":       "",
  "health_note":            "",
  "improvement_suggestion": ""
}}
"""
            output = call_llm(prompt, expect_json=True)
            state["final_output"] = safe_json_load(output)
            print("   Final output compiled.")
            return

        except Exception as e:
            print(f"     Attempt {attempt+1} failed: {e}")
            continue

    state["final_output"] = {
        "error":         "Step 5 failed",
        "raw_recipe":    state.get("recipe", {}),
        "raw_nutrition": state.get("nutrition", {})
    }


# ============================================================
#  STEP 6 — LLM: Friendly chat response
# ============================================================
def step6_human_response():
    """
    INPUT : state["final_output"]
    OUTPUT: state["human_response"] — natural language reply
    WHY SEPARATE: final JSON is machine-readable but not user-friendly;
                  this step translates it into conversational text.
    """
    print("\n [Step 6 — LLM] Generating friendly response...")

    prompt = f"""
You are a warm, helpful food assistant chatting with a user.
Convert the structured data below into a friendly, natural reply.
Do NOT output JSON. Write like you are talking to a friend.
Mention the dish name, key ingredients with quantities, and a brief health note.
Keep it concise — 5 to 7 sentences max.

Data:
{json.dumps(state["final_output"])}
"""
    state["human_response"] = call_llm(prompt, expect_json=False)


# ============================================================
#  EDGE CASE — no ingredients AND no dish name
# ============================================================
def handle_missing_ingredients() -> bool:
    """
    Triggered only when the user gave no ingredients AND no dish name.
    Suggests suitable foods respecting diet_type and cuisine preference.
    Returns True if handled (main loop skips Steps 2-5).
    """
    has_ingredients = bool(state["parsed_data"].get("ingredients"))
    has_dish_name   = bool(state["parsed_data"].get("dish_name", "").strip())

    if has_ingredients or has_dish_name:
        return False

    condition  = state["parsed_data"].get("dietary_condition", "general")
    diet_type  = state["parsed_data"].get("diet_type", "any")
    cuisine    = state["parsed_data"].get("cuisine", "any")

    print(f"\n  No ingredients or dish name — generating suggestions | condition: {condition} | diet: {diet_type} | cuisine: {cuisine}")

    prompt = f"""
The user has not mentioned specific ingredients or a dish name.
Suggest 5 healthy meals or snacks based on their preferences:
- Health condition: {condition}
- Diet type: {diet_type} (if vegetarian, suggest NO meat/fish/egg dishes)
- Cuisine: {cuisine} (if indian, suggest Indian dishes; if western, suggest western dishes)

Return ONLY this JSON:
{{
  "suggestions": [
    {{"name": "dish name", "reason": "why it suits the condition and preferences"}}
  ]
}}
"""
    try:
        output = call_llm(prompt, expect_json=True)
        result = safe_json_load(output)
        state["final_output"] = {
            "final_recipe_name":      "Suggestions",
            "diet_type":              diet_type,
            "cuisine":                cuisine,
            "ingredients_used":       [],
            "removed_ingredients":    [],
            "cooking_steps":          [],
            "portion_size":           "varies",
            "estimated_calories":     "varies",
            "is_safe_for_user":       "yes",
            "health_note":            f"Tailored for {condition}, {diet_type}, {cuisine} cuisine",
            "improvement_suggestion": "",
            "suggestions":            result.get("suggestions", [])
        }
    except Exception:
        state["final_output"] = {
            "final_recipe_name": "Basic Suggestions",
            "suggestions": [
                {"name": "dal khichdi",  "reason": "light and easy to digest"},
                {"name": "fruit salad",  "reason": "low calorie and nutritious"}
            ]
        }

    return True


# ============================================================
#  MAIN FUNCTION
# ============================================================
def run_agent():
    print("=" * 60)
    print("   Health-Aware / Food Suggestion Agent ")
    print("=" * 60)
    print("  Examples:")
    print("  - I have eggs, spinach, oats. I have diabetes.")
    print("  - How to make butter chicken? I am non-vegetarian.")
    print("  - Suggest Indian veg snacks for hypertension.")
    print("  - I have tomatoes, flour, capsicum. Make something Indian and veg.")
    print("  Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()

        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye! Stay healthy 🥗")
            break

        state["user_input"]     = user_input
        state["parsed_data"]    = {}
        state["filtered_data"]  = {}
        state["recipe"]         = {}
        state["nutrition"]      = {}
        state["final_output"]   = {}
        state["human_response"] = ""

        try:
            step1_parse()

            if handle_missing_ingredients():
                step6_human_response()
            else:
                step2_filter()
                step3_recipe()
                step4_nutrition()
                step5_final()
                step6_human_response()

        except Exception as e:
            print(f"\n Pipeline error: {e}")
            print("Bot: Sorry, something went wrong. Please try again.\n")
            continue

        print(f"\nBot: {state['human_response']}\n")
        print("-" * 60)


if __name__ == "__main__":
    run_agent()
