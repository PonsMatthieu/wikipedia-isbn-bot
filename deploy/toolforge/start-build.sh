#!/usr/bin/env bash
# Premier lancement sous le compte outil, après publication sur GitHub.
set -euo pipefail

tool_name='mesange-isbn-bot'
repo_url="${1:-}"
if [[ -z "$repo_url" ]]; then
    repo_url="$(git config --get remote.origin.url || true)"
fi
if [[ ! "$repo_url" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$ ]]; then
    echo 'Usage : bash deploy/toolforge/start-build.sh https://github.com/COMPTE/DEPOT' >&2
    exit 2
fi
if [[ "$(id -un)" != "tools.${tool_name}" ]]; then
    echo "Exécuter d'abord : become ${tool_name}" >&2
    exit 2
fi
command -v toolforge >/dev/null || {
    echo 'Le client toolforge est nécessaire sur login.toolforge.org.' >&2
    exit 2
}

# Ne pas remplacer des jobs déjà configurés. Une erreur de lecture arrête le script.
existing_jobs="$(toolforge jobs list)"
if [[ "$existing_jobs" =~ (^|[^[:alnum:]_-])isbn-(init|first|hourly)([^[:alnum:]_-]|$) ]]; then
    echo 'Un job ISBN existe déjà. Consulter toolforge jobs list avant de relancer.' >&2
    exit 2
fi

echo '1/4 Construction du conteneur ; attendre la fin du build.'
toolforge build start "$repo_url"

echo '2/4 Configuration de la lecture seule.'
toolforge envvars create BOT_OPERATOR 'Mésange_Futée'
toolforge envvars create BOT_MODE DRY_RUN
toolforge envvars create BOT_WRITE_ENABLED false
toolforge envvars create BOT_COMMUNITY_APPROVED false
toolforge envvars create BOT_MAX_PAGES 20
toolforge envvars create BOT_SOURCES bnf,sudoc,openlibrary

image="tool-${tool_name}/tool-${tool_name}:latest"
echo '3/4 Initialisation et premier relevé de la catégorie.'
toolforge jobs run isbn-init --image "$image" --command 'manage-isbn init' --mount all --wait 600
toolforge jobs run isbn-first --image "$image" --command scan-isbn --mount all --wait 3300

echo '4/4 Création de la surveillance horaire.'
toolforge jobs run isbn-hourly --image "$image" --command scan-isbn --mount all \
    --schedule '@hourly' --timeout 3300 --emails onfailure
toolforge jobs list
echo 'Vérifier le premier relevé avec : toolforge jobs logs isbn-first'
echo 'Rapports : /data/project/mesange-isbn-bot/isbn-bot/reports/'
echo 'Le premier relevé constitue la référence ; les passages suivants analysent les ajouts.'
