from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

db = SQLAlchemy()


class Host(db.Model):
    __tablename__ = "hosts"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = db.Column(db.Text, nullable=False, unique=True)
    agent_id = db.Column(db.Text, nullable=False, unique=True)
    first_seen = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_ = db.Column("metadata", JSONB, nullable=False, default=dict)

    config_files = db.relationship("ConfigFile", back_populates="host", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": str(self.id),
            "hostname": self.hostname,
            "agent_id": self.agent_id,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "metadata": self.metadata_,
        }


class ConfigFile(db.Model):
    __tablename__ = "config_files"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False)
    file_path = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("host_id", "file_path"),)

    host = db.relationship("Host", back_populates="config_files")
    snapshots = db.relationship("Snapshot", back_populates="config_file", cascade="all, delete-orphan",
                                order_by="Snapshot.submitted_at.desc()")

    def to_dict(self):
        return {
            "id": str(self.id),
            "host_id": str(self.host_id),
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat(),
        }


class Snapshot(db.Model):
    __tablename__ = "snapshots"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config_file_id = db.Column(UUID(as_uuid=True), db.ForeignKey("config_files.id", ondelete="CASCADE"), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    file_hash = db.Column(db.Text, nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False)
    commit_sha = db.Column(db.Text)
    commit_message = db.Column(db.Text)

    config_file = db.relationship("ConfigFile", back_populates="snapshots")

    def to_dict(self):
        return {
            "id": str(self.id),
            "config_file_id": str(self.config_file_id),
            "submitted_at": self.submitted_at.isoformat(),
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "commit_sha": self.commit_sha,
            "commit_message": self.commit_message,
        }
