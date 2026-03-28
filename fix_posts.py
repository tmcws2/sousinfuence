from pathlib import Path

lines = Path('croisement.py').read_text().split('\n')

start = None
end = None
for i, l in enumerate(lines):
    if l.strip() == 'def generer_posts(analyse):':
        start = i
    if start and i > start and (l.startswith('# ── Mode automatique') or l.startswith('def mode_auto')):
        end = i
        break

print(f"Fonction trouvee : lignes {start+1} a {end}")

new_func = '''def generer_posts(analyse):
    scrutin   = analyse["scrutin"]
    themes    = analyse["themes"]
    resultats = analyse["resultats"]

    if not resultats:
        return []

    posts = []

    # — POST 1 : accroche —
    resultat_str = "\\u2705 Adopt\\u00e9" if scrutin["adopte"] else "\\u274c Rejet\\u00e9"
    titre_court  = scrutin["titre"][:200] + "\\u2026" if len(scrutin["titre"]) > 200 else scrutin["titre"]
    lien_an = f"https://www.assemblee-nationale.fr/dyn/17/scrutins/{scrutin['numero']}"

    accroche = (
        "\\U0001f50d Votes Sous Influence\\n\\n"
        f"\\U0001f5f3\\ufe0f Scrutin n\\u00b0{scrutin['numero']} \\u2014 {scrutin['date']}\\n"
        f"{resultat_str} | Vote en s\\u00e9ance publique\\n\\n"
        f"\\U0001f4cb {titre_court}\\n\\n"
        f"\\U0001f517 {lien_an}\\n\\n"
        f"\\U0001f447 {len(resultats)} d\\u00e9put\\u00e9(s) avec des int\\u00e9r\\u00eats d\\u00e9clar\\u00e9s potentiellement li\\u00e9s \\u00e0 ce vote."
    )
    posts.append(accroche)

    # — POST 2 : résumé GPT du texte —
    resume = resumer_texte_claude(scrutin["titre"], themes)
    if resume:
        posts.append("\\U0001f4d6 Le texte en bref :\\n\\n" + resume)

    # — POST 3+ : un post par député (max 8) —
    TYPE_LABELS = {
        "participation_financiere": "actionnaire",
        "participation_dirigeant": "",
        "participation": "",
        "interet": "",
    }

    for r in resultats[:8]:
        groupe_lower = r["groupe"].lower()
        hashtag = HASHTAGS_GROUPES.get(groupe_lower, "")
        emoji_vote = {"pour": "\\U0001f44d", "contre": "\\U0001f44e", "abstention": "\\U0001faf3"}.get(r["position"], "\\u2753")
        position_label = {"pour": "POUR \\u2705", "contre": "CONTRE \\u274c", "abstention": "ABSTENTION \\U0001faf3"}.get(r["position"], r["position"].upper())

        circo = r.get("circonscription", "")
        corps = f"{emoji_vote} {r['nom']}, D\\u00e9put\\u00e9\\u00b7e {hashtag}\\n"
        if circo:
            corps += f"\\U0001f4cd {circo}\\n"
        corps += f"Vote : {position_label}\\n\\n"

        signaux_forts   = [s for s in r["signaux"] if s["force"] == "fort"]
        signaux_faibles = [s for s in r["signaux"] if s["force"] == "faible"]

        if signaux_forts:
            corps += "\\u26a0\\ufe0f Int\\u00e9r\\u00eats d\\u00e9clar\\u00e9s li\\u00e9s \\u00e0 ce vote :\\n"
            for s in signaux_forts[:4]:
                org = s["organisme"][:50]
                desc = s.get("description", "").strip()
                type_bien = s.get("type", s.get("type_bien", ""))
                label = TYPE_LABELS.get(type_bien, "")
                if desc:
                    corps += f"\\u2192 {org} \\u2014 {desc[:40]}\\n"
                elif label:
                    corps += f"\\u2192 {org} \\u2014 {label}\\n"
                else:
                    corps += f"\\u2192 {org}\\n"

        if signaux_faibles and len(corps) < 250:
            for s in signaux_faibles[:1]:
                org = s["organisme"][:50]
                desc = s.get("description", "").strip()
                corps += f"~ {org}"
                if desc:
                    corps += f" \\u2014 {desc[:30]}"
                corps += "\\n"

        posts.append(corps.strip())

    # — POST final : disclaimer —
    cloture = (
        f"\\U0001f4ca {len(resultats)} d\\u00e9put\\u00e9(s) analys\\u00e9s sur ce scrutin.\\n\\n"
        "Source : d\\u00e9clarations d\'int\\u00e9r\\u00eats HATVP (open data).\\n"
        "\\u2696\\ufe0f Conform\\u00e9ment \\u00e0 l\'art. LO.135-2 du code \\u00e9lectoral, "
        "les d\\u00e9clarations de patrimoine ne sont pas divulgu\\u00e9es.\\n\\n"
        "\\u2139\\ufe0f Ces co-occurrences sont des signaux \\u00e0 investiguer, pas des conclusions."
    )
    posts.append(cloture)

    return posts


'''

new_lines = lines[:start] + new_func.split('\n') + lines[end:]
Path('croisement.py').write_text('\n'.join(new_lines))
print("Fichier mis a jour.")
