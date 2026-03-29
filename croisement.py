"""
croisement.py — Votes Sous Influence
Moteur principal : croise les votes AN avec les déclarations d'intérêts HATVP.

Usage :
    python3.11 croisement.py <numero_scrutin>
    python3.11 croisement.py --auto   (détecte et analyse les nouveaux scrutins)
"""

import json
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

from hatvp_loader import load_index as load_hatvp
from an_votes import get_scrutin, get_deputes_index, resoudre_noms

MOTS_CLES_FILE      = Path("mots_cles.json")
ENTREPRISES_FILE    = Path("entreprises_themes.json")
TRAITES_FILE        = Path("scrutins_traites.json")
CACHE_DIR           = Path("cache/scrutins_json/json")
RAPPORTS_DIR        = Path("cache/rapports")
SEUIL_MATCHING      = 0.82


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalize(text):
    nfkd = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    return s.lower().strip()


# ── Chargement des référentiels ───────────────────────────────────────────────

def load_mots_cles():
    return json.loads(MOTS_CLES_FILE.read_text(encoding="utf-8"))


def load_entreprises():
    return json.loads(ENTREPRISES_FILE.read_text(encoding="utf-8"))


def load_traites():
    if not TRAITES_FILE.exists():
        return []
    return json.loads(TRAITES_FILE.read_text()).get("scrutins_traites", [])


def save_traites(liste):
    TRAITES_FILE.write_text(
        json.dumps({"scrutins_traites": liste}, ensure_ascii=False, indent=2)
    )


# ── Détection des nouveaux scrutins ──────────────────────────────────────────

def detecter_nouveaux_scrutins():
    traites = set(load_traites())
    tous = set()
    for path in CACHE_DIR.glob("VTANR5L17V*.json"):
        num = path.stem.replace("VTANR5L17V", "")
        if num.isdigit():
            tous.add(int(num))
    nouveaux = sorted(tous - {int(t) for t in traites if str(t).isdigit()})
    return nouveaux


# ── Filtrage par mots-clés ────────────────────────────────────────────────────

def scrutin_est_pertinent(scrutin, mots_cles):
    titre_norm = normalize(scrutin["titre"])
    themes_matches = []
    for theme, mots in mots_cles.items():
        for mot in mots:
            if normalize(mot) in titre_norm:
                themes_matches.append(theme)
                break
    return themes_matches


# ── Matching flou député ↔ HATVP ──────────────────────────────────────────────

def match_hatvp(nom_normalise, hatvp_index):
    best_score = 0.0
    best_entry = None
    for cle, data in hatvp_index.items():
        score = SequenceMatcher(None, nom_normalise, cle).ratio()
        if score > best_score:
            best_score = score
            best_entry = data
    if best_score >= SEUIL_MATCHING:
        return best_entry
    return None


# ── Scoring des intérêts ──────────────────────────────────────────────────────

ROLES_SIGNIFICATIFS = [
    "administrateur", "dirigeant", "president", "directeur",
    "gerant", "associe", "membre du conseil", "membre ca",
    "membre du ca", "vice-president", "tresorier",
]

ROLES_A_EXCLURE = [
    "salarie", "employe", "stagiaire", "technicien",
    "ouvrier", "infirmier", "teleconseiller", "delegue medical",
    "chargé de mission", "charge de mission", "journaliste",
    "presentateur", "ingenieur", "consultant",
]

ORGANISMES_EXCLUS_SEUL_SOCIO = [
    "credit agricole", "caisse locale", "caisse regionale",
]


def _role_est_significatif(description):
    desc = normalize(description or "")
    if any(r in desc for r in ROLES_A_EXCLURE):
        return False
    if any(r in desc for r in ROLES_SIGNIFICATIFS):
        return True
    return True


def _organisme_est_banal(organisme, description):
    org = normalize(organisme or "")
    desc = normalize(description or "")
    if any(exclu in org for exclu in ORGANISMES_EXCLUS_SEUL_SOCIO):
        if any(r in desc or r in org for r in ["administrateur", "president", "directeur", "conseil d"]):
            return False
        return True
    return False


def scorer_interets(fiche_hatvp, entreprises, themes_scrutin):
    signaux = []
    tous_organismes = set()

    for theme, orgs in entreprises.items():
        for org in orgs:
            tous_organismes.add(normalize(org))

    for p in fiche_hatvp.get("patrimoine", []):
        org = normalize(p.get("organisme", ""))
        desc = p.get("libelle", "") or ""
        if not org:
            continue
        if not _role_est_significatif(desc):
            continue
        if _organisme_est_banal(p.get("organisme", ""), desc):
            continue
        for org_surveille in tous_organismes:
            if org_surveille in org or org in org_surveille:
                est_dirigeant = any(r in normalize(desc) for r in ROLES_SIGNIFICATIFS)
                force = "fort" if p.get("en_cours") or est_dirigeant else "faible"
                signaux.append({
                    "force":       force,
                    "type":        p.get("type_bien", "participation"),
                    "organisme":   p.get("organisme", ""),
                    "description": desc,
                })
                break

    for i in fiche_hatvp.get("interets", []):
        org_raw = i.get("organisme", "") or i.get("description", "")
        desc    = i.get("description", "") or i.get("categorie", "") or ""
        org     = normalize(org_raw)
        if not org:
            continue
        if not _role_est_significatif(desc):
            continue
        if _organisme_est_banal(org_raw, desc):
            continue
        for org_surveille in tous_organismes:
            if org_surveille in org or org in org_surveille:
                est_dirigeant = any(r in normalize(desc) for r in ROLES_SIGNIFICATIFS)
                force = "fort" if i.get("en_cours") or est_dirigeant else "faible"
                signaux.append({
                    "force":       force,
                    "type":        i.get("type", "interet"),
                    "organisme":   org_raw,
                    "description": desc,
                })
                break

    vus = set()
    uniques = []
    for s in signaux:
        cle = normalize(s["organisme"])
        if cle not in vus:
            vus.add(cle)
            uniques.append(s)

    return uniques


# ── Croisement principal ──────────────────────────────────────────────────────

def croiser(numero_scrutin):
    mots_cles   = load_mots_cles()
    entreprises = load_entreprises()
    hatvp       = load_hatvp()
    deputes     = get_deputes_index()

    scrutin = get_scrutin(numero_scrutin)
    if not scrutin:
        return None

    themes = scrutin_est_pertinent(scrutin, mots_cles)
    if not themes:
        return None

    scrutin = resoudre_noms(scrutin, deputes)

    resultats = []
    for position, votants in scrutin["votants"].items():
        if position == "nonVotant":
            continue
        for v in votants:
            nom_normalise = v.get("nom_normalise", "")
            if not nom_normalise:
                continue
            fiche = match_hatvp(nom_normalise, hatvp)
            if not fiche:
                continue
            signaux = scorer_interets(fiche, entreprises, themes)
            if not signaux:
                continue
            resultats.append({
                "nom":            v["nom_complet"],
                "groupe":         v["groupe"],
                "circonscription": v.get("circonscription", ""),
                "position":       position,
                "signaux":        signaux,
                "url_hatvp":      fiche.get("url_hatvp", ""),
            })

    return {
        "scrutin":   scrutin,
        "themes":    themes,
        "resultats": resultats,
    }


# ── Formatage du rapport texte ────────────────────────────────────────────────

def formater_rapport(analyse):
    scrutin   = analyse["scrutin"]
    themes    = analyse["themes"]
    resultats = analyse["resultats"]

    lignes = []
    lignes.append("=" * 70)
    lignes.append(f"SCRUTIN n°{scrutin['numero']} — {scrutin['date']}")
    lignes.append(scrutin["titre"])
    lignes.append("Résultat : " + ("ADOPTÉ" if scrutin["adopte"] else "REJETÉ"))
    lignes.append("Thèmes   : " + ", ".join(themes))
    lignes.append("=" * 70)

    if not resultats:
        lignes.append("\nAucun signal détecté.")
        return "\n".join(lignes)

    resultats_tries = sorted(
        resultats,
        key=lambda r: (
            0 if any(s["force"] == "fort" for s in r["signaux"]) else 1,
            r["position"]
        )
    )

    for r in resultats_tries:
        emoji = {"pour": "POUR", "contre": "CONTRE", "abstention": "ABSTENTION"}.get(r["position"], r["position"])
        lignes.append(f"\n{r['nom']} ({r['groupe']}) — {emoji}")
        for s in r["signaux"]:
            force_label = "[FORT]" if s["force"] == "fort" else "[faible]"
            lignes.append(f"  {force_label} {s['organisme']} — {s['description'][:80]}")

    lignes.append("\n" + "-" * 70)
    lignes.append("Source : HATVP open data (déclarations d'intérêts)")
    lignes.append("Conformément à l'art. LO.135-2 du code électoral,")
    lignes.append("les déclarations de patrimoine ne sont pas divulguées.")

    return "\n".join(lignes)


# ── Résumé GPT ────────────────────────────────────────────────────────────────

def resumer_texte_gpt(titre, themes):
    import os
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        themes_str = ", ".join(themes)
        prompt = (
            "Tu es un assistant specialise en droit parlementaire francais. "
            "Resume en 2 phrases ce texte vote a l'Assemblee nationale : "
            "ses enjeux et ses consequences concretes pour les citoyens. "
            "Sois factuel, neutre, et termine toujours tes phrases. "
            "Ne commence pas par Ce texte.\n\n"
            "Titre : " + titre + "\n"
            "Themes : " + themes_str
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[openai] Erreur : {e}")
        return ""


# ── Génération des posts Bluesky ──────────────────────────────────────────────

HASHTAGS_GROUPES = {
    "rassemblement national": "#RN",
    "ensemble pour la république": "#EPR",
    "la france insoumise": "#LFI",
    "socialistes et apparentés": "#PS",
    "droite républicaine": "#DR",
    "les démocrates": "#Démocrates",
    "horizons & indépendants": "#Horizons",
    "horizons et indépendants": "#Horizons",
    "libertés, indépendants, outre-mer et territoires": "#LIOT",
    "union des droites pour la république": "#UDR",
    "écologiste et social": "#EcoSocial",
    "gauche démocrate et républicaine": "#GDR",
    "non inscrit": "#NI",
}

TYPE_LABELS = {
    "participation_financiere": "actionnaire",
    "participation_dirigeant": "",
    "participation": "",
    "interet": "",
}


def compter_graphemes(texte):
    """Compte les graphèmes Bluesky (approximation : 1 char = 1 graphème)."""
    return len(texte)


def tronquer_post(texte, max_g=295):
    """Tronque un post à max_g graphèmes en finissant proprement la phrase."""
    if compter_graphemes(texte) <= max_g:
        return texte
    coupe = texte[:max_g]
    # Tente de finir sur une fin de phrase
    for sep in [".", "!", "?"]:
        idx = coupe.rfind(sep)
        if idx > int(max_g * 0.5):
            return coupe[:idx + 1]
    # Sinon coupe sur un saut de ligne
    idx = coupe.rfind("\n")
    if idx > int(max_g * 0.5):
        return coupe[:idx]
    # Sinon coupe sur un espace
    idx = coupe.rfind(" ")
    if idx > 0:
        return coupe[:idx] + "…"
    return coupe + "…"


def generer_posts(analyse):
    scrutin   = analyse["scrutin"]
    themes    = analyse["themes"]
    resultats = analyse["resultats"]

    if not resultats:
        return []

    posts = []

    # POST 1 : accroche (titre court + lien)
    resultat_str = "✅ Adopté" if scrutin["adopte"] else "❌ Rejeté"
    # Titre court : max 120 chars pour laisser de la place au reste
    titre = scrutin["titre"]
    titre_court = titre[:117] + "…" if len(titre) > 120 else titre
    lien_an = f"https://www.assemblee-nationale.fr/dyn/17/scrutins/{scrutin['numero']}"

    accroche = (
        f"🔍 Votes Sous Influence\n\n"
        f"🗳️ Scrutin n°{scrutin['numero']} — {scrutin['date']}\n"
        f"{resultat_str} | Vote en séance publique\n\n"
        f"👇 {len(resultats)} député(s) avec des intérêts déclarés potentiellement liés à ce vote."
    )
    posts.append(accroche)

    # POST 2 : titre + lien (post séparé pour ne pas tronquer le lien)
    post_lien = f"📋 {titre_court}\n\n🔗 {lien_an}"
    posts.append(post_lien)

    # POST 2 : résumé GPT
    resume = resumer_texte_gpt(scrutin["titre"], themes)
    if resume:
        post_resume = f"📖 Le texte en bref :\n\n{resume}"
        posts.append(post_resume)

    # POST 3+ : un post par député (max 8)
    for r in resultats[:8]:
        groupe_lower = r["groupe"].lower()
        hashtag = HASHTAGS_GROUPES.get(groupe_lower, "")
        emoji_vote = {"pour": "👍", "contre": "👎", "abstention": "🫳"}.get(r["position"], "❓")
        position_label = {
            "pour": "POUR ✅",
            "contre": "CONTRE ❌",
            "abstention": "ABSTENTION 🫳"
        }.get(r["position"], r["position"].upper())

        circo = r.get("circonscription", "")
        corps = f"{emoji_vote} {r['nom']}, Député·e {hashtag}\n"
        if circo:
            corps += f"📍 {circo}\n"
        corps += f"Vote : {position_label}\n\n"

        signaux_forts   = [s for s in r["signaux"] if s["force"] == "fort"]
        signaux_faibles = [s for s in r["signaux"] if s["force"] == "faible"]

        if signaux_forts:
            corps += "⚠️ Intérêts déclarés liés à ce vote :\n"
            for s in signaux_forts[:4]:
                org = s["organisme"][:50]
                desc = s.get("description", "").strip()
                type_bien = s.get("type", s.get("type_bien", ""))
                label = TYPE_LABELS.get(type_bien, "")
                if desc:
                    corps += f"→ {org} — {desc[:40]}\n"
                elif label:
                    corps += f"→ {org} — {label}\n"
                else:
                    corps += f"→ {org}\n"

        if signaux_faibles and compter_graphemes(corps) < 240:
            for s in signaux_faibles[:1]:
                org = s["organisme"][:50]
                desc = s.get("description", "").strip()
                corps += f"~ {org}"
                if desc:
                    corps += f" — {desc[:30]}"
                corps += "\n"

        posts.append(corps.strip())

    # POST final : disclaimer
    cloture = (
        f"📊 {len(resultats)} député(s) analysés sur ce scrutin.\n\n"
        "Source : déclarations d'intérêts HATVP (open data).\n"
        "⚖️ Art. LO.135-2 du code électoral : les déclarations de patrimoine ne sont pas divulguées.\n\n"
        "ℹ️ Ces co-occurrences sont des signaux à investiguer, pas des conclusions."
    )
    posts.append(cloture)

    return posts


# ── Mode automatique ──────────────────────────────────────────────────────────

def mode_auto(poster=False):
    nouveaux = detecter_nouveaux_scrutins()
    print(f"[croisement] {len(nouveaux)} nouveaux scrutins à analyser.")

    traites = load_traites()
    analyses_avec_signaux = 0

    for numero in nouveaux:
        print(f"[croisement] Analyse scrutin {numero}...")
        analyse = croiser(numero)

        traites.append(numero)
        save_traites(traites)

        if not analyse:
            continue
        if not analyse["resultats"]:
            continue

        analyses_avec_signaux += 1

        RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
        rapport_path = RAPPORTS_DIR / f"scrutin_{numero}.txt"
        rapport_path.write_text(formater_rapport(analyse), encoding="utf-8")
        print(f"[croisement] Rapport sauvegardé : {rapport_path}")
        print(formater_rapport(analyse))

        if poster:
            publier_bluesky(analyse)

    print(f"[croisement] Terminé — {analyses_avec_signaux} scrutin(s) avec signaux.")


# ── Publication Bluesky ───────────────────────────────────────────────────────

def publier_bluesky(analyse):
    import os
    from atproto import Client
    from atproto_client import models as atmodels

    handle   = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not handle or not password:
        print("[bluesky] BSKY_HANDLE ou BSKY_PASSWORD manquant.")
        return

    posts = generer_posts(analyse)
    if not posts:
        return

    client = Client()
    client.login(handle, password)

    root_ref  = None
    reply_to  = None

    for i, texte in enumerate(posts):
        texte = tronquer_post(texte)
        if reply_to:
            response = client.send_post(text=texte, reply_to=reply_to)
        else:
            response = client.send_post(text=texte)
            root_ref = atmodels.create_strong_ref(response)

        reply_to = atmodels.AppBskyFeedPost.ReplyRef(
            root=root_ref,
            parent=atmodels.create_strong_ref(response)
        )
        print(f"[bluesky] Post {i+1}/{len(posts)} publié.")
        import time
        time.sleep(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    args   = sys.argv[1:]
    poster = "--post" in args
    args   = [a for a in args if not a.startswith("--")]

    if "--auto" in sys.argv:
        mode_auto(poster=poster)
    elif args:
        numero  = int(args[0])
        analyse = croiser(numero)
        if not analyse:
            print(f"Scrutin {numero} non pertinent ou introuvable.")
        else:
            print(formater_rapport(analyse))
            if poster:
                publier_bluesky(analyse)
    else:
        print("Usage :")
        print("  python3.11 croisement.py <numero>        # analyse un scrutin")
        print("  python3.11 croisement.py <numero> --post # analyse + publie")
        print("  python3.11 croisement.py --auto          # tous les nouveaux")
        print("  python3.11 croisement.py --auto --post   # tous + publie")
