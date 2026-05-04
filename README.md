# Health-Aware Food Suggestion Agent

A conversational AI agent that takes a user's food-related query and produces a personalised, health-aware recipe or food suggestion. The user can describe ingredients they have, name a dish they want to make, or ask for suggestions. They can also specify a health condition (diabetes, hypertension, or weight loss), a dietary preference (vegetarian or non-vegetarian), and a cuisine style (Indian or western). The agent runs six sequential steps, where the output of each step becomes the input of the next.

---

## Problem Statement

Giving someone useful food advice is not a task that can be solved with a single prompt. A person with diabetes who has specific ingredients at home and prefers Indian vegetarian cooking needs several things to happen before a useful answer can be produced. Their query must be understood and structured, their ingredients must be checked against real nutritional data, unsafe items must be removed, a recipe must be generated from what remains, and that recipe must be evaluated for health suitability before being presented in a friendly way.

A single prompt asking an LLM to do all of this at once produces vague, hallucinated, and unverifiable answers. The multi-step chain structure forces each step to do one job well, passing structured data forward so the next step can build on it reliably. This is why multi-step chaining genuinely adds value here over a single prompt.

---

## How the Agent Works

The agent accepts free-text input from the user and runs it through a six-step pipeline. Each step reads from a shared Python dictionary called `state` and writes its result back into it.

```
User Input
    │
    ▼
Step 1 — LLM parses raw text into structured JSON
    │
    ▼
Step 2 — USDA API checks each ingredient for nutritional safety
    │
    ▼
Step 3 — LLM generates recipe using only safe ingredients
    │
    ▼
Step 4 — LLM analyses recipe nutrition using real USDA data
    │
    ▼
Step 5 — LLM compiles all outputs into one structured report
    │
    ▼
Step 6 — LLM converts report into a friendly conversational reply
    │
    ▼
Bot Response shown to user
```

---

## Chain Design

Each step is a separate function in code with clearly defined inputs and outputs. No step can be removed without breaking the pipeline.

| Step | LLM Call / Tool | Input | Output (fed to next step) |
|------|----------------|-------|--------------------------|
| 1 | LLM — Parse | Raw user text | Structured JSON: intent, ingredients, dish_name, dietary_condition, meal_type, diet_type, cuisine |
| 2 | Tool — USDA API | Ingredients + dietary_condition + diet_type from Step 1 | Filtered list: safe_ingredients, removed ingredients, real USDA nutrition data |
| 3 | LLM — Recipe | safe_ingredients OR dish_name + cuisine + diet_type from Step 2 | Recipe JSON: recipe_name, ingredients with exact quantities, cooking steps |
| 4 | LLM — Nutrition | Recipe (Step 3) + dietary_condition + USDA data (Step 2) | Nutrition JSON: calories, portion size, safety flag, health note |
| 5 | LLM — Compile | All outputs from Steps 1, 2, 3, 4 combined | Single clean final JSON report |
| 6 | LLM — Respond | Final JSON from Step 5 | Natural language friendly reply shown to user |

### Why each step is separate

**Step 1** exists because the raw user string is unreadable by all downstream steps. Every other step depends on the structured fields this step produces.

**Step 2** exists because LLMs hallucinate nutritional facts. The USDA API returns verified values per 100g and the agent compares them against hardcoded thresholds for each health condition.

**Step 3** exists because the recipe must be built after filtering. Using the pre-filter ingredient list would defeat the entire health-safety purpose.

**Step 4** exists because a recipe and a nutritional analysis are different reasoning tasks. The recipe step creates. The nutrition step evaluates.

**Step 5** exists because each prior step produces a partial, differently shaped JSON object. This step synthesises all of them into one consistent structure.

**Step 6** exists because the final JSON is machine-readable but not appropriate to show a user directly.

### Shared State

```python
state = {
    "user_input":     "",   # raw text from user
    "parsed_data":    {},   # output of Step 1
    "filtered_data":  {},   # output of Step 2 (USDA tool)
    "recipe":         {},   # output of Step 3
    "nutrition":      {},   # output of Step 4
    "final_output":   {},   # output of Step 5
    "human_response": "",   # output of Step 6
    "chat_history":   []    # rolling memory across turns
}
```

---

## Tool Integration

**Tool used:** USDA FoodData Central API  
**URL:** `https://api.nal.usda.gov/fdc/v1/foods/search`  
**Cost:** Free with a free API key

| Condition | Nutrient Checked | Threshold (per 100g) |
|-----------|-----------------|----------------------|
| Diabetes | Sugars | > 5g flagged |
| Diabetes | Carbohydrates | > 20g flagged |
| Hypertension | Sodium | > 140mg flagged |
| Weight Loss | Calories | > 150kcal flagged |
| Weight Loss | Fat | > 10g flagged |

If an ingredient exceeds the threshold it is removed from the safe list before Step 3 runs. The raw USDA data is also passed to Step 4 so the nutritional analysis uses verified figures rather than LLM estimates.

If the USDA API call fails for any ingredient, the agent catches the exception, prints a warning, and treats the ingredient as safe rather than crashing the pipeline.

---

## Installation

### Requirements

- Python 3.8 or higher
- One external library: `requests`

### Install dependency

```bash
pip install requests
```

---

## API Keys Setup

You need two free API keys before running the agent.

### Key 1 — Groq API Key (for all LLM calls)

1. Go to https://console.groq.com
2. Sign up for free (no credit card required)
3. Click **API Keys** in the left sidebar
4. Click **Create API Key**
5. Copy the key — it starts with `gsk_`

### Key 2 — USDA FoodData Central API Key (for Step 2 tool call)

1. Go to https://fdc.nal.usda.gov/api-key-signup.html
2. Enter your email address
3. The key will be emailed to you within a minute

### Add keys to the code

```python
GROQ_API_KEY = "paste your groq key here"    # starts with gsk_
USDA_API_KEY = "paste your usda key here"
```

---

## How to Run

```bash
python agent.py
```

Wait for this screen:

```
=======================================================
  Health-Aware Food Suggestion Agent  
=======================================================
You:
```

Type your query after `You:` and press Enter. Type `exit` to quit.

---

## Example Inputs

```
You: I have oats, sugar, chicken and spinach. I have diabetes.
You: How to make butter chicken? I am non-vegetarian.
You: Suggest Indian veg lunch for hypertension.
You: I have tomatoes, paneer, capsicum. Make something Indian and vegetarian.
You: What can I make for weight loss with eggs and oats?
```

---

## Edge Cases Handled

**No ingredients provided:** The agent skips Steps 2 through 5 and directly generates food suggestions suited to the user's condition and preferences.

**All ingredients filtered out:** Step 3 detects the empty safe list and asks the LLM to suggest an alternative safe recipe instead of failing.

**Named dish request with no ingredients:** The agent recognises this as a dish-by-name request and generates a full recipe for that dish respecting diet type and cuisine preference.

**Vegetarian filter conflict:** Non-vegetarian ingredients are removed in Step 2 before the recipe is generated, and the agent notes what was removed.

**Rate limiting:** If the Groq free tier rate limit is hit, the agent automatically waits and retries up to three times.

---

## Limitations

The veg/non-veg filter relies on a hardcoded keyword list, so regional or brand names for meat products will pass through undetected. Cuisine detection covers only Indian or western, meaning requests for Chinese, Mexican, or other cuisines are not handled correctly. Nutritional thresholds are static approximations and do not account for age, weight, or medical severity. The agent resets state every turn, so follow-up questions about a previous recipe will not produce correct answers. The Groq free tier causes occasional rate limit errors under rapid usage.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Forbidden` | Wrong or missing Groq API key | Check the key starts with `gsk_` and was saved correctly |
| `429 Too Many Requests` | Groq free tier rate limit | Wait 30 seconds and try again |
| `401 Unauthorized` | Groq key invalid or expired | Generate a new key at console.groq.com |
| USDA warning printed | Ingredient not found in database | Ingredient is treated as safe, no action needed |
| JSON parse error | LLM returned malformed JSON | Try the same query again |
