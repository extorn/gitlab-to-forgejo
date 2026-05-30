
from typing import List

from pyforgejo import Organization, Repository, Team, User

from fg_migration import fg_print
from fg_migration.canonical_types import CanonicalOrganization, CanonicalOrganizations, CanonicalRepo, CanonicalRepoAccessor, CanonicalRepoAccessors, CanonicalRepositoryRole, CanonicalSystemUser, CanonicalTeam, MigrationSource
from fg_migration.forgjo import ForgejoMigrator, ForgejoRolePermissionDefinition, ForgejoTeamDefinition
from migrate import ForgejoMigrationConfig, MigrationConfig


class Migrator:

    migration_config : MigrationConfig
    migration_config_forgejo : ForgejoMigrationConfig
    fg_api : ForgejoMigrator
    migration_source: MigrationSource

    def __init__(self, migration_config:MigrationConfig, migration_source:MigrationSource, migration_config_forgejo:ForgejoMigrationConfig, fg_api:ForgejoMigrator):
        self.fg_api = fg_api
        self.migration_config_forgejo = migration_config_forgejo
        self.migration_config = migration_config
        self.migration_source = migration_source
    
        

    # def _import_project_labels(
    #     fg_api: ForgejoMigrator,
    #     labels: List[gitlab.v4.objects.ProjectLabel],
    #     project_owner: str,
    #     project_name: str,
    # ):
    #     forgejo_safe_project_owner_name = name_clean(project_owner)
    #     forgejo_safe_project_name = name_clean(project_name)
    #     """import labels for a repository"""
    #     for label in labels:
    #         if not fg_api.forgejo_label_exists(owner=forgejo_safe_project_owner_name, repo=forgejo_safe_project_name, labelname=label.name):  # need this because status 422 returned for conflict, not 409 
    #             try:
    #                 fg_api.fg_api.issue.create_label(owner=forgejo_safe_project_owner_name, repo=forgejo_safe_project_name, name=label.name, color=label.color, description=label.description)
    #                 fg_print.info(f"Label {label.name} imported!")
    #             except ConflictError:
    #                 continue # already exists :-)
    #             except Exception as e:
    #                 detail = fg_api._get_exception_detail(e)
    #                 fg_print.error(
    #                     f"Label {label.name} import failed: {detail}",
    #                     f"Failed to import label {label.name} for project {forgejo_safe_project_name} in Forgejo: {detail}",
    #                 )
    #                 continue



    # def _import_project_milestones(
    #     fg_api: ForgejoMigrator,
    #     milestones: List[gitlab.v4.objects.ProjectMilestone],
    #     project_owner: str,
    #     project_name: str,
    # ):
    #     """import milestones for a repository from a gitlab project"""
    #     forgejo_safe_project_name = name_clean(project_name)
    #     forgejo_safe_project_owner_name = name_clean(project_owner)
    #     forgejo_milestones = fg_api.get_forgejo_milestones(owner=forgejo_safe_project_owner_name, repo=forgejo_safe_project_name)
    #     for milestone in milestones:
    #         # Note: forgejo_add_milestone appends to the cached list of forgejo_milestones too for efficiency.
    #         success = fg_api.forgejo_add_milestone(owner=forgejo_safe_project_owner_name, repo=forgejo_safe_project_name, 
    #                                         forgejo_milestones=forgejo_milestones, title=milestone.title, 
    #                                         description=milestone.description, due_date=milestone.due_date, 
    #                                         state=milestone.state)
    #         if not success:
    #             continue



    # def _import_project_issues(
    #     fg_api: ForgejoMigrator,
    #     issues: List[gitlab.v4.objects.ProjectIssue],
    #     project_owner: str,
    #     project_name: str,
    # ):
    #     """Import issues for a repo from a gitlab project"""
    #     forgejo_safe_project_owner = name_clean(project_owner)
    #     forgejo_safe_project_name = name_clean(project_name)

    #     # reload all existing milestones and labels, needed for assignment in issues
    #     forgejo_milestones = fg_api.get_forgejo_milestones(owner=forgejo_safe_project_owner, repo=forgejo_safe_project_name)
    #     forgejo_labels = fg_api._get_forgejo_labels(owner=forgejo_safe_project_owner, repo=forgejo_safe_project_name)
    #     # get a list of all existing forgejo issues
    #     forgejo_issues = fg_api.get_forgejo_issues(owner=forgejo_safe_project_owner, repo=forgejo_safe_project_name)
        
    #     for issue in issues:
    #         if not fg_api.forgejo_issue_exists(forgejo_issues, repo=forgejo_safe_project_name, issue_title=issue.title):
    #             due_date = ""
    #             if issue.due_date is not None:
    #                 due_date = dateutil.parser.parse(issue.due_date).strftime(
    #                     "%Y-%m-%dT%H:%M:%SZ"
    #                 )

    #             # extract assignee, mapping to forgejo safe username
    #             assignee = None
    #             if issue.assignee is not None:
    #                 assignee = name_clean(issue.assignee["username"])

    #             # extract list of assignees, mapping to forgejo safe username
    #             assignees : List[str] = []
    #             for tmp_assignee in issue.assignees:
    #                 assignees.append(name_clean(tmp_assignee["username"]))

    #             # Get milestone id for the issue, if milestone is assigned to the issue in Gitlab.
    #             # # We need to get the milestone id for the milestone title from Forgejo, because the 
    #             # milestone id in Gitlab is not the same as the milestone id in Forgejo, and we need 
    #             # the milestone id for the assignment of the milestone to the issue in Forgejo. 
    #             # If there is no milestone with the same title in Forgejo, we do not assign a milestone 
    #             # to the issue in Forgejo, because there is no equivalent milestone in Forgejo.
    #             forgejo_milestoneId = None
    #             missing_milestone = False
    #             if issue.milestone is not None:
    #                 forgejo_milestoneId = fg_api.find_forgejo_milestone_id_by_title(forgejo_milestones, issue.milestone["title"]) # N.b. gitlab issue so dict
    #                 if forgejo_milestoneId is None:
    #                     # if this happens, something went wrong with the milestone import, because the milestone assigned 
    #                     # to the issue in Gitlab should have been imported to Forgejo in the milestone import step before 
    #                     # the issue import step, so we print an error and skip the milestone assignment for this issue, 
    #                     # but we continue with the import of the issue without the milestone assignment, because the 
    #                     # existence of the milestone is not a failure for the import of the issue, we just skip the 
    #                     # milestone assignment for this issue and continue with the import of the issue without the 
    #                     # milestone assignment.
    #                     fg_print.error(
    #                         f"Milestone {issue.milestone['title']} assigned to issue {issue.title} does not exist in Forgejo, skipping milestone assignment for this issue!",
    #                         f"Failed to import issue {issue.title} for project {forgejo_safe_project_name} in Forgejo",
    #                     )
    #                     missing_milestone = True
    #             if missing_milestone:
    #                 continue # stop the import of this issue (to allow milestone import to be fixed and re-run not to create duplicate issues)


    #             missing_label = False
    #             forgejo_issue_label_ids : List[int] = []
    #             for label in issue.labels:
    #                 existing_label : Label = None
    #                 existing_label = next(
    #                     (item for item in forgejo_labels if item.name == label), None
    #                 )
    #                 if existing_label:
    #                     forgejo_issue_label_ids.append(existing_label.id)
    #                 else:
    #                     fg_print.error(
    #                         f"Label {label} assigned to issue {issue.title} does not exist in Forgejo, skipping label assignment for this issue!",
    #                         f"Failed to import issue {issue.title} for project {repo} in Forgejo",
    #                     )
    #                     missing_label = True
    #                     break
    #             if missing_label:
    #                 continue # stop the import of this issue (to allow milestone import to be fixed and re-run not to create duplicate issues)
                    
    #             try:
    #                 fg_api.fg_api.issue.create_issue(owner=forgejo_safe_project_owner, repo=forgejo_safe_project_name,
    #                                         title=issue.title, body=issue.description,
    #                                         assignee=assignee, assignees=assignees,
    #                                         milestone=forgejo_milestoneId, labels=forgejo_issue_label_ids,
    #                                         due_on=due_date, closed=issue.state == "closed")
    #                 fg_print.info(f"Issue {issue.title} imported!")
    #             except Exception as e:
    #                 detail = fg_api._get_exception_detail(e)
    #                 fg_print.error(
    #                     f"Issue {issue.title} import failed: {detail}"
    #                     f"Failed to import issue {issue.title} for project {forgejo_safe_project_name} in Forgejo: {detail}",
    #                 )


    def _resolve_forgejo_repo_owner(self, source_repo: CanonicalRepo) -> tuple[int|None,str|None] | None:
        
        if source_repo.is_individual:
            if user := self.fg_api.get_forgejo_user(username=source_repo.get_safe_owner_name()):
                return self._get_owner_identity(user)
            else:
                fg_print.error(f"Failed to load Forgejo owner User for Forgejo repository {source_repo.get_safe_name()}, skipping import of {source_repo.source_type} {source_repo.name}!")
        else:
            if org := self.fg_api.get_forgejo_organization(repo=source_repo, org_name=source_repo.get_safe_owner_name()):
                return self._get_owner_identity(org)
            else:
                fg_print.error(f"Failed to load Forgejo owner organization for repository {source_repo.get_safe_name()}, skipping import of {source_repo.source_type} {source_repo.name}!")
        return None


    @staticmethod
    def _get_owner_identity(forgejo_owner : Organization|User) -> tuple[int|None,str|None]:
        # org has a username, user has a login... either is used as identity of owner for any given repository
        name = getattr(forgejo_owner, "username", None) or getattr(forgejo_owner, "login", None)
        return (forgejo_owner.id, name)



    def _run_inbuilt_repo_import(self, source_repo: CanonicalRepo):
        """Run the inbuilt import on the project"""
        
        # get either the Forgejo User or Organization name as appropriate for this gitlab project owner
        forgejo_owner = self._resolve_forgejo_repo_owner(source_repo=source_repo)
        
        if forgejo_owner is None:
            fg_print.error(f"Importing {source_repo.source_system} {source_repo.name}. Failed to locate Forgejo repository owner {source_repo.get_safe_owner_name()} for repository {source_repo.get_safe_name()}, skipping import!",
                        f"Importing {source_repo.source_system} {source_repo.name}. Failed to locate Forgejo repository owner for repository {source_repo.get_safe_name()}")
            return
        
        forgejo_owner_id,forgejo_owner_username = forgejo_owner
        
        if forgejo_owner_username is None or forgejo_owner_id is None:
            fg_print.error(f"Importing {source_repo.source_system} {source_repo.name}. Located incomplete Forgejo repository owner {source_repo.get_safe_owner_name()} for repository {source_repo.get_safe_name()}, skipping import!",
                        f"Importing {source_repo.source_system} {source_repo.name}. Located incomplete Forgejo repository owner for repository {source_repo.get_safe_name()}")
            return


        if not self.fg_api.forgejo_repo_exists(owner_username=forgejo_owner_username, repo=source_repo.get_safe_name()):
            
            fg_print.info(f"Importing {source_repo.source_system} {source_repo.source_type} {source_repo.name} from {source_repo.clone_url}...")
            
            try:
                imported_repo : Repository = self.fg_api.fg_api.repository.repo_migrate(
                                            auth_password=source_repo.auth_password,
                                            auth_username=source_repo.auth_username,
                                            auth_token=source_repo.auth_token,
                                            clone_addr=source_repo.clone_url,
                                            description=source_repo.description,
                                            service="gitlab",
                                            issues=True,
                                            labels=True,
                                            milestones=True,
                                            mirror=False,
                                            pull_requests=True,
                                            releases=True,
                                            private=source_repo.is_private,
                                            repo_name=source_repo.get_safe_name(),
                                            uid=forgejo_owner_id,
                                            wiki=True,
                                    )
                fg_print.info(f"{source_repo.source_system} {source_repo.source_type} {source_repo.get_safe_name()} imported from {source_repo.clone_url} and available at {imported_repo.clone_url}!")
            except Exception as e:
                detail = self.fg_api._get_exception_detail(e)
                fg_print.error(f"{source_repo.source_system} {source_repo.source_type} {source_repo.get_safe_name()} import failed from url {source_repo.clone_url} : {detail}")  



    def _import_repository_accessors(
        self,
        source_repo: CanonicalRepo,
        migration_source:MigrationSource
    ):
        """Import all teams or individuals that should have access to a repository"""

        repo_accessors : CanonicalRepoAccessors = migration_source.list_repository_accessors(source_repo)

        """import collaborators for a repository"""
        if source_repo.is_individual:
            fg_print.info(f"\nImporting collaborators for personal {source_repo.source_type} {source_repo.name}...")
        else:
            fg_print.info(f"\nImporting collaborators for shared {source_repo.source_type} {source_repo.name}...")
        
        
        if len(repo_accessors.members) == 0:
            fg_print.info(f"No {repo_accessors.source_type} found for {source_repo.source_type} {source_repo.name}, skipping!")
            return

        # Look up the actual stored username in the database - ensures the project exists but is a marginal overhead
        forgejo_repo_owner = self._resolve_forgejo_repo_owner(source_repo=source_repo)
        if forgejo_repo_owner is None:
            fg_print.error(f"Failed to determine {source_repo.source_system} owner for {source_repo.source_type} {source_repo.name}, skipping import!")
            return
        else:
            _,forgejo_owner_username = forgejo_repo_owner
        
        if forgejo_owner_username is None:
            fg_print.error(f"Importing {source_repo.source_system} {source_repo.name} accessors. Located incomplete Forgejo repository owner {source_repo.get_safe_owner_name()} for repository {source_repo.get_safe_name()}, skipping import!",
                        f"Importing {source_repo.source_system} {source_repo.name} accessors. Located incomplete Forgejo repository owner for repository {source_repo.get_safe_name()}")
            return
        
        # get list of Users that are collaborators already.
        existing_collaborators = self.fg_api.get_forgejo_collaborators(owner_username=forgejo_owner_username, repo=source_repo.get_safe_name())
        existing_collaborator_ids :set[int] = {user.id for user in existing_collaborators if user.id is not None} # id should ALWAYS be not null since from database

        needs_direct_user_collaborators = False # This will become True if not all collaborators are in a team that is itself a Collaborator for this repository
        all_forgejo_teams_members_usernames : set[str] = set() # Collect all users that are members of some team
        if not source_repo.is_individual:
            # owner is an organization
            forgejo_teams = self.fg_api.get_forgejo_teams(org_name=forgejo_owner_username)
            existing_repo_teams = self.fg_api.forgejo_list_team_in_repository(owner_username=forgejo_owner_username, repo_name=source_repo.get_safe_name())
            existing_repo_team_ids = {team.id for team in existing_repo_teams}
            needs_direct_user_collaborators = not (self.migration_config.IS_FUZZY_TEAMS_ALLOWED)
            authorized_forgejo_usernames = {member.get_safe_username() for member in repo_accessors.members}

            forgejo_team : Team
            for forgejo_team in forgejo_teams:
                add_team_to_repo = False
                if forgejo_team.id in existing_repo_team_ids:
                    fg_print.info(f"Skipping team {forgejo_team.name}, already attached to repository {source_repo.get_safe_name()}")
                    continue # examine next team in user_teams
                
                # Only add non empty teams if all members are repository collaborators
                team_members = self.fg_api.get_forgejo_team_members(team=forgejo_team)

                if len(team_members) == 0:
                    add_team_to_repo = self.migration_config.ADD_EMPTY_TEAMS_TO_REPOS
                else:
                    add_team_to_repo = True
                    for member in team_members:
                        if member.login and not member.login in authorized_forgejo_usernames:
                            # at least one user in team is not authorized, do not add team as collaborator
                            add_team_to_repo = False
                            break # exit for team_members loop

                # we now know we should add this team (all members authorized) or not
                if add_team_to_repo:
                    self.fg_api.forgejo_add_team_to_repository(owner_username=forgejo_owner_username,
                                                                repo_name=source_repo.get_safe_name(),
                                                                team_name=forgejo_team.name)
                    if needs_direct_user_collaborators:
                        #TODO will anyone ever want to add all users individually as well as in their teams? (if so, leave this set empty)
                        # add to the list of all those collaborators already accounted for in teams
                        all_forgejo_teams_members_usernames.update(member.login for member in team_members)
            
        if source_repo.is_individual or needs_direct_user_collaborators:
            # For every user that is a project member
            repo_accessors_not_added_via_teams = [accessor
                                                           for accessor in repo_accessors.members
                                                           if accessor.get_safe_username() not in all_forgejo_teams_members_usernames]
            
            # group the accessors by unique source access level
            grouped_repo_accessors_by_source_access_level : dict[str,set[CanonicalRepoAccessor]] = CanonicalRepoAccessors.get_grouped_by_access_level(repo_accessors_not_added_via_teams)

            #TODO do I need to sort the source access level descending to ensure we always add collaborators with the highest access level?
            
            for source_access_level,source_repo_accessors in grouped_repo_accessors_by_source_access_level.items():
                
                role_definition = self._get_forgejo_role_definition(source_access_level=source_access_level, fuzzy=self.migration_config.IS_FUZZY_USERS_ALLOWED)
                
                if role_definition is None:
                    source_usernames : set[str] = {accessor.username for accessor in source_repo_accessors}
                    if self.migration_config.IS_FUZZY_USERS_ALLOWED:
                        fg_print.error(f"Collaborator import failed for users {source_usernames}. Unable to find a direct match for user with source access level {source_access_level}. Check fuzzy match upgrade/downgrade settings in .migrate.ini",
                                    f"Collaborator import failed for users {source_usernames}. Unable to find a direct match for user with source access level {source_access_level}. Check fuzzy match upgrade/downgrade settings in .migrate.ini")
                    else:
                        fg_print.error(f"Collaborator import failed for users {source_usernames}. Unable to find neither a direct nor fuzzy match for team with source access level {source_access_level}. Check fuzzy match upgrade/downgrade settings in .migrate.ini",
                                    f"Collaborator import failed for users {source_usernames}. Unable to find neither a direct nor fuzzy match for team with source access level {source_access_level}. Check fuzzy match upgrade/downgrade settings in .migrate.ini")
                    # try next access level in use.
                    continue
                
                forgejo_user_permissions = role_definition.permission

                for accessor in source_repo_accessors:
                    self._import_individual_user_collaborator(
                                        existing_collaborator_ids=existing_collaborator_ids,
                                        accessor=accessor,
                                        source_repo=source_repo,
                                        forgejo_permissions=forgejo_user_permissions)



    def _import_individual_user_collaborator(self,
                                            existing_collaborator_ids:set[int],
                                            accessor:CanonicalRepoAccessor,
                                            source_repo:CanonicalRepo,
                                            forgejo_permissions:str):
        """identical to _import_individual_collaborator except first checks a user exists in Forgejo with that username"""
        forgejo_user = self.fg_api.get_forgejo_user(username=accessor.get_safe_username())
        if forgejo_user is not None:
            self.fg_api.forgejo_add_replace_collaborator(
                                        existing_collaborator_ids=existing_collaborator_ids, 
                                        collaborator_id=forgejo_user.id,
                                        collaborator_name=forgejo_user.login,
                                        repo=source_repo,
                                        permissions=forgejo_permissions) 
            # Note; this means we can only add a user once...
            # TODO what if they are a member of say 3 teams. will this mean they might get their permission downgraded?
            existing_collaborator_ids.add(forgejo_user.id)
        else:
            fg_print.error(f"Unable to add non existent Forgejo user {accessor.get_safe_username()} as collaborator of {source_repo.get_safe_name()}",
                            f"Unable to add non existent Forgejo user {accessor.get_safe_username()} as collaborator of {source_repo.get_safe_name()}")



    def _import_user_keys(
        self,
        user:CanonicalSystemUser,
    ):
        """import public keys for a user"""
        forgejo_keys = self.fg_api.get_forgejo_user_keys(username=user.get_safe_username())
        forgejo_gpg_keys = self.fg_api.get_forgejo_user_gpg_keys(username=user.get_safe_username())

        #
        # SSH keys
        #
        forgejo_key_values = {k.key for k in forgejo_keys}
        new_keys = [key
                    for key in user.keys
                    if key.key not in forgejo_key_values]
        for key in new_keys:
            # Import key
            new_key = self.fg_api.forgejo_add_user_key(username=user.get_safe_username(), key_name=key.name, key_content=key.key)
            if new_key is not None:
                fg_print.info(f"For {user.source_system} User {user.username} Added new Public Key {key.name} : {new_key.key}")
            # if new_key is not None:
            #     forgejo_keys.append(new_key)

        #
        # GPG keys
        #
        forgejo_gpg_key_values = {k.public_key for k in forgejo_gpg_keys}
        new_gpg_keys = [key
                for key in user.gpg_keys
                if key.armored_public_key not in forgejo_gpg_key_values]
        for gpg_key in new_gpg_keys:
            # Import key
            new_key = self.fg_api.forgejo_add_gpg_key(username=user.get_safe_username(), key_name=gpg_key.name, armored_public_key=gpg_key.armored_public_key, armored_signature=gpg_key.armored_signature)
            if new_key is not None:
                fg_print.info(f"For {user.source_system} User {user.username} Added new GPG Key {gpg_key.name} : {new_key.public_key}")
            # if new_key is not None:
            #     forgejo_gpg_keys.append(new_key)



    def _get_forgejo_team_definition(self, source_access_level:str, fuzzy:bool) -> ForgejoTeamDefinition | None:
        """Retrieves a ForgejoTeamDefinition, creating a new one and adding neccessary data to the maps as required"""
        # get forgejo team definition matching gitlab permission level
        repository_role : CanonicalRepositoryRole|str = self.migration_source.get_repository_role(source_access_level=source_access_level)
        
        if not isinstance(repository_role, CanonicalRepositoryRole):
            nearest_repository_role = None
            if fuzzy:
                fg_print.warning(f"{self.migration_source.getSourceSystemName()} Role:Forgejo Team Mapping missing for {repository_role}. Using fuzzy matching")
                nearest_repository_role = self.migration_source.get_nearest_repository_role(source_access_level=source_access_level,
                                                                                allow_downgrade=self.migration_config.ALLOW_FUZZY_AUTH_DOWNGRADE,
                                                                                allow_upgrade=self.migration_config.ALLOW_FUZZY_AUTH_UPGRADE)
            # if it still isn't valid.
            if not isinstance(nearest_repository_role, CanonicalRepositoryRole):
                return None
            # we now have a valid nearest_repository_role, lets create a mapping based on the team referenced by that for our invalid one.
            self.fg_api.addTeamMapping(map_from_str=repository_role, to_role=nearest_repository_role)

        # now we definitely have a team mapped against this role, even if it is just a basic string
        return self.fg_api.team_definitions[repository_role]
    

    def _get_forgejo_role_definition(self, source_access_level:str, fuzzy:bool) -> ForgejoRolePermissionDefinition | None:
        """Retrieves a ForgejoRoleDefinition, creating a new one and adding neccessary data to the maps as required"""
        # get forgejo team definition matching gitlab permission level
        repository_role : CanonicalRepositoryRole|str = self.migration_source.get_repository_role(source_access_level=source_access_level)
        
        if not isinstance(repository_role, CanonicalRepositoryRole):
            nearest_repository_role = None
            if fuzzy:
                fg_print.warning(f"{self.migration_source.getSourceSystemName()} Role:Forgejo Team Mapping missing for {repository_role}. Using fuzzy matching")
                nearest_repository_role = self.migration_source.get_nearest_repository_role(source_access_level=source_access_level,
                                                                                allow_downgrade=self.migration_config.ALLOW_FUZZY_AUTH_DOWNGRADE,
                                                                                allow_upgrade=self.migration_config.ALLOW_FUZZY_AUTH_UPGRADE)
            # if it still isn't valid.
            if not isinstance(nearest_repository_role, CanonicalRepositoryRole):
                return None
            # we now have a valid nearest_repository_role, lets create a mapping based on the team referenced by that for our invalid one.
            self.fg_api.addRoleMapping(map_from_str=repository_role, to_role=nearest_repository_role)

        # now we definitely have a team mapped against this role, even if it is just a basic string
        return self.fg_api.role_definitions[repository_role]




    def _import_teams(self, organization:CanonicalOrganization):
        """import all organization members (users) as members to a Forgejo organization team if their permissions
           maps to a declared team or if fuzzy team matching is enabled"""
        
        # build a lookup for team name against team
        existing_forgejo_teams = {team.name:team
                                  for team in self.fg_api.get_forgejo_teams(org_name=organization.get_safe_username())
                                  if team.name is not None} # If a team is returned without a name, we can't use it anyway without inferring from permissions so lets just strip them out.
        # list existing teams #TODO just noisy?
        fg_print.info(f"Existing forgejo teams for Forgejo organization {organization.get_safe_username()} : {existing_forgejo_teams.keys()}")
        
        canonical_teams: List[CanonicalTeam] = organization.teams
        
        # list all the usernames being mapped into teams
        #all_team_forgejo_usernames = [user.get_safe_username() for team in canonical_teams for user in team.users]
        #fg_print.info(f"Identified Forgejo roles for members for {organization.source_type} {organization.username} : {all_team_forgejo_usernames}")
        
        # For each used gitlab access level role
        for canonical_team in canonical_teams:
            forgejo_team_definition = self._get_forgejo_team_definition(source_access_level=canonical_team.source_access_level,
                                                                        fuzzy=self.migration_config.IS_FUZZY_TEAMS_ALLOWED)
            if forgejo_team_definition is None:
                team_source_usernames = [user.username for user in canonical_team.users]
                if not self.migration_config.IS_FUZZY_TEAMS_ALLOWED and not self.migration_config.IS_FUZZY_USERS_ALLOWED:
                    fg_print.error(f"Import to Team failed for {self.migration_source.getSourceSystemName()} users {team_source_usernames}. Unable to find a direct match for team with {self.migration_source.getSourceSystemName()}  access level {canonical_team.source_access_level}. Import will need either Fuzzy teams or Fuzzy users to succeed.",
                                f"Import to Team failed for {self.migration_source.getSourceSystemName()} users {team_source_usernames}. Unable to find a direct match for team with {self.migration_source.getSourceSystemName()}  access level {canonical_team.source_access_level}. Import will need either Fuzzy teams or Fuzzy users to succeed.")
                elif not self.migration_config.IS_FUZZY_USERS_ALLOWED:
                    fg_print.error(f"Import to Team failed for {self.migration_source.getSourceSystemName()} users {team_source_usernames}. Unable to find neither a direct nor fuzzy match for team with {self.migration_source.getSourceSystemName()}  access level {canonical_team.source_access_level}. Check fuzzy match < > settings in .migrate.ini",
                                f"Import to Team failed for {self.migration_source.getSourceSystemName()} users {team_source_usernames}. Unable to find neither a direct nor fuzzy match for team with {self.migration_source.getSourceSystemName()}  access level {canonical_team.source_access_level}. Check fuzzy match < > settings in .migrate.ini")
                else: # IS_FUZZY_USERS
                    fg_print.warning(f"Import to Team failed for {self.migration_source.getSourceSystemName()} users {team_source_usernames}. Unable to find neither a direct nor fuzzy match for team with {self.migration_source.getSourceSystemName()}  access level {canonical_team.source_access_level}. User will be added as an individual Collaborator with fuzzy matching if possible")
                # try next access level in use.
                continue
                    
                
            # List of matching teams to use
            matched_team = existing_forgejo_teams.get(forgejo_team_definition.name)
            if matched_team is not None:
                # get a list of existing users and warn that they will get extra access to what they currently do.
                # if the imported team matching theirs has access to new repositories, they will be granted that access too.
                existing_users = set(self.fg_api.get_forgejo_team_members(matched_team))
                fg_print.warning(f"Pre-existing team users will be granted access to new repositories that are created with access granted to this team. Affected Forgejo Team {matched_team.name}, usernames: {existing_users}")

            matching_forgejo_teams = {} # leave as set in case we can alter Owner group name in future 


            # Handle the owners specially since that team is always pre-created in Forgejo and 
            # a new one cannot be added with those permissions. We might need to update it's name to match user requirement
            # NOTE: this was the idea, but actually the team names "Owners" is hardcoded in Forgejo so it breaks other things if you change it
            forgejo_team_definition.role == 
            #if self.fg_api.is_owner_group(matched_team):
            #    matching_forgejo_teams.add(self.fg_api.get_default_owners_team_name())
            
            # find the first matching team
            if matched_team is not None:
                matching_forgejo_teams.append(matched_team)
            
            if len(matching_forgejo_teams) == 0:
                # No matching team found, lets create one
                forgejo_team = self.fg_api.forgejo_add_organization_team(org_name=organization.get_safe_username(), definition=forgejo_team_definition)
                if forgejo_team is None:
                    fg_print.warning(f"Forgejo Team {forgejo_team_definition.name} not available, skipping!")
                    # Unable to add users to this team, continue with next iteration of for loop.
                    continue
                # add to the empty list of matches
                matching_forgejo_teams.append(forgejo_team)
                # also update the existing teams set for consistency.
                existing_forgejo_teams[forgejo_team.name] = forgejo_team
            elif len(matching_forgejo_teams) > 1:
                fg_print.warning(f"Multiple Forgejo teams were found with name {forgejo_team_definition.name}, this shouldn't be possible in Forgejo, using first")
            
            # get matching Forgejo team
            forgejo_team = matching_forgejo_teams[0]
            current_definition = ForgejoTeamDefinition.fromTeam(forgejo_team)
            
            # check team matches that desired (update if not)
            if current_definition != forgejo_team_definition:
                # update the team to be named as script user has configured.
                # NOTE: you MUST NOT change the name of the Owners team. It must be hardcoded in Forgejo somewhere.
                forgejo_team = self.fg_api.forgejo_update_organization_team(team=forgejo_team, definition=forgejo_team_definition)
            
            # Add all matching users to this team
            #TODO reliable check needed 
            existing_member_names = {member.login
                                     for member in self.fg_api.get_forgejo_team_members(team=forgejo_team)
                                     if member.login is not None}

            for canonical_user in canonical_team.users:
                if canonical_user.get_safe_username() in existing_member_names:
                    fg_print.info(f"User {canonical_user.get_safe_username()} is already member of organization {organization.get_safe_username()} team {forgejo_team.name}, skipping.")
                    continue

                added = self.fg_api.forgejo_add_user_to_organization_team(organization_name=organization.get_safe_username(),
                                                                           username=canonical_user.get_safe_username(), team=forgejo_team)
                if added:
                    fg_print.info(f"Imported {self.migration_source.getSourceSystemName()} user {canonical_user.username} permissions in {organization.source_type} {organization.name} team {forgejo_team_definition.name}")
                else:
                    fg_print.error(f"Failed to import {self.migration_source.getSourceSystemName()} user {canonical_user.username} permissions in {organization.source_type} {organization.name}",
                                    f"Failed to import {self.migration_source.getSourceSystemName()} user {canonical_user.username} permissions in {organization.source_type} {organization.name}")



    def import_users(self, notify=False):
        """import users and their public keys"""
        # read all users
        users: List[CanonicalSystemUser] = self.migration_source.list_system_users()

        fg_print.info(f"Found {len(users)} {self.migration_source.getSourceSystemName()} users")

        user : CanonicalSystemUser
        for user in users:
            
            fg_print.info(f"Importing {user.source_system} user {user.username} as {user.get_safe_username()}...")

            fg_print.info(f"Found {len(user.gpg_keys)} gpg keys for user {user.username}")
            fg_print.info(f"Found {len(user.keys)} public keys for user {user.username}")

            if not self.fg_api.forgejo_user_exists(username=user.get_safe_username()):  # need this because status 422 returned for conflict, not 409 
                isAdded = self.fg_api.forgejo_add_user(user=user, notify=notify)
                if not isAdded:
                    # something went wrong with the user import. can't do any more for this user.
                    continue

            # import public keys if possible
            self._import_user_keys(user=user)



    def import_organizations(self):
        """import all organizations and their members"""
        # read all users
        organizations: CanonicalOrganizations = self.migration_source.list_organizations()
        
        fg_print.info(f"Found {len(organizations)} {self.migration_source.getSourceSystemName()} {organizations.source_type}")

        group_names = [org.username for org in organizations]
        fg_print.info(f"Importing groups... {group_names}")
        
        for organization in organizations.members:
            # create the Forgejo organization
            fg_print.info(f"Importing {organization.source_type} {organization.username} as Forgejo organization {organization.get_safe_username()}...")

            # Add the forgejo organization
            added_org = self.fg_api.forgejo_add_organization(org=organization)
            if not added_org:
                fg_print.error(f"Skipping adding teams for Organization {organization.get_safe_username()} that does not exist!",
                               f"Skipping adding teams for Organization {organization.get_safe_username()} that does not exist!")
                continue # org does not exist

            # Finally, import those group members
            self._import_teams(organization=organization)





    def import_repos(self):
        """read all projects and their issues"""
        
        source_repos : List[CanonicalRepo] = self.migration_source.listRepos()

        source_repo : CanonicalRepo
        for source_repo in source_repos:
            
            if source_repo.is_individual:
                fg_print.info(f"Importing personal {source_repo.source_type} {source_repo.name} from owner {source_repo.owner_name}")
            else:
                fg_print.info(f"Importing {source_repo.source_type} {source_repo.name} from owner {source_repo.owner_name}")
                
            # import project repo
            self._run_inbuilt_repo_import(source_repo=source_repo)

            self._import_repository_accessors(source_repo=source_repo, migration_source=self.migration_source)

            # Handled by inbuilt repo migration
            # import labels
            #labels: List[gitlab.v4.objects.ProjectLabel] = project.labels.list(get_all=True)
            #fg_print.info(f"Found {len(labels)} labels for project {project.name}")
            #_import_project_labels(fg_api, labels, project_owner_name, project.name)

            # Handled by inbuilt repo migration
            # import milestones
            #milestones: List[gitlab.v4.objects.ProjectMilestone] = project.milestones.list(all=True)
            #fg_print.info(f"Found {len(milestones)} milestones for project {project.name}")
            #_import_project_milestones(fg_api, milestones, project_owner_name, project.name)

            # Handled by inbuilt repo migration
            # import issues
            #issues: List[gitlab.v4.objects.ProjectIssue] = project.issues.list(get_all=True)
            #fg_print.info(f"Found {len(issues)} issues for project {project.name}")
            #_import_project_issues(fg_api, issues, project_owner_name, project.name)
