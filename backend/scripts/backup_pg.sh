#!/usr/bin/env bash
# Backup logico do PostgreSQL (pg_dump, formato custom, comprimido) com rotacao.
#
# Uso:   DATABASE_URL='postgresql://...' ./scripts/backup_pg.sh [diretorio] [dias_de_retencao]
# Restaurar:  pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" arquivo.dump
#
# Complementa (nao substitui) o backup/PITR do proprio Neon -- ideal para ter uma
# copia FORA do provedor (ex.: enviar o .dump para um bucket S3/R2/Backblaze).
set -euo pipefail

: "${DATABASE_URL:?defina DATABASE_URL}"
DESTINO="${1:-./backups}"
RETENCAO_DIAS="${2:-14}"

# pg_dump nao entende o prefixo "+psycopg2" do SQLAlchemy.
URL="${DATABASE_URL/postgresql+psycopg2:/postgresql:}"
URL="${URL/postgres:\/\//postgresql://}"

mkdir -p "$DESTINO"
ARQUIVO="$DESTINO/eletrogestor_$(date -u +%Y%m%d_%H%M%S).dump"

pg_dump --format=custom --no-owner --no-privileges --file="$ARQUIVO" "$URL"
# Valida que o arquivo e' legivel antes de considerar o backup bom.
pg_restore --list "$ARQUIVO" > /dev/null
chmod 600 "$ARQUIVO"
echo "backup ok: $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"

find "$DESTINO" -name 'eletrogestor_*.dump' -mtime +"$RETENCAO_DIAS" -print -delete
