from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import anthropic
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode

def get_default_config():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    intervals_key = os.environ.get("INTERVALS_API_KEY")
    athlete_id = os.environ.get("INTERVALS_ATHLETE_ID")
    strava_client_id = os.environ.get("STRAVA_CLIENT_ID", "233792")
    strava_client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")

    if not api_key:
        config = {}
        try:
            with open(os.path.expanduser("~/.env_kayak")) as f:
                for line in f:
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        config[key] = value
            api_key = config.get("ANTHROPIC_API_KEY", "")
            intervals_key = config.get("INTERVALS_API_KEY", "")
            athlete_id = config.get("INTERVALS_ATHLETE_ID", "")
            strava_client_id = config.get("STRAVA_CLIENT_ID", "233792")
            strava_client_secret = config.get("STRAVA_CLIENT_SECRET", "")
        except:
            pass

    return api_key, intervals_key, athlete_id, strava_client_id, strava_client_secret

DEFAULT_API_KEY, DEFAULT_INTERVALS_KEY, DEFAULT_ATHLETE_ID, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET = get_default_config()

SERVER_URL = os.environ.get("SERVER_URL", "https://kayak-server.onrender.com")

# ============ STRAVA OAUTH ============

def strava_get_auth_url():
    """Génère l'URL d'autorisation Strava"""
    params = {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": f"{SERVER_URL}/strava/callback",
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    return f"https://www.strava.com/oauth/authorize?{urlencode(params)}"

def strava_exchange_code(code):
    """Échange le code OAuth contre un token d'accès"""
    response = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    })
    return response.json()

def strava_refresh_token(refresh_token):
    """Rafraîchit le token d'accès Strava"""
    response = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    return response.json()

def strava_fetch_activites(access_token, days=30):
    """Récupère les activités Strava"""
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"after": after, "per_page": 50}
    response = requests.get(url, headers=headers, params=params)
    return response.json()

def strava_format_activite(a):
    """Formate une activité Strava dans notre format standard"""
    date_str = a.get("start_date_local", "")[:16]
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M")
        date_affichee = dt.strftime("%d/%m/%Y à %Hh%M")
    except:
        date_affichee = date_str

    return {
        "id": a.get("id"),
        "nom": a.get("name", "Activité"),
        "sport": a.get("type", "?"),
        "date": date_affichee,
        "start_date_local": a.get("start_date_local", ""),
        "distance": round((a.get("distance", 0) or 0) / 1000, 2),
        "duree": round((a.get("moving_time", 0) or 0) / 60),
        "vitesse": round((a.get("average_speed", 0) or 0) * 3.6, 1),
        "fc_moy": a.get("average_heartrate") or 0,
        "fc_max": a.get("max_heartrate") or 0,
        "calories": a.get("calories") or 0,
        "denivele": round(a.get("total_elevation_gain") or 0),
    }

# ============ INTERVALS.ICU ============

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

def get_analyse(api_key=None, intervals_key=None, athlete_id=None, activity_id=None, strava_token=None):
    api_key = api_key or DEFAULT_API_KEY

    # Source des données : Strava ou Intervals
    if strava_token:
        raw = strava_fetch_activites(strava_token, days=180)
        activites = sorted(raw, key=lambda a: a.get('start_date_local', ''), reverse=True)
    else:
        activites = fetch_activites(180, intervals_key, athlete_id)
        activites = sorted(activites, key=lambda a: a.get('start_date_local', ''), reverse=True)

    if not activites:
        return "Aucune activité trouvée dans les 6 derniers mois."

    # Sélection de la séance à analyser
    if activity_id:
        cible = next((a for a in activites if str(a.get('id', '')) == str(activity_id)), None)
        if cible:
            derniere = cible
            autres = [a for a in activites if str(a.get('id', '')) != str(activity_id)]
        else:
            derniere = activites[0]
            autres = activites[1:]
    else:
        derniere = activites[0]
        autres = activites[1:]

    # Données de la séance
    date_dern = derniere.get("start_date_local", "")[:16]
    try:
        dt = datetime.strptime(date_dern, "%Y-%m-%dT%H:%M") + timedelta(hours=2)
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

    # Moyennes même sport
    autres_meme_sport = [a for a in autres if a.get('type') == dern_sport]
    if autres_meme_sport:
        moy_distance = round(sum((a.get("distance", 0) or 0) / 1000 for a in autres_meme_sport) / len(autres_meme_sport), 2)
        moy_vitesse = round(sum((a.get("average_speed", 0) or 0) * 3.6 for a in autres_meme_sport) / len(autres_meme_sport), 1)
        moy_fc_list = [a.get("average_heartrate", 0) or 0 for a in autres_meme_sport if a.get("average_heartrate")]
        moy_fc = round(sum(moy_fc_list) / len(moy_fc_list)) if moy_fc_list else 0
        moy_duree = round(sum((a.get("moving_time", 0) or 0) / 60 for a in autres_meme_sport) / len(autres_meme_sport))
        nb_sorties = len(autres_meme_sport)
    else:
        moy_distance = moy_vitesse = moy_fc = moy_duree = nb_sorties = 0

    if len(autres_meme_sport) >= 6:
        recentes = [round((a.get("average_speed", 0) or 0) * 3.6, 1) for a in autres_meme_sport[:3]]
        anciennes = [round((a.get("average_speed", 0) or 0) * 3.6, 1) for a in autres_meme_sport[3:6]]
        tendance = round(sum(recentes)/len(recentes) - sum(anciennes)/len(anciennes), 2)
        tendance_label = f"+{tendance} km/h" if tendance > 0 else f"{tendance} km/h"
    else:
        tendance_label = "pas assez de données"

    zone_nom, zone_desc, type_effort, fc_relative = calculer_zone_fc(dern_fc_moy, dern_fc_max)
    zone_nom = zone_nom or "Non calculable"
    zone_desc = zone_desc or ""
    fc_relative = fc_relative or 0

    def delta(val, moy, unite=""):
        if moy == 0: return "première séance de ce sport"
        diff = round(val - moy, 2)
        return f"+{diff}{unite}" if diff > 0 else f"{diff}{unite}"

    prompt = f"""Tu es un coach sportif expert en analyse de données d'entraînement.

**SÉANCE — {dern_nom} ({date_dern_affichee})**
- Sport : {dern_sport}
- Distance : {dern_distance} km | Durée : {dern_duree} min
- Vitesse : {dern_vitesse} km/h | FC moy : {dern_fc_moy} bpm | FC max : {dern_fc_max} bpm
- Calories : {dern_calories} kcal | Dénivelé : {dern_denivele} m

**COMPARAISON ({nb_sorties} séances précédentes du même sport)**
- Distance : {dern_distance} km vs {moy_distance} km → {delta(dern_distance, moy_distance, ' km')}
- Vitesse : {dern_vitesse} km/h vs {moy_vitesse} km/h → {delta(dern_vitesse, moy_vitesse, ' km/h')}
- FC : {dern_fc_moy} bpm vs {moy_fc} bpm → {delta(dern_fc_moy, moy_fc, ' bpm')}
- Durée : {dern_duree} min vs {moy_duree} min → {delta(dern_duree, moy_duree, ' min')}
- Tendance vitesse : {tendance_label}

**ZONE D'EFFORT**
- {zone_nom} ({fc_relative}% FC de réserve)
- {zone_desc}

Rédige un debriefing en français :

## 📊 Ta séance en bref
## 💪 Intensité et zone d'effort
## 📈 Par rapport à tes habitudes
## 🔄 Progression
## 🎯 Conseil pour la prochaine séance

Précis, bienveillant, motivant. Max 450 mots."""

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def get_sorties(intervals_key=None, athlete_id=None, strava_token=None):
    if strava_token:
        raw = strava_fetch_activites(strava_token, days=180)
        raw_sorted = sorted(raw, key=lambda a: a.get('start_date_local', ''), reverse=True)
        return [strava_format_activite(a) for a in raw_sorted]
    else:
        activites = fetch_activites(180, intervals_key, athlete_id)
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
                "start_date_local": a.get("start_date_local", ""),
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        req_intervals_key = params.get('intervals_key', [None])[0] or DEFAULT_INTERVALS_KEY
        req_athlete_id = params.get('athlete_id', [None])[0] or DEFAULT_ATHLETE_ID
        req_api_key = DEFAULT_API_KEY
        req_activity_id = params.get('activity_id', [None])[0]
        req_strava_token = params.get('strava_token', [None])[0]

        def respond(data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def respond_html(html, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def redirect(url):
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        # ── STRAVA OAuth ──

        if parsed.path == "/strava/auth":
            # Redirige vers la page d'autorisation Strava
            redirect(strava_get_auth_url())

        elif parsed.path == "/strava/callback":
            # Strava redirige ici après autorisation
            code = params.get('code', [None])[0]
            error = params.get('error', [None])[0]

            if error or not code:
                respond_html("<h1>❌ Autorisation refusée</h1><p>Tu peux fermer cette page.</p>")
                return

            try:
                token_data = strava_exchange_code(code)
                access_token = token_data.get('access_token', '')
                refresh_token = token_data.get('refresh_token', '')
                athlete = token_data.get('athlete', {})
                prenom = athlete.get('firstname', 'Sportif')

                # Redirige vers l'app Flutter avec les tokens
                # L'app intercepte cette URL via un deep link
                app_url = f"mysportcoach://strava/callback?access_token={access_token}&refresh_token={refresh_token}&prenom={prenom}"

                respond_html(f"""
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>My Sport Coach — Connexion réussie</title>
                    <style>
                        body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 40px; background: #0A1628; color: white; }}
                        h1 {{ color: #4a9eff; }}
                        p {{ color: #aaa; }}
                        .btn {{ background: #4a9eff; color: white; padding: 16px 32px; border-radius: 12px; text-decoration: none; display: inline-block; margin-top: 20px; font-size: 18px; }}
                    </style>
                    <script>window.location.href = "{app_url}";</script>
                </head>
                <body>
                    <h1>✅ Connexion réussie !</h1>
                    <p>Bonjour {prenom} ! Ton compte Strava est connecté.</p>
                    <p>Retourne dans l'application My Sport Coach.</p>
                    <a href="{app_url}" class="btn">Ouvrir My Sport Coach</a>
                </body>
                </html>
                """)
            except Exception as e:
                respond_html(f"<h1>❌ Erreur</h1><p>{str(e)}</p>")

        # ── API endpoints ──

        elif parsed.path == "/analyse":
            try:
                analyse = get_analyse(req_api_key, req_intervals_key, req_athlete_id, req_activity_id, req_strava_token)
                respond({"analyse": analyse})
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sorties":
            try:
                respond(get_sorties(req_intervals_key, req_athlete_id, req_strava_token))
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path.startswith("/sortie/"):
            try:
                activity_id = parsed.path.split("/sortie/")[1]
                respond(get_detail_sortie(activity_id, req_intervals_key))
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sante":
            try:
                respond(get_sante(req_intervals_key, req_athlete_id))
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        else:
            self.send_response(404); self.end_headers()

    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 8080))
print(f"🚀 Serveur démarré sur le port {port}")
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
