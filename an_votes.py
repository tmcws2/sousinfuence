import json
import unicodedata
from pathlib import Path

CACHE_DIR     = Path("cache/scrutins_json/json")
CACHE_DEPUTES = Path("cache/deputes_index.json")


def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = s.lower()
    for ch in "-'`":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def get_deputes_index():
    if not CACHE_DEPUTES.exists():
        print("[an] Index manquant — lance d'abord build_deputes_index.py")
        return {}
    return json.loads(CACHE_DEPUTES.read_text(encoding="utf-8"))


def get_scrutin(numero):
    path = CACHE_DIR / f"VTANR5L17V{numero}.json"
    if not path.exists():
        print(f"[an] Scrutin {numero} introuvable.")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _parse_scrutin(data, numero)


def _parse_scrutin(data, numero):
    scrutin = data.get("scrutin", data)
    titre  = scrutin.get("titre", "") or f"Scrutin {numero}"
    date   = scrutin.get("dateScrutin", "")
    sort   = scrutin.get("sort", {})
    code   = sort.get("code", "") if isinstance(sort, dict) else str(sort)
    adopte = "adopt" in code.lower()

    votants  = {"pour": [], "contre": [], "abstention": [], "nonVotant": []}
    map_cles = {
        "pours":       "pour",
        "contres":     "contre",
        "abstentions": "abstention",
        "nonVotants":  "nonVotant",
    }

    groupes = (
        scrutin
        .get("ventilationVotes", {})
        .get("organe", {})
        .get("groupes", {})
        .get("groupe", [])
    )
    if isinstance(groupes, dict):
        groupes = [groupes]

    for groupe in groupes:
        organe_ref = groupe.get("organeRef", "")
        decompte   = groupe.get("vote", {}).get("decompteNominatif", {})
        if not decompte:
            continue
        for cle_json, cle_norm in map_cles.items():
            bloc  = decompte.get(cle_json) or {}
            liste = bloc.get("votant", [])
            if isinstance(liste, dict):
                liste = [liste]
            for v in liste:
                ref = v.get("acteurRef", "")
                if ref:
                    votants[cle_norm].append({
                        "acteurRef": ref,
                        "organeRef": organe_ref,
                    })

    return {
        "numero":  numero,
        "titre":   titre,
        "date":    date,
        "adopte":  adopte,
        "votants": votants,
    }


def resoudre_noms(scrutin, deputes_index):
    for position, liste in scrutin["votants"].items():
        for v in liste:
            ref  = v["acteurRef"]
            info = deputes_index.get(ref, {})
            v["nom_complet"]   = info.get("nom_complet", ref)
            v["groupe"]        = info.get("groupe", "")
            v["nom_normalise"] = normalize_name(info.get("nom_complet", ""))
    return scrutin


def stats_scrutin(scrutin):
    print(f"\n-- Scrutin n°{scrutin['numero']} ---")
    print(f"  Titre   : {scrutin['titre'][:80]}")
    print(f"  Date    : {scrutin['date']}")
    print(f"  Resultat: {'ADOPTE' if scrutin['adopte'] else 'REJETE'}")
    for pos, lst in scrutin["votants"].items():
        print(f"  {pos:12} : {len(lst)}")
    print()


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage : python3.11 an_votes.py <numero_scrutin>")
        sys.exit(0)
    deputes = get_deputes_index()
    scrutin = get_scrutin(int(args[0]))
    if scrutin:
        scrutin = resoudre_noms(scrutin, deputes)
        stats_scrutin(scrutin)
        print("Exemples de votants (pour) :")
        for v in scrutin["votants"]["pour"][:5]:
            print(f"  {v['nom_complet']} ({v['groupe']})")
