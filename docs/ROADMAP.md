# Suite du projet

## Livraison actuelle : analyse et validation humaine

- Veille régulière, sources structurées, rapports et workflow local d'approbation.
- Publication unitaire protégée, désactivée par défaut et conditionnée aux droits de bot.
- Déploiement préparé pour Toolforge, à réaliser après accès au compte.

## Avant les premières éditions

- Obtenir le compte développeur, l'adhésion Toolforge et un compte de tool.
- Publier le code ; créer et présenter le compte de bot.
- Constituer un corpus annoté de cas réels, incluant plusieurs éditions d'une même œuvre, traductions, doublons et ISBN imprimés erronés.
- Suivre le parcours communautaire, obtenir les droits et vérifier quelques diff supervisés.
- Configurer et tester les emails, sauvegardes et arrêt d'urgence sur l'environnement d'hébergement.

## Version suivante : automatisation limitée

Mesurer la précision par famille d'erreurs avant toute whitelist. Définir des critères de preuve explicites et d'indépendance des sources. Un score de correspondance de 0,98 ne suffit pas à prouver une précision de 98 %.

Le job horaire pourra appliquer les décisions admissibles seulement après validation de ce corpus, seuils étayés et procédure communautaire appropriée. Ne pas introduire un mode AUTO_FULL simplement en changeant une variable de configuration.

## LLM et recherche web

La V1 n'utilise pas de LLM. Un futur module pourra proposer des requêtes ou ordonner les candidats en cas de bibliographie difficile. Les ISBN qu'il renvoie devront être retrouvés dans des sources effectivement consultées, puis validés et vérifiés sur l'édition exacte.

Il ne recevra pas de fonction d'édition Wikipédia. Prévoir un budget de requêtes, un journal d'évidence, un traitement des réponses hors schéma et une défense contre les instructions trouvées dans les pages sources.

## Couverture bibliographique

- Recherche libre Sudoc au-delà de la corroboration par identifiant.
- Prise en charge des notices et rôles bibliographiques plus riches, sous-titres, traducteurs et volumes.
- Distinction explicite des ISBN papier, relié et numérique d'une même notice.
- Réexamen des révisions modifiées sans sortie de catégorie, avec contrôle du coût des lectures.
- Page de revue authentifiée si un rapport statique et la CLI deviennent insuffisants.
