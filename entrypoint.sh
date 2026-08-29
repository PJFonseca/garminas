#!/bin/bash
# Verbos da imagem. Sem argumentos corre o cron, que é o modo normal.
#
#   docker compose run --rm garmin setup    escolher e descarregar o modelo
#   docker compose run --rm garmin auth     autenticar na Garmin (interativo)
#   docker compose run --rm garmin report   gerar o relatório agora
#
# O serviço web corre o verbo 'web' e serve a configuração e os relatórios.
#
set -e

case "${1:-cron}" in
  setup)
    exec python3 /opt/coach/setup.py
    ;;
  auth)
    # Chrome real sob display virtual: é assim que se passa a Cloudflare.
    exec xvfb-run -a garmin-givemydata --full
    ;;
  sync)
    shift
    exec xvfb-run -a garmin-givemydata "$@"
    ;;
  web)
    exec python3 /opt/coach/web.py
    ;;
  report)
    exec python3 /opt/coach/coach.py
    ;;
  metrics)
    shift
    exec python3 /opt/coach/metrics.py "$@"
    ;;
  status)
    exec garmin-givemydata --status
    ;;
  cron)
    if [ ! -f /data/garmin.db ]; then
      echo "Sem base de dados em /data/garmin.db."
      echo "Corre primeiro:  docker compose run --rm garmin auth"
    fi
    # Caminho absoluto de proposito: como PID 1 o supercronic re-executa
    # argv[0] para ceifar processos orfaos, e um nome sem caminho falha.
    exec /usr/local/bin/supercronic /etc/crontab.garmin
    ;;
  *)
    exec "$@"
    ;;
esac
