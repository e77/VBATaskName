FROM nginx:1.25-alpine

COPY frontend/public /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1
