# Plan d’amélioration ISBN — 7 octobre 2026

## Objectif et contraintes persistantes

L’opérateur demande d’augmenter la couverture des corrections proposées, avec un objectif de 75 % à mesurer sur les mêmes cas. Son taux manuel annoncé est de 99 % ; ce n’est pas encore un corpus annoté permettant de valider le bot.

Base de départ : commit `c5adb58`, 163 cas issus de 121 articles analysés, 20 remplacements proposés sur 15 articles. Dernier lot : 31 cas sur 20 articles, 5 remplacements sur un article. 62 cas sans candidat ; 60 bloqués par des métadonnées différentes ; 11 types exclus ; 5 champs restreints ; 5 scores insuffisants.

Conserver SQLite et les décisions humaines. Toujours DRY_RUN, zéro édition Wikipédia. Sauvegarder avant réanalyse ; conserver les anciennes versions des cas. Ne pas inventer d’ISBN, ne pas transformer une clé correcte en preuve bibliographique. Google Books nécessite une clé que l’opérateur n’a pas encore configurée.

## Changements autorisés et ordre de réalisation

1. **Comparer correctement les notices.** Normalisation Unicode, auteurs avec initiales/ordre inversé, titre principal et sous-titre, variantes de catalogage de l’éditeur. Une différence réelle d’année, d’édition, de volume ou de langue reste visible et bloque la sélection automatique. Classer les preuves par notice plutôt que propager une réserve de mise en forme à toutes les notices d’un ISBN.
2. **Lire la référence autour du champ.** Modèles bibliographiques supplémentaires vérifiés ; titre et auteur dans les listes non structurées ; contexte local au bon ISBN dans une phrase avec plusieurs traductions ; titres sans italique et alphabets non latins. Ne pas hériter de l’année d’une édition originale pour une réédition citée en commentaire.
3. **Élargir les pistes de recherche.** Variantes bornées d’un chiffre absent/en trop/inversé/substitué ; checksum et formats équivalents ; recherche titre+auteur puis titre seul ; exploration des éditions Open Library avec année/langue/éditeur. Conserver les résultats obtenus avant une erreur de fournisseur, y compris les notices sauvegardées du même champ réévaluées avec son contexte actuel. Suspendre les nouveaux appels au service pendant 60 secondes après épuisement des reprises réseau ; le cache et les autres catalogues restent disponibles. Les variantes mathématiques servent seulement à chercher des notices.
4. **Rendre les résultats mesurables.** Compter séparément cas détectés, candidats, remplacements, articles concernés, erreurs partielles et échecs. Expliquer le blocage et les actions manuelles possibles. Corriger le compteur `proposals` qui comptait auparavant tous les cas.
5. **Réanalyser sans perdre l’historique.** Commande paginée pour les événements déjà analysés, archive des cas remplacés et protection des cas approuvés/rejetés/publiés. Comparaison avant/après sur les mêmes pages, puis run réel en lecture seule.
6. **Valider, publier et déployer.** Tests des erreurs observées et des cas négatifs, tests existants, push GitHub, reconstruction de l’image Toolforge et pilote dry-run. Inscrire le commit et les résultats mesurés ci-dessous.

## Dépendances et suite

Google Books est déjà implémenté, mais l’activation reste dépendante de la clé API. Une recherche web générale/LLM nécessite un fournisseur et ses identifiants : elle ne doit pas être annoncée comme active avant configuration. Les améliorations sans clé et la recherche dans les éditions sont réalisées d’abord.

La couverture de propositions et la précision des propositions validées sont deux indicateurs distincts. Le seuil de 75 % est un objectif, pas un résultat promis. Les ISBN multiples, ISSN/EAN/ISMN et champs sans ISBN nécessitent des actions adaptées, qui doivent être comptées à part des remplacements d’ISBN.

## État de cette intervention

- [x] Analyse des causes et consignation du plan.
- [x] Implémentation et tests : 160 tests et 12 sous-tests réussis sur Toolforge, Python 3.13.
- [x] Publication sur la branche `isbn-recovery-v5`.
- [ ] Fusion dans `main` : mise à jour directe refusée par la vérification automatique, qui demande l’autorisation explicite de cette publication.
- [ ] Déploiement Toolforge.
- [x] Comparaison hors ligne sur le corpus conservé.
- [ ] Pilote réseau sur une copie isolée de SQLite et bilan.

Ce fichier est le point de reprise pour les prochaines sessions ; le compléter à chaque changement de portée ou validation.

Comparaison hors ligne avant déploiement : mêmes 163 cas, mêmes notices sauvegardées, 20 → 34 remplacements proposés (+17, -3 devenus ambigus). Quatre contextes auparavant sans titre sont récupérés. Aucun appel de recherche supplémentaire dans cette mesure ; zéro modification Wikipédia. Ces nouvelles propositions restent à valider humainement.

Le pilote utilise `scripts/pilot_reanalysis.py` : sauvegarde SQLite cohérente en lecture seule, nouveau dossier privé, réanalyse uniquement de la copie, identifiants Wikipédia et notifications désactivés. La branche de travail ne remplace pas l’image de production avant la fusion autorisée.

Diagnostic réseau du pilote : les quatre accès publics Open Library (ISBN seul, ISBN groupés, recherche de titre, notice d’édition) échouent depuis le conteneur Toolforge par `ConnectionRefusedError`, errno 111 ; la résolution DNS fonctionne. Ce diagnostic explique un blocage d’accès au catalogue, sans déterminer son origine. La conservation des preuves en cas de panne et la pause de reprise ont été ajoutées à la portée de cette intervention. Ne pas confondre ces erreurs partielles avec des échecs complets de page.
