#!/usr/bin/env bash
# À lancer après un build réussi, sous le compte du tool.
set -euo pipefail
tool_name="${1:?Usage: bash schedule-build.sh NOM_DU_TOOL}"
if [[ ! "$tool_name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "Nom de tool invalide" >&2
    exit 2
fi
toolforge jobs run isbn-hourly \
  --image "tool-${tool_name}/tool-${tool_name}:latest" \
  --command scan-isbn --mount all --schedule '@hourly' \
  --timeout 3300 --emails onfailure
