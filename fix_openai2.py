from pathlib import Path

lines = Path('croisement.py').read_text().split('\n')

# Trouve le debut de la fonction
start = None
end = None
for i, l in enumerate(lines):
    if l.strip() == 'def resumer_texte_claude(titre, themes):':
        start = i
    if start and i > start and (l.startswith('def ') or l.startswith('HASHTAGS')):
        end = i
        break

print(f"Fonction trouvee : lignes {start+1} a {end}")

new_func = [
    'def resumer_texte_claude(titre, themes):',
    '    """Appelle GPT pour resumer le texte vote."""',
    '    import os',
    '    api_key = os.environ.get("OPENAI_API_KEY", "")',
    '    if not api_key:',
    '        return ""',
    '    try:',
    '        from openai import OpenAI',
    '        client = OpenAI(api_key=api_key)',
    '        themes_str = ", ".join(themes)',
    '        prompt = (',
    '            "Tu es un assistant specialise en droit parlementaire francais. "',
    '            "Resume en 2 phrases maximum ce texte vote a l\'Assemblee nationale, "',
    '            "ses enjeux et ses consequences concretes pour les citoyens. "',
    '            "Sois factuel et neutre. Ne commence pas par Ce texte.\\n\\n"',
    '            "Titre : " + titre + "\\n"',
    '            "Themes : " + themes_str',
    '        )',
    '        resp = client.chat.completions.create(',
    '            model="gpt-4o-mini",',
    '            max_tokens=200,',
    '            messages=[{"role": "user", "content": prompt}]',
    '        )',
    '        return resp.choices[0].message.content.strip()',
    '    except Exception as e:',
    '        print(f"[openai] Erreur resume : {e}")',
    '        return ""',
    '',
]

new_lines = lines[:start] + new_func + lines[end:]
Path('croisement.py').write_text('\n'.join(new_lines))
print("Fichier mis a jour.")
