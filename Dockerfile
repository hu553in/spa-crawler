# syntax=docker/dockerfile:1

FROM caddy:alpine

COPY out/pages /srv/pages
COPY out/assets /srv/assets

COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8080
