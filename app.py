from flask import Flask, jsonify, render_template, request
import google.generativeai as genai
from datetime import datetime
import requests
import json
import time
import uuid
import os

app = Flask(__name__)

# HARDCODED CLIENT INITIALIZATION AT GLOBAL LEVEL (PERMANENT KEY FIX)
# Is key ke aage piche koi space ya extra character nahi hona chahiye
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# Recent mood/weather/category results — stops Gemini spam on refresh
_vibe_cache = {}
_CACHE_MAX = 48

FALLBACK_PREMIUM_PLAYLIST = {
    "description": "Fallback Premium Playlist",
    "music": [
        {"name": "Illahi", "img": "/static/images/vinyl.gif"},
        {"name": "Kesariya", "img": "/static/images/vinyl.gif"},
        {"name": "Night Changes", "img": "/static/images/vinyl.gif"},
        {"name": "Blinding Lights", "img": "/static/images/vinyl.gif"},
        {"name": "Until I Found You", "img": "/static/images/vinyl.gif"},
        {"name": "Peaches", "img": "/static/images/vinyl.gif"}
    ],
    "movies": [
        {"name": "Yeh Jawaani Hai Deewani", "img": "/static/images/movieicon.jpg"},
        {"name": "La La Land", "img": "/static/images/movieicon.jpg"},
        {"name": "The Intern", "img": "/static/images/movieicon.jpg"},
        {"name": "Zindagi Na Milegi Dobara", "img": "/static/images/movieicon.jpg"},
        {"name": "3 Idiots", "img": "/static/images/movieicon.jpg"},
        {"name": "Spider-Man: Into the Spider-Verse", "img": "/static/images/movieicon.jpg"}
    ]
}


def _cache_key(city, vibe, category, weather, temp):
    return f"{city}|{vibe}|{category}|{weather}|{temp}".strip().lower()


def _cache_get(key):
    hit = _vibe_cache.get(key)
    if hit:
        print(f"[CACHE HIT] skipping Gemini for: {key}")
    return hit


def _cache_set(key, payload):
    if key in _vibe_cache:
        _vibe_cache.pop(key, None)
    elif len(_vibe_cache) >= _CACHE_MAX:
        oldest = next(iter(_vibe_cache), None)
        if oldest is not None:
            _vibe_cache.pop(oldest, None)
    _vibe_cache[key] = payload

def get_live_weather(city_name="Noida"):
    if not city_name or city_name.strip() == "":
        city_name = "Noida"
    try:
        url = f"https://wttr.in/{city_name}?format=%C|%t"
        response = requests.get(url, timeout=2)
        if response.status_code == 200 and "|" in response.text:
            parts = response.text.strip().split("|")
            condition = parts[0].strip()
            temperature = parts[1].replace("°C", "").replace("+", "").strip()
            if condition and temperature:
                return condition, temperature
    except Exception as e:
        print(f"Weather Fetch Timeout/Error: {e}")
    return "A timeless sky, waiting for your vibe.", "24"

@app.route("/")
def home():
    weather, temp = get_live_weather("Noida")
    return render_template("index.html", city="Noida", weather=weather, temp=temp)
@app.route("/creator")
def creator():
    return render_template("creator.html")

@app.route('/get_vibe')
def get_vibe():
    
    
    city = request.args.get('city', 'Noida').strip()
    user_vibe = request.args.get('vibe', 'Happy').strip()
    vibe_hint = user_vibe.lower()
    if any(word in vibe_hint for word in ("gloomy", "depress")) and "sad" not in vibe_hint:
        user_vibe = f"{user_vibe} sad"
    
    # NAYA: Frontend se category aayegi
    category = request.args.get('category', 'Bollywood').strip()
    
    try:
        weather, temp = get_live_weather(city)
    except Exception:
        weather, temp = "A timeless sky, waiting for your vibe.", "24"

    lookup = _cache_key(city, user_vibe, category, weather, temp)
    cached = _cache_get(lookup)
    if cached:
        payload = dict(cached)
        payload["weather"] = weather
        payload["temp"] = temp
        payload["cached"] = True
        return jsonify(payload)

    # --- DYNAMIC PROMPT LOGIC ---
    # Har category ke liye Gemini ka "Role" change hoga
    role_description = "Bollywood music and movie expert"
    if category == "Hollywood":
        role_description = "Hollywood pop music and English movie expert"
    elif category == "KDrama":
        role_description = "Korean entertainment expert, focusing on K-Dramas and K-Pop/OSTs"
    elif category == "Anime":
        role_description = "Japanese Anime and J-Pop/Anime OST expert"
    elif category == "Novels":
        role_description = "Literature expert focusing on engaging Novels (put in movies section) and Lo-Fi reading music (put in music section)"
    elif category == "WebSeries":
        role_description = "Global Web Series expert and theme-song curator"
    elif category == "GlobalMovies":
        role_description = "World cinema expert, suggesting movies and music from various languages"
    elif category == "BlogsAndPodcasts":
        role_description = "Curator of popular E-Blogs/Articles (put in movies section) and Podcast/Focus music (put in music section)"

    # Gemini ka prompt ab totally dynamic hai!
    prompt = f"""
    You are a highly empathetic {role_description}. 
    Context: City is {city}, weather is {weather}, temperature is {temp}°C.
    The user's exact current emotional state or story is: "{user_vibe}"
    The selected entertainment category is: "{category}"
    
    CRITICAL INSTRUCTION: Analyze the emotional tone.
    - Match the mood perfectly (e.g., sad vibe gets emotional/healing content, happy gets upbeat).
    - If the category is "Bollywood", recommend Bollywood movies and Hindi songs.
    - If the category is "Hollywood", recommend Hollywood movies and English songs.
    - If the category is "KDrama", recommend Korean Dramas and K-Pop/OSTs.
    - If the category is "Novels", you MUST put 6 book titles in the "movies" array. Crucially, in the "music" array, you MUST provide 6 background/lo-fi instrumental tracks that perfectly match the aesthetic and genre of those exact books.
    - You MUST provide exactly 6 items for music and 6 items for movies/shows/books.
    - If the category is "Anime", recommend popular Anime series/movies and J-Pop/Anime OSTs
    -If the category is "BlogsAndPodcasts", you MUST recommend 6 popular e-blogs, newsletters, or article topics in the "movies" array. Crucially, in the "music" array, you MUST provide 6 popular podcast shows or specific podcast episodes that match the user's mood.
    - If the category is "IndianWebSeries", you MUST recommend 6 highly popular Indian web series in the "movies" array. Crucially, in the "music" array, provide the exact official theme songs or iconic OSTs of those exact 6 Indian web series.
    
    Return ONLY a raw JSON object matching this structure precisely. No markdown block wrappers:
    {{
        "music": [
            {{"name": "Item Name One", "img": "/static/images/vinyl.gif"}},
            {{"name": "Item Name Two", "img": "/static/images/vinyl.gif"}},
            {{"name": "Item Name Three", "img": "/static/images/vinyl.gif"}},
            {{"name": "Item Name Four", "img": "/static/images/vinyl.gif"}},
            {{"name": "Item Name Five", "img": "/static/images/vinyl.gif"}},
            {{"name": "Item Name Six", "img": "/static/images/vinyl.gif"}}
        ],
        "movies": [
            {{"name": "Title One", "img": "/static/images/movieicon.jpg"}},
            {{"name": "Title Two", "img": "/static/images/movieicon.jpg"}},
            {{"name": "Title Three", "img": "/static/images/movieicon.jpg"}},
            {{"name": "Title Four", "img": "/static/images/movieicon.jpg"}},
            {{"name": "Title Five", "img": "/static/images/movieicon.jpg"}},
            {{"name": "Title Six", "img": "/static/images/movieicon.jpg"}}
        ]
    }}
    """
    

    try:
        from google.generativeai import types
        creative_config = types.GenerationConfig(
            temperature=1.0,
            top_p=0.95
        )

        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=creative_config
            )
            raw_text = (response.text or "").strip()
        except Exception as api_err:
            print(f"!!! GEMINI CONNECTION/RATE LIMIT: {api_err}")
            raise

        cleaned_text = raw_text
        if "```" in cleaned_text:
            cleaned_text = cleaned_text.split("```")[1]
            if cleaned_text.startswith("json"):
                cleaned_text = cleaned_text[4:]
        cleaned_text = cleaned_text.strip()

        ai_data = json.loads(cleaned_text)
        music_items = ai_data.get("music") or []
        movie_items = ai_data.get("movies") or []
        if not music_items or not movie_items:
            raise ValueError("Gemini returned empty music or movies")

        print("[GEMINI] Responded successfully with new recs!")
        result = {
            "description": "Vibe synced with Gemini!",
            "music": music_items,
            "movies": movie_items,
            "weather": weather,
            "temp": temp,
            "cached": False
        }
        _cache_set(lookup, result)
        return jsonify(result)

    except Exception as e:
        print(f"!!! GEMINI PARSE ERROR (Using dynamic local fallback): {e}")
        music_items = list(FALLBACK_PREMIUM_PLAYLIST["music"])
        movie_items = list(FALLBACK_PREMIUM_PLAYLIST["movies"])
        print(f"[FALLBACK CHECK] CURRENT CATEGORY IS: '{category}'")
        
        vibe_clean = user_vibe.lower()
        if category == "KDrama":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Stay With Me (Goblin)", "img": "/static/images/vinyl.gif"},
                    {"name": "Will Be Back (Moon Lovers)", "img": "/static/images/vinyl.gif"},
                    {"name": "Forgetting You (Moon Lovers)", "img": "/static/images/vinyl.gif"},
                    {"name": "Let You Go (A Korean Odyssey)", "img": "/static/images/vinyl.gif"},
                    {"name": "Here I Am (Crash Landing on You)", "img": "/static/images/vinyl.gif"},
                    {"name": "Someday (My Mister)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "My Mister", "img": "/static/images/movieicon.jpg"},
                    {"name": "Moon Lovers: Scarlet Heart Ryeo", "img": "/static/images/movieicon.jpg"},
                    {"name": "Uncontrollably Fond", "img": "/static/images/movieicon.jpg"},
                    {"name": "Youth of May", "img": "/static/images/movieicon.jpg"},
                    {"name": "Just Between Lovers", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Red Sleeve", "img": "/static/images/movieicon.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Start Over (Itaewon Class)", "img": "/static/images/vinyl.gif"},
                    {"name": "Running (Start-Up)", "img": "/static/images/vinyl.gif"},
                    {"name": "Fighting (BSS - Seventeen)", "img": "/static/images/vinyl.gif"},
                    {"name": "God's Menu (Stray Kids)", "img": "/static/images/vinyl.gif"},
                    {"name": "Fire (BTS)", "img": "/static/images/vinyl.gif"},
                    {"name": "Adrenaline (Vincenzo OST)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Itaewon Class", "img": "/static/images/movieicon.jpg"},
                    {"name": "Start-Up", "img": "/static/images/movieicon.jpg"},
                    {"name": "Fight For My Way", "img": "/static/images/movieicon.jpg"},
                    {"name": "Vincenzo", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Uncanny Counter", "img": "/static/images/movieicon.jpg"},
                    {"name": "Bloodhounds", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "deep" in vibe_clean:
                music_items = [
                    {"name": "Adult (My Mister)", "img": "/static/images/vinyl.gif"},
                    {"name": "Hush (Goblin)", "img": "/static/images/vinyl.gif"},
                    {"name": "Hyehwa-dong (Reply 1988)", "img": "/static/images/vinyl.gif"},
                    {"name": "My Day (Navillera)", "img": "/static/images/vinyl.gif"},
                    {"name": "The Day (Mr. Sunshine)", "img": "/static/images/vinyl.gif"},
                    {"name": "Breath (Park Hyo Shin)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Navillera", "img": "/static/images/movieicon.jpg"},
                    {"name": "My Mister", "img": "/static/images/movieicon.jpg"},
                    {"name": "Move to Heaven", "img": "/static/images/movieicon.jpg"},
                    {"name": "Reply 1988", "img": "/static/images/movieicon.jpg"},
                    {"name": "Hi Bye, Mama!", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mr. Sunshine", "img": "/static/images/movieicon.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "Christmas Tree (Our Beloved Summer)", "img": "/static/images/vinyl.gif"},
                    {"name": "Romantic Sunday (Hometown Cha-Cha-Cha)", "img": "/static/images/vinyl.gif"},
                    {"name": "Sweet Night (Itaewon Class)", "img": "/static/images/vinyl.gif"},
                    {"name": "In The Rain (Hospital Playlist)", "img": "/static/images/vinyl.gif"},
                    {"name": "Aloha (Hospital Playlist)", "img": "/static/images/vinyl.gif"},
                    {"name": "Day & Night (Start-Up)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Hometown Cha-Cha-Cha", "img": "/static/images/movieicon.jpg"},
                    {"name": "Reply 1988", "img": "/static/images/movieicon.jpg"},
                    {"name": "Hospital Playlist", "img": "/static/images/movieicon.jpg"},
                    {"name": "Summer Strike", "img": "/static/images/movieicon.jpg"},
                    {"name": "Run On", "img": "/static/images/movieicon.jpg"},
                    {"name": "Our Beloved Summer", "img": "/static/images/movieicon.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Fighting (BSS)", "img": "/static/images/vinyl.gif"},
                    {"name": "Go (Twenty Five Twenty One)", "img": "/static/images/vinyl.gif"},
                    {"name": "Start Over (Itaewon Class)", "img": "/static/images/vinyl.gif"},
                    {"name": "Sha La La (Strong Girl Bong-soon)", "img": "/static/images/vinyl.gif"},
                    {"name": "Super Tuna (Jin)", "img": "/static/images/vinyl.gif"},
                    {"name": "Dynamite (BTS)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Weightlifting Fairy Kim Bok-joo", "img": "/static/images/movieicon.jpg"},
                    {"name": "Strong Girl Bong-soon", "img": "/static/images/movieicon.jpg"},
                    {"name": "Business Proposal", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mr. Queen", "img": "/static/images/movieicon.jpg"},
                    {"name": "Welcome to Waikiki", "img": "/static/images/movieicon.jpg"},
                    {"name": "King the Land", "img": "/static/images/movieicon.jpg"}
                ]
            elif "retro" in vibe_clean or "classic" in vibe_clean or "old" in vibe_clean:
                music_items = [
                    {"name": "Because I'm Stupid (Boys Over Flowers)", "img": "/static/images/vinyl.gif"},
                    {"name": "From the Beginning Until Now (Winter Sonata)", "img": "/static/images/vinyl.gif"},
                    {"name": "Lalala, It's Love! (Coffee Prince)", "img": "/static/images/vinyl.gif"},
                    {"name": "I Think I (Full House)", "img": "/static/images/vinyl.gif"},
                    {"name": "That Woman (Secret Garden)", "img": "/static/images/vinyl.gif"},
                    {"name": "Never Say Goodbye (My Girl)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Boys Over Flowers", "img": "/static/images/movieicon.jpg"},
                    {"name": "Winter Sonata", "img": "/static/images/movieicon.jpg"},
                    {"name": "Coffee Prince", "img": "/static/images/movieicon.jpg"},
                    {"name": "Full House", "img": "/static/images/movieicon.jpg"},
                    {"name": "Secret Garden", "img": "/static/images/movieicon.jpg"},
                    {"name": "My Girl", "img": "/static/images/movieicon.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Everytime (Descendants of the Sun)", "img": "/static/images/vinyl.gif"},
                    {"name": "Beautiful (Goblin)", "img": "/static/images/vinyl.gif"},
                    {"name": "Always (Descendants of the Sun)", "img": "/static/images/vinyl.gif"},
                    {"name": "You Are My Everything (Gummy)", "img": "/static/images/vinyl.gif"},
                    {"name": "Love Maybe (Business Proposal)", "img": "/static/images/vinyl.gif"},
                    {"name": "Stand By Me (Boys Over Flowers)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Crash Landing on You", "img": "/static/images/movieicon.jpg"},
                    {"name": "Goblin", "img": "/static/images/movieicon.jpg"},
                    {"name": "Vincenzo", "img": "/static/images/movieicon.jpg"},
                    {"name": "Itaewon Class", "img": "/static/images/movieicon.jpg"},
                    {"name": "Descendants of the Sun", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Heirs", "img": "/static/images/movieicon.jpg"}
                ]
        elif category == "Novels":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Lofi Girl (Sad & Rainy)", "img": "/static/images/vinyl.gif"},
                    {"name": "Chillhop Music (Deep Focus)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kupla - Kingdom in Blue", "img": "/static/images/vinyl.gif"},
                    {"name": "Jinsang - Solitude", "img": "/static/images/vinyl.gif"},
                    {"name": "Idealism - Rainy Evening", "img": "/static/images/vinyl.gif"},
                    {"name": "Eevee - Violas", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "A Little Life by Hanya Yanagihara", "img": "/static/images/novels.jpg"},
                    {"name": "The Kite Runner by Khaled Hosseini", "img": "/static/images/novels.jpg"},
                    {"name": "The Book Thief by Markus Zusak", "img": "/static/images/novels.jpg"},
                    {"name": "Norwegian Wood by Haruki Murakami", "img": "/static/images/novels.jpg"},
                    {"name": "All the Bright Places by Jennifer Niven", "img": "/static/images/novels.jpg"},
                    {"name": "Me Before You by Jojo Moyes", "img": "/static/images/novels.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Chillhop - Upbeat & Energetic", "img": "/static/images/vinyl.gif"},
                    {"name": "Lofi - Morning Motivation", "img": "/static/images/vinyl.gif"},
                    {"name": "Synthwave - Outrun Beats", "img": "/static/images/vinyl.gif"},
                    {"name": "Upbeat Study Beats", "img": "/static/images/vinyl.gif"},
                    {"name": "Jazzhop - Fast Tempo", "img": "/static/images/vinyl.gif"},
                    {"name": "Nujabes - Feather", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Can't Hurt Me by David Goggins", "img": "/static/images/novels.jpg"},
                    {"name": "Atomic Habits by James Clear", "img": "/static/images/novels.jpg"},
                    {"name": "Shoe Dog by Phil Knight", "img": "/static/images/novels.jpg"},
                    {"name": "The Martian by Andy Weir", "img": "/static/images/novels.jpg"},
                    {"name": "Ready Player One by Ernest Cline", "img": "/static/images/novels.jpg"},
                    {"name": "Ender's Game by Orson Scott Card", "img": "/static/images/novels.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "devotion" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "Hang Drum Music", "img": "/static/images/vinyl.gif"},
                    {"name": "Tibetan Singing Bowls", "img": "/static/images/vinyl.gif"},
                    {"name": "Ambient Meditation (Om Chant)", "img": "/static/images/vinyl.gif"},
                    {"name": "Indian Flute Instrumental", "img": "/static/images/vinyl.gif"},
                    {"name": "Zen Garden Music", "img": "/static/images/vinyl.gif"},
                    {"name": "Ethereal Choirs Lofi", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Alchemist by Paulo Coelho", "img": "/static/images/novels.jpg"},
                    {"name": "Siddhartha by Hermann Hesse", "img": "/static/images/novels.jpg"},
                    {"name": "Autobiography of a Yogi", "img": "/static/images/novels.jpg"},
                    {"name": "The Prophet by Kahlil Gibran", "img": "/static/images/novels.jpg"},
                    {"name": "The Power of Now by Eckhart Tolle", "img": "/static/images/novels.jpg"},
                    {"name": "Man's Search for Meaning by Viktor Frankl", "img": "/static/images/novels.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "Lofi Girl (Relax/Study)", "img": "/static/images/vinyl.gif"},
                    {"name": "ChilledCow - Morning Coffee", "img": "/static/images/vinyl.gif"},
                    {"name": "Purrple Cat - Distant Worlds", "img": "/static/images/vinyl.gif"},
                    {"name": "Rook1e - Grape Soda", "img": "/static/images/vinyl.gif"},
                    {"name": "Tomppabeats - Monday Loop", "img": "/static/images/vinyl.gif"},
                    {"name": "Bsd.u - French Inhale", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Alchemist by Paulo Coelho", "img": "/static/images/novels.jpg"},
                    {"name": "The Midnight Library by Matt Haig", "img": "/static/images/novels.jpg"},
                    {"name": "Ikigai by Hector Garcia", "img": "/static/images/novels.jpg"},
                    {"name": "Atomic Habits by James Clear", "img": "/static/images/novels.jpg"},
                    {"name": "Siddhartha by Hermann Hesse", "img": "/static/images/novels.jpg"},
                    {"name": "The Little Prince by Antoine de Saint-Exupéry", "img": "/static/images/novels.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "emotional" in vibe_clean:
                music_items = [
                    {"name": "River Flows in You (Lofi Cover)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kina - get you the moon", "img": "/static/images/vinyl.gif"},
                    {"name": "Idealism - Both of Us", "img": "/static/images/vinyl.gif"},
                    {"name": "Kupla - Sleepy Little One", "img": "/static/images/vinyl.gif"},
                    {"name": "A L E X - I need to paint my walls", "img": "/static/images/vinyl.gif"},
                    {"name": "Nymano - Sorry", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Fault in Our Stars by John Green", "img": "/static/images/novels.jpg"},
                    {"name": "Pride and Prejudice by Jane Austen", "img": "/static/images/novels.jpg"},
                    {"name": "The Seven Husbands of Evelyn Hugo", "img": "/static/images/novels.jpg"},
                    {"name": "Normal People by Sally Rooney", "img": "/static/images/novels.jpg"},
                    {"name": "The Notebook by Nicholas Sparks", "img": "/static/images/novels.jpg"},
                    {"name": "Call Me By Your Name by André Aciman", "img": "/static/images/novels.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "fun" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Lofi Girl (Morning Vibes & Coffee)", "img": "/static/images/vinyl.gif"},
                    {"name": "Saib - Sakura Trees", "img": "/static/images/vinyl.gif"},
                    {"name": "DJ Okawari - Flower Dance", "img": "/static/images/vinyl.gif"},
                    {"name": "Snail's House - Pixel Galaxy", "img": "/static/images/vinyl.gif"},
                    {"name": "Rook1e - I Fell in Love With You", "img": "/static/images/vinyl.gif"},
                    {"name": "Moe Shop - Love Taste", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The House in the Cerulean Sea by TJ Klune", "img": "/static/images/novels.jpg"},
                    {"name": "The Rosie Project by Graeme Simsion", "img": "/static/images/novels.jpg"},
                    {"name": "Crazy Rich Asians by Kevin Kwan", "img": "/static/images/novels.jpg"},
                    {"name": "A Man Called Ove by Fredrik Backman", "img": "/static/images/novels.jpg"},
                    {"name": "Red, White & Royal Blue by Casey McQuiston", "img": "/static/images/novels.jpg"},
                    {"name": "Eleanor Oliphant Is Completely Fine by Gail Honeyman", "img": "/static/images/novels.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Lofi Girl (Upbeat & Chill)", "img": "/static/images/vinyl.gif"},
                    {"name": "In Love With A Ghost", "img": "/static/images/vinyl.gif"},
                    {"name": "Snail's House - Pixel Galaxy", "img": "/static/images/vinyl.gif"},
                    {"name": "Moe Shop - Love Taste", "img": "/static/images/vinyl.gif"},
                    {"name": "Otokaze - Summer Night", "img": "/static/images/vinyl.gif"},
                    {"name": "Nujabes - Aruarian Dance", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Harry Potter Series by J.K. Rowling", "img": "/static/images/novels.jpg"},
                    {"name": "The Hobbit by J.R.R. Tolkien", "img": "/static/images/novels.jpg"},
                    {"name": "Percy Jackson Series by Rick Riordan", "img": "/static/images/novels.jpg"},
                    {"name": "Dune by Frank Herbert", "img": "/static/images/novels.jpg"},
                    {"name": "Project Hail Mary by Andy Weir", "img": "/static/images/novels.jpg"},
                    {"name": "Good Omens by Neil Gaiman & Terry Pratchett", "img": "/static/images/novels.jpg"}
                ]
            
            
        elif category == "Hollywood":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "My Heart Will Go On (Celine Dion)", "img": "/static/images/vinyl.gif"},
                    {"name": "See You Again (Wiz Khalifa)", "img": "/static/images/vinyl.gif"},
                    {"name": "Fix You (Coldplay)", "img": "/static/images/vinyl.gif"},
                    {"name": "Someone Like You (Adele)", "img": "/static/images/vinyl.gif"},
                    {"name": "Let Her Go (Passenger)", "img": "/static/images/vinyl.gif"},
                    {"name": "Shallow (Lady Gaga & Bradley Cooper)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Pursuit of Happyness", "img": "/static/images/movieicon.jpg"},
                    {"name": "Titanic", "img": "/static/images/movieicon.jpg"},
                    {"name": "Interstellar", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Green Mile", "img": "/static/images/movieicon.jpg"},
                    {"name": "Schindler's List", "img": "/static/images/movieicon.jpg"},
                    {"name": "Forrest Gump", "img": "/static/images/movieicon.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Till I Collapse (Eminem)", "img": "/static/images/vinyl.gif"},
                    {"name": "Thunderstruck (AC/DC)", "img": "/static/images/vinyl.gif"},
                    {"name": "Survivor (Destiny's Child)", "img": "/static/images/vinyl.gif"},
                    {"name": "Stronger (Kanye West)", "img": "/static/images/vinyl.gif"},
                    {"name": "Eye of the Tiger (Survivor)", "img": "/static/images/vinyl.gif"},
                    {"name": "Don't Stop Me Now (Queen)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Rocky / Creed", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mad Max: Fury Road", "img": "/static/images/movieicon.jpg"},
                    {"name": "Top Gun: Maverick", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Avengers", "img": "/static/images/movieicon.jpg"},
                    {"name": "Ford v Ferrari", "img": "/static/images/movieicon.jpg"},
                    {"name": "Gladiator", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "deep" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "Now We Are Free (Gladiator)", "img": "/static/images/vinyl.gif"},
                    {"name": "Time (Inception Theme)", "img": "/static/images/vinyl.gif"},
                    {"name": "Hallelujah (Leonard Cohen)", "img": "/static/images/vinyl.gif"},
                    {"name": "A Way of Life (The Last Samurai)", "img": "/static/images/vinyl.gif"},
                    {"name": "Cornfield Chase (Interstellar)", "img": "/static/images/vinyl.gif"},
                    {"name": "Let It Be (The Beatles)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Life of Pi", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Tree of Life", "img": "/static/images/movieicon.jpg"},
                    {"name": "Eat Pray Love", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Matrix (Philosophical)", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Last Samurai", "img": "/static/images/movieicon.jpg"},
                    {"name": "Seven Years in Tibet", "img": "/static/images/movieicon.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "Here Comes The Sun (The Beatles)", "img": "/static/images/vinyl.gif"},
                    {"name": "Yellow (Coldplay)", "img": "/static/images/vinyl.gif"},
                    {"name": "Perfect (Ed Sheeran)", "img": "/static/images/vinyl.gif"},
                    {"name": "A Thousand Years (Christina Perri)", "img": "/static/images/vinyl.gif"},
                    {"name": "Just The Way You Are (Bruno Mars)", "img": "/static/images/vinyl.gif"},
                    {"name": "Fast Car (Tracy Chapman)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Intern", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Secret Life of Walter Mitty", "img": "/static/images/movieicon.jpg"},
                    {"name": "Chef", "img": "/static/images/movieicon.jpg"},
                    {"name": "La La Land", "img": "/static/images/movieicon.jpg"},
                    {"name": "Notting Hill", "img": "/static/images/movieicon.jpg"},
                    {"name": "Groundhog Day", "img": "/static/images/movieicon.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Happy (Pharrell Williams)", "img": "/static/images/vinyl.gif"},
                    {"name": "Uptown Funk (Bruno Mars)", "img": "/static/images/vinyl.gif"},
                    {"name": "Can't Stop the Feeling! (Justin Timberlake)", "img": "/static/images/vinyl.gif"},
                    {"name": "I Gotta Feeling (Black Eyed Peas)", "img": "/static/images/vinyl.gif"},
                    {"name": "Shake It Off (Taylor Swift)", "img": "/static/images/vinyl.gif"},
                    {"name": "Don't Stop Me Now (Queen)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Hangover", "img": "/static/images/movieicon.jpg"},
                    {"name": "Back to the Future", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mamma Mia!", "img": "/static/images/movieicon.jpg"},
                    {"name": "Pitch Perfect", "img": "/static/images/movieicon.jpg"},
                    {"name": "Crazy Rich Asians", "img": "/static/images/movieicon.jpg"},
                    {"name": "Spider-Man: Into the Spider-Verse", "img": "/static/images/movieicon.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "love" in vibe_clean:
                music_items = [
                    {"name": "I Will Always Love You (Whitney Houston)", "img": "/static/images/vinyl.gif"},
                    {"name": "Can't Help Falling in Love (Elvis)", "img": "/static/images/vinyl.gif"},
                    {"name": "All of Me (John Legend)", "img": "/static/images/vinyl.gif"},
                    {"name": "Thinking Out Loud (Ed Sheeran)", "img": "/static/images/vinyl.gif"},
                    {"name": "Unchained Melody (Righteous Brothers)", "img": "/static/images/vinyl.gif"},
                    {"name": "Make You Feel My Love (Adele)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Notebook", "img": "/static/images/movieicon.jpg"},
                    {"name": "A Walk to Remember", "img": "/static/images/movieicon.jpg"},
                    {"name": "About Time", "img": "/static/images/movieicon.jpg"},
                    {"name": "Before Sunrise", "img": "/static/images/movieicon.jpg"},
                    {"name": "Eternal Sunshine of the Spotless Mind", "img": "/static/images/movieicon.jpg"},
                    {"name": "500 Days of Summer", "img": "/static/images/movieicon.jpg"}
                ]
            else:
                # Default (Retro / Classic Hollywood)
                music_items = [
                    {"name": "Hotel California (Eagles)", "img": "/static/images/vinyl.gif"},
                    {"name": "Stayin' Alive (Bee Gees)", "img": "/static/images/vinyl.gif"},
                    {"name": "Careless Whisper (George Michael)", "img": "/static/images/vinyl.gif"},
                    {"name": "Take On Me (a-ha)", "img": "/static/images/vinyl.gif"},
                    {"name": "Jailhouse Rock (Elvis Presley)", "img": "/static/images/vinyl.gif"},
                    {"name": "Every Breath You Take (The Police)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Godfather", "img": "/static/images/movieicon.jpg"},
                    {"name": "Pulp Fiction", "img": "/static/images/movieicon.jpg"},
                    {"name": "Casablanca", "img": "/static/images/movieicon.jpg"},
                    {"name": "12 Angry Men", "img": "/static/images/movieicon.jpg"},
                    {"name": "Psycho", "img": "/static/images/movieicon.jpg"},
                    {"name": "Goodfellas", "img": "/static/images/movieicon.jpg"}
                ]
            
        
        elif category == "Anime":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Unravel (Tokyo Ghoul)", "img": "/static/images/vinyl.gif"},
                    {"name": "Secret Base (Anohana)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kamado Tanjirou no Uta (Demon Slayer)", "img": "/static/images/vinyl.gif"},
                    {"name": "Orange (Your Lie in April)", "img": "/static/images/vinyl.gif"},
                    {"name": "Is There Still Anything That Love Can Do? (Weathering with You)", "img": "/static/images/vinyl.gif"},
                    {"name": "Lit (A Silent Voice)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Grave of the Fireflies", "img": "/static/images/movieicon.jpg"},
                    {"name": "Your Lie in April", "img": "/static/images/movieicon.jpg"},
                    {"name": "Clannad: After Story", "img": "/static/images/movieicon.jpg"},
                    {"name": "A Silent Voice", "img": "/static/images/movieicon.jpg"},
                    {"name": "Violet Evergarden", "img": "/static/images/movieicon.jpg"},
                    {"name": "Plastic Memories", "img": "/static/images/movieicon.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "KICK BACK (Chainsaw Man)", "img": "/static/images/vinyl.gif"},
                    {"name": "The Rumbling (Attack on Titan)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kaikai Kitan (Jujutsu Kaisen)", "img": "/static/images/vinyl.gif"},
                    {"name": "Inferno (Fire Force)", "img": "/static/images/vinyl.gif"},
                    {"name": "Shinzou wo Sasageyo (AOT)", "img": "/static/images/vinyl.gif"},
                    {"name": "Haruka Kanata (Naruto)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Haikyuu!!", "img": "/static/images/movieicon.jpg"},
                    {"name": "Gurren Lagann", "img": "/static/images/movieicon.jpg"},
                    {"name": "My Hero Academia", "img": "/static/images/movieicon.jpg"},
                    {"name": "Demon Slayer", "img": "/static/images/movieicon.jpg"},
                    {"name": "Blue Lock", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kuroko's Basketball", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "deep" in vibe_clean or "peace" in vibe_clean:
                music_items = [
                    {"name": "Mushishi Theme (The Sore Feet Song)", "img": "/static/images/vinyl.gif"},
                    {"name": "One Summer's Day (Spirited Away)", "img": "/static/images/vinyl.gif"},
                    {"name": "Princess Mononoke Main Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Natsume Yuujinchou Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "The Voice in My Heart (Violet Evergarden)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kamado Tanjirou no Uta (Demon Slayer)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Mushishi", "img": "/static/images/movieicon.jpg"},
                    {"name": "Spirited Away", "img": "/static/images/movieicon.jpg"},
                    {"name": "Natsume's Book of Friends", "img": "/static/images/movieicon.jpg"},
                    {"name": "To Your Eternity", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kino's Journey", "img": "/static/images/movieicon.jpg"},
                    {"name": "Princess Mononoke", "img": "/static/images/movieicon.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "Suzume Theme (RADWIMPS)", "img": "/static/images/vinyl.gif"},
                    {"name": "Sparkle (Your Name)", "img": "/static/images/vinyl.gif"},
                    {"name": "Ghibli Piano Collection", "img": "/static/images/vinyl.gif"},
                    {"name": "Shiki No Uta (Samurai Champloo)", "img": "/static/images/vinyl.gif"},
                    {"name": "Blue Bird Lofi (Naruto)", "img": "/static/images/vinyl.gif"},
                    {"name": "Nandemonaiya (Your Name)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Spirited Away", "img": "/static/images/movieicon.jpg"},
                    {"name": "My Neighbor Totoro", "img": "/static/images/movieicon.jpg"},
                    {"name": "Yuru Camp (Laid-Back Camp)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mushishi", "img": "/static/images/movieicon.jpg"},
                    {"name": "Natsume's Book of Friends", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kiki's Delivery Service", "img": "/static/images/movieicon.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Idol (YOASOBI)", "img": "/static/images/vinyl.gif"},
                    {"name": "KICK BACK (Chainsaw Man)", "img": "/static/images/vinyl.gif"},
                    {"name": "Gurenge (Demon Slayer)", "img": "/static/images/vinyl.gif"},
                    {"name": "Silhouette (Naruto Shippuden)", "img": "/static/images/vinyl.gif"},
                    {"name": "Shinzo wo Sasageyo (AOT)", "img": "/static/images/vinyl.gif"},
                    {"name": "Bling-Bang-Bang-Born (Mashle)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Spy x Family", "img": "/static/images/movieicon.jpg"},
                    {"name": "Haikyuu!!", "img": "/static/images/movieicon.jpg"},
                    {"name": "One Punch Man", "img": "/static/images/movieicon.jpg"},
                    {"name": "KonoSuba", "img": "/static/images/movieicon.jpg"},
                    {"name": "Gintama", "img": "/static/images/movieicon.jpg"},
                    {"name": "My Hero Academia", "img": "/static/images/movieicon.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "love" in vibe_clean or "emotional" in vibe_clean:
                music_items = [
                    {"name": "Katawaredoki (Your Name)", "img": "/static/images/vinyl.gif"},
                    {"name": "Fukashigi no Carte (Bunny Girl Senpai)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kimi ni Todoke Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Michishirube (Violet Evergarden)", "img": "/static/images/vinyl.gif"},
                    {"name": "Ichiban no Takaramono (Angel Beats!)", "img": "/static/images/vinyl.gif"},
                    {"name": "Grand Escape (Weathering With You)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Your Name (Kimi no Na wa)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Weathering With You", "img": "/static/images/movieicon.jpg"},
                    {"name": "Rascal Does Not Dream of Bunny Girl Senpai", "img": "/static/images/movieicon.jpg"},
                    {"name": "Horimiya", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kaguya-sama: Love Is War", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kimi ni Todoke", "img": "/static/images/movieicon.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Cruel Angel's Thesis (Evangelion)", "img": "/static/images/vinyl.gif"},
                    {"name": "Again (Fullmetal Alchemist)", "img": "/static/images/vinyl.gif"},
                    {"name": "Crossing Field (SAO)", "img": "/static/images/vinyl.gif"},
                    {"name": "Polaris (My Hero Academia)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kaikai Kitan (Jujutsu Kaisen)", "img": "/static/images/vinyl.gif"},
                    {"name": "Cry Baby (Tokyo Revengers)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Attack on Titan", "img": "/static/images/movieicon.jpg"},
                    {"name": "Death Note", "img": "/static/images/movieicon.jpg"},
                    {"name": "Jujutsu Kaisen", "img": "/static/images/movieicon.jpg"},
                    {"name": "Demon Slayer", "img": "/static/images/movieicon.jpg"},
                    {"name": "Fullmetal Alchemist: Brotherhood", "img": "/static/images/movieicon.jpg"},
                    {"name": "Naruto", "img": "/static/images/movieicon.jpg"}
                ]
        elif category == "WebSeries":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Goodbye (Dark Theme)", "img": "/static/images/vinyl.gif"},
                    {"name": "Light of the Seven (Game of Thrones)", "img": "/static/images/vinyl.gif"},
                    {"name": "Red Right Hand (Peaky Blinders)", "img": "/static/images/vinyl.gif"},
                    {"name": "Succession Main Title", "img": "/static/images/vinyl.gif"},
                    {"name": "The Night King (Game of Thrones)", "img": "/static/images/vinyl.gif"},
                    {"name": "Black Mirror Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Dark", "img": "/static/images/movieicon.jpg"},
                    {"name": "Chernobyl", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Handmaid's Tale", "img": "/static/images/movieicon.jpg"},
                    {"name": "Peaky Blinders", "img": "/static/images/movieicon.jpg"},
                    {"name": "Breaking Bad", "img": "/static/images/movieicon.jpg"},
                    {"name": "Black Mirror", "img": "/static/images/movieicon.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Running Up That Hill (Stranger Things)", "img": "/static/images/vinyl.gif"},
                    {"name": "Bone Digger (The Boys Theme)", "img": "/static/images/vinyl.gif"},
                    {"name": "Do Ya Wanna Taste It (Peacemaker)", "img": "/static/images/vinyl.gif"},
                    {"name": "Succession Theme (Hype Remix)", "img": "/static/images/vinyl.gif"},
                    {"name": "I Think We're Alone Now (Umbrella Academy)", "img": "/static/images/vinyl.gif"},
                    {"name": "My Way (Squid Game Trailer)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Boys", "img": "/static/images/movieicon.jpg"},
                    {"name": "Cobra Kai", "img": "/static/images/movieicon.jpg"},
                    {"name": "Peacemaker", "img": "/static/images/movieicon.jpg"},
                    {"name": "Stranger Things", "img": "/static/images/movieicon.jpg"},
                    {"name": "Money Heist", "img": "/static/images/movieicon.jpg"},
                    {"name": "Reacher", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "deep" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "The Leftovers - Main Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Midnight Mass Choral Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Sense8 - What's Up", "img": "/static/images/vinyl.gif"},
                    {"name": "Westworld - Paint It Black", "img": "/static/images/vinyl.gif"},
                    {"name": "Good Omens Title Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Dark - Goodbye", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "The Good Place (Philosophical)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Midnight Mass", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Leftovers", "img": "/static/images/movieicon.jpg"},
                    {"name": "Sense8", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Chosen", "img": "/static/images/movieicon.jpg"},
                    {"name": "Good Omens", "img": "/static/images/movieicon.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "I'll Be There For You (Friends)", "img": "/static/images/vinyl.gif"},
                    {"name": "The Office Theme Song", "img": "/static/images/vinyl.gif"},
                    {"name": "Parks and Recreation Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Big Bang Theory Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Schitt's Creek Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Brooklyn Nine-Nine Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Friends", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Office", "img": "/static/images/movieicon.jpg"},
                    {"name": "Parks and Recreation", "img": "/static/images/movieicon.jpg"},
                    {"name": "Schitt's Creek", "img": "/static/images/movieicon.jpg"},
                    {"name": "Brooklyn Nine-Nine", "img": "/static/images/movieicon.jpg"},
                    {"name": "Modern Family", "img": "/static/images/movieicon.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "love" in vibe_clean or "emotional" in vibe_clean:
                music_items = [
                    {"name": "Wildest Dreams - Duomo (Bridgerton)", "img": "/static/images/vinyl.gif"},
                    {"name": "Chasing Cars - Snow Patrol (Grey's Anatomy)", "img": "/static/images/vinyl.gif"},
                    {"name": "The Skye Boat Song (Outlander)", "img": "/static/images/vinyl.gif"},
                    {"name": "This Is Us Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Echo - Jason Walker (The Vampire Diaries)", "img": "/static/images/vinyl.gif"},
                    {"name": "Hide and Seek - Imogen Heap (Normal People)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Bridgerton", "img": "/static/images/movieicon.jpg"},
                    {"name": "Outlander", "img": "/static/images/movieicon.jpg"},
                    {"name": "Normal People", "img": "/static/images/movieicon.jpg"},
                    {"name": "This Is Us", "img": "/static/images/movieicon.jpg"},
                    {"name": "Grey's Anatomy", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Vampire Diaries", "img": "/static/images/movieicon.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "fun" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Ted Lasso Theme (Marcus Mumford)", "img": "/static/images/vinyl.gif"},
                    {"name": "Don't Stop Believin' (Glee Cast)", "img": "/static/images/vinyl.gif"},
                    {"name": "Hey Girl - New Girl Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Emily in Paris Title Track", "img": "/static/images/vinyl.gif"},
                    {"name": "Unbreakable Kimmy Schmidt Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Sex Education Original Soundtrack", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Ted Lasso", "img": "/static/images/movieicon.jpg"},
                    {"name": "New Girl", "img": "/static/images/movieicon.jpg"},
                    {"name": "Sex Education", "img": "/static/images/movieicon.jpg"},
                    {"name": "Emily in Paris", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Marvelous Mrs. Maisel", "img": "/static/images/movieicon.jpg"},
                    {"name": "Glee", "img": "/static/images/movieicon.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Bella Ciao (Money Heist)", "img": "/static/images/vinyl.gif"},
                    {"name": "Toss A Coin To Your Witcher", "img": "/static/images/vinyl.gif"},
                    {"name": "Stranger Things Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "The Boys Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Doctor Who Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Sherlock Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Money Heist", "img": "/static/images/movieicon.jpg"},
                    {"name": "Stranger Things", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Boys", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Witcher", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Umbrella Academy", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Mandalorian", "img": "/static/images/movieicon.jpg"}
                ]
        elif category == "IndianWebSeries":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Asur Theme Song", "img": "/static/images/vinyl.gif"},
                    {"name": "Sacred Games Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Paatal Lok Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Mirzapur Title Track", "img": "/static/images/vinyl.gif"},
                    {"name": "Family Man Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Delhi Crime Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Asur", "img": "/static/images/movieicon.jpg"},
                    {"name": "Sacred Games", "img": "/static/images/movieicon.jpg"},
                    {"name": "Paatal Lok", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mirzapur", "img": "/static/images/movieicon.jpg"},
                    {"name": "Delhi Crime", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kohrra", "img": "/static/images/movieicon.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Scam 1992 Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Mirzapur Title Track", "img": "/static/images/vinyl.gif"},
                    {"name": "Family Man Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Sab Farzi (Farzi)", "img": "/static/images/vinyl.gif"},
                    {"name": "Guns & Gulaabs Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Dhaaga (TVF Aspirants)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Scam 1992", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mirzapur", "img": "/static/images/movieicon.jpg"},
                    {"name": "The Family Man", "img": "/static/images/movieicon.jpg"},
                    {"name": "Farzi", "img": "/static/images/movieicon.jpg"},
                    {"name": "TVF Aspirants", "img": "/static/images/movieicon.jpg"},
                    {"name": "TVF Pitchers", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "devotion" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "Bhagavad Gita Chant (Sacred Games)", "img": "/static/images/vinyl.gif"},
                    {"name": "Mahabharat Theme (Hotstar)", "img": "/static/images/vinyl.gif"},
                    {"name": "Devlok Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Ashram Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Taj: Divided by Blood Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Navras (Indian Classical Fusion)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Asur (Mythology Meets Crime)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Devlok with Devdutt Pattanaik", "img": "/static/images/movieicon.jpg"},
                    {"name": "Mahabharat (Disney+ Hotstar)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Ram Siya Ke Luv Kush", "img": "/static/images/movieicon.jpg"},
                    {"name": "Upanishad Ganga", "img": "/static/images/movieicon.jpg"},
                    {"name": "Dharamkshetra", "img": "/static/images/movieicon.jpg"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "Panchayat Title Music", "img": "/static/images/vinyl.gif"},
                    {"name": "Gullak Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Yeh Meri Family Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Aspirants Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Kota Factory Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Little Things Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Panchayat", "img": "/static/images/movieicon.jpg"},
                    {"name": "Gullak", "img": "/static/images/movieicon.jpg"},
                    {"name": "Yeh Meri Family", "img": "/static/images/movieicon.jpg"},
                    {"name": "Little Things", "img": "/static/images/movieicon.jpg"},
                    {"name": "Tripling", "img": "/static/images/movieicon.jpg"},
                    {"name": "Home Shanti", "img": "/static/images/movieicon.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "love" in vibe_clean or "emotional" in vibe_clean:
                music_items = [
                    {"name": "Baarish Lete Aana (Broken But Beautiful)", "img": "/static/images/vinyl.gif"},
                    {"name": "Ye Kya Hua (Broken But Beautiful)", "img": "/static/images/vinyl.gif"},
                    {"name": "Ghar (Permanent Roommates)", "img": "/static/images/vinyl.gif"},
                    {"name": "Aise Kyun - Acoustic (Mismatched)", "img": "/static/images/vinyl.gif"},
                    {"name": "Labb Par Aaye (Bandish Bandits)", "img": "/static/images/vinyl.gif"},
                    {"name": "Mera Safar (Ijazat)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Broken But Beautiful", "img": "/static/images/movieicon.jpg"},
                    {"name": "Permanent Roommates", "img": "/static/images/movieicon.jpg"},
                    {"name": "FLAMES", "img": "/static/images/movieicon.jpg"},
                    {"name": "Never Kiss Your Best Friend", "img": "/static/images/movieicon.jpg"},
                    {"name": "Taj Mahal 1989", "img": "/static/images/movieicon.jpg"},
                    {"name": "Bandish Bandits", "img": "/static/images/movieicon.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "fun" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "Chedkhaniyaan (Bandish Bandits)", "img": "/static/images/vinyl.gif"},
                    {"name": "Mismatched Title Track", "img": "/static/images/vinyl.gif"},
                    {"name": "Four More Shots Please Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Aise Kyun (Mismatched)", "img": "/static/images/vinyl.gif"},
                    {"name": "Sajan Bin (Bandish Bandits)", "img": "/static/images/vinyl.gif"},
                    {"name": "Girls Hostel Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Mismatched", "img": "/static/images/movieicon.jpg"},
                    {"name": "Four More Shots Please!", "img": "/static/images/movieicon.jpg"},
                    {"name": "Girls Hostel", "img": "/static/images/movieicon.jpg"},
                    {"name": "Engineering Girls", "img": "/static/images/movieicon.jpg"},
                    {"name": "Pushpavalli", "img": "/static/images/movieicon.jpg"},
                    {"name": "Hostel Daze", "img": "/static/images/movieicon.jpg"}
                ]
            elif "retro" in vibe_clean or "classic" in vibe_clean or "old" in vibe_clean:
                music_items = [
                    {"name": "Malgudi Days Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Sarabhai vs Sarabhai Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Dekh Bhai Dekh Title Track", "img": "/static/images/vinyl.gif"},
                    {"name": "Shaktimaan Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Office Office Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Khichdi Title Track", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Sarabhai vs Sarabhai", "img": "/static/images/movieicon.jpg"},
                    {"name": "Malgudi Days", "img": "/static/images/movieicon.jpg"},
                    {"name": "Dekh Bhai Dekh", "img": "/static/images/movieicon.jpg"},
                    {"name": "Khichdi", "img": "/static/images/movieicon.jpg"},
                    {"name": "Office Office", "img": "/static/images/movieicon.jpg"},
                    {"name": "Shaktimaan", "img": "/static/images/movieicon.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Scam 1992 Theme (Achint)", "img": "/static/images/vinyl.gif"},
                    {"name": "Pitchers Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Farzi Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "College Romance Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Hostel Daze Theme", "img": "/static/images/vinyl.gif"},
                    {"name": "Comicstaan Theme", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Scam 1992", "img": "/static/images/movieicon.jpg"},
                    {"name": "TVF Pitchers", "img": "/static/images/movieicon.jpg"},
                    {"name": "Farzi", "img": "/static/images/movieicon.jpg"},
                    {"name": "College Romance", "img": "/static/images/movieicon.jpg"},
                    {"name": "Hostel Daze", "img": "/static/images/movieicon.jpg"},
                    {"name": "TVF Bachelors", "img": "/static/images/movieicon.jpg"}
                ]
        elif category == "BlogsAndPodcasts":
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
                music_items = [
                    {"name": "Huberman Lab Podcast", "img": "/static/images/pod.jpg"},
                    {"name": "On Purpose (Jay Shetty)", "img": "/static/images/pod.jpg"},
                    {"name": "Ten Percent Happier", "img": "/static/images/pod.jpg"},
                    {"name": "The Daily Stoic Podcast", "img": "/static/images/pod.jpg"},
                    {"name": "Waking Up (Sam Harris)", "img": "/static/images/pod.jpg"},
                    {"name": "The Calmer You Podcast", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Mark Manson's Blog", "img": "/static/images/Blogging.jpg"},
                    {"name": "James Clear's 3-2-1 Newsletter", "img": "/static/images/Blogging.jpg"},
                    {"name": "Zen Habits", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Daily Stoic Blog", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Marginalian (Brain Pickings)", "img": "/static/images/Blogging.jpg"},
                    {"name": "Wait But Why", "img": "/static/images/Blogging.jpg"}
                ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "The GaryVee Audio Experience", "img": "/static/images/pod.jpg"},
                    {"name": "My First Million", "img": "/static/images/pod.jpg"},
                    {"name": "Huberman Lab (Motivation Episodes)", "img": "/static/images/pod.jpg"},
                    {"name": "Jocko Podcast (Discipline)", "img": "/static/images/pod.jpg"},
                    {"name": "The Tony Robbins Podcast", "img": "/static/images/pod.jpg"},
                    {"name": "How I Built This (Guy Raz)", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "James Clear (Atomic Habits Blog)", "img": "/static/images/bgl.webp"},
                    {"name": "Paul Graham (Startups)", "img": "/static/images/bgl.webp"},
                    {"name": "Wait But Why", "img": "/static/images/bgl.webp"},
                    {"name": "Seth Godin's Blog", "img": "/static/images/bgl.webp"},
                    {"name": "Tim Ferriss Blog", "img": "/static/images/bgl.webp"},
                    {"name": "Mark Manson (Life Advice)", "img": "/static/images/bgl.webp"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "devotion" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "Sadhguru Podcast", "img": "/static/images/pod.jpg"},
                    {"name": "Tara Brach (Meditation)", "img": "/static/images/pod.jpg"},
                    {"name": "The Daily Stoic", "img": "/static/images/pod.jpg"},
                    {"name": "Ten Percent Happier", "img": "/static/images/pod.jpg"},
                    {"name": "Eckhart Tolle: Essential Teachings", "img": "/static/images/pod.jpg"},
                    {"name": "On Purpose with Jay Shetty (Spiritual)", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Zen Habits", "img": "/static/images/bgl.webp"},
                    {"name": "The Marginalian (Brain Pickings)", "img": "/static/images/bgl.webp"},
                    {"name": "Daily Stoic Blog", "img": "/static/images/bgl.webp"},
                    {"name": "Tiny Buddha", "img": "/static/images/bgl.webp"},
                    {"name": "Isha Foundation Blog", "img": "/static/images/bgl.webp"},
                    {"name": "Deepak Chopra Blog", "img": "/static/images/bgl.webp"}
                ]
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                    {"name": "The Joe Rogan Experience", "img": "/static/images/pod.jpg"},
                    {"name": "Conan O'Brien Needs a Friend", "img": "/static/images/pod.jpg"},
                    {"name": "Stuff You Should Know", "img": "/static/images/pod.jpg"},
                    {"name": "99% Invisible", "img": "/static/images/pod.jpg"},
                    {"name": "The Ranveer Show (TRS)", "img": "/static/images/pod.jpg"},
                    {"name": "Armchair Expert", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Wait But Why (Tim Urban)", "img": "/static/images/Blogging.jpg"},
                    {"name": "Farnam Street Blog", "img": "/static/images/Blogging.jpg"},
                    {"name": "Tim Ferriss Blog", "img": "/static/images/Blogging.jpg"},
                    {"name": "Nat Eliason's Blog", "img": "/static/images/Blogging.jpg"},
                    {"name": "Ribbonfarm", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Minimalists", "img": "/static/images/Blogging.jpg"}
                ]
            elif "senti" in vibe_clean or "romantic" in vibe_clean or "love" in vibe_clean or "emotional" in vibe_clean:
                music_items = [
                    {"name": "Figuring Out with Raj Shamani", "img": "/static/images/pod.jpg"},
                    {"name": "Raj Shamani - On Mental Health", "img": "/static/images/pod.jpg"},
                    {"name": "On Purpose (Jay Shetty)", "img": "/static/images/pod.jpg"},
                    {"name": "The Ranveer Show - Senti Episodes", "img": "/static/images/pod.jpg"},
                    {"name": "Oprah's Super Soul", "img": "/static/images/pod.jpg"},
                    {"name": "Modern Love (Podcast)", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Humans of Bombay - Emotional Stories", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Better India - Inspiring Lives", "img": "/static/images/Blogging.jpg"},
                    {"name": "Medium - Heartfelt Essays", "img": "/static/images/Blogging.jpg"},
                    {"name": "Tiny Buddha - Simple Wisdom", "img": "/static/images/Blogging.jpg"},
                    {"name": "Elephant Journal", "img": "/static/images/Blogging.jpg"},
                    {"name": "YourStory - Personal Journeys", "img": "/static/images/Blogging.jpg"}
                ]
            elif "happy" in vibe_clean or "joy" in vibe_clean or "fun" in vibe_clean or "party" in vibe_clean:
                music_items = [
                    {"name": "The Ranveer Show - Fun Episodes", "img": "/static/images/pod.jpg"},
                    {"name": "BeerBiceps - Growth & Fun", "img": "/static/images/pod.jpg"},
                    {"name": "The Seen and the Unseen", "img": "/static/images/pod.jpg"},
                    {"name": "Kanan Gill - Jokes", "img": "/static/images/pod.jpg"},
                    {"name": "Social Media Marketing Podcast", "img": "/static/images/pod.jpg"},
                    {"name": "Ted Talks Daily - Optimism", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Better Humans", "img": "/static/images/Blogging.jpg"},
                    {"name": "Lifehack", "img": "/static/images/Blogging.jpg"},
                    {"name": "MindBodyGreen", "img": "/static/images/Blogging.jpg"},
                    {"name": "Productivity Game", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Art of Manliness", "img": "/static/images/Blogging.jpg"},
                    {"name": "Entrepreneur India", "img": "/static/images/Blogging.jpg"}
                ]
            else:
                music_items = [
                    {"name": "Naval Podcast (Naval Ravikant)", "img": "/static/images/pod.jpg"},
                    {"name": "Finshots Daily", "img": "/static/images/pod.jpg"},
                    {"name": "My First Million", "img": "/static/images/pod.jpg"},
                    {"name": "How I Built This", "img": "/static/images/pod.jpg"},
                    {"name": "The Tim Ferriss Show", "img": "/static/images/pod.jpg"},
                    {"name": "GaryVee Audio Experience", "img": "/static/images/pod.jpg"}
                ]
                movie_items = [
                    {"name": "Paul Graham's Essays", "img": "/static/images/Blogging.jpg"},
                    {"name": "Morning Brew Newsletter", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Ken (Business Blog)", "img": "/static/images/Blogging.jpg"},
                    {"name": "The Hustle", "img": "/static/images/Blogging.jpg"},
                    {"name": "TechCrunch", "img": "/static/images/Blogging.jpg"},
                    {"name": "Atomic Habits Blog", "img": "/static/images/Blogging.jpg"}
                ]
        else:      
        # 1. SAD / TENSION / BACKLOG MOOD
            if "backlog" in vibe_clean or "tens" in vibe_clean or "sad" in vibe_clean:
           
                music_items = [
                    {"name": "Agar Tum Saath Ho", "img": "/static/images/vinyl.gif"},
                    {"name": "Kal Ho Naa Ho", "img": "/static/images/vinyl.gif"},
                    {"name": "Kabira", "img": "/static/images/vinyl.gif"}, # Dummy image paths for now
                    {"name": "Channa Mereya", "img": "/static/images/vinyl.gif"},
                    {"name": "Tujhe Bhula Diya", "img": "/static/images/vinyl.gif"},
                    {"name": "Luka Chuppi", "img": "/static/images/vinyl.gif"}
            ]
            
                movie_items = [
                    {"name": "Kal Ho Naa Ho", "img": "/static/images/movieicon.jpg"},
                    {"name": "Jab We Met", "img": "/static/images/movieicon.jpg"},
                    {"name": "Tamasha", "img": "/static/images/movieicon.jpg"},
                    {"name": "Dear Zindagi", "img": "/static/images/movieicon.jpg"},
                    {"name": "Wake Up Sid", "img": "/static/images/movieicon.jpg"},
                    {"name": "Piku", "img": "/static/images/movieicon.jpg"}
            ]
                


        # 2. PEACEFUL MOOD
            elif "chill" in vibe_clean or "peace" in vibe_clean or "relax" in vibe_clean:
                music_items = [
                {"name": "Sham", "img": "/static/images/vinyl.gif"},
                {"name": "Safarnama", "img": "/static/images/vinyl.gif"},
                {"name": "Khwabon Ke Parindey", "img": "/static/images/vinyl.gif"},
                {"name": "Iktara", "img": "/static/images/vinyl.gif"},
                {"name": "Der Lagi Lekin", "img": "/static/images/vinyl.gif"},
                {"name": "Kabira (Encore)", "img": "/static/images/vinyl.gif"}
            ]
                movie_items = [
                {"name": "Karwaan", "img": "/static/images/movieicon.jpg"},
                {"name": "The Lunchbox", "img": "/static/images/movieicon.jpg"},
                {"name": "Piku", "img": "/static/images/movieicon.jpg"},
                {"name": "Udaan", "img": "/static/images/movieicon.jpg"},
                {"name": "Dil Chahta Hai", "img": "/static/images/movieicon.jpg"},
                {"name": "Khoobsurat", "img": "/static/images/movieicon.jpg"}
            ]
            elif "retro" in vibe_clean or "classic" in vibe_clean or "old" in vibe_clean:
                music_items = [
                {"name": "Lag Ja Gale", "img": "/static/images/vinyl.gif"}, # Sad/Melancholy
                {"name": "Khaike Paan Banaras Wala", "img": "/static/images/vinyl.gif"}, # Happy/Energetic
                {"name": "Tujhse Naraz Nahin Zindagi", "img": "/static/images/vinyl.gif"}, # Thoughtful/Sad
                {"name": "Mere Sapno Ki Rani", "img": "/static/images/vinyl.gif"}, # Romantic/Upbeat
                {"name": "Yeh Dosti Hum Nahi", "img": "/static/images/vinyl.gif"}, # Happy/Friendship
                {"name": "Mera Joota Hai Japani", "img": "/static/images/vinyl.gif"} # Classic/Joyful
            ]
                movie_items = [
                {"name": "Anand 1971", "img": "/static/images/movieicon.jpg"}, # Sad but inspiring
                {"name": "Sholay", "img": "/static/images/movieicon.jpg"}, # Action/Happy ending
                {"name": "Chupke Chupke 1975", "img": "/static/images/movieicon.jpg"}, # Pure Comedy/Happy
                {"name": "Mughal-e-Azam", "img": "/static/images/movieicon.jpg"}, # Dramatic/Sad elements
                {"name": "Guide 1965", "img": "/static/images/movieicon.jpg"}, # Thoughtful/Bittersweet
                {"name": "Padosan 1968", "img": "/static/images/movieicon.jpg"} # Pure Comedy
            ]
            # 3. SENTIMENTAL / ROMANTIC MOOD
            elif "romantic" in vibe_clean or "love" in vibe_clean or "date" in vibe_clean:
                music_items = [
                {"name": "Tum Hi Ho", "img": "/static/images/vinyl.gif"},
                {"name": "Raabta", "img": "/static/images/vinyl.gif"},
                {"name": "Tum Se Hi", "img": "/static/images/vinyl.gif"},
                {"name": "Kesariya", "img": "/static/images/vinyl.gif"},
                {"name": "Pehli Nazar Mein", "img": "/static/images/vinyl.gif"},
                {"name": "Tera Ban Jaunga", "img": "/static/images/vinyl.gif"}
            ]
                movie_items = [
                {"name": "Jab We Met", "img": "/static/images/movieicon.jpg"},
                {"name": "Dilwale Dulhania Le Jayenge", "img": "/static/images/movieicon.jpg"},
                {"name": "Aashiqui 2", "img": "/static/images/movieicon.jpg"},
                {"name": "Sita Ramam", "img": "/static/images/movieicon.jpg"},
                {"name": "2 States", "img": "/static/images/movieicon.jpg"},
                {"name": "Veer-Zaara", "img": "/static/images/movieicon.jpg"}
            ]
            elif "enthusiastic" in vibe_clean or "hype" in vibe_clean or "energy" in vibe_clean or "motivate" in vibe_clean:
                music_items = [
                    {"name": "Zinda (Bhaag Milkha Bhaag)", "img": "/static/images/vinyl.gif"},
                    {"name": "Aarambh Hai Prachand (Gulaal)", "img": "/static/images/vinyl.gif"},
                    {"name": "Kar Har Maidaan Fateh (Sanju)", "img": "/static/images/vinyl.gif"},
                    {"name": "Apna Time Aayega (Gully Boy)", "img": "/static/images/vinyl.gif"},
                    {"name": "Brothers Anthem", "img": "/static/images/vinyl.gif"},
                    {"name": "Besabriyaan (MS Dhoni)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "Bhaag Milkha Bhaag", "img": "/static/images/movieicon.jpg"},
                    {"name": "Chak De! India", "img": "/static/images/movieicon.jpg"},
                    {"name": "Dangal", "img": "/static/images/movieicon.jpg"},
                    {"name": "Gully Boy", "img": "/static/images/movieicon.jpg"},
                    {"name": "Uri: The Surgical Strike", "img": "/static/images/movieicon.jpg"},
                    {"name": "Lakshya", "img": "/static/images/movieicon.jpg"}
                ]
            elif "spiritual" in vibe_clean or "soulful" in vibe_clean or "devotion" in vibe_clean or "god" in vibe_clean:
                music_items = [
                    {"name": "Kun Faya Kun (Rockstar)", "img": "/static/images/vinyl.gif"},
                    {"name": "Khwaja Mere Khwaja (Jodhaa Akbar)", "img": "/static/images/vinyl.gif"},
                    {"name": "O Palanhare (Lagaan)", "img": "/static/images/vinyl.gif"},
                    {"name": "Tu Jhoom (Coke Studio)", "img": "/static/images/vinyl.gif"},
                    {"name": "Aayat (Bajirao Mastani)", "img": "/static/images/vinyl.gif"},
                    {"name": "Namami Shamishan (Asur OST)", "img": "/static/images/vinyl.gif"}
                ]
                movie_items = [
                    {"name": "OMG - Oh My God!", "img": "/static/images/movieicon.jpg"},
                    {"name": "PK", "img": "/static/images/movieicon.jpg"},
                    {"name": "Kantara (Hindi Dub)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Jodhaa Akbar", "img": "/static/images/movieicon.jpg"},
                    {"name": "Swades (For soul-searching)", "img": "/static/images/movieicon.jpg"},
                    {"name": "Udaan", "img": "/static/images/movieicon.jpg"}
                ]


            # 4. HAPPY / DEFAULT MOOD
            elif "happy" in vibe_clean or "party" in vibe_clean or "energetic" in vibe_clean:
                music_items = [
                {"name": "Illahi", "img": "/static/images/vinyl.gif"},
                {"name": "Ghungroo", "img": "/static/images/vinyl.gif"},
                {"name": "Kar Gayi Chull", "img": "/static/images/vinyl.gif"},
                {"name": "Senorita", "img": "/static/images/vinyl.gif"},
                {"name": "Kala Chashma", "img": "/static/images/vinyl.gif"},
                {"name": "Mahi Ve", "img": "/static/images/vinyl.gif"}
            ]
                movie_items = [
                {"name": "Yeh Jawaani Hai Deewani", "img": "/static/images/movieicon.jpg"},
                {"name": "Zindagi Na Milegi Dobara", "img": "/static/images/movieicon.jpg"},
                {"name": "Dil Dhadakne Do", "img": "/static/images/movieicon.jpg"},
                {"name": "Queen", "img": "/static/images/movieicon.jpg"},
                {"name": "Hera Pheri", "img": "/static/images/movieicon.jpg"},
                {"name": "3 Idiots", "img": "/static/images/movieicon.jpg"}
            ]
    else:
            # Agar user ne kuch ajeeb likha ya page load hua aur Gemini fail ho gaya, toh yeh jayega
            music_items = [
                {"name": "Illahi", "img": "/static/images/vinyl.gif"},
                {"name": "Sham", "img": "/static/images/vinyl.gif"},
                {"name": "Kabira", "img": "/static/images/vinyl.gif"},
                {"name": "Safarnama", "img": "/static/images/vinyl.gif"},
                {"name": "Iktara", "img": "/static/images/vinyl.gif"},
                {"name": "Tum Hi Ho", "img": "/static/images/vinyl.gif"}
            ]
            movie_items = [
                {"name": "Yeh Jawaani Hai Deewani", "img": "/static/images/movieicon.jpg"},
                {"name": "Zindagi Na Milegi Dobara", "img": "/static/images/movieicon.jpg"},
                {"name": "Tamasha", "img": "/static/images/movieicon.jpg"},
                {"name": "Jab We Met", "img": "/static/images/movieicon.jpg"},
                {"name": "Piku", "img": "/static/images/movieicon.jpg"},
                {"name": "3 Idiots", "img": "/static/images/movieicon.jpg"}
            ]
            

    # YE RETURN STATEMENT BILKUL "def" KE LINE KI SEEDH MEIN (4 SPACES) HONA CHAHIYE
    # Aapke saare elif blocks yahan upar khatam honge...
        
        # Yeh line frontend ko aapka backup data bhejegi
    try:
        fallback_payload = {
            "description": "Fallback Premium Playlist",
            "music": music_items if music_items else FALLBACK_PREMIUM_PLAYLIST["music"],
            "movies": movie_items if movie_items else FALLBACK_PREMIUM_PLAYLIST["movies"],
            "weather": weather,
            "temp": temp,
            "cached": False
        }
    except Exception as fallback_err:
        print(f"!!! FALLBACK ASSEMBLY FAILED: {fallback_err}")
        fallback_payload = {
            "description": "Fallback Premium Playlist",
            "music": FALLBACK_PREMIUM_PLAYLIST["music"],
            "movies": FALLBACK_PREMIUM_PLAYLIST["movies"],
            "weather": weather,
            "temp": temp,
            "cached": False
        }
    _cache_set(lookup, fallback_payload)
    return jsonify(fallback_payload)


def compose_capsule(payload, paid=False):
    recipient_name = (payload.get("recipient_name") or "").strip() or "Someone special"
    recipient_city = (payload.get("recipient_city") or "").strip() or "Their city"
    sender_city = (payload.get("sender_city") or "").strip() or "Noida"
    vibe = (payload.get("vibe") or "").strip() or "Weather-synced"
    category = (payload.get("category") or "").strip() or "Bollywood"
    note = (payload.get("note") or "").strip() or "A night packed as a ticket."
    weather = (payload.get("weather") or "").strip() or "Clear"
    temp = (payload.get("temp") or "").strip() or "30"

    capsule_code = f"SWAR-{uuid.uuid4().hex[:6].upper()}"
    issued_at = datetime.now().strftime("%d %b %Y · %I:%M %p")
    sky = f"{weather} {temp}".lower()
    album_title = "Midnight Rain"
    track_style = "Lo-Fi Indie"
    if "clear" in sky or "sun" in sky:
        album_title = "Crimson Afterglow"
        track_style = "Warm Vinyl Soul"
    elif "cloud" in sky:
        album_title = "Velvet Overcast"
        track_style = "Bedroom Pop"
    elif "rain" in sky or "drizzle" in sky or "shower" in sky:
        album_title = "Midnight Rain"
        track_style = "Lo-Fi Indie"

    return {
        "code": capsule_code,
        "status": "sent",
        "tier": "premium" if paid else "free",
        "price": "₹99" if paid else "Free",
        "issued_at": issued_at,
        "recipient_name": recipient_name,
        "recipient_city": recipient_city,
        "sender_city": sender_city,
        "vibe": vibe,
        "category": category,
        "note": note,
        "weather": weather,
        "temp": temp,
        "valid_for": "24 hours",
        "album_title": album_title,
        "track_style": track_style
    }


@app.route("/issue_free_capsule", methods=["POST"])
def issue_free_capsule():
    """Freemium gifts 1–2: issue a concert pass with no Razorpay charge."""
    payload = request.get_json(silent=True) or {}
    capsule = compose_capsule(payload, paid=False)
    return jsonify({
        "success": True,
        "message": "Free vibe capsule issued.",
        "payment": None,
        "capsule": capsule
    })


@app.route("/create_capsule_order", methods=["POST"])
def create_capsule_order():
    """Dummy Razorpay order + captured UPI payment for premium Vibe Capsules."""
    payload = request.get_json(silent=True) or {}
    time.sleep(0.7)

    order_id = f"order_{uuid.uuid4().hex[:14]}"
    payment_id = f"pay_{uuid.uuid4().hex[:14]}"
    capsule = compose_capsule(payload, paid=True)

    return jsonify({
        "success": True,
        "message": "Payment captured. Capsule sealed and sent.",
        "order": {
            "id": order_id,
            "entity": "order",
            "amount": 9900,
            "amount_due": 0,
            "currency": "INR",
            "receipt": capsule["code"],
            "status": "paid",
            "notes": {
                "product": "SWAR Premium Vibe Capsule",
                "recipient_name": capsule["recipient_name"],
                "recipient_city": capsule["recipient_city"]
            }
        },
        "payment": {
            "id": payment_id,
            "entity": "payment",
            "amount": 9900,
            "currency": "INR",
            "status": "captured",
            "method": "upi",
            "vpa": "swar@razorpay",
            "captured": True
        },
        "capsule": capsule
    })


@app.route("/soul-chat", methods=["POST"])
def soul_chat():
    """Private therapist-friend reply, grounded in the user's live mood and weather."""
    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("user_message") or "").strip()
    current_mood = (payload.get("current_mood") or "unspecified").strip()
    current_weather = (payload.get("current_weather") or "unknown sky").strip()

    if not user_message:
        return jsonify({
            "success": False,
            "reply": "I'm here. Say anything — even a single word is enough."
        }), 400

    prompt = f"""
You are SWAR's Soul Space companion: a warm, intimate therapist-friend.
Never mention being an AI unless asked. Do not give medical diagnoses or crisis-hotline lectures unless they clearly ask for emergency help.
Acknowledge their current mood AND the weather in a natural way, then respond to what they said.
Keep it to 2–4 short sentences. Gentle, specific, human.

Current mood: {current_mood}
Current weather: {current_weather}
User: {user_message}
"""

    try:
        from google.generativeai import types
        config = types.GenerationConfig(temperature=0.85, top_p=0.9, max_output_tokens=220)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=config
        )
        reply = (response.text or "").strip()
        if not reply:
            raise ValueError("empty gemini reply")
        return jsonify({"success": True, "reply": reply})
    except Exception as err:
        print(f"!!! SOUL CHAT FALLBACK: {err}")
        reply = (
            f"I can feel that {current_mood.lower()} sitting with you under this {current_weather.lower()}. "
            f"What you wrote matters. I'm still here — no fixing, just with you."
        )
        return jsonify({"success": True, "reply": reply, "fallback": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)