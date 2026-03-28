# 🔍 Votes Sous Influence
### [@sousinfluence.bsky.social](https://bsky.app/profile/sousinfluence.bsky.social)

Bot Bluesky qui croise chaque jour les votes de l'Assemblée nationale avec
les déclarations d'intérêts des députés (HATVP), pour signaler les co-occurrences
potentiellement significatives.

---

## Ce que ça fait

Pour chaque nouveau scrutin à l'AN touchant aux thèmes surveillés (énergie,
agriculture, environnement, finance, industrie), le bot vérifie si des députés
ayant voté ont déclaré des intérêts dans des entreprises ou organismes liés au
texte, et publie un thread sur Bluesky.

**Exemple de signal fort :** un député administrateur de TotalEnergies qui vote
pour une loi favorable au secteur pétrolier.

---

## Sources de données

| Source | Format | Mise à jour |
|--------|--------|-------------|
| [HATVP — déclarations d'intérêts](https://www.hatvp.fr/open-data/) | XML | Quotidien |
| [Assemblée nationale — scrutins](https://data.assemblee-nationale.fr) | JSON | Quotidien |

---

## Structure du projet

```
sousinfluence/
├── hatvp_loader.py          # Parser HATVP (intérêts + participations)
├── an_votes.py              # Récupération et parsing des scrutins AN
├── croisement.py            # Moteur de croisement + publication Bluesky
├── build_deputes_index.py   # Construction de l'annuaire des députés
├── mots_cles.json           # Thèmes et mots-clés pour filtrer les scrutins
├── entreprises_themes.json  # Entreprises surveillées par thème
├── scrutins_traites.json    # Scrutins déjà analysés (auto-géré)
├── requirements.txt
└── .github/
    └── workflows/
        └── votes_sous_influence.yml   # GitHub Actions (quotidien à 10h)
```

---

## Déploiement

### Secrets GitHub requis

Dans **Settings > Secrets and variables > Actions** :

| Secret | Valeur |
|--------|--------|
| `BSKY_HANDLE` | `sousinfluence.bsky.social` |
| `BSKY_PASSWORD` | App password Bluesky |

### Lancement manuel

```bash
# Analyse tous les nouveaux scrutins sans poster
python3.11 croisement.py --auto

# Analyse tous les nouveaux scrutins et poste sur Bluesky
BSKY_HANDLE=sousinfluence.bsky.social BSKY_PASSWORD=xxx python3.11 croisement.py --auto --post

# Analyse un scrutin précis
python3.11 croisement.py 844
```

---

## Limites assumées

- Les déclarations d'intérêts sont auto-déclarées par les parlementaires — des oublis sont possibles
- L'outil détecte des **co-occurrences**, pas des causalités. Il ne conclut jamais à un conflit d'intérêts — il signale une hypothèse à investiguer
- Conformément à l'article LO.135-2 du code électoral, les déclarations de patrimoine ne sont pas publiées en ligne et ne peuvent pas être divulguées

---

## Licence

MIT — données sous licence ouverte Etalab
