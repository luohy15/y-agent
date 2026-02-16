from sqlalchemy import Column, Integer, String, ForeignKey
from .base import Base, BaseEntity


class VmConfigEntity(Base, BaseEntity):
    __tablename__ = "vm_config"

    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    api_token = Column(String, nullable=False, default="")
    vm_name = Column(String, nullable=False, default="")
    work_dir = Column(String, nullable=False, default="")
