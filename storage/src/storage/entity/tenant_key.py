from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String, UniqueConstraint

from .base import Base, BaseEntity


class TenantKeyEntity(Base, BaseEntity):
    """Per-tenant DEK wrapped by the server-held master key. Absent rows stay plaintext."""

    __tablename__ = "tenant_key"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    key_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    wrapped_dek = Column(LargeBinary, nullable=False)
    wrap_nonce = Column(LargeBinary, nullable=False)
    bidx_wrapped = Column(LargeBinary, nullable=False)
    bidx_nonce = Column(LargeBinary, nullable=False)
    master_key_id = Column(String, nullable=False, default="")
    kms_key_arn = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "key_id", name="uq_tenant_key_id"),
    )
