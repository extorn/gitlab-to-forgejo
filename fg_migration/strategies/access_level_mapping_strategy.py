"""Defines the AccessLevelAccessMappingStrategy class"""
from abc import ABC
from copy import deepcopy
from dataclasses import dataclass
from typing import override

from pyforgejo import Team

from fg_migration.strategies.base_access_mapping_strategy import BaseAccessMappingStrategy
from fg_migration.utils import fg_print
from fg_migration.core.canonical_types import (CanonicalOrganizationMembership,
                                               CanonicalOrganization,
                                               CanonicalRepo, CanonicalRepoMemberships,
                                               CanonicalUser)
from fg_migration.adapters.forgejo_types import (ForgejoPermission, ForgejoTeamDefinition,
                                                IterativeFetchError)
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.utils.utils import name_clean


class AccessLevelAccessMappingStrategy(BaseAccessMappingStrategy):
    """
    Access mapping strategy that derives Forgejo teams and repository permissions
    directly from source-system access levels.

    This strategy treats access levels as the canonical representation of
    authorization. Users with the same source access level are grouped into a
    corresponding Forgejo team, and repository access is granted through those
    teams whenever possible.

    Example
    -------
    Source system organization memberships:

        alice   -> Maintainer
        bob     -> Maintainer
        charlie -> Developer
        dave    -> Guest

    Team mappings:

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

    The empty "forgejo-auditors" team may still be created when
    ADD_EMPTY_TEAMS_TO_ORGANIZATIONS is enabled and the team definition
    allows empty teams.

    Repository access example
    -------------------------
    If repository "project-a" is accessible to all four users in the source
    system, the strategy will preferentially grant repository access through
    teams:

        project-a
            ├── forgejo-maintainers
            ├── forgejo-developers
            └── forgejo-guests

    rather than creating individual repository collaborators.

    Empty teams can also be attached to repositories when
    ADD_EMPTY_TEAMS_TO_REPOSITORIES is enabled:

        project-a
            ├── forgejo-maintainers
            ├── forgejo-developers
            ├── forgejo-guests
            └── forgejo-auditors (0 members)

    This allows predefined permission structures to exist in Forgejo even when
    no users currently occupy a given role.

    Direct collaborators are only used as a fallback when a user cannot be
    represented through a team-based access mapping.

    Behaviour:
    - Creates or reuses Forgejo teams mapped from source access levels.
    - Optionally creates configured empty teams even when no source users map
      to them.
    - Imports organization membership by assigning users to the appropriate
      access-level team.
    - Grants repository access through teams for organization-owned repositories.
    - Optionally grants repository access to empty teams.
    - Falls back to direct repository collaborators only for users not covered
      by team-based access.
    - Supports fuzzy role/team mapping when enabled by migration configuration.
    - Preserves team-based authorization intent by avoiding automatic conversion
      of failed team assignments into individual collaborator assignments.
    """

    @dataclass
    class TeamMatchResult(ABC):
        """Complex type for use when searching for a team to add users to. If a team is
           found but it needs moving out of the way because it has pre-existing different
           set of users to those being imported, renamed team is set and old_name is set
           otherwise matched team is set (i.e. either or)"""



    @dataclass
    class TeamMatchNoResult(TeamMatchResult):
        """See super type definition"""
        team_definition: ForgejoTeamDefinition

    @dataclass
    class TeamMatchExactResult(TeamMatchResult):
        """See super type definition"""
        matched_team: Team



    @dataclass
    class TeamMatchRenamedResult(TeamMatchResult):
        """See super type definition"""
        renamed_team: Team
        old_name: str



    @dataclass
    class TeamSearchResult:
        """Result of finding team to add members to"""
        team:Team
        is_new_team:bool
        usernames: set[str]



    @override
    def import_teams(self, migration_source: MigrationSource, organization: CanonicalOrganization):
        """Create Forgejo teams as a projection of canonical membership facts"""

        existing_forgejo_org_teams_map: dict[str, Team] # map[Team.name.lower() : Team]
        try:
            iter_all_teams = self.migration_dest.iter_forgejo_teams(
                org_name=organization.get_safe_username()
            )

            existing_forgejo_org_teams_map = {team.name.lower(): team
                                              for team in iter_all_teams
                                              if team.name}

        except IterativeFetchError as e:
            fg_print.error( "Failed to load existing teams for "
                           f"{organization.get_safe_username()}: {e}")
            return # try the next org

        # ---------------------------------------------------
        # STEP 1: derive "team intent" from membership facts
        # ---------------------------------------------------
        # rule: grouping is a *policy decision*, not a model assumption
        team_intent_map: dict[str, list[CanonicalOrganizationMembership]] = {}

        for m in organization.memberships:
            if m.username is None:
                continue

            key = m.access_level

            team_intent_map.setdefault(key, []).append(m)

        # This is potentially a saving in API calls due to the fuzzy mapping to teams
        team_members_cache: dict[int, set[str]] = {} # map[Team.id -> {member.username}]

        # ---------------------------------------------------
        # STEP 2: materialise Forgejo teams
        # ---------------------------------------------------
        fg_print.debug("materializing teams for organization"
                       f" {organization.get_safe_username()}")

        for access_level, memberships in team_intent_map.items():

            team_result = self._get_forgejo_team_for_members_add(
                                migration_source=migration_source,
                                organization=organization,
                                access_level=access_level,
                                memberships=memberships,
                                existing_forgejo_org_teams_map=existing_forgejo_org_teams_map)
            if team_result is None:
                continue

            # ---------------------------------------------------
            # STEP 3: attach users (idempotent)
            # ---------------------------------------------------
            self.import_team_users_from_usernames(
                organization=organization,
                usernames=team_result.usernames,
                dest_team=team_result.team,
                team_members_cache=team_members_cache,
                is_new_team=team_result.is_new_team,
            )

        # ----------------------------------------------------------------------------
        # STEP 4: add any teams with no members defined in the teams config yaml file.
        # ----------------------------------------------------------------------------
        if self.migration_config.ADD_EMPTY_TEAMS_TO_ORGANIZATIONS is True:
            for possible_team in self.migration_dest.get_default_team_definitions():
                if possible_team.name.lower() in existing_forgejo_org_teams_map:
                    # already existed before this operation started
                    continue

                if possible_team.allow_empty:
                    self._safely_add_new_team(organization=organization,
                                              team_definition=possible_team)
                else:
                    fg_print.info(f"Skipped adding empty team {possible_team.name} because"
                                  " defined as empty not allowed in team definitions yaml file")



    def _get_forgejo_team_for_members_add(self,
                    migration_source:MigrationSource,
                    organization:CanonicalOrganization,
                    access_level:str,
                    memberships:list[CanonicalOrganizationMembership],
                    existing_forgejo_org_teams_map: dict[str, Team] # map[Team.name.lower() : Team]
                    ) -> TeamSearchResult | None:

        forgejo_team_definition = self._get_forgejo_team_definition(
            migration_source=migration_source,
            source_access_level=access_level,
            fuzzy=self.migration_config.IS_FUZZY_TEAMS_ALLOWED,
        )

        if forgejo_team_definition is None:
            fg_print.warning(
                f"No Forgejo team mapping for access level {access_level}"
            )
            return None

        usernames = {m.get_safe_username() for m in memberships if m.username}

        try:
            match_result = self._find_existing_org_team_for_new_users_matching(
                organization=organization,
                existing_forgejo_teams_map=existing_forgejo_org_teams_map,
                forgejo_team_definition=forgejo_team_definition,
                canonical_team_members=[CanonicalUser(username=u) for u in usernames]
            )
            is_new_team = False
        except IterativeFetchError:
            # Something went wrong trying to find existing org team
            fg_print.error("skipping import of access level due to match failure...")
            return None

        if isinstance(match_result, self.TeamMatchRenamedResult):
            # Team was moved, remove old mapping and add a new one
            del existing_forgejo_org_teams_map[match_result.old_name.lower()]
            existing_forgejo_org_teams_map[match_result.renamed_team.name.lower()] = \
                                                                match_result.renamed_team
            # Now no team matches the name we renamed from
            existing_team = None
        elif isinstance(match_result, self.TeamMatchExactResult):
            existing_team = match_result.matched_team
        elif isinstance(match_result, self.TeamMatchNoResult):
            is_new_team = True
            existing_team = None
            # Create that required and currently non existent team
            existing_team = self._safely_add_new_team(organization=organization,
                                                      team_definition=match_result.team_definition)
            if existing_team is None:
                return None
            existing_forgejo_org_teams_map[existing_team.name.lower()] = existing_team
        else:
            raise RuntimeError("Unhandled result type for function result TeamMatchResult")

        return self.TeamSearchResult(team=existing_team,
                                     is_new_team=is_new_team,
                                     usernames=usernames)



    @override
    def import_repository_accessors(
        self,
        migration_source: MigrationSource,
        source_repo: CanonicalRepo,
    ):
        """Import all teams or individuals that should have access to a repository"""

        repo_accessors: CanonicalRepoMemberships = (
            migration_source.list_repository_accessors(source_repo)
        )

        if source_repo.is_individual:
            fg_print.info(
                f"\nImporting collaborators for personal {source_repo.source_type}"
                f" {source_repo.name}..."
            )
        else:
            fg_print.info(
                f"\nImporting collaborators for shared {source_repo.source_type}"
                f" {source_repo.name}..."
            )

        if len(repo_accessors.members) == 0:
            fg_print.info(
                f"No accessors found for {source_repo.name}, skipping collaborators"
            )
            return

        fg_print.debug(
            f"Repository {source_repo.name} accessors found: "
            f"{[a.username for a in repo_accessors.members]}"
        )

        # ---------------------------------------------------
        # Resolve repo owner
        # ---------------------------------------------------
        forgejo_repo_owner = self.migration_dest.resolve_forgejo_repo_owner(source_repo)
        if forgejo_repo_owner is None or forgejo_repo_owner.username is None:
            fg_print.error(
                f"Failed to resolve Forgejo owner for {source_repo.name}, skipping"
            )
            return

        # ---------------------------------------------------
        # Existing collaborators
        # ---------------------------------------------------
        try:
            iter_existing = self.migration_dest.iter_forgejo_collaborators(
                owner_username=forgejo_repo_owner.username,
                repo=source_repo.get_safe_username(),
            )

            existing_collaborator_ids: set[int] = {
                u.id for u in iter_existing if u.id is not None
            }

        except IterativeFetchError:
            fg_print.error(
                f"Failed to load existing collaborators for {source_repo.name}"
            )
            return

        # ---------------------------------------------------
        # STEP 1: extract all usernames from canonical facts
        # ---------------------------------------------------
        all_usernames: set[str] = {
            m.username for m in repo_accessors.members if m.username
        }

        all_team_usernames: set[str] = set()

        if source_repo.is_individual:
            # add the owner (these usernames will NOT be turned into collaborators)
            all_team_usernames.add(source_repo.get_safe_owner_name())

        # ---------------------------------------------------
        # STEP 2: attach teams (only if repo is org-owned)
        # ---------------------------------------------------
        if not source_repo.is_individual:

            # Get list of teams in the repository essentially.
            iter_existing_repo_teams = self.migration_dest.iter_forgejo_teams_in_repository(
                                                        owner_username=forgejo_repo_owner.username,
                                                        repo_name=source_repo.get_safe_username(),
                                                    )

            try:
                existing_repo_team_ids = {
                    t.id
                    for t in iter_existing_repo_teams
                    if t.id is not None
                }
            except IterativeFetchError:
                fg_print.error(
                    f"Failed to load existing repository teams for "
                    f"{source_repo.get_safe_username()}"
                )
                return

            try:
                migration_username = self.migration_dest.get_active_user().login
                remove_self = self.should_remove_migration_user_from_owners_team(
                                                migration_source=migration_source,
                                                migration_username=migration_username,
                                                repo_accessors=repo_accessors)

                # get all the teams in the organization owning this repository
                for org_team in self.migration_dest.iter_forgejo_teams(
                                                     org_name=forgejo_repo_owner.username):

                    current_team_def = ForgejoTeamDefinition.from_team(
                                team=org_team,
                                role_builder=self.migration_dest.forgejo_team_to_role_mapper,
                                require_exact=True)

                    if (remove_self
                        and current_team_def.permissions.permission == ForgejoPermission.OWNER):

                        fg_print.debug(f"Removing migration user from team {org_team.name}")
                        self.migration_dest.forgejo_remove_user_from_organization_team(
                                                username=migration_username,
                                                organization_name=forgejo_repo_owner.username,
                                                team=org_team)

                    fg_print.debug(f"Processing team {org_team.name}")
                    try:
                        team_members = list(
                            self.migration_dest.iter_forgejo_team_members(team=org_team)
                        )
                    except IterativeFetchError:
                        continue

                    member_usernames = {
                        m.login for m in team_members if m.login
                    }

                    # only attach team if all members are valid repo accessors
                    if not member_usernames.issubset(all_usernames):
                        fg_print.debug(f"Not all members {member_usernames} are valid repository "
                                       f"accessors {all_usernames}, team {org_team.name} will NOT"
                                       " be added as a collaborator")
                        continue

                    if len(member_usernames) == 0:
                        #if the team is empty....
                        if self.migration_config.ADD_EMPTY_TEAMS_TO_REPOSITORIES is not True:
                            # Don't add this one to the the repository unless user wanted
                            continue

                    if not org_team.id in existing_repo_team_ids:

                        # Try and add the new team.
                        if not self.migration_dest.forgejo_add_team_to_repository(
                            owner_username=forgejo_repo_owner.username,
                            repo_name=source_repo.get_safe_username(),
                            team_name=org_team.name,
                        ):
                            # Only add usernames if successfully added team.
                            affected_usernames = member_usernames.difference(all_team_usernames)
                            fg_print.warning("Team attachment failed. Users represented by this "
                                             "team will not be imported as individual "
                                             "collaborators because doing so would alter the "
                                             "intended authorization model"
                                             f"Affected users: {affected_usernames}")

                    # Mark users as accounted for by team intent.
                    # We deliberately do not fall back to individual collaborators
                    # because that would alter the intended permission model.
                    all_team_usernames.update(member_usernames)
            except IterativeFetchError:
                fg_print.error(
                    f"Failed to load organization teams for "
                    f"{forgejo_repo_owner.username}"
                )
                return

        self.handle_missing_accessors(
                    migration_source=migration_source,
                    source_repo=source_repo,
                    repo_accessors=repo_accessors,
                    all_team_usernames=all_team_usernames,
                    existing_collaborator_ids=existing_collaborator_ids,
                )



    def handle_missing_accessors(
        self,
        migration_source: MigrationSource,
        source_repo: CanonicalRepo,
        repo_accessors: CanonicalRepoMemberships,
        all_team_usernames: set[str],
        existing_collaborator_ids: set[int],
    ):
        """Handle all those accessors not already added by way of membership to a Forgejo Team"""
        # ---------------------------------------------------
        # STEP 3: individual collaborators (true fallback path)
        # ---------------------------------------------------
        direct_users = [
            m for m in repo_accessors.members
            if m.username and m.username not in all_team_usernames
        ]

        # STEP 4: import remaining users directly

        for membership in direct_users:

            perm = self.resolve_forgejo_permission(
                migration_source,
                membership.access_level
            )

            if perm is None:
                fg_print.warning(
                    f"No Forgejo permission mapping for "
                    f"user {membership.username} "
                    f"access level {membership.access_level}"
                )
                continue

            self.migration_dest.import_individual_user_collaborator(
                existing_collaborator_ids=existing_collaborator_ids,
                accessor=membership,
                source_repo=source_repo,
                forgejo_permissions=perm,
            )



    def _find_existing_org_team_for_new_users_matching(self,
                        organization : CanonicalOrganization,
                        existing_forgejo_teams_map : dict[str,Team], # map[Team.name.lower() : Team]
                        forgejo_team_definition : ForgejoTeamDefinition,
                        canonical_team_members : list[CanonicalUser]) -> TeamMatchResult:
        """
        Raises
        ------
        IterativeFetchError
            If there are problems retrieving team members or other items in
            API calls during the check
        """

        matched_team = self._find_matching_team(existing_forgejo_teams_map, forgejo_team_definition)
        if matched_team is None:
            return self.TeamMatchNoResult(team_definition=forgejo_team_definition)

        try:
            existing_usernames = {member.login
                        for member in self.migration_dest.iter_forgejo_team_members(matched_team)
                        if member.login is not None}
        except IterativeFetchError as e:
            fg_print.debug(f"Error loading usernames: {e}")
            raise


        imported_usernames = { user.get_safe_username()
                               for user in canonical_team_members}

        if existing_usernames == imported_usernames:
            fg_print.info(f"Pre-existing team members exactly match team being imported,"
                          " so reusing.\n"
                          f"Affected Forgejo Organization {organization.get_safe_username()}"
                          f" Team {matched_team.name}")
            return self.TeamMatchExactResult(matched_team=matched_team)

        if self.migration_config.USE_EXISTING_TEAMS is True:
            fg_print.warning("Pre-existing team users will be granted access to new repositories"
                             " that are created with access granted to this team.\n"
                             f"Affected Forgejo Organization {organization.get_safe_username()}"
                             f" Team {matched_team.name}, usernames: {existing_usernames}")
            return self.TeamMatchExactResult(matched_team=matched_team)

        # don't want to alter the existing team, rename it so we can create a new
        # one using its name.
        result = self._rename_team_out_of_the_way(team = matched_team)

        return result


    def _rename_team_out_of_the_way(self,
                                    team: Team,
                                    ) -> TeamMatchRenamedResult | None:

        current_definition = ForgejoTeamDefinition.from_team(
            team=team,
            role_builder=self.migration_dest.forgejo_team_to_role_mapper,
            require_exact=True,
        )

        new_definition = deepcopy(current_definition)
        new_definition.name += name_clean(
            f"_pre_migrate_{self.migration_config.MIGRATION_DATE_TIME}"
        )

        updated_team = self.migration_dest.forgejo_update_organization_team(
            team=team,
            current_definition=current_definition,
            new_definition=new_definition,
        )

        if updated_team is not None:
            fg_print.debug(f"Success: Moved team with name {team.name} out of the way to allow "
                           "creation of new team with the same name for import. Renamed team "
                           f"to {updated_team.name}")
        else:
            fg_print.debug(f"Failed: Moved team with name {team.name} out of the way to allow "
                           "creation of new team with the same name for import.")

        if updated_team is not None:
            return self.TeamMatchRenamedResult(renamed_team=updated_team, old_name=team.name)

        # return self.TeamMatchExactResult(matched_team=team)
        return None # Team does exist, but we clearly didn't want to use it



    def _find_matching_team(self,
                        existing_forgejo_teams_map: dict[str, Team], # map[Team.name.lower() : Team]
                        forgejo_team_definition: ForgejoTeamDefinition,
    ) -> Team | None:

        team_key = forgejo_team_definition.name.lower()
        found = existing_forgejo_teams_map.get(
            team_key
        )
        if found is None:
            fg_print.debug(f"No existing team matching {team_key}"
                           f" found in set {set(existing_forgejo_teams_map.keys())}")
        return found
