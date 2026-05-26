-- ============================================
-- RealView — DDL de base de datos
-- ============================================

-- Tabla de control de ejecuciones ETL
CREATE TABLE IF NOT EXISTS etl_jobs (
    id              SERIAL PRIMARY KEY,
    filename        VARCHAR(500) NOT NULL,
    dataset         VARCHAR(100) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    rows_read       INTEGER DEFAULT 0,
    rows_loaded     INTEGER DEFAULT 0,
    rows_rejected   INTEGER DEFAULT 0,
    error           TEXT,
    file_hash       VARCHAR(64),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_etl_jobs_status ON etl_jobs(status);
CREATE INDEX IF NOT EXISTS idx_etl_jobs_dataset ON etl_jobs(dataset);
CREATE INDEX IF NOT EXISTS idx_etl_jobs_file_hash ON etl_jobs(file_hash);

-- Catálogo de datasets registrados
CREATE TABLE IF NOT EXISTS dataset_config (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) UNIQUE NOT NULL,
    table_name      VARCHAR(100) NOT NULL,
    file_pattern    VARCHAR(200),
    column_mapping  JSONB,
    schema_def      JSONB,
    active          INTEGER DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);

-- ============================================
-- Ejemplo: tabla de shipments (cargas/envíos)
-- ============================================
CREATE TABLE IF NOT EXISTS shipments (
    id              SERIAL PRIMARY KEY,
    shipment_id     VARCHAR(100) UNIQUE NOT NULL,
    origin          VARCHAR(200),
    destination     VARCHAR(200),
    weight_kg       NUMERIC(10,2),
    volume_m3       NUMERIC(10,2),
    status          VARCHAR(50),
    carrier         VARCHAR(200),
    client_name     VARCHAR(200),
    departure_date  DATE,
    arrival_date    DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_departure ON shipments(departure_date);
CREATE INDEX IF NOT EXISTS idx_shipments_client ON shipments(client_name);
