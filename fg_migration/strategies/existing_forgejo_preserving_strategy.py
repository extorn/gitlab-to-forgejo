"""contains the ExistingForgejoPreservingStrategy class"""
from copy import deepcopy
from typing import override

from pyforgejo import Team

from fg_migration.adapters.destination_forgejo import ForgejoDestination
from fg_migration.adapters.forgejo_types import (ForgejoPermission,
                                                ForgejoTeamDefinition,
                                                IterativeFetchError)
from fg_migration.core.canonical_types import (CanonicalOrganization,
                                               CanonicalOrganizationMembership,
                                               CanonicalUser)
from fg_migration.core.config_types import MigrationConfig
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.strategies.access_level_mapping_strategy import AccessLevelAccessMappingStrategy
from fg_migration.utils import fg_print


class ExistingForgejoPreservingStrategy(AccessLevelAccessMappingStrategy):
    """
    Migration strategy that preserves all pre-existing Forgejo structures.

    This strategy creates new teams only when they do not already exist.
    Existing Forgejo teams are never modified, renamed, repurposed, or
    assumed to represent source-system groups.

    When a source group conflicts with an existing Forgejo team name, a
    new migration-specific team is created instead.

    Example
    -------
    Source-system groups:

        Maintainers
            ├── alice
            └── bob

        Developers
            └── charlie

        Guests
            └── dave

    Existing Forgejo organization:

        Maintainers
            └── legacy-user

    Because the existing team is preserved, the migration creates:

        Maintainers_migrated
            ├── alice
            └── bob

        Developers
            └── charlie

        Guests
            └── dave

    rather than modifying the existing Maintainers team.

    Repository access is then attached to the migration-created teams:

        project-a
            ├── Maintainers_migrated
            ├── Developers
            └── Guests

    Existing Forgejo teams remain untouched.

    Behaviour:
    - Never modifies existing Forgejo teams.
    - Never removes existing team members.
    - Never repurposes existing teams.
    - Creates migration-specific teams on naming conflict.
    - Preserves empty source groups as empty teams.
    - Grants repository access through migration-created teams.
    - Suitable for migrations into active Forgejo environments.
    """

    TEAM_SUFFIX = "_migrated"

    @override
    def __init__(self, migration_dest:ForgejoDestination, migration_config:MigrationConfig):
        super().__init__(migration_dest=migration_dest, migration_config=migration_config)
        self.org_remapped_team_names : dict[str,str] = {} # name.lower() : name.lower()
        self.migration_username : str | None = None
        self._team_members_cache: dict[int, set[str]] = {}  # team.id set[member.username]

    @override
    def import_teams(self, migration_source: MigrationSource, organization: CanonicalOrganization):

        # cache the migration_username to avoid an API lookup for every team
        self.migration_username = self.migration_dest.get_active_user().login
        self.org_remapped_team_names.clear()
        self._team_members_cache.clear()
        try:
            super().import_teams(migration_source=migration_source, organization=organization)
        finally:
            self.org_remapped_team_names.clear() # ensure it is ready for the next organization
            self._team_members_cache.clear()



    @override
    def _find_existing_org_team_for_new_users_matching(
        self,
        organization: CanonicalOrganization,
        existing_forgejo_teams_map: dict[str, Team], # map[Team.name.lower() : Team]
        forgejo_team_definition:ForgejoTeamDefinition,
        canonical_team_members: list[CanonicalUser]
    ) -> AccessLevelAccessMappingStrategy.TeamMatchResult | None:
        """
        Raises
        ------
        IterativeFetchError
            If there are problems retrieving team members or other items in
            API calls during the check
        """

        # NOTE: this override is called ONLY while materializing teams, NOT adding collaborators

        remapped_team_name_to_name = self.org_remapped_team_names.get(
                                                        forgejo_team_definition.name.lower())
        if remapped_team_name_to_name is not None:
            # skip the rest of the logic in this function (we know there is a match).
            matched_team = existing_forgejo_teams_map.get(remapped_team_name_to_name.lower())
            fg_print.debug(f"Using remapped team {remapped_team_name_to_name} in lieu"
                           f" of {forgejo_team_definition.name}  in "
                           f"org {organization.get_safe_username()}")
            if matched_team is not None:
                return self.TeamMatchExactResult(matched_team=matched_team)

        #
        # First look for an exact-name team.
        #
        matched_team = self._find_matching_team(
            existing_forgejo_teams_map,
            forgejo_team_definition,
        )

        if matched_team is None:
            # No team exists, can create a team as desired
            fg_print.debug(f"No existing team {forgejo_team_definition.name} in "
                           f"org {organization.get_safe_username()}, safe to use")
            return self.TeamMatchNoResult(team_definition=forgejo_team_definition)

        # get a list of all users in the existing team
        # (don't yet know if we'll be able to use it)
        try:
            existing_usernames = self._load_usernames(matched_team)
        except IterativeFetchError as e:
            fg_print.debug(f"error retrieving existing usernames {e}")
            raise

        # get a list of all users that are expected to be a member of this team
        # that was found (don't yet know if we'll be able to use it)
        imported_usernames = {
            user.get_safe_username()
            for user in canonical_team_members
        }


        #
        # Exact current membership match for migration user AND is the Owners group
        # and migration user is NOT in the Owners group...
        # We will presume that this team was created during this import and
        # reuse it as a special case, allowing the migration user that was
        # temporarily added as owner to be removed later on
        #
        if (forgejo_team_definition.permissions.permission == ForgejoPermission.OWNER
            and existing_usernames == {self.migration_username}
            and self.migration_username not in imported_usernames):
            fg_print.debug("discovered migration user is sole member "
                          f"of {forgejo_team_definition.name} Team (but is not an "
                          f"Owner in {organization.source_system}). Will reuse team.")
            return self.TeamMatchExactResult(matched_team=matched_team)



        #
        # Exact membership match -> reuse (IF allow use of existing teams is true).
        #
        if (existing_usernames == imported_usernames
            and self.migration_config.USE_EXISTING_TEAMS is True):
            fg_print.info(
                "Pre-existing team members exactly match team "
                "being imported, so reusing.\n"
                f"Affected Forgejo Organization "
                f"{organization.get_safe_username()} "
                f"Team {matched_team.name}"
            )

            return self.TeamMatchExactResult(matched_team=matched_team)

        #
        # Conflict:
        # Keep existing team untouched.
        # Reuse a migrated team (from a previous migration) if one already exists
        # AND the team members exactly match those to add
        existing_team_names = set(existing_forgejo_teams_map.keys())
        latest_existing_team_name_variant, next_available_team_name_variant \
            = self._get_migrated_team_sequence(forgejo_team_definition.name,
                                               existing_names=existing_team_names)
        migrated_team = None
        if latest_existing_team_name_variant != forgejo_team_definition.name:
            # direct previous team name has the migration suffix
            migrated_team = existing_forgejo_teams_map.get(latest_existing_team_name_variant.lower())

        if migrated_team is not None:
            fg_print.debug("Existing previously migrated team found:"
                           f" {migrated_team.name} id:{migrated_team.id}")

            try:
                migrated_usernames = self._load_usernames(migrated_team)
            except IterativeFetchError as e:
                fg_print.debug(f"Error retrieving migrated usernames: {e}")
                raise


            if migrated_usernames == imported_usernames:
                fg_print.info(
                    f"Reusing migrated team "
                    f"{migrated_team.name}"
                )

                return self.TeamMatchExactResult(
                    matched_team=migrated_team
                )

        #
        # Force creation of a new team.
        #
        updated_definition = deepcopy(forgejo_team_definition)
        if forgejo_team_definition.permissions.permission == ForgejoPermission.OWNER:
            # We must downgrade this permission to administrator
            # (cannot create owner grade teams)
            role = self.migration_dest.forgejo_team_to_role_mapper \
                            .get_role_matching_permission(ForgejoPermission.ADMIN)
            admin_perms = self.migration_dest \
                            .forgejo_team_to_role_mapper.get_role_permissions(role)
            updated_definition.permissions = admin_perms
            fg_print.warning(f"Downgrading migration team {next_available_team_name_variant}"
                                " role from Owner to Admin")
        updated_definition.name = next_available_team_name_variant
        fg_print.info(f"Created migration team {next_available_team_name_variant} "
                        f"to avoid clash with {forgejo_team_definition.name}")
        # update the cache so we get a headstart next time(n.b. inserting in lower case).
        self.org_remapped_team_names[
            forgejo_team_definition.name.lower()] = updated_definition.name.lower()
        return self.TeamMatchNoResult(team_definition=updated_definition)



    def _load_usernames(self, team:Team) -> set[str]:
        """
        Raises
        ------
        IterativeFetchError
            If there are problems retrieving team members
        """
        usernames = self._team_members_cache.get(team.id)
        if usernames is None:
            try:
                usernames = {
                    member.login
                    for member in self.migration_dest
                        .iter_forgejo_team_members(
                            team
                        )
                    if member.login is not None
                }
                self._team_members_cache[team.id] = usernames
            except IterativeFetchError as e:
                fg_print.debug(f"API error while loading usernames for team {team.name}: {e}")
                raise
        return usernames



    def _get_migrated_team_sequence(
        self,
        source_name: str,
        existing_names: set[str],
    ) -> tuple[str, str]:
        """returns:
        (
            latest existing team in the migration naming sequence,
            first available team name in the migration naming sequence
        )
        """

        counter = 0
        last_existing = source_name

        while True:

            candidate = (
                f"{source_name}{self.TEAM_SUFFIX}"
                if counter == 0
                else f"{source_name}{self.TEAM_SUFFIX}_{counter}"
            )

            if candidate.lower() not in existing_names:
                return last_existing, candidate

            last_existing = candidate
            counter += 1
