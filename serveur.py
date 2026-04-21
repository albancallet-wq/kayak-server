from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import anthropic
import os
from datetime import datetime, timedelta

def get_config():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    intervals_key = os.environ.get("INTERVALS_API_KEY")
    athlete_id = os.environ.get("INTERVALS_ATHLETE_ID")

    if not api_key:
        config = {}
        with open(os.path.expanduser("~/.env_kayak")) as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    config[key] = value
        api_key = config["ANTHROPIC_API_KEY"]
        intervals_key = config["INTERVALS_API_KEY"]
        athlete_id = config["INTERVALS_ATHLETE_ID"]

    return api_key, intervals_key, athlete_id

api_key, intervals_key, athlete_id = get_config()

def fetch_activites(days=180):
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities"
    params = {
        "oldest": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "newest": datetime.now().strftime("%Y-%m-%d"),
    }
    response = requests.get(url, params=params, auth=("API_KEY", intervals_key))
    return response.json()

def get_stats():
    activites = fetch_activites(30)

    sorties = []
    distance_totale = 0
    for a in activites:
        date = a.get("start_date_local", "")[:10]
        try:
            dt = datetime.strptime(a.get("start_date_local", "")[:16], "%Y-%m-%dT%H:%M")
            dt = dt + timedelta(hours=2)
            date = dt.strftime("%d/%m")
        except:
            pass

        distance = round((a.get("distance", 0) or 0) / 1000, 2)
        distance_totale += distance
        duree = round((a.get("moving_time", 0) or 0) / 60)
        vitesse = round((a.get("average_speed", 0) or 0) * 3.6, 1)
        fc_moy = a.get("average_heartrate") or 0
        cadence = a.get("average_cadence") or 0
        nom = a.get("name", "Activité")
        sport = a.get("type", "?")

        sorties.append({
            "date": date,
            "nom": nom,
            "sport": sport,
            "distance": distance,
            "duree": duree,
            "vitesse": vitesse,
            "fc_moy": fc_moy,
            "cadence": round(cadence),
        })

    # Vanity metric
    references = [
        (50, "Paris → Compiègne"),
        (80, "Paris → Beauvais"),
        (150, "Paris → Rouen"),
        (300, "Paris → Nantes"),
        (500, "Paris → Bordeaux"),
        (736, "Paris → Barcelone"),
        (1000, "Paris → Madrid"),
        (2000, "Paris → Le Caire"),
    ]

    # Distance totale sur 6 mois
    activites_6mois = fetch_activites(180)
    dist_6mois = sum((a.get("distance", 0) or 0) / 1000 for a in activites_6mois)

    vanity_label = "Paris → ?"
    for seuil, label in references:
        if dist_6mois >= seuil:
            vanity_label = label

    return {
        "sorties": sorties,
        "distance_totale_30j": round(distance_totale, 1),
        "distance_totale_6mois": round(dist_6mois, 1),
        "vanity_metric": vanity_label,
        "nb_sorties_30j": len(sorties),
    }

def get_analyse():
    activites = fetch_activites(180)

    par_sport = {}
    for a in activites:
        sport = a.get("type", "Autre")
        if sport not in par_sport:
            par_sport[sport] = {"count": 0, "distance": 0, "duree": 0, "calories": 0}
        par_sport[sport]["count"] += 1
        par_sport[sport]["distance"] += (a.get("distance", 0) or 0) / 1000
        par_sport[sport]["duree"] += (a.get("moving_time", 0) or 0) / 60
        par_sport[sport]["calories"] += (a.get("calories", 0) or 0)

    resume = f"Résumé des 6 derniers mois ({len(activites)} activités) :\n\n"
    for sport, stats in par_sport.items():
        resume += f"🏃 {sport} : {stats['count']} sorties, "
        resume += f"{round(stats['distance'], 1)} km, "
        resume += f"{round(stats['duree'])} min, "
        resume += f"{round(stats['calories'])} cal\n"

    resume += "\n--- 5 dernières activités en détail ---\n\n"
    for i, a in enumerate(activites[:5], 1):
        date = a.get("start_date_local", "")[:16].replace("T", " à ")
        try:
            dt = datetime.strptime(date, "%Y-%m-%d à %H:%M")
            dt = dt + timedelta(hours=2)
            date = dt.strftime("%d/%m/%Y à %Hh%M")
        except:
            pass
        nom = a.get("name", "Activité")
        sport = a.get("type", "?")
        distance = round((a.get("distance", 0) or 0) / 1000, 2)
        duree = round((a.get("moving_time", 0) or 0) / 60)
        fc_moy = a.get("average_heartrate", "N/A")
        fc_max = a.get("max_heartrate", "N/A")
        vitesse = round((a.get("average_speed", 0) or 0) * 3.6, 1)
        calories = a.get("calories", "N/A")

        resume += f"Activité {i} - {nom} ({sport}) - {date}\n"
        resume += f"  Distance : {distance} km | Durée : {duree} min\n"
        resume += f"  Vitesse : {vitesse} km/h | FC moy : {fc_moy} | FC max : {fc_max}\n"
        resume += f"  Calories : {calories}\n\n"

    prompt = resume + """
Tu es un coach sportif expert en analyse de performance.
Analyse ces données sur 6 mois et donne moi :
1. Une analyse globale de mes performances tous sports confondus
2. Les tendances et progressions observées
3. Les corrélations intéressantes entre les sports
4. Des conseils personnalisés pour progresser
5. Un focus sur mes points forts et axes d'amélioration

Réponds en français, de façon personnalisée et encourageante. Sois concis (max 400 mots).
"""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/analyse":
            try:
                analyse = get_analyse()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"analyse": analyse}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif self.path == "/stats":
            try:
                stats = get_stats()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(stats).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 8080))
print(f"🚀 Serveur démarré sur le port {port}")
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
