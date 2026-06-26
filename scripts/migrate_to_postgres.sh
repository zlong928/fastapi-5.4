#!/usr/bin/env bash
set -euo pipefail

echo "==========================================="
echo "  SQLite → PostgreSQL Migration Assistant"
echo "==========================================="
echo ""

POSTGRES_USER="${POSTGRES_USER:-fastapi_user}"
POSTGRES_PASS="${POSTGRES_PASS:-fastapi_pass}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-fastapi_app}"

PG_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASS}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo "Target PostgreSQL: ${PG_URL}"
echo ""

# Step 1: Ensure PostgreSQL is running
echo "[1/5] Checking PostgreSQL connection..."
if command -v pg_isready &>/dev/null; then
    pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" 2>/dev/null || {
        echo "  PostgreSQL not reachable. Start it with: docker compose up -d postgres"
        exit 1
    }
else
    echo "  pg_isready not found, attempting direct connection..."
    python3 -c "from sqlalchemy import create_engine; create_engine('${PG_URL}').connect()" 2>/dev/null || {
        echo "  Cannot connect to PostgreSQL. Start it with: docker compose up -d postgres"
        exit 1
    }
fi
echo "  ✓ PostgreSQL is running"

# Step 2: Create tables from SQLAlchemy models
echo ""
echo "[2/5] Creating target tables..."
DATABASE_URL="${PG_URL}" python3 -c "
from app.db.session import create_db_and_tables
create_db_and_tables()
print('  ✓ Tables created')
"
echo "  ✓ Tables created"

# Step 3: Migrate data
echo ""
echo "[3/5] Migrating data..."
echo "  Method: pgloader (recommended) or Python fallback"

if command -v pgloader &>/dev/null; then
    echo "  Using pgloader..."
    pgloader scripts/migrate_with_pgloader.load
    echo "  ✓ pgloader migration complete"
else
    echo "  pgloader not found, using Python script..."
    DATABASE_URL="${PG_URL}" python3 scripts/migrate_sqlite_to_postgres.py
    echo "  ✓ Python migration complete"
fi

# Step 4: Verify data
echo ""
echo "[4/5] Verifying migration..."
python3 -c "
from sqlalchemy import create_engine, inspect, text

src = create_engine('sqlite:///./data/app.db', connect_args={'check_same_thread': False})
tgt = create_engine('${PG_URL}')

src_inspector = inspect(src)
tgt_inspector = inspect(tgt)

tables = [t for t in src_inspector.get_table_names() if t not in ('alembic_version', 'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4')]
all_ok = True
for table in sorted(tables):
    src_count = src.connect().execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
    tgt_count = tgt.connect().execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
    status = '✓' if src_count == tgt_count else '✗'
    print(f'  {status} {table}: {src_count} → {tgt_count} rows')
    if src_count != tgt_count:
        all_ok = False

if all_ok:
    print()
    print('  ✓ All tables match!')
else:
    print()
    print('  ⚠ Some tables have mismatched row counts — check above')
"

# Step 5: Generate Alembic baseline
echo ""
echo "[5/5] Generating Alembic baseline migration..."
DATABASE_URL="${PG_URL}" alembic revision --autogenerate -m "initial_postgres_migration" 2>/dev/null || {
    echo "  (skip if already exists — run 'alembic stamp head' to mark current state)"
}
DATABASE_URL="${PG_URL}" alembic stamp head 2>/dev/null || true

echo ""
echo "==========================================="
echo "  Migration complete!"
echo ""
echo "  To start using PostgreSQL:"
echo "    export DATABASE_URL=${PG_URL}"
echo "    uvicorn app.main:app --reload"
echo ""
echo "  To revert (keep SQLite):"
echo "    export DATABASE_URL=sqlite:///./data/app.db"
echo "==========================================="
