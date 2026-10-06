# Démarrer sur Wikimedia Toolforge

Guide préparé à partir de la documentation officielle consultée les 5 et 6 octobre 2026. État des comptes vérifié le 6 octobre 2026.

## 1. Comptes

- Compte Wikipédia opérateur : **Mésange_Futée**.
- Compte développeur : **Mésange Futée** ; nom UNIX : **mesangefutee**.
- Phabricator associé : **Mesange_Futee**.
- [Demande Toolforge n° 2391](https://toolsadmin.wikimedia.org/tools/membership/status/2391) : **Approved**.
- [Compte outil mesange-isbn-bot](https://toolsadmin.wikimedia.org/tools/id/mesange-isbn-bot) : **créé**, licence MIT, mainteneur Mésange Futée.

L'installation du code et le lancement des jobs restent à faire. Ajouter sa **clé SSH publique** dans la console ; aucune clé n'était enregistrée au moment de cette vérification. Conserver la clé privée sur son ordinateur.

L'inscription indique que l'adresse du compte développeur sera visible publiquement. Choisir une adresse adaptée à cet usage ; aucune adresse personnelle n'est préremplie dans le projet.

### Clé SSH depuis Windows / PowerShell

Ouvrir PowerShell sur son ordinateur et exécuter ces commandes. Elles réutilisent la clé dédiée si elle existe déjà ; sinon `ssh-keygen` demande de choisir sa phrase de passe dans le terminal.

```powershell
$toolforgeKeyPath = Join-Path $env:USERPROFILE '.ssh\id_ed25519_toolforge'
New-Item -ItemType Directory -Force -Path (Split-Path $toolforgeKeyPath) | Out-Null
if (-not (Test-Path -LiteralPath $toolforgeKeyPath)) {
    ssh-keygen -t ed25519 -f $toolforgeKeyPath -C 'mesangefutee@toolforge'
}
Get-Content -LiteralPath "$toolforgeKeyPath.pub"
```

Copier uniquement la ligne publique affichée dans **Public key**, sur [la page des clés SSH](https://toolsadmin.wikimedia.org/profile/settings/ssh-keys/), puis cliquer sur **Add SSH key**. Le fichier sans extension `.pub` est la clé privée et reste sur son ordinateur.

Connexion depuis ce même PowerShell :

```powershell
ssh -i $toolforgeKeyPath -o 'HostKeyAlgorithms=ssh-ed25519' mesangefutee@login.toolforge.org
```

Au premier accès, comparer l'empreinte du **serveur** avec [la page officielle des empreintes SSH](https://wikitech.wikimedia.org/wiki/Help:SSH_Fingerprints/login.toolforge.org). L'empreinte ED25519 publiée lors de la consultation est :

```text
SHA256:0i1eqK9uOYmCjOe5a0oAWTmnEPUh0b7h2Flm1IDl0sg
```

Une fois connecté, exécuter `become mesange-isbn-bot` pour travailler sous le compte outil.

### Connexion depuis Linux / macOS

Connexion depuis son ordinateur :

```bash
ssh -i ~/.ssh/id_ed25519_toolforge mesangefutee@login.toolforge.org
become mesange-isbn-bot
```

`mesangefutee` est l'identifiant shell confirmé du compte développeur.

## 2. Méthode recommandée : Build Service

Le dépôt GitHub public du projet est [PonsMatthieu/wikipedia-isbn-bot](https://github.com/PonsMatthieu/wikipedia-isbn-bot). Le projet est sous licence MIT. Le dépôt doit comprendre `Procfile`, `.python-version`, `requirements.txt`, `pyproject.toml` et `src/`.

Ne pas publier `.env`, les bases de données ni les rapports réels. Le `.gitignore` fourni les exclut.

Le dépôt contient les fichiers du projet à sa racine : `Procfile`, `pyproject.toml`, `requirements.txt` et `src/`. Aucun dépôt manuel de fichiers n’est nécessaire.

### Premier lancement avec GitHub, en une commande

Après connexion SSH, exécuter `become mesange-isbn-bot`, puis copier ce bloc :

```bash
git clone https://github.com/PonsMatthieu/wikipedia-isbn-bot.git
cd wikipedia-isbn-bot
bash deploy/toolforge/start-build.sh
```

Le script lit l'URL GitHub du dépôt cloné, construit l'image, configure la lecture seule, initialise la base, fait le premier relevé et demande la surveillance horaire. Il conserve les données et arrête les étapes suivantes si une commande échoue. Il refuse de remplacer des jobs ISBN existants. Les commandes détaillées ci-dessous permettent de comprendre et de reprendre chaque étape.

L'accès SSH reste nécessaire pour ce premier lancement. Le dépôt GitHub et son téléchargement ne lancent pas à eux seuls le bot sur Toolforge. Le service de déploiement continu Toolforge permet ensuite des mises à jour depuis une CI, après une configuration initiale et la création d'un jeton ; ce parcours est facultatif.

Sous le compte du tool :

```bash
toolforge build start URL_DU_DEPOT_GIT_PUBLIC
toolforge build show
```

Attendre un build réussi. Pour un tool appelé `mesange-isbn-bot`, l'image habituelle est `tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest` ; reprendre le nom d'image exact annoncé par le build.

Créer la configuration sans secret :

```bash
toolforge envvars create BOT_OPERATOR 'Mésange_Futée'
toolforge envvars create BOT_MODE DRY_RUN
toolforge envvars create BOT_WRITE_ENABLED false
toolforge envvars create BOT_COMMUNITY_APPROVED false
toolforge envvars create BOT_MAX_PAGES 20
toolforge envvars create BOT_SOURCES bnf,sudoc,openlibrary
```

Un compte de bot n'est pas nécessaire pour lire les API publiques. Initialiser puis lancer le premier snapshot :

```bash
toolforge jobs run isbn-init --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest --command 'manage-isbn init' --mount all --wait
toolforge jobs run isbn-first --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest --command scan-isbn --mount all --wait
```

Le premier snapshot constitue la liste de référence. Pour un petit pilote sur des articles existants :

```bash
toolforge jobs run isbn-pilot --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest --command 'scan-isbn --process-existing' --mount all --wait
```

Puis planifier la surveillance :

```bash
toolforge jobs run isbn-hourly --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest --command scan-isbn --mount all --schedule '@hourly' --timeout 3300 --emails onfailure
toolforge jobs list
toolforge jobs logs isbn-hourly
```

Le script `deploy/toolforge/schedule-build.sh` crée ce job en prenant le nom du tool en argument. Il faut que le job `isbn-hourly` n'existe pas déjà.

**`--mount all` est nécessaire** pour conserver SQLite et les rapports entre les runs. Le code utilise `TOOL_DATA_DIR`, pas le HOME du conteneur. Les données vivent dans `/data/project/NOM_DU_TOOL/isbn-bot/`.

SQLite est prévu pour **un seul worker**. Le projet utilise un journal rollback plutôt que WAL et un verrou de dossier. Ne pas lancer plusieurs réplicas ; migrer vers une base serveur si le besoin évolue.

## 3. Alternative : transférer le dossier sans dépôt Git

Copier `wikipedia-isbn-bot/` dans le home du tool par SFTP ou depuis son ordinateur :

```bash
scp -i ~/.ssh/id_ed25519_toolforge -r wikipedia-isbn-bot mesangefutee@login.toolforge.org:/data/project/mesange-isbn-bot/
```

Depuis PowerShell, dans le répertoire parent du dossier décompressé :

```powershell
$toolforgeKeyPath = Join-Path $env:USERPROFILE '.ssh\id_ed25519_toolforge'
scp -i $toolforgeKeyPath -r .\wikipedia-isbn-bot mesangefutee@login.toolforge.org:/data/project/mesange-isbn-bot/
```

Selon les permissions de votre compte, passer par SFTP et vérifier que le compte du tool peut lire les fichiers. Après `become mesange-isbn-bot` :

```bash
cd "$HOME/wikipedia-isbn-bot"
cp .env.example .env
chmod 600 .env
chmod +x deploy/toolforge/*.sh
toolforge jobs run isbn-bootstrap --image python3.13 --command "$HOME/wikipedia-isbn-bot/deploy/toolforge/bootstrap.sh" --wait
toolforge jobs run isbn-first --image python3.13 --command "$HOME/wikipedia-isbn-bot/deploy/toolforge/run.sh run" --wait
toolforge jobs run isbn-hourly --image python3.13 --command "$HOME/wikipedia-isbn-bot/deploy/toolforge/run.sh run" --schedule '@hourly' --timeout 3300 --emails onfailure
```

La création du venv se fait **dans le job**, avec la même image que celle d'exécution, pas directement sur le bastion. Les scripts fournis doivent être exécutables (`chmod +x deploy/toolforge/*.sh` si nécessaire).

## 4. Récupérer le rapport

Pour la méthode Build Service, depuis son ordinateur :

```bash
scp -i ~/.ssh/id_ed25519_toolforge mesangefutee@login.toolforge.org:/data/project/mesange-isbn-bot/isbn-bot/reports/report.html .
scp -i ~/.ssh/id_ed25519_toolforge mesangefutee@login.toolforge.org:/data/project/mesange-isbn-bot/isbn-bot/reports/report.json .
```

Ouvrir ensuite le HTML localement. Les données appartiennent au compte du tool ; si votre compte personnel ne peut pas les lire, utiliser les permissions de groupe appropriées ou les copier sous `become` vers un emplacement que vous contrôlez. Le code crée ses fichiers avec des permissions restrictives.

Pour consulter l'état via un buildpack :

```bash
toolforge jobs run isbn-status --image tool-mesange-isbn-bot/tool-mesange-isbn-bot:latest --command 'manage-isbn status' --mount all --wait
```

## 5. SMTP et publication, ultérieurement

Ajouter les secrets avec la saisie masquée :

```bash
toolforge envvars create MAIL_PASSWORD
toolforge envvars create WIKI_BOT_PASSWORD
```

Ne pas fournir les secrets comme arguments de commande. Les nouveaux jobs prendront la nouvelle configuration. Les variables d'environnement de Toolforge s'appliquent aussi aux jobs ; pour la méthode du venv, `.env` peut servir de configuration locale avec les variables injectées prioritaires.

Activer la publication seulement après le parcours communautaire de `GOUVERNANCE.md`. `run` reste une commande d'analyse même lorsque l'écriture est activée : la publication exige un job explicite `manage-isbn apply ID --confirm`.

Le compte développeur, l'association Phabricator, l'adhésion Toolforge et le compte outil ont été vérifiés et créés. Le code est publié sur GitHub. L'accès SSH, le build distant, les jobs et l'envoi SMTP restent à configurer. La publication du dépôt ne lance aucun job sur Toolforge.
