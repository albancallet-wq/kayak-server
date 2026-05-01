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

DEFAULT_API_KEY, DEFAULT_INTERVALS_KEY, DEFAULT_ATHLETE_ID = get_default_config()

SPORT_MAPPING = {
    'Kayak': ['Kayaking', 'Canoeing'],
    'Rando': ['Walk', 'Hike', 'Trail', 'Hiking'],
    'Running': ['Run', 'VirtualRun'],
    'Velo': ['Ride', 'VirtualRide', 'MountainBikeRide'],
    'Natation': ['Swim', 'OpenWaterSwim'],
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

def calculer_zone_fc(fc_moy, fc_max_seance, fc_repos=50, fc_max_theorique=170):
    if not fc_moy:
        return None, None, None, None
    fc_reserve = fc_max_theorique - fc_repos
    fc_relative = (fc_moy - fc_repos) / fc_reserve * 100 if fc_reserve > 0 else 0

    if fc_relative < 60:
        return "Zone 1 — Récupération active", "Effort très léger, idéal pour récupérer", "récupération", round(fc_relative)
    elif fc_relative < 70:
        return "Zone 2 — Endurance fondamentale", "Aérobie pur — tu brûles les graisses et construis ton fond", "aérobie", round(fc_relative)
    elif fc_relative < 80:
        return "Zone 3 — Endurance active", "Aérobie modéré — amélioration de l'efficacité cardiovasculaire", "aérobie modéré", round(fc_relative)
    elif fc_relative < 90:
        return "Zone 4 — Seuil anaérobie", "Tu approches ton seuil — effort intense mais contrôlé", "seuil", round(fc_relative)
    else:
        return "Zone 5 — Effort maximal", "Anaérobie — effort très intense, court mais efficace", "anaérobie", round(fc_relative)

def get_analyse(api_key=None, intervals_key=None, athlete_id=None, activity_id=None):
    """Analyse une séance spécifique (par activity_id) ou la dernière séance"""
    api_key = api_key or DEFAULT_API_KEY
    activites = fetch_activites(180, intervals_key, athlete_id)
    activites = sorted(activites, key=lambda a: a.get('start_date_local', ''), reverse=True)

    if not activites:
        return "Aucune activité trouvée dans les 6 derniers mois."

    # Si un activity_id est fourni, on cherche cette activité spécifique
    if activity_id:
        cible = next((a for a in activites if str(a.get('id', '')) == str(activity_id)), None)
        if cible:
            # La séance cible devient la "dernière", les autres sont les précédentes
            autres = [a for a in activites if str(a.get('id', '')) != str(activity_id)]
            derniere = cible
        else:
            # ID non trouvé, on prend la dernière
            derniere = activites[0]
            autres = activites[1:]
    else:
        derniere = activites[0]
        autres = activites[1:]

    # ---- DONNÉES DE LA SÉANCE ANALYSÉE ----
    date_dern = derniere.get("start_date_local", "")[:16]
    try:
        dt = datetime.strptime(date_dern, "%Y-%m-%dT%H:%M")
        dt = dt + timedelta(hours=2)
        date_dern_affichee = dt.strftime("%d/%m/%Y à %Hh%M")
    except:
        date_dern_affichee = date_dern

    dern_nom = derniere.get("name", "Activité")
    dern_sport = derniere.get("type", "?")
    dern_distance = round((derniere.get("distance", 0) or 0) / 1000, 2)
    dern_duree = round((derniere.get("moving_time", 0) or 0) / 60)
    dern_vitesse = round((derniere.get("average_speed", 0) or 0) * 3.6, 1)
    dern_fc_moy = derniere.get("average_heartrate") or 0
    dern_fc_max = derniere.get("max_heartrate") or 0
    dern_calories = derniere.get("calories") or 0
    dern_denivele = round(derniere.get("total_elevation_gain") or 0)

    # ---- MOYENNES SUR LES SÉANCES DU MÊME SPORT ----
    # On filtre les autres séances par sport similaire
    sport_type = derniere.get('type', '')
    autres_meme_sport = [a for a in autres if a.get('type') == sport_type]
    autres_tous = autres

    if autres_meme_sport:
        moy_distance = round(sum((a.get("distance", 0) or 0) / 1000 for a in autres_meme_sport) / len(autres_meme_sport), 2)
        moy_vitesse = round(sum((a.get("average_speed", 0) or 0) * 3.6 for a in autres_meme_sport) / len(autres_meme_sport), 1)
        moy_fc_list = [a.get("average_heartrate", 0) or 0 for a in autres_meme_sport if a.get("average_heartrate")]
        moy_fc = round(sum(moy_fc_list) / len(moy_fc_list)) if moy_fc_list else 0
        moy_duree = round(sum((a.get("moving_time", 0) or 0) / 60 for a in autres_meme_sport) / len(autres_meme_sport))
        nb_sorties_meme_sport = len(autres_meme_sport)
    else:
        moy_distance = moy_vitesse = moy_fc = moy_duree = 0
        nb_sorties_meme_sport = 0

    # Tendance vitesse (3 dernières du même sport vs 3 précédentes)
    if len(autres_meme_sport) >= 6:
        recentes = [round((a.get("average_speed", 0) or 0) * 3.6, 1) for a in autres_meme_sport[:3]]
        anciennes = [round((a.get("average_speed", 0) or 0) * 3.6, 1) for a in autres_meme_sport[3:6]]
        tendance = round(sum(recentes)/len(recentes) - sum(anciennes)/len(anciennes), 2)
        tendance_label = f"+{tendance} km/h" if tendance > 0 else f"{tendance} km/h"
    else:
        tendance_label = "pas assez de données"

    # ---- ZONE FC ----
    zone_nom, zone_desc, type_effort, fc_relative = calculer_zone_fc(dern_fc_moy, dern_fc_max)
    zone_nom = zone_nom or "Non calculable"
    zone_desc = zone_desc or ""
    type_effort = type_effort or ""
    fc_relative = fc_relative or 0

    # ---- COMPARAISONS ----
    def delta(val, moy, unite=""):
        if moy == 0: return "première séance de ce sport"
        diff = round(val - moy, 2)
        signe = "+" if diff > 0 else ""
        return f"{signe}{diff}{unite}"

    # ---- PROMPT ----
    prompt = f"""Tu es un coach sportif expert en analyse de données d'entraînement.

Voici les données de la séance à analyser :

**SÉANCE — {dern_nom} ({date_dern_affichee})**
- Sport : {dern_sport}
- Distance : {dern_distance} km
- Durée : {dern_duree} min
- Vitesse moyenne : {dern_vitesse} km/h
- FC moyenne : {dern_fc_moy} bpm | FC max : {dern_fc_max} bpm
- Calories : {dern_calories} kcal
- Dénivelé : {dern_denivele} m

**COMPARAISON AVEC LA MOYENNE ({nb_sorties_meme_sport} séances précédentes du même sport)**
- Distance : {dern_distance} km vs {moy_distance} km → {delta(dern_distance, moy_distance, ' km')}
- Vitesse : {dern_vitesse} km/h vs {moy_vitesse} km/h → {delta(dern_vitesse, moy_vitesse, ' km/h')}
- FC moyenne : {dern_fc_moy} bpm vs {moy_fc} bpm → {delta(dern_fc_moy, moy_fc, ' bpm')}
- Durée : {dern_duree} min vs {moy_duree} min → {delta(dern_duree, moy_duree, ' min')}
- Tendance vitesse récente : {tendance_label}

**ZONE D'EFFORT**
- Zone : {zone_nom}
- FC relative : {fc_relative}% de la FC de réserve
- Type : {type_effort}
- Signification : {zone_desc}

Rédige un debriefing complet et personnalisé en français avec ces sections :

## 📊 Ta séance en bref
(résumé des chiffres clés en 2-3 phrases)

## 💪 Intensité et zone d'effort
(explique la zone d'effort EN TERMES SIMPLES — qu'est-ce que ça veut dire concrètement ?)

## 📈 Par rapport à tes habitudes
(compare avec la moyenne — est-ce mieux, pareil, moins bien ?)

## 🔄 Progression
(tendance générale — est-ce que ça progresse ?)

## 🎯 Conseil pour la prochaine séance
(UN conseil concret et spécifique basé sur ces données)

Sois précis avec les chiffres, bienveillant et motivant. Max 450 mots."""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def get_sante(intervals_key=None, athlete_id=None):
    wellness = fetch_wellness(90, intervals_key, athlete_id)
    poids, fc_repos, hrv, sommeil_duree, sommeil_score, pas, dates = [], [], [], [], [], [], []

    for w in wellness:
        dates.append(w.get("id", ""))
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
        try:
            dt = datetime.strptime(date_activite, "%Y-%m-%d")
            veille = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
            if veille in dates:
                idx = dates.index(veille)
                sv = sommeil_duree[idx]
                hv = hrv[idx]
                if sv and vitesse > 0:
                    correlations.append({"date": date_activite, "sport": a.get("type"), "vitesse": vitesse, "fc_moy": a.get("average_heartrate"), "sommeil_veille": sv, "hrv_veille": hv})
        except:
            pass

    return {
        "dates": dates, "poids": poids, "fc_repos": fc_repos, "hrv": hrv,
        "sommeil_duree": sommeil_duree, "sommeil_score": sommeil_score, "pas": pas,
        "derniers": {"poids": derniere_valeur(poids), "fc_repos": derniere_valeur(fc_repos), "hrv": derniere_valeur(hrv), "sommeil_duree": derniere_valeur(sommeil_duree), "sommeil_score": derniere_valeur(sommeil_score), "pas": derniere_valeur(pas)},
        "moyennes_30j": {"poids": moyenne(poids), "fc_repos": moyenne(fc_repos), "hrv": moyenne(hrv), "sommeil_duree": moyenne(sommeil_duree), "sommeil_score": moyenne(sommeil_score), "pas": moyenne(pas)},
        "correlations": correlations[:10],
    }

def get_sorties(intervals_key=None, athlete_id=None):
    activites = fetch_activites(28, intervals_key, athlete_id)
    sorties = []
    for a in activites:
        date_str = a.get("start_date_local", "")[:16]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M") + timedelta(hours=2)
            date_affichee = dt.strftime("%d/%m/%Y à %Hh%M")
        except:
            date_affichee = date_str

        sorties.append({
            "id": a.get("id"),
            "nom": a.get("name", "Activité"),
            "sport": a.get("type", "?"),
            "date": date_affichee,
            "distance": round((a.get("distance", 0) or 0) / 1000, 2),
            "duree": round((a.get("moving_time", 0) or 0) / 60),
            "vitesse": round((a.get("average_speed", 0) or 0) * 3.6, 1),
            "fc_moy": a.get("average_heartrate") or 0,
            "fc_max": a.get("max_heartrate") or 0,
            "calories": a.get("calories") or 0,
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
        if t == "time": result["time"] = [round(x / 60, 1) for x in data]
        elif t == "heartrate": result["heartrate"] = data
        elif t == "velocity_smooth": result["speed"] = [round(x * 3.6, 1) for x in data]
        elif t == "altitude": result["altitude"] = data
    step = 10
    for key in result:
        result[key] = result[key][::step]
    return result

def get_stats(intervals_key=None, athlete_id=None):
    activites = fetch_activites(30, intervals_key, athlete_id)
    sorties = []
    distance_totale = 0
    for a in activites:
        try:
            dt = datetime.strptime(a.get("start_date_local", "")[:16], "%Y-%m-%dT%H:%M") + timedelta(hours=2)
            date = dt.strftime("%d/%m")
        except:
            date = a.get("start_date_local", "")[:10]
        distance = round((a.get("distance", 0) or 0) / 1000, 2)
        distance_totale += distance
        sorties.append({
            "date": date, "nom": a.get("name", "Activité"), "sport": a.get("type", "?"),
            "distance": distance, "duree": round((a.get("moving_time", 0) or 0) / 60),
            "vitesse": round((a.get("average_speed", 0) or 0) * 3.6, 1),
            "fc_moy": a.get("average_heartrate") or 0, "cadence": round(a.get("average_cadence") or 0),
        })

    references = [(50,"Paris → Compiègne"),(80,"Paris → Beauvais"),(150,"Paris → Rouen"),(300,"Paris → Nantes"),(500,"Paris → Bordeaux"),(736,"Paris → Barcelone"),(1000,"Paris → Madrid"),(2000,"Paris → Le Caire")]
    activites_6mois = fetch_activites(180, intervals_key, athlete_id)
    dist_6mois = sum((a.get("distance", 0) or 0) / 1000 for a in activites_6mois)
    vanity_label = next((label for seuil, label in reversed(references) if dist_6mois >= seuil), "Paris → ?")

    return {"sorties": sorties, "distance_totale_30j": round(distance_totale, 1), "distance_totale_6mois": round(dist_6mois, 1), "vanity_metric": vanity_label, "nb_sorties_30j": len(sorties)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        req_intervals_key = params.get('intervals_key', [None])[0] or DEFAULT_INTERVALS_KEY
        req_athlete_id = params.get('athlete_id', [None])[0] or DEFAULT_ATHLETE_ID
        req_api_key = DEFAULT_API_KEY
        # activity_id optionnel pour analyser une séance spécifique
        req_activity_id = params.get('activity_id', [None])[0]

        def respond(data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        if parsed.path == "/analyse":
            try:
                analyse = get_analyse(req_api_key, req_intervals_key, req_athlete_id, req_activity_id)
                respond({"analyse": analyse})
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/stats":
            try: respond(get_stats(req_intervals_key, req_athlete_id))
            except Exception as e: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sorties":
            try: respond(get_sorties(req_intervals_key, req_athlete_id))
            except Exception as e: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path.startswith("/sortie/"):
            try:
                activity_id = parsed.path.split("/sortie/")[1]
                respond(get_detail_sortie(activity_id, req_intervals_key))
            except Exception as e: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sante":
            try: respond(get_sante(req_intervals_key, req_athlete_id))
            except Exception as e: self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        else:
            self.send_response(404); self.end_headers()

    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 8080))
print(f"🚀 Serveur démarré sur le port {port}")
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
