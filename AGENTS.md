# Contexte du projet ISBN

Lire `docs/CHANGE_PLAN.md` avant de reprendre une intervention : ce fichier conserve l’objectif, les décisions, les validations et les étapes restantes demandées par l’opérateur.

- Le bot reste en dry-run. Une demande d’amélioration ou de déploiement n’autorise pas une édition Wikipédia.
- Conserver SQLite, les identifiants des cas et les décisions humaines. Sauvegarder avant une réanalyse de production ; les anciennes versions restent dans `finding_history`.
- Distinguer cas détectés, candidats trouvés, remplacements proposés et corrections validées. Un score est un classement, pas une probabilité.
- Tester les cas positifs et les mauvais titres/auteurs/années/éditions/langues. Une clé recalculée sans notice ne doit jamais produire un remplacement.
- Les identifiants ne viennent que de notices d’édition ; les ISBN agrégés d’une œuvre Open Library ne sont pas des preuves.
- Google Books nécessite une clé privée configurée. Aucune recherche web générale ou LLM n’est active sans fournisseur configuré ; ne pas prétendre le contraire.
- Comparer le corpus sur son serveur et ne rapporter que les résultats utiles. Ne pas publier la base, les rapports réels, les clés ou les identifiants de connexion dans Git.

La version précédant cette amélioration est `c5adb58`. L’objectif de couverture de propositions est 75 %, à mesurer sur les mêmes cas et à distinguer de la précision validée manuellement.
