# Install Notes

This document preserves essential setup information formerly stored in `install/` (excluding shell scripts), for open-source distribution.

## Docker Services

### OnlyOffice Document Server

```bash
docker run -d \
  --name onlyoffice-docs \
  --restart=always \
  -p 8081:80 \
  -v /data/onlyoffice/logs:/var/log/onlyoffice \
  -v /data/onlyoffice/data:/var/www/onlyoffice/Data \
  onlyoffice/documentserver:9.2
```

### Draw.io Export Server

```bash
docker run -d \
  --name drawio-export \
  -p 8025:8000 \
  jgraph/export-server
```

### Kroki + Excalidraw

```bash
docker compose -f install/kroki-compose.yml up -d
```

Kroki endpoint (local):

```
http://127.0.0.1:8004
```

### PostgreSQL

```bash
docker run -d \
  --name pgsql-container-5618 \
  -p 5618:5432 \
  -e POSTGRES_PASSWORD=844700 \
  -e POSTGRES_USER=root \
  -e POSTGRES_DB=queen \
  postgres:16.0
```

#### pgvector (required)

```bash
docker exec pgsql-container-5618 bash -lc "apt-get update && apt-get install -y postgresql-16-pgvector"
docker exec pgsql-container-5618 psql -U root -d queen -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Redis

```bash
docker run -d \
  --name redis \
  -p 6379:6379 \
  --restart=always \
  redis:7
```

## Kroki Compose (Reference)

```yaml
services:
  kroki:
    image: yuzutech/kroki
    depends_on:
      - excalidraw
    environment:
      - KROKI_EXCALIDRAW_HOST=excalidraw
      - KROKI_EXCALIDRAW_PORT=8004
    ports:
      - "8004:8000"
    tmpfs:
      - /tmp:exec
  excalidraw:
    image: yuzutech/kroki-excalidraw
    expose:
      - "8004"
```

## Nginx Reverse Proxy (Reference)

```nginx
server {
    listen 80;
    server_name queenbeecai.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name queenbeecai.com;

    ssl_certificate     /home/queenbeecai.com_nginx/queenbeecai.com_nginx/queenbeecai.com_bundle.crt;
    ssl_certificate_key /home/queenbeecai.com_nginx/queenbeecai.com_nginx/queenbeecai.com.key;

    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 100M;

    # Safer defaults
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    location /web-apps/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /doc/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /cache/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /coauthoring/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /hosting/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location ~ ^/\d+\.\d+\.\d+-[^/]+/ {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
