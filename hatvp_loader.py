import json, time, unicodedata, xml.etree.ElementTree as ET
from pathlib import Path
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

HATVP_XML_URL = "https://www.hatvp.fr/livraison/merge/declarations.xml"
CACHE_XML     = Path("cache/hatvp_declarations.xml")
CACHE_INDEX   = Path("cache/hatvp_index.json")
CACHE_TTL_H   = 24

def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = s.lower()
    for ch in "-'`":
        s = s.replace(ch, " ")
    return " ".join(s.split())

def download_hatvp(force=False):
    CACHE_XML.parent.mkdir(parents=True, exist_ok=True)
    if not force and CACHE_XML.exists():
        age_h = (time.time() - CACHE_XML.stat().st_mtime) / 3600
        if age_h < CACHE_TTL_H:
            print(f"[hatvp] Cache valide ({age_h:.1f}h).")
            return CACHE_XML
    print("[hatvp] Téléchargement…")
    resp = requests.get(HATVP_XML_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with open(CACHE_XML, "wb") as f:
        for chunk in resp.iter_content(65536):
            f.write(chunk)
    print(f"[hatvp] Sauvegardé ({CACHE_XML.stat().st_size/1e6:.1f} Mo)")
    return CACHE_XML

def _find_text(el, tag):
    found = el.find(f".//{tag}")
    if found is not None and found.text and found.text.strip():
        return found.text.strip()
    return ""

def _est_parlementaire(qualite):
    q = normalize_name(qualite)
    return any(kw in q for kw in ["depute", "senateur", "senatrice", "deputee"])

def _parse_interets(declaration):
    interets = []
    for bloc in declaration.findall(".//activiteAnnexe"):
        organisme   = _find_text(bloc, "nomSociete") or _find_text(bloc, "nomOrganisme") or _find_text(bloc, "organisme")
        description = _find_text(bloc, "activite") or _find_text(bloc, "description")
        date_fin    = _find_text(bloc, "dateFin")
        if not organisme and not description:
            continue
        interets.append({
            "type": "activite_annexe",
            "organisme": organisme,
            "description": description,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin),
        })
    for bloc in declaration.findall(".//participationOrg"):
        organisme   = _find_text(bloc, "nomSociete") or _find_text(bloc, "nomOrganisme")
        description = _find_text(bloc, "activite") or _find_text(bloc, "typeParticipation")
        date_fin    = _find_text(bloc, "dateFin")
        if not organisme:
            continue
        interets.append({
            "type": "participation",
            "organisme": organisme,
            "description": description,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin),
        })
    for bloc in declaration.findall(".//mandatElectif") + declaration.findall(".//autreMandat"):
        description = _find_text(bloc, "descriptionMandat") or _find_text(bloc, "description")
        organisme   = _find_text(bloc, "organisme") or _find_text(bloc, "nomOrganisme")
        date_fin    = _find_text(bloc, "dateFin")
        if not description and not organisme:
            continue
        interets.append({
            "type": "mandat",
            "organisme": organisme,
            "description": description,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin),
        })
    for bloc in declaration.findall(".//activProfCinqDerniereDto//items"):
        organisme   = _find_text(bloc, "employeur")
        description = _find_text(bloc, "description")
        date_fin    = _find_text(bloc, "dateFin")
        if not organisme and not description:
            continue
        interets.append({
            "type": "activite_pro",
            "organisme": organisme,
            "description": description,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin),
        })
    return interets

def _parse_patrimoine(declaration):
    """
    Extrait les participations dans des sociétés/organismes.
    Le XML HATVP ne publie pas les actions détenues en données structurées
    (disponibles uniquement en PDF). En revanche participationDirigeantDto
    et participationFinanciereDto contiennent les rôles dans des organismes
    (administrateur, membre du CA, associé...) — signal encore plus fort.
    """
    valeurs = []

    # Participations en tant que dirigeant / administrateur
    for bloc in declaration.findall(".//participationDirigeantDto//items"):
        organisme = _find_text(bloc, "nomSociete") or _find_text(bloc, "nomOrganisme")
        activite  = _find_text(bloc, "activite") or _find_text(bloc, "descriptionActivite")
        date_debut= _find_text(bloc, "dateDebut")
        date_fin  = _find_text(bloc, "dateFin")
        conservee = _find_text(bloc, "conservee")
        if not organisme:
            continue
        valeurs.append({
            "type_bien": "participation_dirigeant",
            "libelle": activite,
            "organisme": organisme,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin) or conservee == "true",
        })

    # Participations financières (parts sociales, associé...)
    for bloc in declaration.findall(".//participationFinanciereDto//items"):
        organisme = _find_text(bloc, "nomSociete") or _find_text(bloc, "nomOrganisme")
        activite  = _find_text(bloc, "activite") or _find_text(bloc, "typeParticipation")
        date_debut= _find_text(bloc, "dateDebut")
        date_fin  = _find_text(bloc, "dateFin")
        if not organisme:
            continue
        valeurs.append({
            "type_bien": "participation_financiere",
            "libelle": activite,
            "organisme": organisme,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "en_cours": not bool(date_fin),
        })

    return valeurs

def parse_hatvp(xml_path):
    print(f"[hatvp] Parsing {xml_path}…")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    index = {}
    total = retenus = 0
    for declaration in root.findall(".//declaration"):
        total += 1
        declarant = declaration.find(".//declarant")
        if declarant is None:
            continue
        nom    = _find_text(declarant, "nom")
        prenom = _find_text(declarant, "prenom")
        if not nom:
            continue
        qualite = _find_text(declaration, "qualiteDeclarantForPDF") or _find_text(declaration, "qualiteDeclarant")
        if not _est_parlementaire(qualite):
            continue
        url        = _find_text(declarant, "urlProfilDeclarant")
        interets   = _parse_interets(declaration)
        patrimoine = _parse_patrimoine(declaration)
        cle = normalize_name(f"{prenom} {nom}")
        if cle in index:
            index[cle]["interets"]   += interets
            index[cle]["patrimoine"] += patrimoine
        else:
            index[cle] = {
                "nom": nom, "prenom": prenom, "qualite": qualite,
                "url_hatvp": url, "interets": interets, "patrimoine": patrimoine,
            }
            retenus += 1
    print(f"[hatvp] {total} déclarations, {retenus} parlementaires retenus.")
    return index

def save_index(index, path=CACHE_INDEX):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"[hatvp] Index sauvegardé ({len(index)} entrées)")

def load_index(path=CACHE_INDEX):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_index(force=False):
    xml_path = download_hatvp(force=force)
    index = parse_hatvp(xml_path)
    save_index(index)
    return index

def stats(index):
    print(f"\n── Stats HATVP ────────────────────────────────────")
    print(f"  Parlementaires     : {len(index)}")
    print(f"  Avec intérêts      : {sum(1 for v in index.values() if v['interets'])}")
    print(f"  Avec patrimoine    : {sum(1 for v in index.values() if v['patrimoine'])}")
    print(f"  Total intérêts     : {sum(len(v['interets']) for v in index.values())}")
    print(f"  Total valeurs mob. : {sum(len(v['patrimoine']) for v in index.values())}")
    print(f"───────────────────────────────────────────────────\n")

def rechercher(index, nom):
    return index.get(normalize_name(nom))

if __name__ == "__main__":
    import sys
    if "--build" in sys.argv or not CACHE_INDEX.exists():
        index = build_index(force="--force" in sys.argv)
    else:
        print("[hatvp] Chargement cache…")
        index = load_index()
    stats(index)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        nom = " ".join(args)
        fiche = rechercher(index, nom)
        if fiche:
            print(f"\n{fiche['prenom']} {fiche['nom']} ({fiche['qualite']})")
            print(f"URL : {fiche['url_hatvp']}")
            print(f"\nIntérêts ({len(fiche['interets'])}) :")
            for i in fiche["interets"]:
                print(f"  [{i['type']}] {i.get('organisme') or i.get('description')} {'[EN COURS]' if i.get('en_cours') else ''}")
            print(f"\nPatrimoine ({len(fiche['patrimoine'])}) :")
            for p in fiche["patrimoine"]:
                print(f"  {p.get('libelle') or p.get('organisme')} — {p.get('valeur')} EUR")
        else:
            print(f"Pas de fiche pour : {nom}")
            proches = [k for k in index if normalize_name(nom)[:5] in k][:5]
            for k in proches:
                print(f"  → {k}")
