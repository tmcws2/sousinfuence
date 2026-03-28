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
    """Retourne les numéros de scrutins pas encore traités."""
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
    """
    Retourne la liste des thèmes matchés si le titre du scrutin
    contient au moins un mot-clé, sinon liste vide.
    """
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
    """Retourne la fiche HATVP la plus proche ou None."""
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

# Rôles qui indiquent un vrai lien (même passé)
ROLES_SIGNIFICATIFS = [
    "administrateur", "dirigeant", "president", "directeur",
    "gerant", "associe", "membre du conseil", "membre ca",
    "membre du ca", "vice-president", "tresorier",
]

# Rôles à exclure car trop ténus
ROLES_A_EXCLURE = [
    "salarie", "employe", "stagiaire", "technicien",
    "ouvrier", "infirmier", "teleconseiller", "delegue medical",
    "chargé de mission", "charge de mission", "journaliste",
    "presentateur", "ingenieur", "consultant",
]

# Organismes trop communs pour être significatifs seuls
ORGANISMES_EXCLUS_SEUL_SOCIO = [
    "credit agricole", "caisse locale", "caisse regionale",
]


def _role_est_significatif(description):
    """
    Retourne True si le rôle décrit est un mandat dirigeant
    (même passé), False si c est un simple emploi salarié.
    """
    desc = normalize(description or "")
    # Exclure les rôles salariés
    if any(r in desc for r in ROLES_A_EXCLURE):
        return False
    # Garder explicitement les rôles dirigeants (même passés)
    if any(r in desc for r in ROLES_SIGNIFICATIFS):
        return True
    # Par défaut : garder (on préfère les faux positifs aux faux négatifs)
    return True


def _organisme_est_banal(organisme, description):
    """
    Retourne True si l organisme est trop commun pour être signalé
    sans rôle dirigeant (ex: simple sociétaire Crédit Agricole).
    """
    org = normalize(organisme or "")
    desc = normalize(description or "")
    if any(exclu in org for exclu in ORGANISMES_EXCLUS_SEUL_SOCIO):
        # Garder quand même si rôle d administrateur
        if any(r in desc or r in org for r in ["administrateur", "president", "directeur", "conseil d"]):
            return False
        return True
    return False


def scorer_interets(fiche_hatvp, entreprises, themes_scrutin):
    """
    Retourne une liste de signaux trouvés.
    Règles :
    - Garde : participation en cours (administrateur, dirigeant)
    - Garde : participation passée si rôle dirigeant (conflit de gratitude)
    - Retire : ancien salarié, stagiaire, employé
    - Retire : simple sociétaire Crédit Agricole sans rôle dirigeant
    """
    signaux = []
    tous_organismes = set()

    # Collecte tous les organismes surveillés (tous thèmes confondus)
    for theme, orgs in entreprises.items():
        for org in orgs:
            tous_organismes.add(normalize(org))

    # Vérifie les participations
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
                # Signal fort si en cours OU si rôle dirigeant passé
                est_dirigeant = any(r in normalize(desc) for r in ROLES_SIGNIFICATIFS)
                force = "fort" if p.get("en_cours") or est_dirigeant else "faible"
                signaux.append({
                    "force":       force,
                    "type":        p.get("type_bien", "participation"),
                    "organisme":   p.get("organisme", ""),
                    "description": desc,
                })
                break

    # Vérifie les intérêts déclarés
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

    # Dédoublonnage par organisme
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
    """
    Analyse un scrutin et retourne un rapport structuré.
    """
    mots_cles   = load_mots_cles()
    entreprises = load_entreprises()
    hatvp       = load_hatvp()
    deputes     = get_deputes_index()

    scrutin = get_scrutin(numero_scrutin)
    if not scrutin:
        return None

    # Filtre par mots-clés
    themes = scrutin_est_pertinent(scrutin, mots_cles)
    if not themes:
        return None

    # Résolution des noms
    scrutin = resoudre_noms(scrutin, deputes)

    # Croisement
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
                "nom":      v["nom_complet"],
                "groupe":   v["groupe"],
                "position": position,
                "signaux":  signaux,
                "url_hatvp": fiche.get("url_hatvp", ""),
            })

    return {
        "scrutin":  scrutin,
        "themes":   themes,
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

    # Trier : signaux forts en premier, puis par position
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


# ── Génération des posts Bluesky ──────────────────────────────────────────────

def generer_posts(analyse):
    scrutin   = analyse["scrutin"]
    themes    = analyse["themes"]
    resultats = analyse["resultats"]

    if not resultats:
        return []

    posts = []

    # Post d'accroche
    nb_signaux_forts = sum(
        1 for r in resultats
        if any(s["force"] == "fort" for s in r["signaux"])
    )
    resultat_str = "✅ Adopté" if scrutin["adopte"] else "❌ Rejeté"
    titre_court  = scrutin["titre"][:140] + "…" if len(scrutin["titre"]) > 140 else scrutin["titre"]

    accroche = (
        f"🔍 Votes Sous Influence\n\n"
        f"🗳️ Scrutin n°{scrutin['numero']} — {scrutin['date']}\n"
        f"{titre_court}\n"
        f"{resultat_str}\n\n"
        f"{len(resultats)} député(s) avec des intérêts déclarés "
        f"potentiellement liés à ce vote."
    )
    posts.append(accroche)

    # Un post par député (max 8)
    for r in resultats[:8]:
        emoji_vote = {"pour": "👍", "contre": "👎", "abstention": "🫳"}.get(r["position"], "❓")
        signaux_forts   = [s for s in r["signaux"] if s["force"] == "fort"]
        signaux_faibles = [s for s in r["signaux"] if s["force"] == "faible"]

        corps = f"{emoji_vote} {r['nom']} ({r['groupe']})\nVote : {r['position'].upper()}\n\n"

        if signaux_forts:
            corps += "⚠️ Signal fort :\n"
            for s in signaux_forts[:2]:
                corps += f"→ {s['organisme'][:60]}\n"

        if signaux_faibles and len(corps) < 250:
            corps += "~ Signal faible :\n"
            for s in signaux_faibles[:1]:
                corps += f"→ {s['organisme'][:60]}\n"

        posts.append(corps.strip())

    # Post de clôture avec disclaimer
    cloture = (
        f"📊 {len(resultats)} député(s) analysés sur ce scrutin.\n\n"
        f"Ces données proviennent des déclarations d'intérêts "
        f"publiées en open data par la HATVP.\n"
        f"Conformément à l'art. LO.135-2 du code électoral, "
        f"les déclarations de patrimoine ne sont pas divulguées.\n\n"
        f"ℹ️ Ces co-occurrences sont des signaux, pas des conclusions."
    )
    posts.append(cloture)

    return posts


# ── Mode automatique ──────────────────────────────────────────────────────────

def mode_auto(poster=False):
    """Détecte et analyse tous les nouveaux scrutins."""
    nouveaux = detecter_nouveaux_scrutins()
    print(f"[croisement] {len(nouveaux)} nouveaux scrutins à analyser.")

    traites = load_traites()
    analyses_avec_signaux = 0

    for numero in nouveaux:
        print(f"[croisement] Analyse scrutin {numero}...")
        analyse = croiser(numero)

        # Marquer comme traité même si pas de signal
        traites.append(numero)
        save_traites(traites)

        if not analyse:
            continue

        if not analyse["resultats"]:
            continue

        analyses_avec_signaux += 1

        # Sauvegarde du rapport
        RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
        rapport_path = RAPPORTS_DIR / f"scrutin_{numero}.txt"
        rapport_path.write_text(
            formater_rapport(analyse), encoding="utf-8"
        )
        print(f"[croisement] Rapport sauvegardé : {rapport_path}")
        print(formater_rapport(analyse))

        # Publication Bluesky
        if poster:
            publier_bluesky(analyse)

    print(f"[croisement] Terminé — {analyses_avec_signaux} scrutin(s) avec signaux.")


def publier_bluesky(analyse):
    import os
    from atproto import Client

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

    reply_to = None
    for i, texte in enumerate(posts):
        if reply_to:
            response = client.send_post(text=texte, reply_to=reply_to)
        else:
            response = client.send_post(text=texte)
        from atproto_client import models as atmodels
        reply_to = atmodels.AppBskyFeedPost.ReplyRef(
            root=atmodels.create_strong_ref(response),
            parent=atmodels.create_strong_ref(response)
        )
        print(f"[bluesky] Post {i+1}/{len(posts)} publié.")


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
