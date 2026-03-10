from sqlalchemy import Column, Integer, BigInteger, String, Boolean
from .base import Base, BaseEntity


class UserEntity(Base, BaseEntity):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    hashed_password = Column(String(255), nullable=True)
    deleted = Column(Boolean, default=False, nullable=False)
    telegram_id = Column(BigInteger, nullable=True, unique=True, index=True)

    def set_password(self, password: str) -> None:
        import bcrypt
        self.hashed_password = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def verify_password(self, password: str) -> bool:
        if not self.hashed_password:
            return False
        import bcrypt
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.hashed_password.encode('utf-8')
        )

    def is_anonymous(self) -> bool:
        return self.hashed_password is None and self.email is None

    @staticmethod
    def parse_user_id(user_id: str) -> dict:
        """Parse username and email from user_id like 'hash_name_at_domain_dot_com'.

        Returns dict with 'username' and 'email' keys (None if not parseable).
        """
        result = {'username': None, 'email': None}
        # Find first underscore separating hash from the rest
        idx = user_id.find('_')
        if idx == -1 or '_at_' not in user_id:
            return result
        after_hash = user_id[idx + 1:]
        at_idx = after_hash.find('_at_')
        if at_idx == -1:
            return result
        result['username'] = after_hash[:at_idx]
        result['email'] = after_hash.replace('_at_', '@').replace('_dot_', '.')
        return result
