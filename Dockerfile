# syntax=docker/dockerfile:1

FROM caddy:alpine

COPY out /srv

COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8080
