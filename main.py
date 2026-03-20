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
    raise ValueError("API Key не найден. Проверьте файл .env.")

client = genai.Client(api_key=api_key)
app = FastAPI(title="S.A.V.E. Heritage Generator")

templates = Jinja2Templates(directory="templates")


# --- СХЕМА ДАННЫХ ---
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


# ==========================================
# 💾 ПОСТОЯННАЯ БАЗА ДАННЫХ (JSON ФАЙЛ)
# ==========================================
DB_FILE = "archive_data.json"

DEFAULT_DB = {
    "sunbeam": {
        "id": "sunbeam",
        "title": "Sunbeam Theatre",
        "label": "North Point, Hong Kong",
        "tagline": "The iconic spiritual home of Cantonese Opera, digitally reconstructed to preserve its structural and cultural essence.",
        "image": "https://images.unsplash.com/photo-1578144670233-0498305f2c25?q=80&w=800&auto=format&fit=crop",
        "is_custom": True
    }
}


def load_db():
    """Загружает архив из файла. Если файла нет, создает его с Sunbeam внутри."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DB, f, ensure_ascii=False, indent=4)
        return DEFAULT_DB
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    """Сохраняет новые сайты в файл навсегда."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# --- ЭНДПОИНТЫ НАВИГАЦИИ ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/archive", response_class=HTMLResponse)
async def archive(request: Request):
    db = load_db()
    # Передаем все сохраненные сайты в шаблон архива
    return templates.TemplateResponse("archive.html", {"request": request, "sites": db.values()})


@app.get("/site/{site_id}", response_class=HTMLResponse)
async def view_site(request: Request, site_id: str):
    db = load_db()
    if site_id not in db:
        raise HTTPException(status_code=404, detail="Сайт не найден в архиве.")

    site_info = db[site_id]

    # Если это вручную созданный Sunbeam
    if site_info.get("is_custom"):
        return templates.TemplateResponse(f"{site_id}.html", {"request": request})

    # Если это сгенерированный ИИ сайт
    return templates.TemplateResponse("heritage_template.html", {"request": request, "data": site_info["full_data"]})


# --- ЭНДПОИНТ ГЕНЕРАЦИИ ---

@app.post("/generate")
async def generate_site(request: Request, url: str = Form(...)):
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(downloaded)

    if not text:
        raise HTTPException(status_code=400, detail="Не удалось извлечь текст.")

    prompt = (
        f"Ты редактор и веб-дизайнер проекта S.A.V.E. Heritage.\n"
        f"1. Извлеки данные: 4 карточки 'about_cards', 4 карточки 'culture_cards', факты.\n"
        f"2. Подбери ЦВЕТА (theme) для этого сайта в формате HEX. Фон делай темным, текст - светлым, акценты - яркими.\n\n"
        f"ТЕКСТ:\n{text[:15000]}"
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=HeritageSiteData,
                temperature=0.4
            )
        )

        site_data = HeritageSiteData.model_validate_json(response.text).model_dump()

        # 💾 СОХРАНЯЕМ В ФАЙЛ НАВСЕГДА
        db = load_db()
        site_id = site_data["title"].lower().replace(" ", "_").replace("'", "")
        db[site_id] = {
            "id": site_id,
            "title": site_data["title"],
            "label": site_data["label"],
            "tagline": site_data["tagline"],
            "image": "https://images.unsplash.com/photo-1541888086053-53b47f07bf2e?q=80&w=800&auto=format&fit=crop",
            "is_custom": False,
            "full_data": site_data
        }
        save_db(db)

        # Перенаправляем на сохраненную страницу
        return RedirectResponse(url=f"/site/{site_id}", status_code=303)

    except Exception as e:
        return HTMLResponse(f"<h2 style='color:red;'>Ошибка генерации:</h2><p>{str(e)}</p>")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)