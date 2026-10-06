# Parcours communautaire

L'hébergement Toolforge, le compte développeur, le compte Wikipédia de bot et le statut de bot sont quatre démarches différentes.

1. L'opérateur reste **Mésange_Futée**. Créer un compte de bot distinct avant les éditions.
2. Publier le code et la présentation du bot, en précisant le périmètre et la procédure d'arrêt.
3. Exécuter l'analyse et vérifier manuellement des références de plusieurs types d'erreurs. Consigner les éditions correctes, les propositions rejetées et les raisons.
4. Présenter le projet suivant la procédure actuelle de [Wikipédia:Bot/Statut](https://fr.wikipedia.org/wiki/Wikip%C3%A9dia:Bot/Statut), discuter du périmètre et suivre les demandes de tests formulées par la communauté.
5. Pour d'éventuels tests d'édition avant attribution du statut, suivre les consignes communautaires et intervenir directement de manière supervisée. Le logiciel livré refuse de publier avec un compte sans droit `bot`.
6. Après accord et attribution des droits, activer les variables d'écriture. Les commandes `approve` et `apply` restent explicites dans cette V1.

## Informations à présenter

- Wikipédia en français, espace principal uniquement.
- Catégorie surveillée et fréquence horaire.
- Bibliothèque de validation, règles de correspondance des éditions et exclusions.
- Sources consultées et preuves sauvegardées.
- Résultats du corpus annoté, sans assimiler le score à une probabilité.
- Diff minimal et protection par révision.
- Respect des modèles `nobots`/`bots`, fichier STOP, arrêt sur blocage ou erreur de droits.
- Méthode de retour arrière et contact de l'opérateur.

## Esquisse de demande de statut

À adapter au formulaire actuel et à compléter seulement avec des éléments réellement obtenus :

```text
Opérateur : [[Utilisateur:Mésange Futée]]
Compte du bot : [nom effectif à renseigner]
Code source : [URL du dépôt public]
Langage : Python
Objet : vérification et correction supervisée de champs ISBN invalides.
Périmètre : espace principal, modèles de citation pris en charge.
Sources : BnF, Sudoc, Open Library ; Google Books si configuré.
Exclusions : éditions ambiguës, ISBN publié comme erroné, identifiants d'autres types,
champs commentés, modèles inconnus ou paramètre dupliqué.
Tests réalisés : [liens vers les vrais diffs et résultats du corpus annoté].
Fréquence d'analyse : horaire ; plafond d'éditions initial : trois soumissions/jour UTC.
Arrêt : fichier STOP, blocage du compte et contrôle persistant des incidents.
```
