"""contains the DirectCollaboratorOnlyStrategy class"""
from typing import override

from pyforgejo import Team

from fg_migration.core.canonical_types import (
    CanonicalOrganization,
    CanonicalRepo,
    CanonicalRepoMemberships,
)
from fg_migration.adapters.forgejo_types import (ForgejoPermission, ForgejoTeamDefinition,
                                                IterativeFetchError)
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.strategies.base_access_mapping_strategy import BaseAccessMappingStrategy
from fg_migration.utils import fg_print


class DirectCollaboratorOnlyStrategy(BaseAccessMappingStrategy):
    """
        Strategy that bypasses all access-level team modelling and assigns
        repository access directly to users.

        This strategy treats repository memberships as the canonical representation
        of authorization and does not attempt to group users into Forgejo teams.
        Each repository accessor is imported as an individual collaborator with the
        closest matching Forgejo permission.

        Example
        -------
        Given source-system membership data:

            alice   -> Maintainer
            bob     -> Maintainer
            charlie -> Developer
            dave    -> Guest

        and a configured role mapping:

            Maintainer -> admin
            Developer  -> write
            Guest      -> read
            Auditor    -> read

        Unlike team-based strategies, no additional Forgejo teams are created:

            Forgejo Organization
                └── Owner Team (platform required)

        The following potential team structure is intentionally NOT created:

            forgejo-maintainers
            forgejo-developers
            forgejo-guests
            forgejo-auditors

        For repository "project-a", access is granted directly to users:

            project-a
                ├── alice   (admin)
                ├── bob     (admin)
                ├── charlie (write)
                └── dave    (read)

        Even if an access level exists in configuration but has no users:

            Auditor -> read

        no Forgejo team is created and no repository team assignment is made.

        Behaviour:
        - Does not create access-level Forgejo teams.
        - Does not manage team membership.
        - Does not attach teams to repositories.
        - Imports all repository accessors as direct collaborators.
        - Maps source access levels directly to Forgejo permissions.
        - Requires only the mandatory Forgejo owner team.
        - Ignores empty team definitions because no team modelling is performed.
        - Suitable for migrations where preserving repository access is important
        but reproducing the source-system team structure is not.
        """

    # ---------------------------------------------------------
    # Teams: explicitly disabled except for required owner team
    # ---------------------------------------------------------
    @override
    def import_teams(self, migration_source: MigrationSource, organization: CanonicalOrganization):
        fg_print.info(
            f"Skipping access-level team import for {organization.get_safe_username()} "
            f"(owner team assumed pre-existing / handled elsewhere)"
        )
        return



    # ---------------------------------------------------------
    # Repository access: direct users only
    # ---------------------------------------------------------
    @override
    def import_repository_accessors(
        self,
        migration_source: MigrationSource,
        source_repo: CanonicalRepo,
    ):
        repo_accessors: CanonicalRepoMemberships = (
            migration_source.list_repository_accessors(source_repo)
        )

        if not repo_accessors.members:
            fg_print.info(f"No accessors for {source_repo.name}")
            return

        # ------------------------------------------------------------------------------------------
        # STEP 1: Remove the current user from the owner team if that wouldn't leave it empty
        # ------------------------------------------------------------------------------------------

        migration_username = self.migration_dest.get_active_user().login
        remove_self = self.should_remove_migration_user_from_owners_team(
                                        migration_source=migration_source,
                                        migration_username=migration_username,
                                        repo_accessors=repo_accessors)

        owner_team = self.find_owner_team_for_repo(source_repo=source_repo)
        if owner_team is None:
            fg_print.error("Unable to safely import accessors, skipping")
            return

        fg_print.info(f"Importing direct collaborators for {source_repo.name}")

        forgejo_repo_owner = self.migration_dest.resolve_forgejo_repo_owner(source_repo)
        if not forgejo_repo_owner or not forgejo_repo_owner.username:
            fg_print.error(f"Cannot resolve owner for {source_repo.name}")
            return

        try:
            existing_iter = self.migration_dest.iter_forgejo_collaborators(
                owner_username=forgejo_repo_owner.username,
                repo=source_repo.get_safe_username(),
            )

            existing_collaborator_ids = {
                u.id for u in existing_iter if u.id is not None
            }

        except IterativeFetchError:
            fg_print.error(f"Failed to load collaborators for {source_repo.name}")
            return
        owner_added = False
        for membership in repo_accessors.members:
            if not membership.username:
                continue

            perm = self.resolve_forgejo_permission(
                migration_source,
                membership.access_level,
            )

            if perm is None:
                fg_print.warning(
                    f"No permission mapping for {membership.username} "
                    f"(level={membership.access_level})"
                )
                continue

            handled = False
            if perm == ForgejoPermission.OWNER and not source_repo.is_individual:
                handled = True
                owner_added = self.migration_dest.forgejo_add_user_to_organization_team(
                                                membership.username,
                                                organization_name=source_repo.get_safe_owner_name(),
                                                team=owner_team)
                fg_print.info(f"Added User {membership.username} to owners team {owner_team.name}")

            if not handled:
                # dont add the owner as a collaborator
                self.migration_dest.import_individual_user_collaborator(
                    existing_collaborator_ids=existing_collaborator_ids,
                    accessor=membership,
                    source_repo=source_repo,
                    forgejo_permissions=perm,
                )

        if remove_self and owner_added:
            fg_print.debug(f"Removing migration user from team {owner_team.name}")
            self.migration_dest.forgejo_remove_user_from_organization_team(
                                    username=migration_username,
                                    organization_name=source_repo.get_safe_owner_name(),
                                    team=owner_team)
