# Vérification de cette livraison

Réalisée le 5 octobre 2026 avec Python 3.12.14. Python 3.13 est configuré pour l'hébergement Toolforge ; le build Toolforge distant reste à exécuter.

## Contrôles réalisés

| Contrôle | Résultat |
|---|---|
| Installation du paquet et point d'entrée CLI | Réussite |
| Tests hors ligne | 75 tests réussis |
| Compilation des modules Python | Réussite |
| Syntaxe des trois scripts de déploiement Bash | Réussite |
| Démonstration sans réseau | Un candidat sourcé fictif, un diff, zéro édition |
| MediaWiki réel | Catégorie récupérée, 211 articles au moment du contrôle |
| BnF réel | Une notice pour le livre du contrôle, avec recherche ISBN-10/13 équivalents |
| Sudoc réel | Une notice et son RDF pour l'identifiant du contrôle |
| Open Library réel | Une édition pour l'identifiant du contrôle |
| Analyse d'un article réel | Rapport produit ; aucune modification Wikipédia |

## Deux difficultés réelles couvertes

Un ISBN précédé de `2025` et d'espaces pouvait être confondu avec un identifiant de dix chiffres composé de l'année et du début de l'ISBN. Le parseur de tokens repère désormais les ISBN de treize chiffres d'abord. Une régression dédiée couvre ce cas.

Certains ISBN de treize chiffres n'obtiennent pas de notice BnF alors que leur équivalent ISBN-10 est indexé. L'adaptateur interroge désormais les deux représentations lorsqu'elles existent.

## Exemple public

`examples/public-sample/report.html` et `report.json` sont issus d'une lecture de l'article **Lucie Pierrat-Pajot**, révision **240049631**. Le champ précédé d'une année est classé `EXTRA_TEXT`. Des notices retournées par la BnF associent le même ISBN à des titres différents ; l'adaptateur Sudoc a également rencontré une erreur HTTP pendant cette recherche.

Le logiciel affiche les données contradictoires et ne propose pas de substitution publiable. C'est un exemple de résultat à vérifier manuellement, pas une référence validée. Le rapport a été créé sans connexion au compte Wikipédia et sans édition.

`examples/demo/` est un autre exemple, intégralement fictif, permettant de tester une proposition et un diff sans réseau.

## Contrôles restant à effectuer dans l'environnement réel

- Build ou installation sous l'image Python Toolforge, exécution du job horaire et vérification de la persistance après relance.
- SMTP avec l'adresse effectivement choisie.
- Connexion au compte de bot et publication d'un diff autorisé par la communauté.
- Corpus annoté permettant de mesurer la précision bibliographique sur des éditions réelles.

## Mise à jour du 6 octobre 2026 : lancement depuis GitHub

Le compte développeur, l'association Phabricator, l'adhésion Toolforge approuvée et le compte outil `mesange-isbn-bot` ont été vérifiés. Le code du projet est publié sur la branche `main` du dépôt public GitHub `PonsMatthieu/wikipedia-isbn-bot`, sous licence MIT. Les 58 fichiers publics excluent les secrets, les bases de données et les rapports réels. Le build et les jobs Toolforge restent à effectuer.

La syntaxe de `deploy/toolforge/start-build.sh` a été contrôlée avec `bash -n`. Ses cinq tests hors ligne couvrent quatorze situations : parcours de lancement, configuration sans écriture, stockage persistant, compte incorrect, URL incorrecte, jobs préexistants et arrêt après échec du client Toolforge. Les appels au client sont simulés ; ces tests ne vérifient pas le build distant ni l'état effectif des conteneurs.

```bash
python3 -m unittest discover -s tests -p test_toolforge_start.py -v
```

Les résultats des 75 tests du bot ci-dessus concernent la livraison du 5 octobre. Le code Python du bot n'a pas changé lors de cette mise à jour. Les tests de publication utilisent des réponses simulées et aucune correction réelle n'a été publiée.

## Incident du pilote Toolforge, 6 octobre 2026

Résultats fournis par l'opérateur : 196 articles dans la catégorie, 20 analysés, 33 cas enregistrés, 12 recherches incomplètes et zéro édition. Le rapport cumulatif compte 33 erreurs Sudoc `HttpError` et deux erreurs BnF `ValueError`. Ces types seuls ne précisent pas le code HTTP, l'étape Sudoc en cause ni le diagnostic BnF. L'accès SSH et l'exécution de l'image sont donc confirmés par ce retour ; l'accès complet aux catalogues reste à contrôler.

La correction conserve les notices obtenues avant une erreur dans les recherches BnF et Sudoc. Les erreurs restent visibles dans le rapport et sont maintenant journalisées avec le code HTTP ou SRU disponible, sans message fournisseur brut ni URL. Les recherches sans candidat après une erreur gardent leur statut d'échec et leur délai de reprise. Un résultat Sudoc XML vide reste un résultat normal ; une erreur HTTP 404 reste signalée.

Contrôle local sous Python 3.12.14 : **90 tests réussis et 12 sous-tests réussis**, dont dix nouvelles régressions couvrant les résultats partiels, les erreurs HTTP/SRU, les journaux, les réponses vides et la conservation des échecs sans candidat.

```bash
python -m pytest -q
```

La correction doit encore être reconstruite dans l'image Toolforge et vérifiée avec un nouveau pilote. Les erreurs externes des catalogues ne sont pas considérées comme résolues par les tests simulés.

## Diagnostic direct et correction des catalogues, 6 octobre 2026

Accès SSH réalisé depuis `Matthieu_Omen`, sous le compte outil `mesange-isbn-bot`. Le build terminé à 21:34:34 UTC et les journaux `isbn-pilot-v2` confirment l'exécution de la correction `092e564` : 20 articles analysés, 26 cas enregistrés, deux recherches incomplètes et zéro édition. Le job `isbn-hourly` est planifié. Les variables sont `BOT_MODE=DRY_RUN`, `BOT_WRITE_ENABLED=false` et `BOT_COMMUNITY_APPROVED=false`.

Deux causes ont été reproduites par des appels réels depuis Toolforge :

- Sudoc `isbn2ppn` renvoie HTTP 404 avec un XML `<sudoc service="isbn2ppn"><error>Aucune notice n'est associée à cette valeur ISBN</error></sudoc>` pour certains ISBN sans notice. Cette réponse précise est désormais validée comme absence de résultat ; un 404 HTML, un message de panne, un ISBN différent, une réponse XML non fiable ou un 404 RDF restent des erreurs. Les deux formes ISBN-10/13 sont recherchées sans télécharger deux fois le même PPN.
- BnF `bib.title all "Le cheval d'orgueil"`, `maximumRecords=20`, renvoie des notices et un diagnostic SRU `131` (« erreur de traitement »). Le parseur conserve désormais les notices convertibles dans cette même réponse, avec leur avertissement.

La base existante a été sauvegardée via l'API SQLite `backup` avant intervention : `backups/state-pre-catalogues-20261006T214822Z.sqlite3`. Son `PRAGMA quick_check` est `ok` ; elle contient 196 événements, 96 cas et zéro édition à cet instant. Aucune réinitialisation ni suppression des données n'a été effectuée.

Tests locaux sous Python 3.13.15 : **107 tests réussis et 12 sous-tests réussis**. Les nouvelles régressions couvrent les réponses observées, la distinction panne/absence, l'isolation du cache, la conversion ISBN-10/13 et la propagation des notices BnF partielles jusqu'au rapport. La reconstruction et le pilote de cette nouvelle correction restent à vérifier après publication.
