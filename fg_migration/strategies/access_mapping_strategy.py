"""Contains the interface AccessMappingStrategy"""
from abc import ABC, abstractmethod

from pyforgejo import Organization, Team

from fg_migration.adapters.forgejo_types import ForgejoPermission
from fg_migration.core.canonical_types import CanonicalOrganization, CanonicalRepo
from fg_migration.core.migration_source_type import MigrationSource



class AccessMappingStrategy(ABC):
    """
        Interface for strategies that translate source-system authorization models
        into Forgejo permissions, teams, and repository access.

        A strategy implementation is responsible for deciding:

        - How source-system users are grouped into Forgejo teams.
        - Whether Forgejo teams should be created.
        - How repository access should be granted.
        - When direct repository collaborators should be used.
        - How source-system access levels map to Forgejo permissions.

        Example
        -------
        Given source-system membership data:

            alice   -> Maintainer
            bob     -> Maintainer
            charlie -> Developer
            dave    -> Guest

        and a configured Forgejo team mapping:

            Maintainer -> forgejo-maintainers
            Developer  -> forgejo-developers
            Guest      -> forgejo-guests
            Auditor    -> forgejo-auditors

        one strategy may choose to create the following Forgejo organization
        structure:

            forgejo-maintainers
                ├── alice
                └── bob

            forgejo-developers
                └── charlie

            forgejo-guests
                └── dave

            forgejo-auditors
                └── <no members>

        For a repository "project-a", that strategy may then grant access through
        teams:

            project-a
                ├── forgejo-maintainers
                ├── forgejo-developers
                ├── forgejo-guests
                └── forgejo-auditors

        while another strategy could choose to grant access directly to individual
        users instead.

        The specific grouping rules, team creation behaviour, handling of empty
        teams, permission mapping, and collaborator fallback behaviour are all
        defined by the concrete AccessMappingStrategy implementation.
        """
    @abstractmethod
    def import_teams(self, migration_source:MigrationSource, organization: CanonicalOrganization):
        """Entry point from the migrator to import teams (no requirement to import teams)"""


    @abstractmethod
    def import_team_users_from_usernames(
        self,
        organization: CanonicalOrganization|Organization,
        usernames: set[str],
        dest_team: Team,
        team_members_cache: dict[int, set[str]], # map[Team.id -> {member.username}]
        is_new_team: bool,
    ):
        """A common enough function of this strategy that an implementation is required for adding
           any users matching usernames into the team provided.
           Don't forget to update the team_members_cache"""

    @abstractmethod
    def import_repository_accessors(
        self,
        migration_source: MigrationSource,
        source_repo: CanonicalRepo,
    ):
        """Entry point from the migrator to import repository accessors"""

    @abstractmethod
    def resolve_forgejo_permission(
        self,
        migration_source:MigrationSource,
        source_access_level: str,
    ) -> ForgejoPermission | None:
        """return the most appropriate Forgejo permission string
           for the given access level {read,write,admin}"""
