"""Contains an implementation of AccessMappingStrategy"""
from typing import override


from fg_migration.adapters.forgejo_types import (ForgejoRolePermissionDefinition,
                                                ForgejoTeamDefinition)
from fg_migration.core.canonical_types import CanonicalRepo, CanonicalRepoMemberships
from fg_migration.strategies.access_level_mapping_strategy import AccessLevelAccessMappingStrategy
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.utils import fg_print


class StrictAccessLevelMappingStrategy(AccessLevelAccessMappingStrategy):
    """
        Strict access-level mapping strategy.

        This strategy treats canonical access levels as the authoritative source of
        authorization.

        Users sharing an access level are grouped into a corresponding Forgejo team,
        and repository access is granted exclusively through those teams.

        Users not representable through team mappings are reported as strict access
        violations and are not imported.

        Unlike AccessLevelAccessMappingStrategy, this implementation does not permit
        fuzzy role mapping, fuzzy team mapping, permission approximation, or direct
        collaborator fallback.

        Example
        -------
        Canonical organization memberships:

            alice   -> Maintainer
            bob     -> Maintainer
            charlie -> Developer
            dave    -> Guest

        Configured team mappings:

            Maintainer -> forgejo-maintainers
            Developer  -> forgejo-developers
            Guest      -> forgejo-guests
            Auditor    -> forgejo-auditors

        Resulting Forgejo organization structure:

            forgejo-maintainers
                ├── alice
                └── bob

            forgejo-developers
                └── charlie

            forgejo-guests
                └── dave

            forgejo-auditors
                └── <no members>

        Repository access is granted only through teams:

            project-a
                ├── forgejo-maintainers
                ├── forgejo-developers
                ├── forgejo-guests
                └── forgejo-auditors

        Strict enforcement
        ------------------
        If a repository accessor cannot be represented through one of the configured
        teams, the strategy reports a strict access violation.

        No direct collaborators are created.

        Behaviour:
        - Creates Forgejo teams from configured access-level mappings.
        - Assigns users to teams strictly according to access level.
        - Supports configured empty teams.
        - Grants repository access only through teams.
        - Never creates direct collaborators.
        - Never performs fuzzy role mapping.
        - Never performs fuzzy team mapping.
        - Reports mapping violations instead of falling back, note:
            * Users not representable through team mappings are reported as strict access
              violations and are not imported, but the remaining migration succeeds
        """

    @override
    def _get_forgejo_team_definition(
        self,
        migration_source: MigrationSource,
        source_access_level: str,
        fuzzy: bool,
    ) -> ForgejoTeamDefinition | None:
        return super()._get_forgejo_team_definition(
            migration_source=migration_source,
            source_access_level=source_access_level,
            fuzzy=False,
        )

    @override
    def _get_forgejo_role_definition(
        self,
        migration_source: MigrationSource,
        source_access_level: str,
        fuzzy: bool,
    )-> ForgejoRolePermissionDefinition | None:
        return super()._get_forgejo_role_definition(
            migration_source=migration_source,
            source_access_level=source_access_level,
            fuzzy=False)



    @override
    def handle_missing_accessors(
        self,
        migration_source: MigrationSource,
        source_repo: CanonicalRepo,
        repo_accessors: CanonicalRepoMemberships,
        all_team_usernames: set[str],
        existing_collaborator_ids: set[int],
    ):
        missing = {
            m.username
            for m in repo_accessors.members
            if m.username and m.username not in all_team_usernames
        }

        if missing:
            fg_print.error(
                f"Strict access violation for "
                f"{source_repo.name}. "
                f"Users not covered by any mapped team: "
                f"{sorted(missing)}"
            )
