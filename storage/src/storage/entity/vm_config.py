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

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
    )
