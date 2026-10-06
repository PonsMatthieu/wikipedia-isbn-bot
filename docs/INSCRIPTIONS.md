# Comptes et inscriptions de Mésange_Futée

**État vérifié le 6 octobre 2026 :** le compte développeur est actif et associé aux comptes Wikimedia et Phabricator. La [demande Toolforge n° 2391](https://toolsadmin.wikimedia.org/tools/membership/status/2391) est **Approved**, approuvée le 6 octobre à 13:17 UTC (15:17 au Luxembourg). L'outil [mesange-isbn-bot](https://toolsadmin.wikimedia.org/tools/id/mesange-isbn-bot) a été créé sous licence MIT, avec Mésange Futée comme mainteneur.

**Prochaine étape :** enregistrer une clé SSH publique, transférer ou construire le projet, puis démarrer les jobs en lecture seule. Aucune clé SSH n'était enregistrée lors de cette vérification ; l'installation et la planification du bot restent à réaliser. Le compte de bot Wikipédia et l'autorisation communautaire de publication restent à organiser.

## Compte développeur Wikimedia

- Compte Wikimedia existant : **Mésange_Futée**.
- Nom développeur confirmé : **Mésange Futée**.
- Identifiant UNIX confirmé : **mesangefutee**.
- Compte Phabricator associé : **Mesange_Futee**.
- Nom de tool créé : **mesange-isbn-bot**.
- Adresse email : choisie par le titulaire ; la console indique qu'elle est visible publiquement.
- Mot de passe : géré par le titulaire, sans le transmettre dans une conversation.

Créer un compte développeur ne crée pas automatiquement un compte Wikipédia de bot.

## Demande d'adhésion à Toolforge approuvée

Texte soumis pour la demande n° 2391 :

> I contribute to French Wikipedia as Mésange_Futée. I would like to host a Python tool that monitors the category “Page avec ISBN invalide” and helps verify invalid ISBNs in bibliographic references.
>
> The tool will perform scheduled checks using the MediaWiki API and public bibliographic sources, including BnF, Sudoc and Open Library. It will generate evidence-based reports for human review and initially operate in read-only mode.
>
> Any future Wikipedia edits will require community approval and a separate bot account. The source code will be published under the MIT licence.


Ajouter le lien réel du dépôt lorsque celui-ci est publié. Ne pas annoncer un statut bot déjà obtenu ou une précision bibliographique déjà mesurée.

## Description du tool

**Nom lisible créé :** Mésange ISBN Bot. **Licence :** MIT.

> Monitors French Wikipedia pages with invalid ISBNs and checks bibliographic references against BnF, Sudoc and Open Library. Produces evidence and reports for human review. Initially runs in read-only mode; any future Wikipedia edits require separate community approval.

## Compte de bot dédié

Nom proposé : **MesangeISBNBot**, sous réserve de disponibilité et du choix de l'opérateur.

Après création et autorisation communautaire, générer un Bot Password réservé à ce projet avec uniquement les droits nécessaires à la lecture et à la modification des pages. Le logiciel exige le droit `bot` pour publier. Ne pas donner de droits d'administration, de suppression ou de blocage.

Le dossier comprend `PAGE_BOT.wikitext` pour la présentation publique. Le texte de demande de statut reste un modèle à compléter après un pilote vérifié ; il ne doit pas être envoyé avec des résultats de test inventés.

## GitHub

Le dépôt public [PonsMatthieu/wikipedia-isbn-bot](https://github.com/PonsMatthieu/wikipedia-isbn-bot) contient le code du projet sous licence MIT. Le lancement sur Toolforge se fait depuis ce dépôt, après connexion SSH sous le compte outil.
