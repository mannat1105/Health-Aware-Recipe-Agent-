# Health Aware/Food Suggestion Agent

**What the agent does**

This is a multi-step LLM agent that takes a user's food-related query and produces a personalised, health-aware recipe or food suggestion. The user can describe ingredients they have, name a dish they want to make, or ask for suggestions. They can also specify a health condition (diabetes, hypertension, or weight loss) and a dietary preference (vegetarian or non-vegetarian) and a cuisine style (Indian or western). The agent runs six sequential steps: parsing the query, checking ingredients against the USDA nutritional database, generating a recipe, analysing its nutrition, compiling a structured report, and producing a friendly conversational reply.

**Requirements**

Python 3.8 or higher. One external library: requests.

**Installation**

Open your terminal or PowerShell and run:
pip install requests

That is the only dependency. No other libraries are required.

API Keys needed

You need two free API keys before running the agent.

Key 1 — Groq API key. Go to https://console.groq.com, sign up for free, click API Keys, and create a new key. It starts with gsk_.

Key 2 — USDA FoodData Central API key. Go to https://fdc.nal.usda.gov/api-key-signup.html, enter your email, and the key will be emailed to you within a minute.
Once you have both keys, open agent.py in any text editor and replace the placeholders at the top of the file:

GROQ_API_KEY = "paste your groq key here"

USDA_API_KEY = "paste your usda key here"

**How to run**

Navigate to the folder containing main.py in your terminal and run:

python main.py

Wait for the welcome screen to appear and then type your query after the You: prompt.

Example inputs to test
You: I have tomatoes, paneer, spinach. Make something Indian and veg.

You: How to make butter chicken? I am non-vegetarian.

You: Suggest Indian veg lunch for hypertension.

You: I have oats, sugar, chicken. I have diabetes.

You: What can I make for weight loss with eggs and oats?

Type exit to quit the agent.

**Chain structure summary**

Step 1 — LLM parses raw user input into structured JSON fields including ingredients, dish name, health condition, diet type, and cuisine. Step 2 — USDA API tool checks each ingredient for nutritional safety and removes unsafe or diet-incompatible items. Step 3 — LLM generates a recipe using only the safe ingredients, respecting cuisine and diet preferences, with specific quantities for each ingredient. Step 4 — LLM analyses the recipe's nutritional profile using real USDA data and flags whether it is safe for the user's condition. Step 5 — LLM compiles all outputs from previous steps into one clean structured JSON report. Step 6 — LLM converts the structured report into a natural, friendly conversational reply.

**What to do if you get errors**

If you see a 429 error, the Groq free tier rate limit was hit. Wait 30 seconds and try again. The agent has a built-in retry mechanism but very rapid queries can still exceed the limit. If you see a 401 error, your Groq API key is incorrect or was not saved properly. If the USDA tool prints a warning for an ingredient, it means the API did not find that ingredient in its database. The ingredient will be treated as safe and passed to the recipe step.
