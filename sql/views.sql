-- ============================================
-- RealView — Vistas para Power BI (DirectQuery)
-- ============================================

-- Vista: resumen de envíos por mes
CREATE OR REPLACE VIEW v_shipments_monthly AS
SELECT
    DATE_TRUNC('month', departure_date)::DATE AS month,
    COUNT(*)                                   AS total_shipments,
    COUNT(*) FILTER (WHERE status = 'delivered') AS delivered,
    COUNT(*) FILTER (WHERE status = 'in_transit') AS in_transit,
    COUNT(*) FILTER (WHERE status = 'pending')    AS pending,
    SUM(weight_kg)                             AS total_weight,
    SUM(volume_m3)                             AS total_volume
FROM shipments
GROUP BY DATE_TRUNC('month', departure_date)
ORDER BY month DESC;

-- Vista: top clientes por volumen
CREATE OR REPLACE VIEW v_top_clients AS
SELECT
    client_name,
    COUNT(*)              AS total_shipments,
    SUM(weight_kg)        AS total_weight,
    SUM(volume_m3)        AS total_volume,
    AVG(weight_kg)        AS avg_weight,
    MAX(departure_date)   AS last_shipment_date
FROM shipments
GROUP BY client_name
ORDER BY total_shipments DESC;

-- Vista: tracking de últimas ejecuciones ETL
CREATE OR REPLACE VIEW v_etl_status AS
SELECT
    id,
    filename,
    dataset,
    status,
    rows_read,
    rows_loaded,
    rows_rejected,
    error,
    started_at,
    finished_at,
    CASE
        WHEN status = 'success' THEN '✅'
        WHEN status = 'failed'  THEN '❌'
        ELSE '⏳'
    END AS status_icon
FROM etl_jobs
ORDER BY started_at DESC
LIMIT 100;

-- Vista: tabla plana de envíos para Power BI (DirectQuery)
CREATE OR REPLACE VIEW v_shipments_flat AS
SELECT
    shipment_id,
    origin,
    destination,
    weight_kg,
    volume_m3,
    status,
    carrier,
    client_name,
    departure_date,
    arrival_date,
    EXTRACT(DAY FROM (arrival_date - departure_date)) AS transit_days,
    CASE
        WHEN status = 'delivered' THEN 100
        WHEN status = 'in_transit' THEN 50
        WHEN status = 'pending' THEN 10
        ELSE 0
    END AS progress_pct,
    created_at,
    updated_at
FROM shipments;
