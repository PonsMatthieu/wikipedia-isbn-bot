# Bot ISBN Wikipédia

Première version exécutable du projet décrit dans `Wikipedia_ISBN_Bot_Documentation.pdf`, préparée le 5 octobre 2026 pour **Mésange_Futée**.

Le bot surveille `Catégorie:Page avec ISBN invalide` sur Wikipédia en français, analyse les références et produit des propositions sourcées. Il peut publier **une correction approuvée explicitement**. Le job horaire ne publie jamais dans cette version.

## Essayer tout de suite

Python 3.11 ou supérieur est nécessaire. Aucun compte ni clé API pour la démonstration.

```bash
python -m venv .venv
```

Sous Windows PowerShell :

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
isbn-bot demo --output examples/demo
Start-Process examples/demo/report.html
python -m pytest -q
```

Sous Linux/macOS :

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
isbn-bot demo --output examples/demo
python -m pytest -q
```

Ouvrir `examples/demo/report.html`. Les données de cette démonstration sont **fictives** et aucune requête réseau n'est effectuée.

## Surveiller réellement Wikipédia

```bash
isbn-bot init
isbn-bot run
isbn-bot status
```

Le premier `run` enregistre la liste initiale sans analyser les articles déjà présents. Les runs suivants traitent les ajouts et les réentrées. Pour analyser volontairement un lot existant :

```bash
isbn-bot run --process-existing
```

Chaque run traite au maximum `BOT_MAX_PAGES` pages, par défaut 20. Répéter la commande pour avancer dans le lot initial. Pour cibler un article :

```bash
isbn-bot analyze-page "Titre exact de l'article"
isbn-bot list --status NEEDS_REVIEW
isbn-bot show 1
```

Les rapports sont écrits dans `data/reports/` localement, et dans `$TOOL_DATA_DIR/isbn-bot/reports/` sur Toolforge. Ce sont des fichiers HTML et JSON consultables localement ; ce projet n'expose pas de serveur web.

## Valider puis publier

```bash
isbn-bot approve 1
isbn-bot approve 2 --isbn 9780306406157
isbn-bot reject 3
```

`approve` et `reject` modifient seulement la base locale. Après examen de l'édition exacte, accord communautaire, création du compte de bot et configuration des identifiants :

```text
BOT_MODE=REVIEW_ONLY
BOT_WRITE_ENABLED=true
BOT_COMMUNITY_APPROVED=true
WIKI_BOT_ACCOUNT=NomDuCompteBot
WIKI_BOT_LOGIN=NomDuCompteBot@NomDuBotPassword
WIKI_BOT_PASSWORD=...
```

```bash
isbn-bot apply 1 --confirm
```

Le compte doit posséder le droit `bot`. La publication est refusée si la révision a changé, si la page a quitté la catégorie, si elle refuse les bots, si l'ISBN n'est pas présent dans les notices sauvegardées ou si un arrêt est actif. Limite initiale : trois soumissions par jour UTC. Une réponse perdue ne déclenche jamais une nouvelle soumission automatique.

## Ce qui est livré

| Partie | Fonctionnement |
|---|---|
| MediaWiki | Catégorie paginée, révisions, connexion Bot Password, protection contre les conflits |
| Détection | Liste initiale, nouveaux articles, réentrées, suivi persistant SQLite |
| ISBN | ISBN-10/13, préfixes, clé de contrôle, distinction ISBN/ISSN/EAN/ISMN |
| Wikitexte | Analyse des modèles, contexte bibliographique, substitution minimale |
| BnF | Recherche SRU par ISBN et titre ; conservation des ISBN erronés signalés |
| Sudoc | Corroboration des ISBN via isbn2ppn et notices RDF |
| Open Library | Consultation d'éditions ; jamais les ISBN agrégés d'une œuvre |
| Google Books | Adaptateur optionnel avec clé API |
| Validation | Candidats, sources, score de classement, diff, approbation/rejet |
| Exploitation | Rapport HTML/JSON, SMTP facultatif, STOP, audit des éditions |
| Toolforge | Procfile, Build Service, job horaire et alternative par transfert de dossier |
| Tests | Tests hors ligne des règles, catalogues, reprises et protections de publication |

## Démarrer directement sur Wikimedia Toolforge

L'accès développeur **mesangefutee**, l'adhésion Toolforge et le compte outil **mesange-isbn-bot** ont été vérifiés le 6 octobre 2026. Le dépôt public est [PonsMatthieu/wikipedia-isbn-bot](https://github.com/PonsMatthieu/wikipedia-isbn-bot). Le pilote et la correction des catalogues ont été validés sur Toolforge le 6 octobre ; la veille horaire est active en dry-run. Voir [docs/VALIDATION.md](docs/VALIDATION.md) pour les versions déployées et les contrôles encore nécessaires. L'autorisation d'hébergement et le statut de bot sur Wikipédia sont distincts.

Suivre [docs/TOOLFORGE.md](docs/TOOLFORGE.md). Après publication sur GitHub et connexion sous le compte outil, le script `bash deploy/toolforge/start-build.sh` prépare le build et la surveillance horaire en lecture seule. Une méthode sans dépôt Git est également fournie, avec l'image `python3.13`.

Les inscriptions réalisées et les étapes restantes sont consignées dans [docs/INSCRIPTIONS.md](docs/INSCRIPTIONS.md). Le lancement initial ne nécessite aucun mot de passe de bot Wikipédia.

## Configuration des sources et notifications

`BOT_SOURCES=bnf,sudoc,openlibrary` fonctionne sans clé. Sudoc confirme les ISBN découverts dans les autres catalogues ; son adaptateur V1 ne fait pas de recherche libre par titre.

Pour ajouter Google Books : renseigner `GOOGLE_BOOKS_API_KEY` puis `BOT_SOURCES=bnf,sudoc,openlibrary,googlebooks`.

L'option `--sources` permet aussi de choisir les catalogues pour une analyse, sans modifier la configuration permanente :

```bash
isbn-bot sources
isbn-bot run --process-existing --sources bnf sudoc openlibrary googlebooks
isbn-bot analyze-page 'Titre de l’article' --sources googlebooks bnf sudoc
```

Google Books recherche les deux formats ISBN, puis le titre avec l'auteur lorsqu'il est disponible et le titre seul. Seuls les identifiants explicitement déclarés `ISBN_10` ou `ISBN_13` et valides sont retenus. Les notices déjà obtenues sont conservées si une requête suivante échoue ; les erreurs de clé, de quota et de réseau restent visibles sans afficher la clé API. L'API nécessite une clé configurée avant son activation ; aucune clé n'est fournie avec le projet.

### Clé de contrôle et équivalence ISBN-10/ISBN-13

```bash
isbn-bot check-isbn 9780306406158
isbn-bot check-isbn 0306406156
isbn-bot check-isbn 0804429570
```

Ces commandes fonctionnent hors ligne. Pour `9780306406158`, la clé attendue est `7` : la piste est `9780306406157`, dont l'équivalent ISBN-10 est `0306406152`. Pour `0804429570`, la clé attendue est `X`. Le rapport HTML/JSON montre ces contrôles, les conversions et les sources ayant retrouvé l'identifiant.

La conversion ISBN-10 → ISBN-13 ajoute `978` devant les neuf chiffres du corps et recalcule la dernière clé. La conversion inverse retire `978` et recalcule la clé ISBN-10, qui peut être `X`. Il n'existe pas de remplacement fixe « 6 → 2 ». Les ISBN commençant par `979` n'ont pas d'équivalent ISBN-10 ; `9790` est réservé à l'ISMN. Un ISBN-10 valide reste accepté et n'est pas signalé comme erroné uniquement à cause de sa longueur.

Une clé correcte prouve seulement la cohérence mathématique. L'hypothèse « seule la clé est fausse » sert à rechercher une notice ; elle ne devient pas un candidat bibliographique sans identifiant valide attesté et ne remplace pas la vérification du titre, de l'auteur et de l'édition. Les anciens cas reçoivent aussi les contrôles lors d'un nouvel export, sans réécriture de leur historique dans SQLite.

Pour recevoir les alertes : renseigner `MAIL_HOST`, `MAIL_PORT`, `MAIL_SECURITY`, `MAIL_FROM` et `MAIL_TO`, ainsi que les identifiants si le serveur les exige. Tester avec `isbn-bot notify-test`. Un seul message regroupé est envoyé par run. Les rapports restent disponibles même si SMTP échoue.

## Vérification et limites

```bash
python -m pytest -q
python scripts/smoke_readonly.py
```

Le premier contrôle utilise des réponses simulées. Le second interroge réellement les services publics sans connexion ni édition. Des tests réussis ne remplacent pas un corpus de références annotées : le score sert à classer, ce n'est pas une probabilité de justesse.

La V1 laisse à une intervention directe dans Wikipédia les cas d'ISBN multiples, d'ISBN publié comme erroné, d'ISSN/EAN/ISMN mal placé, de champ commenté et de modèle inconnu. Les pages signalées par la catégorie sans champ ISBN explicite sont consignées comme `NO_SUPPORTED_FINDING`.

La correction entièrement automatique et le recours à un LLM/recherche web restent dans [docs/ROADMAP.md](docs/ROADMAP.md). Aucun service LLM n'est appelé dans cette livraison et aucune clé LLM n'est nécessaire.

Sources officielles, fonctionnement interne et procédures d'arrêt : [docs/SOURCES.md](docs/SOURCES.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/OPERATIONS.md](docs/OPERATIONS.md).

Les résultats des contrôles de livraison sont consignés dans [docs/VALIDATION.md](docs/VALIDATION.md). Le dossier téléchargeable contient aussi `examples/public-sample/`, un rapport d'analyse réelle en lecture seule ; il est exclu du dépôt public et met en évidence un cas contradictoire laissé à la revue humaine.
