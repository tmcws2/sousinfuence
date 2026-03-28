import json
import time
import re
from pathlib import Path
import requests

CACHE_DIR    = Path("cache/scrutins_json/json")
CACHE_INDEX  = Path("cache/deputes_index.json")
AN_URL       = "https://www.assemblee-nationale.fr/dyn/deputes/{ref}"


def collecter_refs():
    refs = set()
    for path in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            scrutin = data.get("scrutin", {})
            groupes = (
                scrutin.get("ventilationVotes", {})
                .get("organe", {})
                .get("groupes", {})
                .get("groupe", [])
            )
            if isinstance(groupes, dict):
                groupes = [groupes]
            for g in groupes:
                decompte = g.get("vote", {}).get("decompteNominatif", {})
                for cle in ["pours", "contres", "abstentions", "nonVotants"]:
                    bloc = decompte.get(cle) or {}
                    votants = bloc.get("votant", [])
                    if isinstance(votants, dict):
                        votants = [votants]
                    for v in votants:
                        ref = v.get("acteurRef", "")
                        if ref:
                            refs.add(ref)
        except Exception:
            continue
    return refs


def scraper_depute(ref):
    url = AN_URL.format(ref=ref)
    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        return None
    m = re.search(r'<meta name="description" content="([^"]+)"', resp.text)
    if not m:
        return None
    desc = m.group(1)
    parts = desc.split(" - ")
    if not parts:
        return None
    nom_complet = parts[0].strip()
    for civ in ["M. ", "Mme ", "M ", "Mme"]:
        nom_complet = nom_complet.replace(civ, "").strip()
    groupe = ""
    for part in parts:
        if "groupe" in part.lower():
            groupe = part.lower().replace("député du groupe", "").replace("députée du groupe", "").strip().rstrip(" .")
    return {"nom_complet": nom_complet, "groupe": groupe}


def build_index():
    refs = collecter_refs()
    print(f"[an] {len(refs)} acteurRef collectés depuis les scrutins.")

    index = {}
    if CACHE_INDEX.exists():
        index = json.loads(CACHE_INDEX.read_text())
        print(f"[an] {len(index)} déjà en cache.")

    manquants = [r for r in refs if r not in index]
    print(f"[an] {len(manquants)} à télécharger...")

    for i, ref in enumerate(manquants):
        try:
            result = scraper_depute(ref)
            if result:
                index[ref] = result
        except Exception as e:
            print(f"  Erreur {ref}: {e}")

        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(manquants)}...")
            CACHE_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2))

        time.sleep(0.3)

    CACHE_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(f"[an] Annuaire sauvegardé : {len(index)} députés.")
    return index


if __name__ == "__main__":
    index = build_index()
    # Vérification rapide
    exemples = list(index.items())[:3]
    for ref, info in exemples:
        print(f"  {ref} -> {info['nom_complet']} ({info['groupe']})")
