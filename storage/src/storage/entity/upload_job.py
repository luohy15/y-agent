from sqlalchemy import Column, Integer, BigInteger, String, Boolean, ForeignKey, Index, UniqueConstraint
from storage.entity.base import Base, BaseEntity


class UploadJobEntity(Base, BaseEntity):
    __tablename__ = "upload_job"
    __table_args__ = (
        UniqueConstraint("user_id", "upload_id"),
        Index("ix_upload_job_batch_id", "batch_id"),
        Index("ix_upload_job_user_status", "user_id", "status"),
        Index("ix_upload_job_status_enqueued", "status", "last_enqueued_at_unix"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    upload_id = Column(String(36), nullable=False)
    batch_id = Column(String(36), nullable=False)
    vm_name = Column(String, nullable=False)
    work_dir = Column(String, nullable=False)
    dest_dir = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    expected_checksum_sha256_b64 = Column(String(44), nullable=False)
    staging_key = Column(String, nullable=False)
    staging_version_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="authorized")
    attempts = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at_unix = Column(BigInteger, nullable=True)
    last_enqueued_at_unix = Column(BigInteger, nullable=True)
    overwrite_ack = Column(Boolean, nullable=False, default=False)
    error = Column(String, nullable=True)
    staged_at = Column(String, nullable=True)
    saved_at = Column(String, nullable=True)
