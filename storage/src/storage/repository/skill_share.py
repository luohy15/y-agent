from sqlalchemy import select, text
from storage.database.base import get_db
from storage.entity.skill_share import SkillEntity, SkillVersionEntity, SkillInstallEntity
from storage.skill_bundle import version_key


class SkillNotFound(ValueError):
    pass


class SkillConflict(ValueError):
    pass


def _lock(session, user_id):
    session.execute(text('SELECT pg_advisory_xact_lock(4232, :owner)'), {'owner': user_id})


def _version(row):
    return {key: getattr(row, key) for key in
            ('name', 'version', 'bundle_sha', 'manifest', 'source_commit', 'source_repo')}


def publish(user_id, name, digest, manifest, version, source_commit, source_repo):
    with get_db() as session:
        _lock(session, user_id)
        row = session.query(SkillVersionEntity).filter_by(user_id=user_id, name=name, version=version).first()
        if row:
            if row.bundle_sha != digest:
                raise SkillConflict('skill_version_conflict')
            return {**_version(row), 'created': False}
        row = SkillVersionEntity(user_id=user_id, name=name, version=version, bundle_sha=digest,
                                 manifest=manifest, source_commit=source_commit, source_repo=source_repo)
        session.add(row)
        skill = session.query(SkillEntity).filter_by(user_id=user_id, name=name).first()
        if not skill:
            skill = SkillEntity(user_id=user_id, name=name, latest_version=version)
            session.add(skill)
        elif version_key(version) > version_key(skill.latest_version):
            skill.latest_version = version
        session.commit()
        return {**_version(row), 'created': True}


def list_skills(user_id):
    with get_db() as session:
        return [{'name': row.name, 'latest_version': row.latest_version}
                for row in session.query(SkillEntity).filter_by(user_id=user_id).order_by(SkillEntity.name)]


def _show(session, user_id, name, version=None):
    if version is None:
        skill = session.query(SkillEntity).filter_by(user_id=user_id, name=name).first()
        if not skill:
            raise SkillNotFound('skill_not_found')
        version = skill.latest_version
    row = session.query(SkillVersionEntity).filter_by(user_id=user_id, name=name, version=version).first()
    if not row:
        raise SkillNotFound('skill_version_not_found')
    return row


def show(user_id, name, version=None):
    with get_db() as session:
        return _version(_show(session, user_id, name, version))


def list_installs(user_id, node=None):
    with get_db() as session:
        query = select(SkillInstallEntity, SkillVersionEntity).join(SkillVersionEntity, (
            (SkillVersionEntity.user_id == SkillInstallEntity.user_id)
            & (SkillVersionEntity.name == SkillInstallEntity.name)
            & (SkillVersionEntity.version == SkillInstallEntity.version)
        )).where(SkillInstallEntity.user_id == user_id)
        if node is not None:
            query = query.where(SkillInstallEntity.node == node)
        return [{**_version(version), 'node': install.node, 'previous_version': install.previous_version}
                for install, version in session.execute(query.order_by(SkillInstallEntity.name, SkillInstallEntity.node))]


def change_install(user_id, name, node, operation, version=None, validate_node=None):
    with get_db() as session:
        _lock(session, user_id)
        current = session.query(SkillInstallEntity).filter_by(user_id=user_id, name=name, node=node).first()
        if operation == 'uninstall':
            if current:
                session.delete(current)
            session.commit()
            return {'name': name, 'node': node, 'installed': False}
        validate_node()
        if operation in ('upgrade', 'rollback') and not current:
            raise SkillNotFound('skill_install_not_found')
        if operation == 'rollback':
            if not current.previous_version:
                raise SkillConflict('skill_no_previous_version')
            version = current.previous_version
        target = _show(session, user_id, name, version)
        if operation == 'install' and current and current.version != target.version:
            raise SkillConflict('skill_already_installed')
        installed = {row.name for row in session.query(SkillInstallEntity).filter_by(user_id=user_id, node=node)}
        if not set(target.manifest['requires']['skills']).issubset(installed | {name}):
            raise SkillConflict('skill_dependency_not_installed')
        if not current:
            current = SkillInstallEntity(user_id=user_id, name=name, node=node, version=target.version)
            session.add(current)
        elif current.version != target.version:
            current.previous_version, current.version = current.version, target.version
        session.commit()
        return {'name': name, 'node': node, 'version': current.version, 'previous_version': current.previous_version}
