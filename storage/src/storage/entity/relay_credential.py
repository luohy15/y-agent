from sqlalchemy import Column, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint

from storage.entity.base import Base, BaseEntity


class RelayCredentialEntity(Base, BaseEntity):
    """One sealed relay key for a user and relay origin.

    ``api_key`` is plaintext only in memory. With a tenant key it is stored as a
    ``yenc:v1`` envelope (``enc_version=1``); a keyless row stays plaintext
    (``enc_version=0``). Responses never return this column.
    """

    __tablename__ = "relay_credential"

    id = Column(Integer, primary_key=True, autoincrement=True)
    credential_id = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    relay_origin = Column(String, nullable=False)
    relay_key_id = Column(String, nullable=False, default="")
    key_name = Column(String, nullable=False)
    billing_mode = Column(String, nullable=False, default="real")
    api_key = Column(Text, nullable=False)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "relay_origin", name="uq_relay_credential_user_origin"),
    )
