from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import anthropic
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

def get_default_config():
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

# Clés par défaut (les tiennes)
DEFAULT_API_KEY, DEFAULT_INTERVALS_KEY, DEFAULT_ATHLETE_ID = get_default_config()

SPORT_MAPPING = {
    'Kayak': ['Kayaking', 'Canoeing'],
    'Rando': ['Walk', 'Hike', 'Trail', 'Hiking'],
    'Running': ['Run', 'VirtualRun'],
    'Velo': ['Ride', 'VirtualRide', 'MountainBikeRide'],
    'Natation': ['Swim', 'OpenWaterSwim'],
}

SPORT_EMOJI = {
    'Kayak': '🚣',
    'Rando': '🥾',
    'Running': '🏃',
    'Velo': '🚴',
    'Natation': '🏊',
}

def fetch_activites(days=180, intervals_key=None, athlete_id=None):
    intervals_key = intervals_key or DEFAULT_INTERVALS_KEY
    athlete_id = athlete_id or DEFAULT_ATHLETE_ID
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/activities"
    params = {
        "oldest": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "newest": datetime.now().strftime("%Y-%m-%d"),
    }
    response = requests.get(url, params=params, auth=("API_KEY", intervals_key))
    return response.json()

def fetch_wellness(days=90, intervals_key=None, athlete_id=None):
    intervals_key = intervals_key or DEFAULT_INTERVALS_KEY
    athlete_id = athlete_id or DEFAULT_ATHLETE_ID
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness"
    params = {
        "oldest": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "newest": datetime.now().strftime("%Y-%m-%d"),
    }
    response = requests.get(url, params=params, auth=("API_KEY", intervals_key))
    return response.json()

def get_sante(intervals_key=None, athlete_id=None):
    wellness = fetch_wellness(90, intervals_key, athlete_id)

    poids = []
    fc_repos = []
    hrv = []
    sommeil_duree = []
    sommeil_score = []
    pas = []
    dates = []

    for w in wellness:
        date = w.get("id", "")
        dates.append(date)
        poids.append(w.get("weight") or None)
        fc_repos.append(w.get("restingHR") or None)
        hrv.append(w.get("hrv") or None)
        sommeil_duree.append(round((w.get("sleepSecs") or 0) / 3600, 1) if w.get("sleepSecs") else None)
        sommeil_score.append(w.get("sleepScore") or None)
        pas.append(w.get("steps") or None)

    derniere_valeur = lambda lst: next((x for x in reversed(lst) if x is not None), None)

    def moyenne(lst):
        valeurs = [x for x in lst[-30:] if x is not None]
        return round(sum(valeurs) / len(valeurs), 1) if valeurs else None

    activites = fetch_activites(90, intervals_key, athlete_id)
    correlations = []
    for a in activites:
        date_activite = a.get("start_date_local", "")[:10]
        vitesse = round((a.get("average_speed", 0) or 0) * 3.6, 1)
        fc_moy = a.get("average_heartrate") or None
        try:
            dt = datetime.strptime(date_activite, "%Y-%m-%d")
            veille = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            if veille in dates:
                idx = dates.index(veille)
                sommeil_veille = sommeil_duree[idx]
                hrv_veille = hrv[idx]
                if sommeil_veille and vitesse > 0:
                    correlations.append({
                        "date": date_activite,
                        "sport": a.get("type"),
                        "vitesse": vitesse,
                        "fc_moy": fc_moy,
                        "sommeil_veille": sommeil_veille,
                        "hrv_veille": hrv_veille,
                    })
        except:
            pass

    return {
        "dates": dates,
        "poids": poids,
        "fc_repos": fc_repos,
        "hrv": hrv,
        "sommeil_duree": sommeil_duree,
        "sommeil_score": sommeil_score,
        "pas": pas,
        "derniers": {
            "poids": derniere_valeur(poids),
            "fc_repos": derniere_valeur(fc_repos),
            "hrv": derniere_valeur(hrv),
            "sommeil_duree": derniere_valeur(sommeil_duree),
            "sommeil_score": derniere_valeur(sommeil_score),
            "pas": derniere_valeur(pas),
        },
        "moyennes_30j": {
            "poids": moyenne(poids),
            "fc_repos": moyenne(fc_repos),
            "hrv": moyenne(hrv),
            "sommeil_duree": moyenne(sommeil_duree),
            "sommeil_score": moyenne(sommeil_score),
            "pas": moyenne(pas),
        },
        "correlations": correlations[:10],
    }

def get_sorties(intervals_key=None, athlete_id=None):
    activites = fetch_activites(28, intervals_key, athlete_id)
    sorties = []
    for a in activites:
        date_str = a.get("start_date_local", "")[:16]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
            dt = dt + timedelta(hours=2)
            date_affichee = dt.strftime("%d/%m/%Y à %Hh%M")
        except:
            date_affichee = date_str

        distance = round((a.get("distance", 0) or 0) / 1000, 2)
        duree = round((a.get("moving_time", 0) or 0) / 60)
        vitesse = round((a.get("average_speed", 0) or 0) * 3.6, 1)
        fc_moy = a.get("average_heartrate") or 0
        fc_max = a.get("max_heartrate") or 0
        calories = a.get("calories") or 0

        sorties.append({
            "id": a.get("id"),
            "nom": a.get("name", "Activité"),
            "sport": a.get("type", "?"),
            "date": date_affichee,
            "distance": distance,
            "duree": duree,
            "vitesse": vitesse,
            "fc_moy": fc_moy,
            "fc_max": fc_max,
            "calories": calories,
        })
    return sorties

def get_detail_sortie(activity_id, intervals_key=None):
    intervals_key = intervals_key or DEFAULT_INTERVALS_KEY
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams"
    params = {"streams": "heartrate,velocity_smooth,altitude,time"}
    response = requests.get(url, params=params, auth=("API_KEY", intervals_key))
    streams = response.json()

    result = {}
    for stream in streams:
        t = stream.get("type")
        data = stream.get("data", [])
        if t == "time":
            result["time"] = [round(x / 60, 1) for x in data]
        elif t == "heartrate":
            result["heartrate"] = data
        elif t == "velocity_smooth":
            result["speed"] = [round(x * 3.6, 1) for x in data]
        elif t == "altitude":
            result["altitude"] = data

    step = 10
    for key in result:
        result[key] = result[key][::step]

    return result

def get_stats(intervals_key=None, athlete_id=None):
    activites = fetch_activites(30, intervals_key, athlete_id)
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

        sorties.append({
            "date": date,
            "nom": a.get("name", "Activité"),
            "sport": a.get("type", "?"),
            "distance": distance,
            "duree": duree,
            "vitesse": vitesse,
            "fc_moy": fc_moy,
            "cadence": round(cadence),
        })

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

    activites_6mois = fetch_activites(180, intervals_key, athlete_id)
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

def get_analyse(sport_filtre=None, api_key=None, intervals_key=None, athlete_id=None):
    api_key = api_key or DEFAULT_API_KEY
    activites = fetch_activites(180, intervals_key, athlete_id)

    if sport_filtre and sport_filtre in SPORT_MAPPING:
        types_acceptes = SPORT_MAPPING[sport_filtre]
        activites = [a for a in activites if a.get('type') in types_acceptes]
        emoji = SPORT_EMOJI.get(sport_filtre, '🏃')
        sport_label = f"{emoji} {sport_filtre}"
    else:
        sport_label = "tous sports"

    if not activites:
        return f"Aucune activité {sport_filtre} trouvée dans les 6 derniers mois."

    total_distance = sum((a.get("distance", 0) or 0) / 1000 for a in activites)
    total_duree = sum((a.get("moving_time", 0) or 0) / 60 for a in activites)
    total_calories = sum((a.get("calories", 0) or 0) for a in activites)

    resume = f"Analyse {sport_label} — {len(activites)} sorties sur 6 mois\n"
    resume += f"Total : {round(total_distance, 1)} km | {round(total_duree)} min | {round(total_calories)} cal\n\n"
    resume += "--- 5 dernières sorties ---\n\n"

    for i, a in enumerate(activites[:5], 1):
        date = a.get("start_date_local", "")[:16].replace("T", " à ")
        try:
            dt = datetime.strptime(date, "%Y-%m-%d à %H:%M")
            dt = dt + timedelta(hours=2)
            date = dt.strftime("%d/%m/%Y à %Hh%M")
        except:
            pass

        distance = round((a.get("distance", 0) or 0) / 1000, 2)
        duree = round((a.get("moving_time", 0) or 0) / 60)
        fc_moy = a.get("average_heartrate", "N/A")
        fc_max = a.get("max_heartrate", "N/A")
        vitesse = round((a.get("average_speed", 0) or 0) * 3.6, 1)
        calories = a.get("calories", "N/A")

        resume += f"Sortie {i} - {a.get('name', 'Activité')} ({date})\n"
        resume += f"  Distance : {distance} km | Durée : {duree} min\n"
        resume += f"  Vitesse : {vitesse} km/h | FC moy : {fc_moy} | FC max : {fc_max}\n"
        resume += f"  Calories : {calories}\n\n"

    # Calcul des moyennes pour comparaison dernière sortie
    if len(activites) > 1:
        autres = activites[1:]
        moy_distance = round(sum((a.get("distance", 0) or 0) / 1000 for a in autres) / len(autres), 2)
        moy_vitesse = round(sum((a.get("average_speed", 0) or 0) * 3.6 for a in autres) / len(autres), 1)
        moy_fc = round(sum((a.get("average_heartrate", 0) or 0) for a in autres) / len(autres))
        moy_duree = round(sum((a.get("moving_time", 0) or 0) / 60 for a in autres) / len(autres))

        derniere = activites[0]
        dern_distance = round((derniere.get("distance", 0) or 0) / 1000, 2)
        dern_vitesse = round((derniere.get("average_speed", 0) or 0) * 3.6, 1)
        dern_fc = derniere.get("average_heartrate", 0) or 0
        dern_duree = round((derniere.get("moving_time", 0) or 0) / 60)

        resume += f"--- Comparaison dernière sortie vs moyenne ---\n\n"
        resume += f"Distance : {dern_distance} km vs {moy_distance} km en moyenne\n"
        resume += f"Vitesse : {dern_vitesse} km/h vs {moy_vitesse} km/h en moyenne\n"
        resume += f"FC moyenne : {dern_fc} bpm vs {moy_fc} bpm en moyenne\n"
        resume += f"Durée : {dern_duree} min vs {moy_duree} min en moyenne\n\n"

    prompt = resume + f"""
Tu es un coach expert en {sport_filtre or 'sport'}.
Analyse ces données sur 6 mois et donne moi :
1. Une analyse de ma dernière sortie par rapport à ma moyenne habituelle (points précis avec chiffres)
2. Les tendances et progressions observées sur 6 mois
3. Mes points forts
4. Des conseils concrets et techniques pour progresser
5. Un objectif réaliste pour les 4 prochaines semaines

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
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Récupération des clés depuis les paramètres de la requête
        # Si absentes, on utilise les clés par défaut
        req_intervals_key = params.get('intervals_key', [None])[0] or DEFAULT_INTERVALS_KEY
        req_athlete_id = params.get('athlete_id', [None])[0] or DEFAULT_ATHLETE_ID
        req_api_key = DEFAULT_API_KEY  # La clé Anthropic reste toujours la nôtre

        if parsed.path == "/analyse":
            try:
                sport_filtre = params.get('sport', [None])[0]
                analyse = get_analyse(sport_filtre, req_api_key, req_intervals_key, req_athlete_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"analyse": analyse}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif parsed.path == "/stats":
            try:
                stats = get_stats(req_intervals_key, req_athlete_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(stats).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif parsed.path == "/sorties":
            try:
                sorties = get_sorties(req_intervals_key, req_athlete_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(sorties).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif parsed.path.startswith("/sortie/"):
            try:
                activity_id = parsed.path.split("/sortie/")[1]
                detail = get_detail_sortie(activity_id, req_intervals_key)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(detail).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())

        elif parsed.path == "/sante":
            try:
                sante = get_sante(req_intervals_key, req_athlete_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(sante).encode())
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
