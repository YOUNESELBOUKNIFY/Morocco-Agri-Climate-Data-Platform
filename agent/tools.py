"""Weather and location tools for the agent (Open-Meteo + own Supabase database)."""

import unicodedata

import requests
from sqlalchemy import text

import db_tools

# Nominatim requires a User-Agent that identifies your application
HEADERS = {"User-Agent": "morocco-weather-agent/0.1 (github.com/YOUNESELBOUKNIFY)"}

# WMO weather codes used by Open-Meteo
WMO = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine", 55: "bruine dense",
    61: "pluie faible", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "forte pluie verglaçante",
    71: "neige faible", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses faibles", 81: "averses", 82: "fortes averses",
    85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grêle", 99: "orage avec forte grêle",
}

# Main cities of the 12 regions of Morocco
REGIONS = {
    "Tanger-Tétouan-Al Hoceïma": ["Tanger", "Tetouan", "Al Hoceima"],
    "Oriental": ["Oujda", "Nador", "Berkane"],
    "Fès-Meknès": ["Fes", "Meknes", "Taza"],
    "Rabat-Salé-Kénitra": ["Rabat", "Sale", "Kenitra"],
    "Béni Mellal-Khénifra": ["Beni Mellal", "Khenifra", "Khouribga"],
    "Casablanca-Settat": ["Casablanca", "Settat", "El Jadida"],
    "Marrakech-Safi": ["Marrakech", "Safi", "Essaouira"],
    "Drâa-Tafilalet": ["Errachidia", "Ouarzazate", "Tinghir"],
    "Souss-Massa": ["Agadir", "Taroudant", "Tiznit"],
    "Guelmim-Oued Noun": ["Guelmim", "Tan-Tan", "Sidi Ifni"],
    "Laâyoune-Sakia El Hamra": ["Laayoune", "Boujdour", "Tarfaya"],
    "Dakhla-Oued Ed-Dahab": ["Dakhla"],
}


def _norm(s: str) -> str:
    """'Fès-Meknès' -> 'fes meknes'"""
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").strip()


# ------------------------------------------------------------ location ----

def _search_db(place: str, max_results: int) -> list:
    """Search the `localites` table (Latin or Arabic name, accent-insensitive)."""
    sql = text("""
        SELECT nom, nom_ar, region, latitude, longitude
        FROM localites
        WHERE unaccent(nom) ILIKE unaccent(:contains) OR nom_ar LIKE :contains
        ORDER BY
            (LOWER(unaccent(nom)) = LOWER(unaccent(:exact)) OR nom_ar = :exact) DESC,
            unaccent(nom) ILIKE unaccent(:starts) DESC,
            LENGTH(nom)
        LIMIT :n
    """)
    try:
        with db_tools.get_engine().connect() as c:
            rows = c.execute(sql, {"contains": f"%{place}%", "starts": f"{place}%",
                                   "exact": place, "n": max_results})
            return [{
                "name": r.nom, "name_ar": r.nom_ar, "region": r.region, "province": None,
                "latitude": r.latitude, "longitude": r.longitude, "elevation_m": None,
                "source": "database",
            } for r in rows]
    except Exception as e:
        print(f"[DB] {e}")
        return []


def find_location(place: str, max_results: int = 3) -> dict:
    """Find the coordinates of a city or village in Morocco (database, then Open-Meteo, then OSM)."""

    # 1) Own database (43k localities)
    results = _search_db(place, max_results)

    # 2) Fallback: Open-Meteo Geocoding
    if not results:
        try:
            r = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": place, "count": max_results, "language": "en", "countryCode": "MA"},
                timeout=10,
            ).json()
        except requests.RequestException:
            r = {}
        results = [{
            "name": x["name"], "name_ar": None,
            "region": x.get("admin1"), "province": x.get("admin2"),
            "latitude": x["latitude"], "longitude": x["longitude"],
            "elevation_m": x.get("elevation"), "source": "open-meteo",
        } for x in r.get("results", [])]

    # 3) Fallback: OpenStreetMap (Nominatim)
    if not results:
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": place, "countrycodes": "ma", "format": "json",
                        "limit": max_results, "addressdetails": 1, "accept-language": "en"},
                headers=HEADERS, timeout=10,
            ).json()
        except requests.RequestException:
            r = []
        results = [{
            "name": x["display_name"].split(",")[0], "name_ar": None,
            "region": x.get("address", {}).get("state"),
            "province": x.get("address", {}).get("province") or x.get("address", {}).get("county"),
            "latitude": float(x["lat"]), "longitude": float(x["lon"]),
            "elevation_m": None, "source": "openstreetmap",
        } for x in r]

    if not results:
        return {"error": f"Place not found in Morocco: {place}"}
    return {"query": place, "results": results}


# ------------------------------------------------------------- weather ----

def meteo_ville(ville: str, jours: int = 3) -> dict:
    """Current weather and daily forecast for any city or village in Morocco."""
    loc = find_location(ville, max_results=1)
    if "error" in loc:
        return {"erreur": f"Lieu introuvable au Maroc : {ville}"}
    lieu = loc["results"][0]
    jours = max(1, min(int(jours), 16))

    try:
        d = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lieu["latitude"], "longitude": lieu["longitude"],
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
            "forecast_days": jours, "timezone": "auto"}, timeout=10).json()
    except requests.RequestException as e:
        return {"erreur": f"API météo indisponible : {e}"}

    c, j = d["current"], d["daily"]
    return {
        "lieu": lieu["name"],
        "region": lieu["region"],
        "coordonnees": [lieu["latitude"], lieu["longitude"]],
        "maintenant": {
            "temperature_C": c["temperature_2m"], "humidite_pct": c["relative_humidity_2m"],
            "vent_kmh": c["wind_speed_10m"], "pluie_mm": c["precipitation"],
            "ciel": WMO.get(c["weather_code"], "inconnu")},
        "previsions": [{
            "date": j["time"][i], "min_C": j["temperature_2m_min"][i],
            "max_C": j["temperature_2m_max"][i], "pluie_mm": j["precipitation_sum"][i],
            "ciel": WMO.get(j["weather_code"][i], "inconnu")} for i in range(len(j["time"]))],
    }


def meteo_region(region: str) -> dict:
    """Today's weather for the main cities of a Moroccan region."""
    cle = next((r for r in REGIONS if _norm(region) in _norm(r) or _norm(r) in _norm(region)), None)
    if not cle:
        return {"erreur": f"Région inconnue : {region}", "regions_disponibles": list(REGIONS)}
    return {"region": cle, "villes": [meteo_ville(v, jours=1) for v in REGIONS[cle]]}


def conseil_irrigation(culture: str, pluie_totale_mm: float, temp_max_moyenne: float) -> dict:
    """Simple irrigation advice from forecast rain and heat (demo rules)."""
    if pluie_totale_mm >= 20:
        conseil = "Pas besoin d'arroser : beaucoup de pluie prévue."
    elif temp_max_moyenne >= 30 and pluie_totale_mm < 5:
        conseil = "Arroser : temps chaud et sec. De préférence tôt le matin ou le soir."
    elif pluie_totale_mm < 10:
        conseil = "Arrosage léger conseillé : peu de pluie prévue."
    else:
        conseil = "Surveiller l'humidité du sol : pluie modérée prévue."
    return {"culture": culture, "pluie_totale_mm": pluie_totale_mm,
            "temp_max_moyenne": temp_max_moyenne, "conseil": conseil}


# ---------------------------------------------------- tool descriptions ----

FUNCS = {
    "find_location": find_location,
    "meteo_ville": meteo_ville,
    "meteo_region": meteo_region,
    "conseil_irrigation": conseil_irrigation,
}

TOOLS = [
    {"type": "function", "function": {
        "name": "find_location",
        "description": "Trouve les coordonnées (latitude, longitude) et la région d'une ville ou d'un village du Maroc",
        "parameters": {"type": "object", "properties": {
            "place": {"type": "string", "description": "Nom du lieu, en lettres latines ou en arabe"}},
            "required": ["place"]}}},
    {"type": "function", "function": {
        "name": "meteo_ville",
        "description": "Météo actuelle et prévisions d'une ville ou d'un village du Maroc",
        "parameters": {"type": "object", "properties": {
            "ville": {"type": "string", "description": "Nom du lieu, ex. Fes, Agadir, Fritissa"},
            "jours": {"type": "integer", "description": "Jours de prévision, 1 à 16 (défaut 3)"}},
            "required": ["ville"]}}},
    {"type": "function", "function": {
        "name": "meteo_region",
        "description": "Météo du jour des villes principales d'une région du Maroc, ex. Fès-Meknès, Souss-Massa",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "string"}}, "required": ["region"]}}},
    {"type": "function", "function": {
        "name": "conseil_irrigation",
        "description": "Conseil d'arrosage à partir de la pluie totale prévue et de la température max moyenne",
        "parameters": {"type": "object", "properties": {
            "culture": {"type": "string"},
            "pluie_totale_mm": {"type": "number"},
            "temp_max_moyenne": {"type": "number"}},
            "required": ["culture", "pluie_totale_mm", "temp_max_moyenne"]}}},
]


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(find_location("Fes"))
    print(meteo_ville("Fritissa", jours=2))