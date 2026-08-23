"""contains the DirectCollaboratorOnlyStrategy class"""
from copy import deepcopy
from typing import override

from pyforgejo import Team


from fg_migration.core.canonical_types import (
    CanonicalOrganization,
    CanonicalRepo,
    CanonicalRepoMemberships,
    HierarchyNode,
)
from fg_migration.adapters.forgejo_types import (ForgejoPermission, ForgejoTeamDefinition,
                                                IterativeFetchError)
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.strategies.base_access_mapping_strategy import BaseAccessMappingStrategy
from fg_migration.utils import fg_print
from fg_migration.utils.utils import name_clean


class FlattenedHierarchyStrategy(BaseAccessMappingStrategy):
    """
Access mapping strategy that derives Forgejo teams from source-system
group hierarchies rather than access levels.

This strategy treats repository memberships and their originating group
paths as the canonical representation of authorization. Nested groups are
flattened into Forgejo-compatible team names, allowing GitLab subgroup and
descendant-group structures to be represented without requiring Forgejo to
support nested teams.

Each unique hierarchy path is projected into a Forgejo team. Users are
assigned to the team corresponding to the group through which they gained
access, and repository permissions are granted through those teams whenever
possible.

Example
-------

Given the following GitLab group structure:

    engineering
    ├── backend
    │   └── api
    └── frontend

and repository memberships:

    alice   -> engineering/backend
    bob     -> engineering/backend
    charlie -> engineering/frontend
    dave    -> engineering/backend/api

the hierarchy is flattened into Forgejo teams:

    engineering-backend
    engineering-frontend
    engineering-backend-api

Resulting Forgejo organization structure:

    engineering-backend
    ├── alice
    └── bob

    engineering-frontend
    └── charlie

    engineering-backend-api
    └── dave

Repository access example
-------------------------

For repository "project-a":

    project-a
        ├── engineering-backend
        ├── engineering-frontend
        └── engineering-backend-api

Repository permissions are granted through the flattened hierarchy teams
rather than through individual collaborators whenever possible.

Hierarchy markers may optionally be preserved when generating team names.
For example:

    engineering/:s:/backend
        -> engineering-sub-backend

    engineering/:d:/platform/:d:/api
        -> engineering-desc-platform-desc-api

Behaviour:
- Creates Forgejo teams from source-system group hierarchies.
- Flattens nested group structures into Forgejo-compatible team names.
- Preserves hierarchy information in team naming.
- Imports organization membership through hierarchy-derived teams.
- Grants repository access through hierarchy-derived teams.
- Avoids creating direct collaborators when team-based access can represent
  the authorization model.
- Supports configurable naming conventions for flattened hierarchies.
- Suitable for GitLab migrations where subgroup and descendant-group
  structures should be preserved despite Forgejo lacking nested teams.
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

        migration_username = self.migration_dest.get_active_user().login
        remove_self = self.should_remove_migration_user_from_owners_team(
                                        migration_source=migration_source,
                                        migration_username=migration_username,
                                        repo_accessors=repo_accessors)

        if not repo_accessors.members:
            fg_print.info(f"No accessors for {source_repo.name}")
            return

        fg_print.info(f"Importing Teams and Collaborators for {source_repo.name}")

        if not source_repo.is_individual:
            hierachical_map : dict[str,ForgejoTeamDefinition] = {}
            owner_team = self._build_teams_linked_to_repository(
                                                migration_source=migration_source,
                                                hierachical_map=hierachical_map,
                                                source_repo=source_repo,
                                                repo_accessors=repo_accessors)
        else:
            owner_team = self.find_owner_team_for_repo(source_repo=source_repo)
            if owner_team is None:
                fg_print.error("Unable to safely import accessors, skipping")
                return


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

    def _build_teams_linked_to_repository(self,
                                          migration_source: MigrationSource,
                                          hierachical_map : dict[str,ForgejoTeamDefinition],
                                          source_repo:CanonicalRepo,
                                          repo_accessors: CanonicalRepoMemberships) -> Team|None:

        assert len(hierachical_map) == 0

        organization = self.migration_dest.get_forgejo_organization_owner_of_repository(
                                                                    repo=source_repo)

        existing_teams_iter = self.migration_dest.iter_forgejo_teams_in_repository(
                                        owner_username=organization.username,
                                        repo_name=source_repo.get_safe_username())
        # technically a set of teams, but no guarantee they've added support for sets to Team
        team_name_team_map = {item.name:item
                              for item in existing_teams_iter
                              if item.name is not None}

        # build a cache of hierarchy specific to this repo to Team.
        # there should ALWAYS be a value in here by the point it is requested.
        hierarchy_key_to_team_map : dict[str,Team] = {}

        # This is potentially a saving in API calls due to the fuzzy mapping to teams
        team_members_cache: dict[int, set[str]] = {} # map[Team.id -> {member.username}]

        owner_team : Team|None = None

        for accessor in repo_accessors.members:

            #################################
            # 1. Create or acquire the team
            #################################

            suffix = self._hierarchy_to_team_suffix(accessor.hierarchy)
            hierarchy_key = f"{accessor.access_level}-{suffix}"
            hierachical_team_definition = hierachical_map.get(hierarchy_key)
            is_new_team = False
            team : Team
            if not hierachical_team_definition:
                # Not yet processed this team for this group of accessors.
                team_definition = self._get_forgejo_team_definition(
                                                migration_source=migration_source,
                                                source_access_level=accessor.access_level,
                                                fuzzy=self.migration_config.IS_FUZZY_TEAMS_ALLOWED)

                if team_definition.permissions.permission == ForgejoPermission.OWNER:
                    existing_team = team_name_team_map.get(team_definition.name)
                else:
                    team_name = f"{team_definition.name}-{suffix}"
                    existing_team = team_name_team_map.get(team_name)
                if not existing_team:
                    # Will be the case for any non OWNER teams that didn't already exist

                    hierachical_team_definition = deepcopy(team_definition)
                    hierachical_team_definition.name = team_name
                    hierachical_map[hierarchy_key] = hierachical_team_definition

                    if team_definition.permissions.permission == ForgejoPermission.OWNER:
                        # cannot create the owner team, but it should ALWAYS exist (this block should NEVER be hit)
                        fg_print.error("Unable to find Owner team, "
                                       "but not permitted to create it, skipping")
                        return None # Owner team is None

                    team = self._safely_add_new_team(organization=organization,
                                                     team_definition=hierachical_team_definition)
                    if team is None:
                        fg_print.error(f"Unable to create team {hierachical_team_definition.name}. "
                                       "Unable to process it further")
                        continue
                    if team.name is None:
                        fg_print.error(f"Created team id {team.id} with no name. "
                                        "Unable to process it further")
                        continue

                    team_name_team_map[team.name] = team
                    is_new_team = True

                    # Now add this team to the repository as a collaborator
                    added = self.migration_dest.forgejo_add_team_to_repository(
                                                owner_username=organization.name,
                                                repo_name=source_repo.get_safe_username(),
                                                team_name=team.name)

                    if not added:
                        fg_print.error(f"Created Team {team.name}, but was failed to add it to"
                                       f" repository {source_repo.get_safe_username()} of "
                                       f"organization {organization.name}")
                else:
                    team = existing_team
                    if team_definition.permissions.permission == ForgejoPermission.OWNER:
                        fg_print.warning(f"Located Owner team {team.name} for repo {source_repo.get_safe_username()}")
                        owner_team = team
                hierarchy_key_to_team_map[hierarchy_key] = team

            else:
                team = hierarchy_key_to_team_map.get(hierarchy_key)
                if team is None:
                    fg_print.error("Earlier attempt to get/create team for "
                                   f"hierarchy {hierarchy_key} failed. Skipping.")
                    continue

            ##########################
            # 2. Add the members
            ##########################
            self.import_team_users_from_usernames(organization=organization,
                                                  dest_team=team,
                                                  usernames={accessor.get_safe_username()},
                                                  team_members_cache=team_members_cache,
                                                  is_new_team=is_new_team)

        return owner_team




    def _hierarchy_to_team_suffix(self, hierarchy: list[HierarchyNode] | None) -> str:

        if hierarchy is None:
            return "direct"

        parts: list[str] = []

        for token in hierarchy:
            if token.name is None or token.name == "":
                # should never happen
                fg_print.debug(f"Unexpected value in Hierarchy {hierarchy}")
                continue
            match token.relation:
                case HierarchyNode.RelationEnum.DESCENDANT:
                    parts.append("desc")
                case HierarchyNode.RelationEnum.SUB:
                    parts.append("sub")
                case _:
                    pass
            parts.append(name_clean(token.name))
        return "-".join(parts)
