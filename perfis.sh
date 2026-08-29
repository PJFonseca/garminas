#!/bin/bash
# Corre um comando uma vez por perfil, com GARMIN_DATA_DIR a apontar para o
# diretório de cada um. É assim que a sincronização diária serve a casa toda
# em vez de só a primeira pessoa que se registou.
set -u
raiz="${GARMIN_DATA_DIR_ROOT:-/data}"

python3 -c "import sys; sys.path.insert(0,'/opt/coach'); import perfis; perfis.migrar()" 2>/dev/null || true

perfis=$(ls -1 "$raiz/perfis" 2>/dev/null || true)
if [ -z "$perfis" ]; then
  echo "Sem perfis em $raiz/perfis. Configura o primeiro na página web."
  exit 0
fi

falhas=0
for p in $perfis; do
  [ -d "$raiz/perfis/$p" ] || continue
  echo "=== $p ==="
  GARMIN_DATA_DIR="$raiz/perfis/$p" "$@" || { echo "$p: falhou"; falhas=$((falhas+1)); }
done
exit $((falhas > 0))
