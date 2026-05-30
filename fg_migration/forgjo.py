
from copy import deepcopy
from dataclasses import dataclass, field
import os
import random
import string
from typing import Dict
from typing import List
from pyforgejo.core import RequestOptions
from typing_extensions import deprecated

import dateutil.parser
from httpx import Client as HttpxClient

import pyforgejo  # pip install pyforgejo (https://github.com/h44z/pyforgejo)

# Forgejo API imports:
from pyforgejo import ConflictError, CreateTeamOptionPermission, GpgKey, Issue, Label, Milestone, NotFoundError, Organization, PublicKey, PyforgejoApi, Repository, Team, TeamPermission, User
from pyforgejo.core.api_error import ApiError

from fg_migration import fg_print
from fg_migration.canonical_types import CanonicalOrganization, CanonicalRepo, CanonicalRepositoryRole, CanonicalSystemUser, CanonicalTeam
from fg_migration.config_types import ForgejoConfig, ForgejoMigrationConfig
from fg_migration.utils import diff_dataclasses

@dataclass
class ForgejoRolePermissionDefinition:
    can_create_org_repo:bool = False
    includes_all_repositories:bool = False
    permission:CreateTeamOptionPermission = ""
    units_map: dict[str,str] = field(default_factory=dict) # use of field here ensures new instance for every instance of the class

    def diff(self, other:ForgejoRolePermissionDefinition) -> str :
        return diff_dataclasses(self,other)

@dataclass
class ForgejoTeamDefinition:
    name: str
    description: str
    permissions: ForgejoRolePermissionDefinition

    @staticmethod
    def fromTeam(team:Team) -> ForgejoTeamDefinition:
        return ForgejoTeamDefinition(name=team.name,
                              description=team.description,
                              permissions=ForgejoRolePermissionDefinition(
                                  can_create_org_repo=team.can_create_org_repo,
                                  includes_all_repositories=team.includes_all_repositories,
                                  permission=team.permission,
                                  units_map=team.units_map
                              ))
    
    def diff(self, other:ForgejoTeamDefinition) -> str :
        return diff_dataclasses(self,other)


class ForgejoMigrator:
    
    fg_api : pyforgejo.PyforgejoApi
    forgejo_config : ForgejoConfig
    forgejo_migration_config : ForgejoMigrationConfig
    role_definitions : Dict[CanonicalRepositoryRole|str,ForgejoRolePermissionDefinition]
    team_definitions : Dict[CanonicalRepositoryRole|str,ForgejoTeamDefinition]


    def __init__(self, fg_api:pyforgejo.PyforgejoApi, forgejo_config:ForgejoConfig, forgejo_migration_config=ForgejoMigrationConfig):
        self.fg_api = fg_api
        self.forgejo_config = forgejo_config
        self.forgejo_migration_config = forgejo_migration_config
        self._build_role_definitions()
        self._build_team_definitions()
    
    def _get_forgejo_labels(self, owner: str, repo: str) -> List[Label]:
        """get labels for a repository"""
        
        try:
            existing_labels = self.fg_api.issue.list_labels(owner, repo)
            return existing_labels
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load existing labels for project {repo}! {detail}")
            return []



    def  _build_team_definitions(self):
        self.team_definitions = {}
        for role in CanonicalRepositoryRole:
            match role:
                case CanonicalRepositoryRole.OWNER:
                    self.team_definitions[role] = ForgejoTeamDefinition(name=self.forgejo_migration_config.ORG_TEAM_OWNERS_NAME,
                                                                        description=self.forgejo_migration_config.ORG_TEAM_OWNERS_DESCRIPTION,
                                                                        permissions=self.role_definitions[role]),
                case CanonicalRepositoryRole.MAINTAINER:
                    self.team_definitions[role] = ForgejoTeamDefinition(name=self.forgejo_migration_config.ORG_TEAM_MAINTAINERS_NAME,
                                                                        description=self.forgejo_migration_config.ORG_TEAM_MAINTAINERS_DESCRIPTION,
                                                                        permissions=self.role_definitions[role])
                case CanonicalRepositoryRole.DEVELOPER:
                    self.team_definitions[role] = ForgejoTeamDefinition(name=self.forgejo_migration_config.ORG_TEAM_DEVELOPERS_NAME,
                                                                        description=self.forgejo_migration_config.ORG_TEAM_DEVELOPERS_DESCRIPTION,
                                                                        permissions=self.role_definitions[role])
                case CanonicalRepositoryRole.REPORTER:
                    self.team_definitions[role] = ForgejoTeamDefinition(name=self.forgejo_migration_config.ORG_TEAM_REPORTERS_NAME,
                                                                        description=self.forgejo_migration_config.ORG_TEAM_REPORTERS_DESCRIPTION,
                                                                        permissions=self.role_definitions[role])
                case CanonicalRepositoryRole.GUEST:
                    self.team_definitions[role] = ForgejoTeamDefinition(name=self.forgejo_migration_config.ORG_TEAM_GUESTS_NAME,
                                                                        description=self.forgejo_migration_config.ORG_TEAM_GUESTS_DESCRIPTION,
                                                                        permissions=self.role_definitions[role])
                case _:
                    raise Exception(f"No Forgejo Team Definition mapping for Role {role}")   
        


    def _build_role_definitions(self):
        self.role_definitions = {}
        for role in CanonicalRepositoryRole:
            match role:
                case CanonicalRepositoryRole.OWNER:
                    self.role_definitions[role] = ForgejoRolePermissionDefinition(
                                                    role=role,
                                                    permission="admin", # Not supported
                                                    units_map= { "repo.actions": "write", "repo.code": "write", "repo.ext_issues": "read", 
                                                                 "repo.ext_wiki": "admin", "repo.issues": "write", "repo.packages": "write", 
                                                                 "repo.projects": "write", "repo.pulls": "owner", "repo.releases": "write", 
                                                                 "repo.wiki": "admin" }
                                                )
                case CanonicalRepositoryRole.MAINTAINER:
                    self.role_definitions[role] = ForgejoRolePermissionDefinition(
                                                    role=role,
                                                    permission="admin",
                                                    units_map= { "repo.actions": "write", "repo.code": "write", "repo.ext_issues": "read", 
                                                                "repo.ext_wiki": "admin", "repo.issues": "write", "repo.packages": "write", 
                                                                "repo.projects": "write", "repo.pulls": "owner", "repo.releases": "write", 
                                                                "repo.wiki": "admin" }
                                                )
                case CanonicalRepositoryRole.DEVELOPER:
                    self.role_definitions[role] = ForgejoRolePermissionDefinition(
                                                    role=role,
                                                    permission="write",
                                                    units_map= { "repo.actions": "read", "repo.code": "write", "repo.ext_issues": "read", 
                                                                "repo.ext_wiki": "read", "repo.issues": "write", "repo.packages": "write", 
                                                                "repo.projects": "read", "repo.pulls": "owner", "repo.releases": "write", 
                                                                "repo.wiki": "write" }
                                                )
                case CanonicalRepositoryRole.REPORTER:
                    self.role_definitions[role] = ForgejoRolePermissionDefinition(
                                                    role=role,
                                                    permission="read",
                                                    units_map= { "repo.actions": "none", "repo.code": "read", "repo.ext_issues": "read", 
                                                                "repo.ext_wiki": "read", "repo.issues": "write", "repo.packages": "none", 
                                                                "repo.projects": "none", "repo.pulls": "none", "repo.releases": "none", 
                                                                "repo.wiki": "none" }
                                                )
                case CanonicalRepositoryRole.GUEST:
                    self.role_definitions[role] = ForgejoRolePermissionDefinition(
                                                    role=role,
                                                    permission="read",
                                                    units_map= { "repo.actions": "none", "repo.code": "read", "repo.ext_issues": "none", 
                                                                "repo.ext_wiki": "none", "repo.issues": "read", "repo.packages": "read", 
                                                                "repo.projects": "read", "repo.pulls": "read", "repo.releases": "read", 
                                                                "repo.wiki": "read" }
                                                )
                case _:
                    raise Exception(f"No Forgejo Role Definition mapping for Role {role}")
    

    def get_forgejo_milestones(self, owner: str, repo: str) -> List[Milestone]:
        """get milestones for a repository"""

        try:
            existing_milestones : List[Milestone] = self.fg_api.issue.get_milestones_list(owner, repo)
            return existing_milestones
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load existing milestones for project {repo}! {detail}")
            return []



    def get_forgejo_issues(self, owner: str, repo: str) -> List[Issue]:
        """get issues for a repository"""

        try:
            existing_issues = self.fg_api.issue.list_issues(owner, repo)
            return existing_issues
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load existing issues for project {repo}! {detail}")
            return []

    def is_owner_group(self, team:CanonicalTeam) -> bool:
         return team.source_access_level == self.forgejo_config.FORGEJO_DEFAULT_OWNERS_TEAM_NAME)

    def get_default_owners_team_name(self) -> str:
        return self.forgejo_config.FORGEJO_DEFAULT_OWNERS_TEAM_NAME
       

    def get_forgejo_teams(self, org_name: str) -> List[Team]:
        """get teams for an organization"""

        try:
            existing_teams = self.fg_api.organization.org_list_teams(org_name)
            return existing_teams
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load existing teams for organization {org_name}! {detail}")
            return []
        


    def get_forgejo_team_members(self, team: Team) -> List[User]:
        """get members for a team"""

        try:
            members = self.fg_api.organization.org_list_team_members(id=team.id)
            return members
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load team members for team {team.name} {detail}")
            return []



    def get_forgejo_collaborators(self, owner_username: str, repo: str) -> List[User]:
        """get collaborators for a repository"""

        try:
            collaborators = self.fg_api.repository.repo_list_collaborators(owner_username, repo)
            return collaborators
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load collaborators for repo {repo} {detail}")
            return []



    def get_forgejo_user_keys(self, username : str) -> List[PublicKey] :
        """get public keys for a user"""

        try:
            keys = self.fg_api.user.list_keys(username)
            return keys
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load public keys for user {username}! {detail}")
        return []

    def get_forgejo_user_gpg_keys(self, username : str) -> List[GpgKey] :
        """get gpg keys for a user"""

        try:
            keys = self.fg_api.user.user_list_gpg_keys(username)
            return keys
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load gpg keys for user {username}! {detail}")
            
        return []



    def get_forgejo_organization(self, repo: CanonicalRepo, org_name: str) -> Organization:
        
        try:
            #fg_print.info(f"Trying to load forgejo organization {possible_org} for gitlab project {project.name}...")
            org = self.fg_api.organization.org_get(org_name)
            fg_print.info(f"loaded organization {org.full_name} for {repo.source_system} {repo.source_type} {repo.name}!")
            return org
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load forgejo organization {org_name} for repo {repo.get_safe_name()} using {repo.source_system} {repo.source_type} {repo.name}! {detail}")
        return None



    def get_forgejo_user(self, username: str) -> User|None:
        """get user by name"""
        try:
            user = self.fg_api.user.get(username)
            fg_print.info(f"loaded user {user.username}!")
            return user
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to load user {username}! {detail}")
        return None



    def forgejo_user_exists(self, username: str) -> bool:
        """check if a user exists"""
        try:
            user = self.fg_api.user.get(username)
            fg_print.warning(f"User {username} already exists in Forgejo, skipping!")
            return True
        except NotFoundError:
            return False
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.info(f"User {username} not found in Forgejo, importing! {detail}")
            return False


    @deprecated("working, but Not used")
    def forgejo_organization_exists(self, orgname: str) -> bool:
        """check if an organization exists"""
        try:
            org = self.fg_api.organization.org_get(orgname)
            fg_print.warning(f"Organization {orgname} already exists in Forgejo, skipping!")
            return True
        except NotFoundError:
            return False
        except Exception as e:
            fg_print.info(f"Organization {orgname} not found in Forgejo, importing!")
            return False


    @deprecated("working, but Not used")
    def forgejo_team_member_exists(self, username: str, team: Team) -> bool:
        """check if a member exists in a team"""
        existing_members = self.get_forgejo_team_members(team=team)
        if existing_members:
            
            existing_member = next(
                (item for item in existing_members if item.username == username), None
            )

            if existing_member:
                fg_print.warning(
                    f"Member {username} is already in team {team.name}, skipping!"
                )
                return True

            fg_print.info(f"Member {username} is not in team {team.name}, importing!")
            return False

        fg_print.info(f"No members in team {team.name}, importing!")
        return False


    @deprecated("working, but Not used")
    def forgejo_collaborator_exists(self, _owner: str, repo: str, username: str) -> bool:
        """check if a collaborator exists in a repository"""
        try:
            collaborators : List[User] = self.fg_api.repository.repo_list_collaborators(_owner, repo)
            existing = next(
                (c for c in collaborators if c.username == username),
                None,
            )
            if existing:
                fg_print.warning(
                    f"Collaborator {username} already exists in Forgejo, skipping!"
                )
                return True
            else:
                fg_print.info(f"Collaborator {username} not found in Forgejo, importing!")
                return False
        except NotFoundError:
            return False
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to list collaborators for project {repo} for owner {_owner} {detail}!")
            return False



    def forgejo_repo_exists(self, owner_username: str, repo: str) -> bool:
        """check if a repository exists"""
        try:
            fg_print.info(f"Checking if project {repo} exists in Forgejo for owner {owner_username}...")
            repository = self.fg_api.repository.repo_get(owner=owner_username, repo=repo)
            if repository is not None:
                fg_print.warning(f"Project {repo} already exists in Forgejo, skipping!")
                return True
        except Exception as e:
            if isinstance(e, NotFoundError):
                fg_print.info(f"Project {repo} not found in Forgejo, importing!")
                return False
            else:
                detail = self._get_exception_detail(e)
                fg_print.error(f"Failed to check if project {repo} exists in Forgejo for owner {owner_username}! {detail}")

        
        fg_print.info(f"Project {repo} not found in Forgejo, importing!")
        return False



    def forgejo_label_exists(self, owner: str, repo: str, labelname: str) -> bool:
        """check if a label exists in a repository"""
        #issues = self.fg_api.issue.list_issues(owner, repo)
        existing_labels = self.fg_api.issue.list_labels(owner, repo)
        if existing_labels:
            existing_label = next(
                (item for item in existing_labels if item.name == labelname), None
            )

            if existing_label is not None:
                fg_print.warning(
                    f"Label {labelname} already exists in project {repo}, skipping!"
                )
                return True

            fg_print.info(f"Label {labelname} does not exist in project {repo}, importing!")
            return False

        fg_print.info(f"No labels in project {repo}, importing!")
        return False



    def forgejo_issue_exists(self, existing_issues : List[Issue], repo: str, issue_title: str) -> bool:
        """check if an issue exists in a repository"""
        
        if existing_issues:
            existing_issue = next(
                (item for item in existing_issues if item.title == issue_title), None
            )

            if existing_issue is not None:
                fg_print.warning(
                    f"Issue {issue_title} already exists in project {repo}, skipping!"
                )
                return True

            fg_print.info(f"Issue {issue_title} does not exist in project {repo}, importing!")
            return False

        fg_print.info(f"No issues in project {repo}, importing!")
        return False



    def find_forgejo_milestone_id_by_title(self, forgejo_milestones: List[Milestone], title: str) -> int:
        """get milestone id by title"""
        # get the forgejo milestone with matching title
        # the issue, if it exists, otherwise return None
        
        forgejo_milestone : Milestone = next(
            (
                item
                for item in forgejo_milestones
                if item.title == title
            ),
            None,
        )
        if forgejo_milestone:
            return forgejo_milestone.id
        return None



    def find_forgejo_milestone_by_title(self, existing_milestones : List[Milestone], title: str) -> bool:
        """check if a milestone exists in a repository"""
        
        if existing_milestones:
            existing_milestone = next(
                (item for item in existing_milestones if item.title == title), None
            )

            return existing_milestone
        
        return None



    def _forgejo_delete_collaborator(self, repo: CanonicalRepo, collaborator_name: str) -> bool:
        """delete a collaborator from a repository"""
        try:
            self.fg_api.repository.repo_delete_collaborator(owner = repo.get_safe_owner_name(), 
                                                            repo = repo.get_safe_name(), 
                                                            collaborator = collaborator_name)
            fg_print.info(f"Collaborator {collaborator_name} deleted!")
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                    f"Collaborator {collaborator_name} delete failed: {detail}",
                    f"Collaborator {collaborator_name} delete from {repo}, skipping!: {detail}"
                )
            return False
        return True



    def forgejo_add_replace_collaborator(self,
                                        existing_collaborator_ids:set[int], 
                                        collaborator_name:str,
                                        collaborator_id:int,
                                        repo:CanonicalRepo, permissions:str):
        """Add collaboration entry for repo. Will replace any existing one matching the name provided"""
        # If there is an existing collaboration record, delete it.
        if collaborator_id in existing_collaborator_ids:
            deleted = self._forgejo_delete_collaborator(repo=repo,
                                                    collaborator_name=collaborator_name)
            if not deleted:
                return False
        # Add new collaboration record for user
        added = self._forgejo_add_collaborator(repo=repo, 
                                                collaborator_name=collaborator_name,
                                                permission=permissions)
        if not added:
            pass
        return added



    def _forgejo_add_collaborator(self, repo: CanonicalRepo, collaborator_name: str, permission: str) -> bool:
        """add a collaborator to a repository"""
        try:
            self.fg_api.repository.repo_add_collaborator(owner = repo.get_safe_owner_name(), 
                                                        repo = repo.get_safe_name(), 
                                                        collaborator = collaborator_name, 
                                                        permission = permission)
            fg_print.info(f"Collaborator {collaborator_name} imported!")
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                    f"Collaborator name={collaborator_name} import failed: {detail}",
                    f"Collaborator name={collaborator_name} import failed {repo}, skipping!: {detail}"
                )
            return False
        # return true even if the collaborator already exists in the repository, because the existence of the collaborator in the repository is not a failure for the import of the project, we just skip it and continue with the import of the other collaborators
        return True



    def forgejo_add_user(self, user:CanonicalSystemUser, notify: bool) -> bool:
        """add a user to Forgejo, return True if user created or already exists"""

        if not self.forgejo_user_exists(username=user.get_safe_username()): # need this because status 422 returned for conflict, not 409 
            rnd_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
            tmp_password = f"Tmp1!{rnd_str}"
            try:
                self.fg_api.admin.create_user(
                    email=user.email,
                    full_name=user.full_name,
                    login_name=user.get_safe_username(),
                    password=tmp_password,
                    send_notify=notify,
                    source_id=0,  # local user
                    username=user.get_safe_username(),
                )
                fg_print.info(f"User {user.username} imported as {user.get_safe_username()}, temporary password: {tmp_password}")
                return True
            except ConflictError:
                return True # already exists
            except Exception as e:
                detail = self._get_exception_detail(e)
                fg_print.error(f"Adding User {user.username} as {user.get_safe_username()} failed: {detail}",
                                f"failed to import user {user.username} as {user.get_safe_username()} in Forgejo: {detail}",
                )
                return False
        return True


    def forgejo_list_team_in_repository(self,
                                        owner_username:str,
                                        repo_name:str) -> List[Team]:
        """List all teams in a repository"""
        try:
            return self.fg_api.repository.repo_list_teams(owner=owner_username,repo=repo_name)
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Listing teams in Repository {repo_name} Failed: {detail}"
            )
            return []


    def forgejo_add_team_to_repository(self,
                                        owner_username:str,
                                        repo_name:str,
                                        team_name:str):
        """Add a team to a repository"""
        try:
            self.fg_api.repository.repo_add_team(owner=owner_username,repo=repo_name,team=team_name)
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Adding team {team_name} to Repository {repo_name} Failed: {detail}",
                f"Adding team {team_name} to Repository {repo_name} Failed: {detail}",
            )
            return None



    def forgejo_add_user_key(self, username : str, key_name : str, key_content : str) -> PublicKey|None :
        """Add a public key to the user"""
        try:
            # fg_print.info(f"Importing public key {key_name} for user {username}...")
            new_key = self.fg_api.admin.create_public_key(
                username=username,
                key=key_content,
                read_only=True,
                title=key_name,
            )
            fg_print.info(f"Public key {key_name} imported for user {username}!")
            return new_key
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Public key {key_name} import failed: {detail}",
                f"failed to import Public key '{key_name}' for user {username}",
            )
            return None



    def _build_forgejo_sudo_request_options(self, username:str) -> RequestOptions :
        headers : Dict = { "Sudo" : username }
        request_options : RequestOptions = RequestOptions(additional_headers=headers)
        return request_options



    def forgejo_add_gpg_key(self, username : str, key_id : str, armored_signature:str| None, armored_public_key : str) -> GpgKey|None :
        """Add a GPG key to the user"""
        
        try:
            if armored_signature is None:
                new_key = self.fg_api.user.user_current_post_gpg_key (
                    armored_public_key=armored_public_key,
                    request_options=self._build_forgejo_sudo_request_options(username)
                )
            else:
                new_key = self.fg_api.user.user_current_post_gpg_key (
                    armored_signature=armored_signature,
                    armored_public_key=armored_public_key,
                    request_options=self._build_forgejo_sudo_request_options(username)
                )
            fg_print.info(f"GPG key {key_id} imported for user {username}!")
            return new_key
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"GPG key {key_id} import failed: {e}",
                f"failed to import GPG key '{key_id}' for user {username} {detail}",
            )
            return None



    @deprecated("This cannot be used to create api tokens when the API was authorised using an access token")
    def forgejo_delete_temp_api_token_for_user(self, username:str, token_name:str):
        """Delete an Access Token for the user (if using sudo)"""
        try:
            self.fg_api.user.delete_access_token(username=username, token=token_name)
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Delete temporary user api token {token_name} of user {username} failed: {detail}",
            )



    @deprecated("This cannot be used to create api tokens when the API was authorised using an access token")
    def forgejo_add_temp_api_token_for_user(self, username:str, token_name:str, desired_scopes:Dict[str] = None) -> str:
        """Create an Access Token for the user (if using sudo)"""
        #Example desired_scopes=["read:user","write:user"]
        # A full list is here: https://forgejo.org/docs/latest/user/token-scope/
        try:
            fg_print.info(f"Creating access token for user {username} {token_name} with scope {desired_scopes}")
            user_api_token = self.fg_api.user.create_token(username=username, name=token_name, scopes=desired_scopes)
        except Exception as e:
            fg_print.warning(f"Creating access token for user {username} {token_name} with scope {desired_scopes} failed...")
            detail = self._get_exception_detail(e)
            try:
                self.fg_api.user.delete_access_token(username=username, token=token_name)
                user_api_token = self.fg_api.user.create_token(username=username, name=token_name, scopes=desired_scopes)
            except Exception as e:
                detail = self._get_exception_detail(e)
                fg_print.error(f"Error creating temporary API token {token_name} for user {username} {detail}")
                return None
        return user_api_token



    def forgejo_add_organization(self, organization: CanonicalOrganization) -> bool:
        """add a group as organization in Forgejo"""
        if not self.forgejo_organization_exists(orgname=organization.get_safe_username()): # need this because status 422 returned for conflict, not 409 
            try:
                self.fg_api.organization.org_create(
                    description=organization.description,
                    full_name=organization.full_name,
                    location="",
                    username=organization.get_safe_username(),
                    website="",
                )
                fg_print.info(f"{organization.source_type} {organization.username} imported as Organization {organization.get_safe_username()}!")
            except ConflictError:
                return True # already exists
            except Exception as e:
                detail = self._get_exception_detail(e)
                fg_print.error(
                    f"Adding {organization.source_type} {organization.username} as Organization {organization.get_safe_username()} failed: {detail}",
                    f"failed to import {organization.source_type} {organization.username}: {detail}",
                )
                return False
        # return true even if the organization already exists, because the existence of the organization is not a failure for the import of the group, we just skip it and continue with the import of the group members and projects
        return True



    def forgejo_add_organization_team(self, org_name: str, definition : ForgejoTeamDefinition) -> Team | None:
        """Add a team to an organization"""
        try:
            team = self.fg_api.organization.org_create_team(org=org_name,
                                                name=definition.name,
                                                can_create_org_repo=definition.permissions.can_create_org_repo, 
                                                description=definition.description,
                                                includes_all_repositories=definition.permissions.includes_all_repositories,
                                                permission=definition.permissions.permission,
                                                units=list(definition.permissions.units_map.keys()),
                                                units_map=definition.permissions.units_map
                                                )
            fg_print.info(f"Added team {definition.name} to organization {org_name}")
            return team
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Adding team {definition.name} to organization {org_name} import failed: {detail}",
                f"Failed to add team {definition.name} to organization {org_name} in Forgejo: {detail}",
            )
            return None


    def forgejo_add_user_to_organization_team(self, username: str, organization_name: str, team: Team) -> bool:
        """add a user to a team for a group"""
        
        try:
            self.fg_api.organization.org_add_team_member(team.id, username)
            fg_print.info(f"User {username} added to team {team.name} of organization {organization_name}!")
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Adding user {username} to team {team.name} of organization {organization_name} import failed: {detail}",
                f"Failed to add member {username} to team {team.name} for organization {organization_name} in Forgejo: {detail}",
            )
            return False
        return True



    def forgejo_add_milestone(self, owner: str, repo: str, forgejo_milestones:List[Milestone], title: str, description: str, due_date: str, state: str) -> bool:
        """add a milestone to a repository"""
        forgejo_milestone : Milestone = self.find_forgejo_milestone_by_title(forgejo_milestones, title)

        # if the milestone doesn't exist in the list
        if forgejo_milestone == None:
            if due_date:
                due_date = dateutil.parser.parse(due_date).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            try:
                forgejo_milestones.append(
                    self.fg_api.issue.create_milestone(owner, repo, title=title, description=description, due_on=due_date, state=state)
                )
            except Exception as e:
                detail = self._get_exception_detail(e)
                fg_print.error(
                    f"Milestone {title} import failed: {detail}",
                    f"Failed to import milestone {title} for project {repo} in Forgejo {detail}",
                )
                return False
        return True
            


    def forgejo_update_organization_team(self, team:Team, definition:ForgejoTeamDefinition) -> Team | None :
        """Rename a Forgejo Team (e.g. Owners)"""
        try:
            updated = self.fg_api.organization.org_edit_team(id=team.id,
                                                        name=definition.name,
                                                        can_create_org_repo=definition.permissions.can_create_org_repo, 
                                                        description=definition.description,
                                                        includes_all_repositories=definition.permissions.includes_all_repositories,
                                                        permission=definition.permissions.permission,
                                                        units=list(definition.permissions.units_map.keys()),
                                                        units_map=definition.permissions.units_map
                                                        )
            changes = ForgejoTeamDefinition.fromTeam(team).diff(definition)
            fg_print.info(f"Updated Forgejo team {team.name} changes: {changes}")
            return updated
        except Exception as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Update Forgejo {team.name} to {definition} failed: {detail}",
                f"Failed to update team {team.name} in Forgejo {detail}",
            )
            return None
        
    def _get_exception_detail(self, e: Exception) -> str:
        if isinstance(e, ApiError):
            body = getattr(e, "body", None)
            detail = body.get("message") if isinstance(body, dict) else str(body)
            if("token does not have at least one of required scope" in detail):
                fg_print.error(f"Trapped Error {detail}")
                fg_print.error(f"ERROR: Access Token used MUST have read+write permission on everything (permission:all) and be admin. Please create a new one and update the .migrate.ini file.")
                os.sys.exit(1)
        else:
            detail = str(e)
        return detail

    def addTeamMapping(self, map_from_str:str, to_role:CanonicalRepositoryRole):
        """Add a custom team mapping for an access level not explicitly defined in Forgejo  but encountered during migration"""
        new_team = deepcopy(self.team_definitions[to_role])
        new_team.name=map_from_str
        new_team.description="Temporary team for grouping collaborators with unmapped source access permission"
        self.team_definitions[map_from_str]=new_team
    
    def addRoleMapping(self, map_from_str:str, to_role:CanonicalRepositoryRole):
        """Add a custom user role mapping for an access level not explicitly defined in Forgejo  but encountered during migration.
            Note that the default Forgejo permissions values in here are used for both team and user of same role"""
        new_role_permissions_definition = deepcopy(self.role_definitions[to_role])
        new_role_permissions_definition.name=map_from_str
        new_role_permissions_definition.description="Temporary Role for collaborators with unmapped source access permission"
        self.role_definitions[map_from_str]=new_role_permissions_definition
