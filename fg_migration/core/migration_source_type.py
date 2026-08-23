"""module contains only interface definition for MigrationSource"""
from abc import ABC, abstractmethod

from fg_migration.core.canonical_types import (CanonicalOrganizations, CanonicalRepo,
                                               CanonicalRepoMemberships, CanonicalSystemUser)
from fg_migration.adapters.destination_forgejo import ForgejoRepositoryRole


class MigrationSource(ABC):
    """An implementation for this class should be written for each source system to be migrated
       into Forgejo. Then, the source can be specified in the command args e.g. source=gitlab etc"""

    @abstractmethod
    def get_source_system_name(self) -> str:
        """Name of the source system, e.g. gitlab - used for logging"""

    @abstractmethod
    def list_repositories(self) -> list[CanonicalRepo]:
        """Build and return a full list of repositories extracted"""

    @abstractmethod
    def list_organizations(self) -> CanonicalOrganizations:
        """Build and return a full list of organizations extracted"""

    @abstractmethod
    def list_repository_accessors(self, repo:CanonicalRepo) -> CanonicalRepoMemberships:
        """Build and return a List all those individuals who use a repository"""

    @abstractmethod
    def list_system_users(self) -> list[CanonicalSystemUser]:
        """Build and return a List all those individuals who have access
           to the source control system"""

    @abstractmethod
    def get_repository_role(self, source_access_level:str) -> ForgejoRepositoryRole:
        """Return the exact Forgejo repository role that matches this string representation of
           the source system access level.
           A role must always be returned, so if one doesn't exist, you'll need to create one.
           whether you cache them or not is up to you, but recommended
           (@see list_mapped_forgejo_repository_roles)."""

    @abstractmethod
    def get_nearest_repository_role(self, source_access_level:str,
                                 allow_downgrade:bool,
                                 allow_upgrade:bool) -> ForgejoRepositoryRole | None:
        """Return the Forgejo repository role that matches this string representation of the
           source system access level based on whether upgrade or downgrade are permitted.
           The precise logic over prefering closest match or downgrade vs upgrade if allowed
           for example is not defined at present."""

    @abstractmethod
    def list_mapped_forgejo_repository_roles(self) -> set[ForgejoRepositoryRole]:
        """return a list of all repository roles that you expect to use during an import."""
