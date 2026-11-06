from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from storage.database.base import get_db
from storage.entity.skill_share import SkillBundleEntity, SkillPinEntity


def publish(user_id, name, digest, manifest, version, nodes):
    with get_db() as session:
        session.execute(text('SELECT pg_advisory_xact_lock(4232, :owner)'), {'owner': user_id})
        session.execute(insert(SkillBundleEntity).values(
            user_id=user_id, name=name, bundle_sha=digest, manifest=manifest, version=version,
        ).on_conflict_do_nothing(index_elements=['user_id', 'name', 'bundle_sha']))
        # A publish replaces this skill's complete target set atomically.
        session.execute(delete(SkillPinEntity).where(SkillPinEntity.user_id == user_id, SkillPinEntity.name == name))
        for node in nodes:
            session.add(SkillPinEntity(user_id=user_id, name=name, node=node, bundle_sha=digest))
        session.commit()


def list_pins(user_id, node=None):
    with get_db() as session:
        query = select(SkillPinEntity, SkillBundleEntity).join(SkillBundleEntity, (
            (SkillBundleEntity.user_id == SkillPinEntity.user_id)
            & (SkillBundleEntity.name == SkillPinEntity.name)
            & (SkillBundleEntity.bundle_sha == SkillPinEntity.bundle_sha)
        )).where(SkillPinEntity.user_id == user_id)
        if node is not None:
            query = query.where(SkillPinEntity.node == node)
        return [{'name': pin.name, 'node': pin.node, 'bundle_sha': pin.bundle_sha,
                 'manifest': bundle.manifest, 'version': bundle.version}
                for pin, bundle in session.execute(query.order_by(SkillPinEntity.name, SkillPinEntity.node))]


def unshare(user_id, name):
    with get_db() as session:
        session.execute(text('SELECT pg_advisory_xact_lock(4232, :owner)'), {'owner': user_id})
        session.execute(delete(SkillPinEntity).where(SkillPinEntity.user_id == user_id, SkillPinEntity.name == name))
        session.commit()
