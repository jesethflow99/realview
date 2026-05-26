from sqlalchemy import Column, Integer, String, DateTime, Float, Text, JSON, Index
from sqlalchemy.sql import func
from src.db.connection import Base


class ETLJob(Base):
    __tablename__ = "etl_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    dataset = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    rows_read = Column(Integer, default=0)
    rows_loaded = Column(Integer, default=0)
    rows_rejected = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_etl_jobs_status", "status"),
        Index("idx_etl_jobs_dataset", "dataset"),
        Index("idx_etl_jobs_file_hash", "file_hash"),
    )


class DatasetConfig(Base):
    __tablename__ = "dataset_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    table_name = Column(String(100), nullable=False)
    file_pattern = Column(String(200), nullable=True)
    column_mapping = Column(JSON, nullable=True)
    schema_def = Column(JSON, nullable=True)
    active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
