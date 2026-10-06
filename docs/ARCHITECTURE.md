# Architecture V1/V2

## Chemin de lecture

`cli → WikiClient.category_members → State.sync_memberships → WikiClient.page → extract_fields → Analyzer → State.save_finding → write_reports`

La liste de catégorie est récupérée entièrement avant toute mise à jour des présences. La base enregistre un nouvel événement pour une réentrée constatée ou un changement d'horodatage de catégorie. Le premier snapshot pose une liste de référence, sauf demande explicite de traitement des éléments existants.

Le parseur travaille sur l'AST `mwparserfromhell`. Il conserve les indices des modèles et paramètres, leur nom, la valeur originale et le contexte bibliographique. Le remplacement ne passe pas par une expression régulière globale. Les structures complexes, doublons de paramètres et modèles inconnus sont exclus de la publication.

Les fournisseurs renvoient des notices normalisées avec identifiant, URL et ISBN réellement présents. BnF interroge les titres et identifiants. Open Library consulte les éditions. Sudoc corrobore les identifiants potentiels. Le cache persiste les lectures bibliographiques pendant 24 heures. Les sessions de catalogue et de compte Wikipédia sont distinctes.

Le score compare le titre, les auteurs, l'éditeur, l'année et l'édition/volume. Les contradictions explicites abaissent le score. La similarité numérique d'ISBN est faible. Les équivalents ISBN-10 et ISBN-13 sont regroupés. La présence dans plusieurs catalogues est affichée, mais n'est pas interprétée comme une indépendance éditoriale garantie.

## Chemin d'écriture

`approve → sources présentes + ISBN valide + champ pris en charge → statut APPROVED`

`apply --confirm → configuration d'écriture + accord communautaire + droit bot → révision/catégorie/opt-out → diff minimal → journal SUBMITTING → appel edit unique → EDITED`

Le journal est écrit avant la requête. Une soumission interrompue reste `SUBMITTING` ou `UNKNOWN_SUBMISSION` ; elle n'est pas automatiquement reprise. `reconcile` compare le texte actuel à la cible enregistrée sans reposter.

## État

| Table | Usage |
|---|---|
| `memberships` | Présence actuelle et événement associé |
| `events` | Liste initiale, événements et tentatives d'analyse |
| `findings` | Révision originale, champ, candidats, preuves, diff, approbation |
| `edits` | Intention de publication, empreinte cible, statut, révisions |
| `alerts` | Incidents et état d'envoi des alertes |
| `cache` | Lectures des catalogues |
| `meta` | Liste initiale établie, dernier succès, arrêt persistant |

L'état est local ou dans le home persistant du tool. Un verrou de dossier empêche des opérations simultanées. Un arrêt brutal peut laisser ce verrou ; sa levée est volontaire et documentée.

## Extension

Un fournisseur supplémentaire implémente `search(context, seeds, raw_isbn) → list[Record]` et expose `name`. Il ne reçoit ni compte Wikipédia ni fonction de publication. Un futur LLM devra respecter cette même séparation.
