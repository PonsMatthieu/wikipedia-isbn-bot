# Exploitation, incidents et retour arrière

## Contrôles courants

```bash
isbn-bot status
isbn-bot list --status NEEDS_REVIEW,NO_CANDIDATE,STALE
isbn-bot export
```

Un article déjà examiné n'est pas systématiquement réanalysé à chaque modification : la veille suit les événements de catégorie. Utiliser `analyze-page` pour réexaminer un article encore présent, par exemple après une correction partielle.

Les lectures HTTP retentent les erreurs réseau, 429 et certaines erreurs serveur avec un délai borné. Les erreurs MediaWiki `maxlag` de lecture sont aussi retentées. Les éditions ne sont jamais soumises deux fois automatiquement.

## Pilote Toolforge marqué Failed

Le job renvoie le code 1 lorsqu'au moins un article reste sans candidat après une erreur de catalogue. Les articles traités et leurs propositions restent dans le rapport. Les compteurs `analysed`, `failures` et `proposals` permettent de distinguer ce résultat partiel d'un arrêt avant analyse.

Les journaux indiquent le catalogue, l'étape (`isbn2ppn`, `RDF` ou `SRU`) et le code HTTP ou SRU disponible. Les notices déjà obtenues dans une recherche BnF ou Sudoc restent utilisables si une requête suivante échoue ; la recherche conserve aussi son avertissement. Un résultat Sudoc XML vide est une absence de notice normale. Le service `isbn2ppn` utilise aussi HTTP 404 pour une absence explicite : seule une réponse XML `sudoc`, service `isbn2ppn`, contenant exactement le message « Aucune notice n'est associée à cette valeur » suivi de l'ISBN interrogé, est acceptée comme résultat vide. Les autres 404, notamment ceux des notices RDF, restent visibles comme erreurs. Les ISBN-10 et ISBN-13 équivalents sont interrogés et les PPN dédupliqués.

Une réponse BnF peut contenir des notices convertibles et un diagnostic SRU de remplacement pour une notice non convertible (code `131` observé). Les notices lisibles sont conservées ; le diagnostic reste dans le rapport. Une réponse contenant uniquement des diagnostics reste une recherche en erreur.

Sur le bastion Toolforge, `isbn-bot` n'est pas installé par le build. Exécuter les commandes applicatives dans un job de l'image : `manage-isbn status`, `manage-isbn export` ou `scan-isbn --process-existing`.

Pour un pilote dont les journaux doivent rester consultables après la fin du job :

```bash
toolforge jobs run isbn-pilot-check \
  --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest \
  --command 'scan-isbn --process-existing' \
  --mount all --filelog --wait 3300
tail -n 80 /data/project/mesange-isbn-bot/isbn-pilot-check.out /data/project/mesange-isbn-bot/isbn-pilot-check.err
```

Le rapport est dans `/data/project/mesange-isbn-bot/isbn-bot/reports/`. Les erreurs enregistrées dans les anciens cas conservent leur ancien format ; une nouvelle analyse produit les détails supplémentaires. La catégorie, les événements, les propositions et les rapports sont conservés lors d'une reconstruction de l'image.

Une analyse de page échouée est réessayée lors d'un run ultérieur, jusqu'à quatre tentatives, avec un délai croissant. Les résultats sans candidat et les résultats incomplets restent visibles pour réexamen.

## Arrêt

```bash
isbn-bot stop
```

Sur Toolforge, lancer cette commande via `manage-isbn stop`, ou créer `$TOOL_DATA_DIR/isbn-bot/STOP` sous le compte du tool. Le job courant vérifie STOP entre les champs et avant la publication.

Les incidents de blocage, d'authentification, de droits ou de publication arrêtent aussi les écritures dans la base. Un STOP ne retire pas une édition déjà envoyée.

## Soumission incertaine

Un timeout après l'envoi peut cacher une édition réussie. Vérifier sans reposter :

```bash
isbn-bot reconcile 12
```

Si le texte courant correspond exactement à la cible et après inspection de l'historique :

```bash
isbn-bot reconcile 12 --accept-match
isbn-bot resume --confirm
```

`RECONCILED` atteste une concordance de texte, sans affirmer que le bot est l'auteur de la révision. Si le texte a encore changé, examiner manuellement l'historique. Aucun bouton de reprise aveugle n'est fourni. Un événement restant `SUBMITTING` ou `UNKNOWN_SUBMISSION` empêche la reprise des écritures.

## Révision dépassée

La proposition devient `STALE`. Réanalyser :

```bash
isbn-bot analyze-page "Titre de l'article"
```

La nouvelle proposition conserve la nouvelle révision. Les propositions anciennes ne sont pas fusionnées avec les modifications d'un autre contributeur.

## Verrou restant après arrêt brutal

Le dossier de données contient `run.lock/owner.json`. Vérifier qu'aucun job ne s'exécute (`toolforge jobs list`), arrêter la planification si nécessaire et inspecter l'horodatage. Ensuite seulement, supprimer `owner.json` et le dossier **vide** `run.lock`. Ne pas supprimer la base SQLite.

Le verrou est conservateur : il n'expire pas automatiquement pendant un job long.

## Sauvegarde

Arrêter les jobs et copier le dossier de données, ou utiliser l'API `sqlite3.Connection.backup` pour une sauvegarde cohérente. Ne pas copier seulement un fichier SQLite pendant une transaction. Restaurer uniquement lorsque les jobs sont arrêtés et conserver l'ancien état.

Ne pas lancer plusieurs workers SQLite sur le partage NFS. Pour davantage de concurrence, migrer l'état vers une base serveur supportée sur Toolforge.

## Retour arrière

Le journal `edits` conserve `old_revid`, `new_revid`, le résumé et l'empreinte du texte proposé ; `findings` conserve le texte original et le diff.

En cas de mauvaise correction, arrêter les écritures, ouvrir le diff Wikipédia de la révision enregistrée et utiliser **Annuler** en vérifiant le résultat. Si d'autres contributeurs ont modifié la page, annuler seulement le champ ISBN concerné. La V1 ne fait pas de revert automatique d'un texte complet.

## Notifications

`isbn-bot notify-test` permet de vérifier le SMTP configuré. L'authentification SMTP utilise TLS ; les secrets ne figurent pas dans les rapports. Toolforge `--emails onfailure` fournit une alerte du job séparée de la notification bibliographique.

Un échec d'envoi est consigné en base ; le rapport HTML/JSON reste la référence. Le SMTP n'a pas été configuré ni testé avec une vraie boîte dans cette livraison.
