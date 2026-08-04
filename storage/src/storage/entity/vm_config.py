from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class VmConfigEntity(Base, BaseEntity):
    __tablename__ = "vm_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String, nullable=False, default="default")
    api_token = Column(String, nullable=False, default="")
    vm_name = Column(String, nullable=False, default="")
    work_dir = Column(String, nullable=False, default="")
    ec2_instance_id = Column(String, nullable=False, default="")
    ec2_region = Column(String, nullable=False, default="")
    last_up = Column(Integer, nullable=True)
    # NOTE: the live table still has a `finance_config` jsonb column (NOT NULL
    # DEFAULT '{}'). It is finance domain data that moved to the module-owned
    # `finance_config` table (todo 3020, D8); the expand/contract DROP is the
    # commented last step of modules/finance/migration/001_finance_config.sql.

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
    )
