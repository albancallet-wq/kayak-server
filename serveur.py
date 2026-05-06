from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import anthropic
import os
import base64
import tempfile
import cv2
import numpy as np
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

# ============ ANALYSE VIDEO — OPTICAL FLOW + CLAUDE VISION ============

def extraire_frames_intelligentes(video_path, nb_frames=4):
    """
    Extrait les frames les plus pertinentes via Optical Flow.
    On cherche les moments avec le plus de mouvement significatif
    — idéal pour capturer les moments clés d'un geste sportif.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("Impossible d'ouvrir la vidéo")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0

    frames_data = []  # (index, frame, score_mouvement)

    ret, prev_frame = cap.read()
    if not ret:
        raise ValueError("Vidéo vide")

    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    frame_idx = 1

    # Calcul du score de mouvement pour chaque frame via Optical Flow
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Optical Flow de Farneback — calcule le mouvement entre 2 frames
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0
        )

        # Score = magnitude moyenne du flux
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        score = float(np.mean(magnitude))

        frames_data.append((frame_idx, frame.copy(), score))
        prev_gray = gray
        frame_idx += 1

    cap.release()

    if not frames_data:
        raise ValueError("Pas de frames analysables")

    # Stratégie de sélection : on divise la vidéo en segments
    # et on prend la frame avec le score max dans chaque segment.
    # Ça garantit une couverture temporelle ET les moments clés.
    segment_size = len(frames_data) // nb_frames
    selected_frames = []

    for i in range(nb_frames):
        start = i * segment_size
        end = start + segment_size if i < nb_frames - 1 else len(frames_data)
        segment = frames_data[start:end]
        if segment:
            # Frame avec le plus de mouvement dans ce segment
            best = max(segment, key=lambda x: x[2])
            selected_frames.append(best)

    return selected_frames, duration

def frame_to_base64(frame):
    """Convertit une frame OpenCV en JPEG base64"""
    # Resize pour optimiser les tokens (max 800px sur le grand côté)
    h, w = frame.shape[:2]
    max_size = 800
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buffer).decode('utf-8')

def analyser_video_claude(video_bytes, api_key=None):
    """
    Analyse biomécanique complète via Optical Flow + Claude Vision.
    - Extrait les frames clés via Optical Flow
    - Envoie les frames + données de mouvement à Claude
    - Retourne une analyse coaching détaillée
    """
    api_key = api_key or DEFAULT_API_KEY

    # Sauvegarde temporaire de la vidéo
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    try:
        # Extraction des frames intelligentes
        selected_frames, duration = extraire_frames_intelligentes(tmp_path, nb_frames=4)

        # Préparation du contexte mouvement pour Claude
        scores = [f[2] for f in selected_frames]
        score_max = max(scores) if scores else 1
        scores_normalises = [round(s / score_max * 100) for s in scores]

        contexte_mouvement = f"Vidéo de {round(duration, 1)}s analysée. "
        contexte_mouvement += "Intensité du mouvement par frame sélectionnée : "
        for i, score in enumerate(scores_normalises):
            contexte_mouvement += f"Frame {i+1}: {score}% "

        # Construction du message multimodal pour Claude
        # Images d'abord (meilleures performances), texte ensuite
        content = []

        # Ajout des frames comme images
        for i, (idx, frame, score) in enumerate(selected_frames):
            b64 = frame_to_base64(frame)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64
                }
            })

        # Prompt coaching
        content.append({
            "type": "text",
            "text": f"""Tu es un coach sportif expert en biomécanique et analyse du mouvement.

Ces {len(selected_frames)} images sont des frames clés extraites d'une vidéo sportive de {round(duration, 1)} secondes, sélectionnées aux moments de mouvement le plus significatif via analyse Optical Flow.

{contexte_mouvement}

Analyse ces frames et fournis un coaching technique détaillé :

## 🏃 Sport et contexte
(identifie le sport et la situation)

## 📐 Analyse biomécanique
(posture, alignement, position des segments corporels — sois précis avec les angles et les positions)

## ✅ Points forts
(ce qui est bien exécuté)

## ⚠️ Axes d'amélioration
(max 3 points concrets avec explication biomécanique)

## 💡 Exercices correctifs
(exercices spécifiques pour corriger les points faibles)

## 📊 Score technique estimé
(note sur 10 avec justification)

Réponds en français, de façon précise et encourageante. Max 500 mots."""
        })

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}]
        )

        return message.content[0].text

    finally:
        # Nettoyage du fichier temporaire
        try:
            os.unlink(tmp_path)
        except:
            pass

# ============ STRAVA OAUTH ============

def strava_get_auth_url():
    params = {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": f"{SERVER_URL}/strava/callback",
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    return f"https://www.strava.com/oauth/authorize?{urlencode(params)}"

def strava_exchange_code(code):
    response = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    })
    return response.json()

def strava_get_valid_token(access_token, refresh_token):
    if not access_token:
        return None, None
    test = requests.get("https://www.strava.com/api/v3/athlete", headers={"Authorization": f"Bearer {access_token}"})
    if test.status_code == 200:
        return access_token, None
    if refresh_token:
        data = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).json()
        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if new_access:
            return new_access, new_refresh
    return None, None

def strava_fetch_activites(access_token, days=180):
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"after": after, "per_page": 100}
    response = requests.get(url, headers=headers, params=params)
    return response.json()

def strava_format_activite(a):
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

def get_analyse(api_key=None, intervals_key=None, athlete_id=None, activity_id=None, strava_token=None, contexte=None):
    api_key = api_key or DEFAULT_API_KEY
    if strava_token:
        raw = strava_fetch_activites(strava_token, days=180)
        activites = sorted(raw, key=lambda a: a.get('start_date_local', ''), reverse=True)
    else:
        activites = fetch_activites(180, intervals_key, athlete_id)
        activites = sorted(activites, key=lambda a: a.get('start_date_local', ''), reverse=True)

    if not activites:
        return "Aucune activité trouvée dans les 6 derniers mois."

    if activity_id:
        cible = next((a for a in activites if str(a.get('id', '')) == str(activity_id)), None)
        derniere = cible if cible else activites[0]
        autres = [a for a in activites if str(a.get('id', '')) != str(derniere.get('id', ''))]
    else:
        derniere = activites[0]
        autres = activites[1:]

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
- {zone_desc}"""

    if contexte and contexte.strip():
        prompt += f"\n\n**CONTEXTE DE L'ATHLÈTE**\n{contexte}\n\n⚠️ Intègre ce contexte dans ton analyse."

    prompt += "\n\nRédige un debriefing en français :\n\n## 📊 Ta séance en bref\n## 💪 Intensité et zone d'effort\n## 📈 Par rapport à tes habitudes\n## 🔄 Progression\n## 🎯 Conseil pour la prochaine séance\n\nPrécis, bienveillant, motivant. Max 450 mots."

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
        req_strava_refresh = params.get('strava_refresh', [None])[0]
        req_contexte = params.get('contexte', [None])[0]

        new_strava_token = None
        new_strava_refresh = None
        if req_strava_token and req_strava_refresh:
            valid_token, refreshed = strava_get_valid_token(req_strava_token, req_strava_refresh)
            if valid_token:
                req_strava_token = valid_token
                if refreshed:
                    new_strava_token = valid_token
                    new_strava_refresh = refreshed

        def respond(data, status=200):
            if new_strava_token and isinstance(data, dict):
                data['new_strava_token'] = new_strava_token
                data['new_strava_refresh'] = new_strava_refresh
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

        if parsed.path == "/strava/auth":
            redirect(strava_get_auth_url())

        elif parsed.path == "/strava/callback":
            code = params.get('code', [None])[0]
            error = params.get('error', [None])[0]
            if error or not code:
                respond_html("<h1>❌ Autorisation refusée</h1>")
                return
            try:
                token_data = strava_exchange_code(code)
                access_token = token_data.get('access_token', '')
                refresh_token = token_data.get('refresh_token', '')
                athlete = token_data.get('athlete', {})
                prenom = athlete.get('firstname', 'Sportif')
                app_url = f"mysportcoach://strava/callback?access_token={access_token}&refresh_token={refresh_token}&prenom={prenom}"
                respond_html(f"""<html>
                <head><meta charset="UTF-8"><title>My Sport Coach</title>
                <style>body{{font-family:-apple-system,sans-serif;text-align:center;padding:40px;background:#0A1628;color:white}}h1{{color:#4a9eff}}.btn{{background:#4a9eff;color:white;padding:16px 32px;border-radius:12px;text-decoration:none;display:inline-block;margin-top:20px;font-size:18px}}</style>
                <script>window.location.href="{app_url}";</script></head>
                <body><h1>✅ Connexion réussie !</h1><p>Bonjour {prenom} !</p><a href="{app_url}" class="btn">Ouvrir My Sport Coach</a></body></html>""")
            except Exception as e:
                respond_html(f"<h1>❌ Erreur</h1><p>{str(e)}</p>")

        elif parsed.path == "/analyse":
            try:
                analyse = get_analyse(req_api_key, req_intervals_key, req_athlete_id, req_activity_id, req_strava_token, req_contexte)
                respond({"analyse": analyse})
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sorties":
            try:
                sorties = get_sorties(req_intervals_key, req_athlete_id, req_strava_token)
                if new_strava_token:
                    respond({"items": sorties, "new_strava_token": new_strava_token, "new_strava_refresh": new_strava_refresh})
                else:
                    respond(sorties)
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        elif parsed.path == "/sante":
            try:
                respond(get_sante(req_intervals_key, req_athlete_id))
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode())

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        """Endpoint POST pour l'analyse vidéo approfondie"""
        parsed = urlparse(self.path)

        if parsed.path == "/analyse-video":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                video_bytes = self.rfile.read(content_length)

                analyse = analyser_video_claude(video_bytes, DEFAULT_API_KEY)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"analyse": analyse}).encode())

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"erreur": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        """CORS preflight"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass

port = int(os.environ.get("PORT", 8080))
print(f"🚀 Serveur démarré sur le port {port}")
HTTPServer(("0.0.0.0", port), Handler).serve_forever()
