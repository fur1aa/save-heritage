import os
import json
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import trafilatura
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("API Key not found. Please check your .env file.")

client = genai.Client(api_key=api_key)
app = FastAPI(title="S.A.V.E. Heritage Generator")

templates = Jinja2Templates(directory="templates")

# --- DATA SCHEMA ---
class SiteTheme(BaseModel):
    bg: str
    bg_darker: str
    accent_red: str
    accent_gold: str
    text_cream: str
    card_bg: str
    border_color: str

class InfoCard(BaseModel):
    title: str
    content: str

class HeritageSiteData(BaseModel):
    label: str
    title: str
    subtitle: str
    tagline: str
    about_cards: list[InfoCard]
    culture_title: str
    culture_subtitle: str
    culture_cards: list[InfoCard]
    quick_facts: list[str]
    did_you_know_text: str
    theme: SiteTheme
    latitude: float = 0.0    
    longitude: float = 0.0

# ==========================================
# PERSISTENT DATABASE (JSON FILE)
# ==========================================
DB_FILE = "archive_data.json"

DEFAULT_DB = {
    "sunbeam": {
        "id": "sunbeam",
        "title": "Sunbeam Theatre",
        "label": "North Point, Hong Kong",
        "tagline": "The iconic spiritual home of Cantonese Opera, digitally reconstructed to preserve its structural and cultural essence.",
        "is_custom": True
    }
}

def load_db():
    """Loads the archive from the file. Creates a new one with Sunbeam if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DB, f, ensure_ascii=False, indent=4)
        return DEFAULT_DB
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    """Saves the updated database to the JSON file."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- NAVIGATION ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Renders the main generator page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/archive", response_class=HTMLResponse)
async def archive(request: Request):
    """Renders the archive page with all saved sites."""
    db = load_db()
    return templates.TemplateResponse("archive.html", {"request": request, "sites": db.values()})

@app.get("/site/{site_id}", response_class=HTMLResponse)
async def view_site(request: Request, site_id: str):
    """Renders a specific heritage site page based on its ID."""
    db = load_db()
    if site_id not in db:
        raise HTTPException(status_code=404, detail="Site not found in the archive.")

    site_info = db[site_id]

    if site_info.get("is_custom"):
        return templates.TemplateResponse(f"{site_id}.html", {"request": request})

    return templates.TemplateResponse("heritage_template.html", {
        "request": request, 
        "data": site_info["full_data"],
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", "")
    })

# --- GENERATION ENDPOINT ---

@app.post("/generate")
async def generate_site(request: Request, url: str = Form(...)):
    """Fetches text from the URL, generates content via Gemini, and saves it to the database."""
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(downloaded)

    if not text:
        raise HTTPException(status_code=400, detail="Failed to extract text from the provided URL.")

    # STRICT PROMPT TO ENSURE ENGLISH OUTPUT, COLOR GENERATION AND COORDINATES
    prompt = (
        f"You are the lead editor and web designer for the S.A.V.E. Heritage project.\n"
        f"CRITICAL RULE: TRANSLATE EVERYTHING TO ENGLISH. The final output MUST be 100% in English, even if the source text is in Russian, Chinese, or any other language.\n"
        f"1. Extract data: 4 'about_cards', 4 'culture_cards', and quick facts.\n"
        f"2. Extract GPS Coordinates: Find the location (latitude and longitude) of the heritage site. Use decimal degrees format. For example, for the Colosseum: latitude 41.8902, longitude 12.4922.\n"
        f"3. Choose COLORS (theme) for this site in HEX format. Dark background, light text, bright accents.\n\n"
        f"TEXT:\n{text[:15000]}"
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HeritageSiteData,
                temperature=0.3
            )
        )

        site_data = HeritageSiteData.model_validate_json(response.text).model_dump()

        # SAVE TO THE PERSISTENT DATABASE
        db = load_db()
        # Create a safe URL-friendly ID
        site_id = site_data["title"].lower().replace(" ", "_").replace("'", "")
        db[site_id] = {
            "id": site_id,
            "title": site_data["title"],
            "label": site_data["label"],
            "tagline": site_data["tagline"],
            "is_custom": False,
            "full_data": site_data
        }
        save_db(db)

        # Redirect the user to their newly created page
        return RedirectResponse(url=f"/site/{site_id}", status_code=303)

    except Exception as e:
        return HTMLResponse(f"<h2 style='color:red;'>Generation Error:</h2><p>{str(e)}</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
