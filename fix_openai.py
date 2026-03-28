from pathlib import Path

content = Path('croisement.py').read_text()

old = '''def resumer_texte_claude(titre, themes):
    """Appelle GPT pour résumer le texte voté."""
    import os
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = (
            f"Tu es un assistant spécialisé en droit parlementaire français. "
            f"Résume en 2 phrases maximum ce texte voté à l\'Assemblée nationale, "
            f"ses enjeux et ses conséquences concrètes pour les citoyens. "
            f"Sois factuel et neutre. Ne commence pas par \'Ce texte\'.\\n\\n"
            f"Titre : {titre}\\nThèmes : {\', \'.join(themes)}"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[openai] Erreur résumé : {e}")
        return ""'''

new = '''def resumer_texte_claude(titre, themes):
    """Appelle GPT pour resumer le texte vote."""
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
            "Resume en 2 phrases maximum ce texte vote a l'Assemblee nationale, "
            "ses enjeux et ses consequences concretes pour les citoyens. "
            "Sois factuel et neutre. Ne commence pas par Ce texte.\n\n"
            "Titre : " + titre + "\n"
            "Themes : " + themes_str
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[openai] Erreur resume : {e}")
        return ""'''

if old in content:
    Path('croisement.py').write_text(content.replace(old, new))
    print("OK")
else:
    print("PATTERN NOT FOUND")
