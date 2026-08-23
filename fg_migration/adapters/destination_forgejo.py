"""This is a Series of classes directly involved in the updating of Forgejo as a destination"""
from copy import deepcopy
import os
import random
import string
from typing import Iterator
from pyforgejo.core import RequestOptions
from requests import RequestException
from typing_extensions import deprecated

import dateutil.parser

from pyforgejo import (CreateTeamOptionPermission,
                       EditTeamOptionPermission,
                       PyforgejoApi) # pip install pyforgejo (https://github.com/h44z/pyforgejo)

# Forgejo API imports:
from pyforgejo import (ConflictError, GpgKey, Issue, Label,
                       MigrateRepoOptionsService, Milestone,
                      NotFoundError, Organization, PublicKey, Repository, Team, User)
from pyforgejo.core.api_error import ApiError
import yaml

from fg_migration.utils import fg_print
from fg_migration.core.canonical_types import (CanonicalOrganization, CanonicalRepo,
                                               CanonicalRepoMembership,
                                               CanonicalRepoOwner, CanonicalSystemUser)
from fg_migration.core.config_types import ForgejoConfig
from fg_migration.adapters.forgejo_types import (ApiPaginator, ForgejoPermission,
                                                ForgejoRepositoryRole,
                                                ForgejoRolePermissionDefinition,
                                                ForgejoTeamDefinition, ForgejoTeamRoleBuilder,
                                                ForgejoTeamRoleMapper)
from fg_migration.utils.utils import get_union_values_as_str


class ForgejoDestination:
    """This is a wrapper around a destination for the migration"""

    fg_api : PyforgejoApi
    forgejo_config : ForgejoConfig
    #TODO maybe use the frozendict package here to make it clear these defaults don't change.
    default_role_definitions : dict[ForgejoRepositoryRole,ForgejoRolePermissionDefinition]
    default_team_definitions : dict[ForgejoRepositoryRole,ForgejoTeamDefinition]
    role_definitions : dict[ForgejoRepositoryRole,ForgejoRolePermissionDefinition]
    team_definitions : dict[ForgejoRepositoryRole,ForgejoTeamDefinition]
    forgejo_team_to_role_mapper : ForgejoTeamRoleBuilder

    def __init__(self, fg_api:PyforgejoApi, forgejo_config:ForgejoConfig):
        self.fg_api = fg_api
        self.forgejo_config = forgejo_config
        (self.default_role_definitions,
        self.default_team_definitions) = self.load_roles(path=forgejo_config.USER_ROLES_FILE_PATH)
        self.role_definitions = deepcopy(self.default_role_definitions)
        self.team_definitions = deepcopy(self.default_team_definitions)
        self.forgejo_team_to_role_mapper = ForgejoTeamRoleMapper(
                                                role_definitions=self.role_definitions)



    def get_default_team_definitions(self) -> list[ForgejoTeamDefinition]:
        """retrieve a list of all default ForgejoTeamDefinition
           (no custom definitions will be added here)"""
        return self.default_team_definitions.values()



    def load_roles(self, path: str) -> tuple[dict[ForgejoRepositoryRole,
                                                  ForgejoRolePermissionDefinition],
                                             dict[ForgejoRepositoryRole,
                                                  ForgejoTeamDefinition]]:
        """Load the User roles and mappings from config files"""
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        role_definitions = {}
        team_definitions = {}

        for role_id, role_cfg in cfg["roles"].items():
            role = ForgejoRepositoryRole(role_id)

            # Trim whitespace on cfg values just in case with strip()
            cfg_permission = ForgejoPermission(role_cfg.get("permission", "").strip())
            permissions = ForgejoRolePermissionDefinition(
                role=role,
                can_create_org_repo=role_cfg.get("can_create_org_repo", False),
                includes_all_repositories=role_cfg.get("includes_all_repositories", False),
                permission=cfg_permission,
                units_map=role_cfg.get("units_map",{}),
            )

            cfg_name : str = role_cfg.get("team_name", "").strip()

            cfg_desc : str = role_cfg.get("team_description", "").strip()

            # Is this team permitted to be created when empty of users?
            cfg_allow_empty : bool = role_cfg.get("team_allow_empty", True)

            team = ForgejoTeamDefinition(
                name=cfg_name,
                description=cfg_desc,
                permissions=permissions,
                allow_empty=cfg_allow_empty
            )

            role_definitions[role] = permissions
            team_definitions[role] = team

        return role_definitions, team_definitions



    def iter_forgejo_labels(self, owner: str, repo: str) -> Iterator[Label]:
        """an iterator over all labels for a repository"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Labels",retrieval_detail=f" for project {repo}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.issue.list_labels(
                owner=owner,
                repo=repo,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_milestones(self, owner: str, repo: str) -> Iterator[Milestone]:
        """get milestones for a repository"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Milestones",retrieval_detail=f" for project {repo}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.issue.get_milestones_list(
                owner=owner,
                repo=repo,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_issues(self, owner: str, repo: str) -> Iterator[Issue]:
        """get issues for a repository"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Issues",retrieval_detail=f" for project {repo}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.issue.list_issues(
                owner=owner,
                repo=repo,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_teams(self, org_name: str) -> Iterator[Team]:
        """get teams for an organization"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE, items_type="Teams",
                                 retrieval_detail=f" for organization {org_name}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.organization.org_list_teams(
                org=org_name,
                page=page,
                limit=limit,
            )
        )


    #FIXME currently retrieve these 3 times in the migrator,
    #      2x while importing teams (may be reducable to 1x with some thought)!!!!
    def iter_forgejo_team_members(self, team: Team) -> Iterator[User]:
        """get members for a team"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE, items_type="Team Members",
                                 retrieval_detail=f" for Team {team.name}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.organization.org_list_team_members(
                id=team.id,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_collaborators(self, owner_username: str, repo: str) -> Iterator[User]:
        """get collaborators for a repository"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Collaborators",retrieval_detail=f" for repo {repo}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.repository.repo_list_collaborators(
                owner=owner_username,
                repo=repo,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_user_keys(self, username : str) -> Iterator[PublicKey] :
        """get public keys for a user"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Public Keys",retrieval_detail=f" for user {username}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.user.list_keys(
                username=username,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_user_gpg_keys(self, username : str) -> Iterator[GpgKey] :
        """get gpg keys for a user"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="GPG Keys",retrieval_detail=f" for user {username}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.user.user_list_gpg_keys(
                username=username,
                page=page,
                limit=limit,
            )
        )



    def iter_forgejo_teams_in_repository(self,
                                        owner_username:str,
                                        repo_name:str) -> Iterator[Team]:
        """List all teams in a repository"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Teams",retrieval_detail=f" in Repository {repo_name}")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.repository.repo_list_teams(
                owner=owner_username,
                repo=repo_name,
                # Currently no pagination support for this call.
                # page=page,
                # limit=limit,
            )
        )



    def iter_forgejo_organizations(self) -> Iterator[Organization]:
        """list all organizations in Forgejo"""

        paginator = ApiPaginator(fg_api=self.fg_api, page_size=self.forgejo_config.API_MAX_PAGE_SIZE,
                                 items_type="Organizations", retrieval_detail=" in Forgejo")
        return paginator.iterate(fetch_page_from_api=
            lambda fg_api, page, limit: fg_api.organization.org_get_all(
                page=page,
                limit=limit,
            )
        )



    def get_forgejo_organization(self, org: CanonicalOrganization,
                                 quiet:bool=False) -> Organization|None:
        """Retrieve Forgejo organization with a given name"""
        try:
            #fg_print.debug(f"Trying to load forgejo organization {possible_org} "
            #               f"for gitlab project {project.name}...")
            forgejo_org = self.fg_api.organization.org_get(org=org.get_safe_username())
            fg_print.debug(f"Loaded organization {forgejo_org.username} ({forgejo_org.full_name})"
                           f" matching {org.source_system}"
                           f" {org.source_type} {org.username}")
            return forgejo_org
        except NotFoundError:
            msg=f"Organization not found : {org.get_safe_username()}"
            if not quiet:
                fg_print.error(msg)
            else:
                fg_print.debug(msg)
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to retrieve forgejo organization {org.get_safe_username()}"
                           f" for repo {org.get_safe_username()} matching {org.source_system}"
                           f" {org.source_type} {org.username}! {detail}")
        return None



    def get_forgejo_organization_owner_of_repository(self, repo: CanonicalRepo) -> Organization:
        """Retrieve organization owner of repository"""
        org_name : str = repo.get_safe_owner_name()
        try:
            #fg_print.debug(f"Trying to load forgejo organization {possible_org}"
            #               f" for gitlab project {project.name}...")
            org = self.fg_api.organization.org_get(org_name)
            fg_print.debug(f"Loaded organization {org.full_name} for {repo.source_system}"
                           f" {repo.source_type} {repo.name}")
            return org
        except (NotFoundError, ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to retrieve forgejo organization {org_name} "
                           f"for repo {repo.get_safe_username()} using {repo.source_system}"
                           f" {repo.source_type} {repo.name}! {detail}")
        return None



    def get_forgejo_user(self, username: str) -> User|None:
        """get user by name"""
        try:
            user = self.fg_api.user.get(username)
            fg_print.debug(f"loaded user {user.username}")
            return user
        except (NotFoundError, ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to retrieve Forgejo user {username}! {detail}")
        return None



    def forgejo_user_exists(self, username: str) -> bool:
        """check if a user exists"""
        try:
            user = self.fg_api.user.get(username)
            fg_print.warning(f"User {user.login}, (name '{user.full_name}') "
                             "already exists in Forgejo, skipping")
            return True
        except NotFoundError:
            return False
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.info(f"User {username} not found in Forgejo, importing! {detail}")
            return False



    def forgejo_repo_exists(self, forgejo_owner: CanonicalRepoOwner, repo: CanonicalRepo) -> bool:
        """check if a repository exists"""
        try:
            fg_print.debug(f"Checking if Repository {repo.get_safe_username()} exists in Forgejo"
                           f" for owner {forgejo_owner.username} to match {repo.source_system}"
                           f" {repo.source_type}...")
            repository = self.fg_api.repository.repo_get(owner=forgejo_owner.username,
                                                         repo=repo.get_safe_username())
            if repository is not None:
                fg_print.warning(f"{repo.source_type} {repo.name}"
                                  " already exists in Forgejo, skipping")
            return True
        except NotFoundError:
            fg_print.info(f"{repo.get_safe_username()} owned by {forgejo_owner.username} "
                          f"from {repo.source_type} {repo.username} not found "
                          "in Forgejo, importing")
            return False
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to check if {repo.source_type} {repo.name} "
                           f"exists in Forgejo for owner {forgejo_owner.username}! {detail}")


        fg_print.info(f"{repo.source_type} {repo.name} not found in Forgejo, importing")
        return False



    @deprecated("Not currently used")
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
                    f"Label {labelname} already exists in project {repo}, skipping"
                )
                return True

            fg_print.info(f"Label {labelname} does not exist in project {repo}, importing")
            return False

        fg_print.info(f"No labels in project {repo}, importing")
        return False



    @deprecated("Not currently used")
    def forgejo_issue_exists(self, existing_issues : list[Issue],
                             repo: str, issue_title: str) -> bool:
        """check if an issue exists in a repository"""

        if existing_issues:
            existing_issue = next(
                (item for item in existing_issues if item.title == issue_title), None
            )

            if existing_issue is not None:
                fg_print.warning(
                    f"Issue {issue_title} already exists in project {repo}, skipping"
                )
                return True

            fg_print.info(f"Issue {issue_title} does not exist in project {repo}, importing")
            return False

        fg_print.info(f"No issues in project {repo}, importing")
        return False



    @deprecated("Not currently used")
    def find_forgejo_milestone_id_by_title(self, forgejo_milestones: list[Milestone],
                                           title: str) -> int:
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



    @deprecated("Not currently used")
    def find_forgejo_milestone_by_title(self, existing_milestones : list[Milestone],
                                        title: str) -> Milestone|None:
        """check if a milestone exists in a repository"""

        if existing_milestones:
            existing_milestone = next(
                (item for item in existing_milestones if item.title == title), None
            )

            return existing_milestone

        return None



    def _forgejo_delete_collaborator(self, repo: CanonicalRepo, collaborator_username: str) -> bool:
        """delete a collaborator from a repository"""
        try:
            self.fg_api.repository.repo_delete_collaborator(owner = repo.get_safe_owner_name(),
                                                            repo = repo.get_safe_username(),
                                                            collaborator = collaborator_username)
            fg_print.debug(f"User {collaborator_username} removed as collaborator"
                           f" from repository {repo.get_safe_username()}")
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"User {collaborator_username} removal as collaborator from "
                f"repository {repo.get_safe_username()} failed: {detail}")
            return False
        return True



    def forgejo_add_replace_collaboration(self,
                                        existing_collaborator_ids:set[int],
                                        user:User,
                                        repo:CanonicalRepo, permissions:ForgejoPermission):
        """Add collaboration entry for repo. Will replace any existing one
           matching the name provided"""
        # If there is an existing collaboration record, delete it.
        if user.id in existing_collaborator_ids:

            fg_print.warning(f"Collaboration record for user {user.login} already exists"
                             f" in repository {repo.get_safe_username()},"
                              " replacing with new permissions...")
            deleted = self._forgejo_delete_collaborator(repo=repo,
                                                    collaborator_username=user.login)
            if not deleted:
                return False
        # Add new collaboration record for user
        added = self._forgejo_add_collaboration(repo=repo,
                                                collaborator_username=user.login,
                                                permission=permissions)
        if not added:
            pass
        return added



    def _forgejo_add_collaboration(self, repo: CanonicalRepo, collaborator_username: str,
                                   permission: str) -> bool:
        """add a collaborator to a repository"""
        try:
            self.fg_api.repository.repo_add_collaborator(owner = repo.get_safe_owner_name(),
                                                        repo = repo.get_safe_username(),
                                                        collaborator = collaborator_username,
                                                        permission = permission)
            fg_print.debug(f"Collaboration on {repo.get_safe_username()} "
                           f"for user {collaborator_username} recorded")
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to add Collaboration for user {collaborator_username}"
                           f" on {repo.get_safe_username()}: {detail}")
            return False
        # return true even if the collaborator already exists in the repository,
        # because the existence of the collaborator in the repository is not a failure
        # for the import of the project, we just skip it and continue with the
        # import of the other collaborators
        return True



    def forgejo_add_user(self, user:CanonicalSystemUser, notify: bool,
                         must_change_password:bool=True) -> bool:
        """add a user to Forgejo, return True if user created or already exists"""

        # need this because status 422 returned for conflict, not 409
        if not self.forgejo_user_exists(username=user.get_safe_username()):
            rnd_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
            tmp_password = f"Tmp1!{rnd_str}"
            try:
                # note temporary passsword, so vital they change as soon as they log in
                self.fg_api.admin.create_user(
                    email=user.email,
                    full_name=user.full_name,
                    login_name=user.get_safe_username(),
                    password=tmp_password,
                    send_notify=notify,
                    must_change_password=must_change_password,
                    source_id=0,  # local user
                    username=user.get_safe_username(),
                )
                fg_print.info(f"User {user.username} imported as {user.get_safe_username()}")
                user.password = tmp_password
                return True
            except ConflictError:
                return True # already exists
            except (ApiError, RequestException) as e:
                detail = self._get_exception_detail(e)
                fg_print.error(f"Failed to import {user.source_system} user {user.username}"
                               f" as {user.get_safe_username()}: {detail}",
                               f"Failed to import {user.source_system} user {user.username}"
                               f" as {user.get_safe_username()}",
                )
                return False
        return True


    def forgejo_force_password_change(self, user:CanonicalSystemUser, new_value:bool=True):
        """Force user to change password on next login"""
        try:
            self.fg_api.admin.edit_user(username=user.username, must_change_password=new_value)
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"Failed to force password change for {user.source_system} "
                           f"user {user.username} as {user.get_safe_username()}: {detail}",
                           f"Failed to force password change for {user.source_system} "
                           f"user {user.username} as {user.get_safe_username()}",
            )
            return False


    def forgejo_add_team_to_repository(self,
                                        owner_username:str,
                                        repo_name:str,
                                        team_name:str) -> bool :
        """Add a team to a repository"""
        try:
            self.fg_api.repository.repo_add_team(owner=owner_username,repo=repo_name,team=team_name)
            return True
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Adding team {team_name} to Repository {repo_name} Failed: {detail}",
                f"Adding team {team_name} to Repository {repo_name} Failed: {detail}",
            )
            return False


    def forgejo_add_user_key(self, username : str, key_name : str,
                             key_content : str) -> PublicKey|None :
        """Add a public key to the user"""
        try:
            # fg_print.info(f"Importing public key {key_name} for user {username}...")
            new_key = self.fg_api.admin.create_public_key(
                username=username,
                key=key_content,
                read_only=True,
                title=key_name,
            )
            fg_print.info(f"Public key {key_name} imported for user {username}")
            return new_key
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Public key {key_name} import failed: {detail}",
                f"failed to import Public key '{key_name}' for user {username}",
            )
            return None



    def _build_forgejo_sudo_request_options(self, username:str) -> RequestOptions :
        headers : dict = { "Sudo" : username }
        request_options : RequestOptions = RequestOptions(additional_headers=headers)
        return request_options



    def repo_migrate(
        self,
        *,
        source_repo:CanonicalRepo,
        forgejo_owner:CanonicalRepoOwner,
        issues: bool = True,
        labels: bool = True,
        lfs:bool = True,
        lfs_endpoint:str|None = None,
        milestones: bool = True,
        mirror: bool = True,
        mirror_interval:str=None,
        pull_requests: bool = True,
        releases: bool = True,
        service: MigrateRepoOptionsService | None = None,
        wiki: bool = True,
    ) -> Repository | None:
        """Migrate a repository from the source service to Forgejo"""

        try:
            fg_print.debug(f"Importing {source_repo.source_system} {source_repo.source_type}"
                           f" {source_repo.username}, owner {forgejo_owner.username}.\n"
                           f"as repo {source_repo.get_safe_username()} owned by"
                           f" {source_repo.get_safe_owner_name()}")
            repo = self.fg_api.repository.repo_migrate(
                                                clone_addr=source_repo.clone_url,
                                                repo_name=source_repo.get_safe_username(),
                                                auth_password=source_repo.auth_password,
                                                auth_token=source_repo.auth_token,
                                                auth_username=source_repo.auth_username,
                                                description=source_repo.description,
                                                issues=issues,
                                                labels=labels,
                                                lfs=lfs,
                                                lfs_endpoint=lfs_endpoint,
                                                milestones=milestones,
                                                mirror=mirror,
                                                mirror_interval=mirror_interval,
                                                private=source_repo.is_private,
                                                pull_requests=pull_requests,
                                                releases=releases,
                                                repo_owner=forgejo_owner.username,
                                                service=service,
                                                uid=forgejo_owner.id, # deprecated (only in for backwards compatability reasons)
                                                wiki=wiki,
                                        )
            return repo
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(f"{source_repo.source_system} {source_repo.source_type}"
                            f" {source_repo.get_safe_username()} import failed from url"
                            f" {source_repo.clone_url} : {detail}")
            if detail.find("The repository with the same name already exists.") >= 0:
                fg_print.info("If you're certain this repository doesn't exist, then "
                                "forgejo user likely doesn't have write access to the "
                                "configured /tmp or similar folder (check Forgejo logs "
                                "and app.ini for path)")
        return None



    def get_active_user(self) -> User:
        """The current logged in User (or owner of the current API Token in use)"""
        try:
            return self.fg_api.user.get_current()
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"failed to retrieve current user {detail}",
            )
            return None



    def forgejo_add_gpg_key(self, username : str, key_name : str,
                            armored_signature:str| None, armored_public_key : str) -> GpgKey|None :
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
            fg_print.info(f"GPG key {key_name} imported for user {username}")
            return new_key
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"GPG key {key_name} import failed: {e}",
                f"failed to import GPG key '{key_name}' for user {username} {detail}",
            )
            return None



    @deprecated("WARNING: This cannot be used to create api tokens "
                "when the API was authorised using an access token")
    def forgejo_delete_temp_api_token_for_user(self, username:str, token_name:str):
        """Delete an Access Token for the user (if using sudo)"""
        try:
            self.fg_api.user.delete_access_token(username=username, token=token_name)
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Delete temporary user api token {token_name} of user {username} failed: {detail}",
            )



    @deprecated("WARNING: This cannot be used to create api tokens" \
                " when the API was authorised using an access token")
    def forgejo_add_temp_api_token_for_user(self, username:str, token_name:str,
                                            desired_scopes:dict[str] = None) -> str:
        """Create an Access Token for the user (if using sudo)"""
        #Example desired_scopes=["read:user","write:user"]
        # A full list is here: https://forgejo.org/docs/latest/user/token-scope/
        try:
            fg_print.info(f"Creating access token for user {username} {token_name}"
                          f" with scope {desired_scopes}")
            user_api_token = self.fg_api.user.create_token(username=username,
                                                           name=token_name, scopes=desired_scopes)
        except (ApiError, RequestException) as e:
            fg_print.warning(f"Creating access token for user {username} {token_name}"
                             f" with scope {desired_scopes} failed...")
            detail = self._get_exception_detail(e)
            try:
                self.fg_api.user.delete_access_token(username=username, token=token_name)
                user_api_token = self.fg_api.user.create_token(username=username,
                                                               name=token_name,
                                                               scopes=desired_scopes)
            except (ApiError, RequestException) as e1:
                detail = self._get_exception_detail(e1)
                fg_print.error(f"Error creating temporary API token {token_name} "
                               f"for user {username} {detail}")
                return None
        return user_api_token



    def forgejo_add_organization(self, organization: CanonicalOrganization,
                                 existing_forgejo_org:Organization|None) -> bool:
        """add a group as organization in Forgejo"""
        if existing_forgejo_org is None:
            try:
                self.fg_api.organization.org_create(
                    description=organization.description,
                    full_name=organization.full_name,
                    location="",
                    username=organization.get_safe_username(),
                    website="",
                )
                fg_print.info(f"{organization.source_type} {organization.username} "
                              f"imported as Organization {organization.get_safe_username()}")
            except ConflictError:
                return True # already exists
            except (ApiError, RequestException) as e:
                detail = self._get_exception_detail(e)
                fg_print.error(
                    f"Adding {organization.source_type} {organization.username} "
                    f"as Organization {organization.get_safe_username()} failed: {detail}",
                    f"Adding {organization.source_type} {organization.username} "
                    f"as Organization {organization.get_safe_username()} failed",
                )
                return False
        # return true even if the organization already exists, because the existence of
        # the organization is not a failure for the import of the group, we just skip it
        # and continue with the import of the group members and projects
        return True



    def forgejo_add_organization_team(self, org_name: str,
                                      definition : ForgejoTeamDefinition) -> Team | None:
        """Add a team to an organization"""
        try:
            perm = definition.permissions.permission
            acceptable_values = get_union_values_as_str(CreateTeamOptionPermission)
            if not perm.value in acceptable_values:
                # Trying to create the Owner Team (but this is always created automatically)!
                fg_print.error(
                    f"Unsupported permission for creating Forgejo Team {definition.name}. "
                    "Updating Team cancelled.",
                    f"Failed to create team {definition.name} in Forgejo organization {org_name}. "
                    f"Valid Permissions are : {acceptable_values}",
                )
                return None

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
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to add team {definition.name} to organization {org_name}: {detail}",
                f"Failed to add team {definition.name} to organization {org_name}",
            )
            return None


    def forgejo_add_user_to_organization_team(self, username: str,
                                              organization_name: str, team: Team) -> bool:
        """add a user to a team for a group"""

        try:
            self.fg_api.organization.org_add_team_member(team.id, username)
            fg_print.info(f"User {username} added to team {team.name}"
                          f" of organization {organization_name}")
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to add member {username} to team {team.name} "
                f"of organization {organization_name}: {detail}",
                f"Failed to add member {username} to team {team.name} "
                f"for organization {organization_name}",
            )
            return False
        return True



    def forgejo_remove_user_from_organization_team(self, username: str,
                                                   organization_name: str, team: Team) -> bool:
        """remove a user from a team for a group"""

        try:
            self.fg_api.organization.org_remove_team_member(team.id, username)
            fg_print.info(f"User {username} removed from team {team.name}"
                          f" of organization {organization_name}")
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to remove member {username} of team {team.name} "
                f"of organization {organization_name}: {detail}",
                f"Failed to remove member {username} of team {team.name} "
                f"for organization {organization_name}",
            )
            return False
        return True


    def forgejo_add_milestone(self, owner: str, repo: str, forgejo_milestones:list[Milestone],
                              title: str, description: str, due_date: str, state: str) -> bool:
        """add a milestone to a repository"""
        forgejo_milestone : Milestone = self.find_forgejo_milestone_by_title(forgejo_milestones,
                                                                             title)

        # if the milestone doesn't exist in the list
        if forgejo_milestone is None:
            if due_date:
                due_date = dateutil.parser.parse(due_date).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            try:
                forgejo_milestones.append(
                    self.fg_api.issue.create_milestone(owner, repo, title=title,
                                                       description=description,
                                                       due_on=due_date, state=state)
                )
            except (ApiError, RequestException) as e:
                detail = self._get_exception_detail(e)
                fg_print.error(
                    f"Milestone {title} import failed: {detail}",
                    f"Failed to import milestone {title} for project {repo} in Forgejo {detail}",
                )
                return False
        return True



    def forgejo_update_organization_team(self, team:Team, current_definition:ForgejoTeamDefinition,
                                         new_definition:ForgejoTeamDefinition) -> Team | None :
        """Rename a Forgejo Team (But not Owners, that's unsupported by Forgejo)"""
        try:
            fg_print.info(f"Updating Forgejo team {team.name}"
                          f" using new definition {new_definition}...")

            perm = new_definition.permissions.permission
            acceptable_values = get_union_values_as_str(EditTeamOptionPermission)
            if (current_definition.permissions.permission != perm
                and not perm.value in acceptable_values):
                # Trying to change the permission of the team up to Owner!
                fg_print.error(
                    f"Unsupported permission for editing Forgejo Team {team.name}. "
                    "Updating Team cancelled.",
                    f"Failed to update team {team.name} in Forgejo. "
                    f"Valid new Permissions are : {acceptable_values}")
                return None
            if perm == ForgejoPermission.OWNER and current_definition.name != new_definition.name:
                fg_print.error(
                    f"Changing the name of the Forgejo Owners Team {team.name} is not supported. "
                    "Updating Team cancelled.",
                    f"Failed to update team {team.name} in Forgejo. ")
                return None

            updated = self.fg_api.organization.org_edit_team(id=team.id,
                    name=new_definition.name,
                    can_create_org_repo=new_definition.permissions.can_create_org_repo,
                    description=new_definition.description,
                    includes_all_repositories=new_definition.permissions.includes_all_repositories,
                    permission=perm.value,
                    units=list(new_definition.permissions.units_map.keys()),
                    units_map=new_definition.permissions.units_map
                    )
            changes = current_definition.diff(new_definition)
            fg_print.info(f"Updated Forgejo team {team.name} changes: {changes}")
            return updated
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Update Forgejo Team {team.name} to {new_definition} failed: {detail}",
                f"Failed to update team {team.name} in Forgejo {detail}",
            )
            return None

    def _get_exception_detail(self, e: Exception) -> str:
        if isinstance(e, ApiError):
            body = getattr(e, "body", None)
            detail = body.get("message") if isinstance(body, dict) else str(body)
            if "token does not have at least one of required scope" in detail:
                fg_print.error(f"Trapped Error {detail}")
                fg_print.error("ERROR: Access Token used MUST have read+write"
                               " permission on everything (permission:all) and be"
                               " admin. Please create a new one and update the .migrate.ini file.")
                os.sys.exit(1)
        else:
            detail = str(e)
        return detail

    def add_team_mapping(self, map_from_role:ForgejoRepositoryRole, to_role:ForgejoRepositoryRole):
        """Add a custom team mapping for an access level not explicitly
           defined in Forgejo  but encountered during migration"""
        new_team_definition = deepcopy(self.team_definitions[to_role])
        new_team_definition.name = map_from_role
        new_team_definition.description = "Temporary team for grouping collaborators with" \
                                          " unmapped source access permission"
        self.team_definitions[map_from_role] = new_team_definition

    def add_role_mapping(self, map_from_role:ForgejoRepositoryRole,
                         to_existing_role:ForgejoRepositoryRole):
        """Add a custom user role mapping for an access level not explicitly defined in
           Forgejo  but encountered during migration.
            Note that the default Forgejo permissions values in here are used for both
            team and user of same role"""
        new_role_permissions_definition = deepcopy(self.role_definitions[to_existing_role])
        new_role_permissions_definition.name=map_from_role.id
        new_role_permissions_definition.description="Temporary Role for collaborators"\
                                                    " with unmapped source access permission"
        self.role_definitions[ForgejoRepositoryRole]=new_role_permissions_definition



    def import_individual_user_collaborator(self,
                                            existing_collaborator_ids:set[int],
                                            accessor:CanonicalRepoMembership,
                                            source_repo:CanonicalRepo,
                                            forgejo_permissions:ForgejoPermission):
        """identical to _import_individual_collaborator except first checks
           a user exists in Forgejo with that username"""
        forgejo_user = self.get_forgejo_user(username=accessor.get_safe_username())
        if forgejo_user is not None:
            self.forgejo_add_replace_collaboration(
                                        existing_collaborator_ids=existing_collaborator_ids,
                                        user=forgejo_user,
                                        repo=source_repo,
                                        permissions=forgejo_permissions)
            fg_print.info(f"Registered Forgejo user {accessor.username}"
                          f" as collaborator of {source_repo.get_safe_username()}")
        else:
            fg_print.error(f"Unable to add non existent Forgejo user {accessor.get_safe_username()}"
                           f" as collaborator of {source_repo.get_safe_username()}",
                           f"Unable to add non existent Forgejo user {accessor.get_safe_username()}"
                           f" as collaborator of {source_repo.get_safe_username()}")




    def resolve_forgejo_repo_owner(self, source_repo: CanonicalRepo) -> CanonicalRepoOwner | None:
        """Return the owner object for the repository provided. None if there was some problem"""
        if source_repo.is_individual:
            if user := self.get_forgejo_user(username=source_repo.get_safe_owner_name()):
                return self._get_owner_identity(user)

            fg_print.error( "Failed to retrieve Forgejo owner User for Forgejo repository"
                            f" {source_repo.get_safe_username()}, skipping import of "
                            f"{source_repo.source_type} {source_repo.name}")
        else:
            if org := self.get_forgejo_organization_owner_of_repository(repo=source_repo):
                return self._get_owner_identity(org)

            fg_print.error( "Failed to retrieve Forgejo owner organization for repository "
                            f"{source_repo.get_safe_username()}, skipping import of "
                            f"{source_repo.source_type} {source_repo.name}")
        return None



    @staticmethod
    def _get_owner_identity(forgejo_owner : Organization|User) -> CanonicalRepoOwner:
        # org has a username, user has a login... either is used as identity
        # of owner for any given repository
        name = getattr(forgejo_owner, "username", None) or getattr(forgejo_owner, "login", None)
        return CanonicalRepoOwner(id=forgejo_owner.id, username=name)
