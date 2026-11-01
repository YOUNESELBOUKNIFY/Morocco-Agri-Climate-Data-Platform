import requests

# Nominatim requires a User-Agent that identifies your application
HEADERS = {"User-Agent": "morocco-weather-agent/0.1 (github.com/YOUNESELBOUKNIFY)"}


def find_location(place: str, max_results: int = 3) -> dict:
    """Find the latitude and longitude of a city or village in Morocco."""

    # 1) Open-Meteo Geocoding
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": max_results, "language": "en", "countryCode": "MA"},
            timeout=10,
        ).json()
    except requests.RequestException:
        r = {}

    results = [{
        "name": x["name"],
        "region": x.get("admin1"),
        "province": x.get("admin2"),
        "latitude": x["latitude"],
        "longitude": x["longitude"],
        "elevation_m": x.get("elevation"),
        "source": "open-meteo",
    } for x in r.get("results", [])]

    # 2) Fallback: OpenStreetMap (Nominatim), better for small villages
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
            "name": x["display_name"].split(",")[0],
            "region": x.get("address", {}).get("state"),
            "province": x.get("address", {}).get("province") or x.get("address", {}).get("county"),
            "latitude": float(x["lat"]),
            "longitude": float(x["lon"]),
            "elevation_m": None,
            "source": "openstreetmap",
        } for x in r]

    if not results:
        return {"error": f"Place not found in Morocco: {place}"}
    return {"query": place, "results": results}


if __name__ == "__main__":
    print(find_location("Fes"))
    print(find_location("Imouzzer Kandar"))