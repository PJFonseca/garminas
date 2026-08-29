FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    GARMIN_DATA_DIR=/data \
    TZ=Europe/Lisbon \
    PYTHONUNBUFFERED=1

# O apt dentro do build tenta IPv6 primeiro e fica 30 s a espera por cada
# pacote em redes so-IPv4, o que faz o build parecer pendurado. Forcar IPv4 e
# insistir algumas vezes resolve, e nao custa nada em redes saudaveis.
RUN printf 'Acquire::ForceIPv4 "true";\nAcquire::Retries "5";\nAcquire::http::Timeout "20";\n' \
      > /etc/apt/apt.conf.d/99-build-network

# Dependencias de sistema: Chrome (necessario para o SeleniumBase UC mode),
# Xvfb (display virtual, o container nao tem ecra) e bibliotecas graficas.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tzdata procps sqlite3 \
      xvfb xauth \
      fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
      libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-xcb1 \
      libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# supercronic: cron em foreground, bem comportado em containers
ARG SUPERCRONIC_VERSION=v0.2.33
RUN curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic

RUN pip install --no-cache-dir garmin-givemydata pyyaml flask markdown

COPY coach/ /opt/coach/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /opt/coach/*.py /entrypoint.sh

WORKDIR /data
COPY crontab /etc/crontab.garmin

ENTRYPOINT ["/entrypoint.sh"]
CMD ["cron"]
