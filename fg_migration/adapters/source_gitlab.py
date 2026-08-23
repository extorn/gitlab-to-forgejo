"""GitLab Migration source definition"""
from copy import copy
import os
import re
from typing import Iterator, override

import gitlab  # pip install python-gitlab
import gitlab.v4 # pylint: disable=no-name-in-module
import gitlab.v4.objects
import yaml

from fg_migration.adapters.gitlab_types import GitLabApiPaginator, IterativeFetchError
from fg_migration.utils import fg_print
from fg_migration.adapters.destination_forgejo import ForgejoRepositoryRole
from fg_migration.core.migration_source_type import MigrationSource
from fg_migration.core.canonical_types import (CanonicalGpgKey, CanonicalOrganizationMembership,
                                               CanonicalKey, CanonicalOrganization,
                                               CanonicalOrganizations, CanonicalRepo,
                                               CanonicalRepoMembership, CanonicalRepoMemberships,
                                               CanonicalSystemUser, CanonicalUser, HierarchyNode)
from fg_migration.core.config_types import GitLabMigrationConfig, GitLabConfig

class GitLabMigrationSource(MigrationSource):
    """A Gitlab implementation of a MigrationSource for Forgejo.
       Note that all lists are retrieved in one operation, without paging"""

    gitlab_api: gitlab.Gitlab
    gitlab_config: GitLabConfig
    gitlab_migration_config: GitLabMigrationConfig
    source_system: str = "GitLab"
    access_level_role_map : dict[int,ForgejoRepositoryRole]
    BOT_REGEX = re.compile(r"^project_\d{2}_bot_[a-zA-Z0-9]{32}$")

    def __init__(self,
                 gitlab_api:gitlab.Gitlab,
                 gitlab_config:GitLabConfig,
                 gitlab_migration_config:GitLabMigrationConfig):
        self.gitlab_api = gitlab_api
        self.gitlab_config = gitlab_config
        self.gitlab_migration_config = gitlab_migration_config
        self.access_level_role_map = self._load_access_levels_roles_map(
            path=self.gitlab_migration_config.ACCESS_LEVELS_TO_FORGEJO_ROLES_MAP_FILE_PATH)

    def _load_access_levels_roles_map(self, path: str) -> dict[int,ForgejoRepositoryRole]:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        access_level_role_map : dict[int,ForgejoRepositoryRole] = {}

        for gitlab_access_level, role_cfg in cfg["gitlab_access_levels"].items():
            role_id = role_cfg.get("forgejo_role").strip() # remove whitespace just in case
            role = ForgejoRepositoryRole(role_id)
            gitlab_access_level_int = int(gitlab_access_level)
            access_level_role_map[gitlab_access_level_int] = role

        return access_level_role_map



    def _iter_all_emails_of_user(self,
                                 user: gitlab.v4.objects.User
                                 ) -> Iterator[gitlab.v4.objects.UserEmail]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="UserEmails")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: user.emails.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_projects(self) -> Iterator[gitlab.v4.objects.Project]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Projects")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: gl_api.projects.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_groups_of_project(self,
                                    project: gitlab.v4.objects.Project
                                    ) -> Iterator[gitlab.v4.objects.Group]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Project Groups")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: project.groups.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_groups(self) -> Iterator[gitlab.v4.objects.Group]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Groups")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: gl_api.groups.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_sub_groups_of_group(self, group:
                                   gitlab.v4.objects.Group
                                   ) -> Iterator[gitlab.v4.objects.GroupSubgroup]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="SubGroups")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: group.subgroups.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_descendant_groups_of_group(self, group:
                                   gitlab.v4.objects.Group
                                   ) -> Iterator[gitlab.v4.objects.GroupDescendantGroup]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE,
                                       items_type="DescendantGroups")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: group.descendant_groups.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_members_of_group(self, group:
                                   gitlab.v4.objects.Group
                                   ) -> Iterator[gitlab.v4.objects.GroupMember]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Groups")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: group.members.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_members_of_project(self,
                                     project: gitlab.v4.objects.Project
                                     ) -> Iterator[gitlab.v4.objects.ProjectMember]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Project Members")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: project.members.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_users(self) -> Iterator[gitlab.v4.objects.User]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="Users")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: gl_api.users.list(
                page=page,
                per_page=limit,
            )
        )


    def _iter_all_gpg_keys_of_user(self,
                                   user:gitlab.v4.objects.User
                                   ) -> Iterator[gitlab.v4.objects.UserGPGKey]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="UserGPGKeys")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: user.gpgkeys.list(
                page=page,
                per_page=limit,
            )
        )



    def _iter_all_public_keys_of_user(self,
                                      user:gitlab.v4.objects.User
                                      ) -> Iterator[gitlab.v4.objects.UserKey]:
        paginator = GitLabApiPaginator(gl_api=self.gitlab_api, page_size=self.gitlab_config.API_MAX_PAGE_SIZE, items_type="UserKeys")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: user.keys.list(
                page=page,
                per_page=limit,
            )
        )



    def _get_is_individual(self, project : gitlab.v4.objects.Project) -> bool:
        namespace_kind = project.namespace.get("kind")
        if namespace_kind == "user":
            return True
        elif namespace_kind == "group":
            return False
        else:
            fg_print.error(f"Unsupported namespace kind {project.namespace['kind']}"
                           f" for project {project.name}, skipping import")
            raise ValueError(f"namespace unsupported {project.namespace['kind']}")



    def _get_gitlab_project_owner_slug(self, project: gitlab.v4.objects.Project) -> str | None:

        if project.namespace["kind"] == "user":
            # Needs to be path here because it is the stable id used for gitlab
            return project.namespace["path"]

        if project.namespace["kind"] == "group":
            # Needs to be path here because it is the stable id used for gitlab
            return project.namespace["path"]

        fg_print.error(f"Unsupported namespace kind {project.namespace['kind']}"
                       f" for project {project.name}, skipping import")
        return None



    def _is_ignore_gitlab_user(self, username : str) -> bool:
        if (username in self.gitlab_migration_config.IGNORED_GITLAB_SYSTEM_USERS
            or self.BOT_REGEX.match(username)):
            return True

        fg_print.debug(f"username {username} not in ignored users list "
                       f"{list(self.gitlab_migration_config.IGNORED_GITLAB_SYSTEM_USERS)}"
                       " and does not match bot regex, will not ignore")
        return False



    def _build_or_extract_email(self, user: gitlab.v4.objects.User) -> str:
        """build an email address for a user, if the email is not available,
           we use a dummy email address based on the username"""

        # Some gitlab instances do not publish user emails, so we use a dummy email

        try:
            return user.email
        except AttributeError:
            pass

        try:
            emails = list(self._iter_all_emails_of_user(user))
            if emails:
                return emails[0].email
        except AttributeError, IterativeFetchError:
            pass

        return f"{user.username}@noemail-git.local"



    @override
    def get_source_system_name(self) -> str:
        return self.source_system



    @override
    def list_mapped_forgejo_repository_roles(self) -> set[ForgejoRepositoryRole]:
        return set(self.access_level_role_map.values())



    @override
    def list_repositories(self) -> list[CanonicalRepo]:
        # projects: list[gitlab.v4.objects.Project] = self.gitlab_api.projects.list(get_all=True)
        # fg_print.info(f"Found {len(projects)} gitlab projects"
        #               f" as user {self.gitlab_api.user.username}")

        repos : list[CanonicalRepo] = []
        project : gitlab.v4.objects.Project
        seen_repos_map: dict[int,str] = {}
        try:
            for project in self._iter_all_projects():
                if project.get_id() in seen_repos_map:
                    fg_print.error(f"Already have reference to Project "
                                   f"{seen_repos_map[project.get_id()]} with ID {project.get_id()}")
                    continue

                owner_name = self._get_gitlab_project_owner_slug(project)

                if owner_name is None:
                    continue # unable to continue with this project

                is_individual = self._get_is_individual(project)
                # clone_url = project.web_url

                repo_name = self._get_gitlab_repo_name(project)
                if repo_name is None:
                    fg_print.error(f"Could not extract repository name for project {project.name}"
                                   f" with path {project.path_with_namespace}, skipping import")
                    continue
                clone_url = self._build_gitlab_repo_url(owner_name, repo_name)

                is_private = (project.visibility == "private" or project.visibility == "internal")
                auth_password=self.gitlab_config.GITLAB_ADMIN_PASS
                auth_username=self.gitlab_config.GITLAB_ADMIN_USER
                auth_token=self.gitlab_config.GITLAB_TOKEN

                fg_print.debug(f"{self.source_system} Project name {project.path} : path {project.name}")
                repo = CanonicalRepo(source_system=self.source_system,
                                     source_id=project.get_id(),
                                     is_individual=is_individual,
                                     username=project.path,
                                     name=project.name,
                                     owner_name=owner_name,
                                     clone_url=clone_url,
                                     is_private=is_private,
                                     description=project.description,
                                     auth_username=auth_username,
                                     auth_password=auth_password,
                                     auth_token=auth_token,
                                     source_type="Project")
                repos.append(repo)
                seen_repos_map[repo.source_id] = repo.name
        except IterativeFetchError:
            fg_print.error("Failed to load all Projects. "
                           "Import will need to be run again for Repositories")
        return repos



    def _get_gitlab_repo_name(self, project: gitlab.v4.objects.Project) -> str|None:
        proj_path = project.path_with_namespace

        fg_print.debug(f"retrieving {self.source_system} project: {proj_path}")

        path_parts = proj_path.split("/", 1)

        if len(path_parts) != 2:
            fg_print.error(
                f"Invalid repository path: {proj_path}"
            )
            return None
        return path_parts[1]



    def _build_gitlab_repo_url(self, owner: str, repo: str) -> str:
        if self.gitlab_config.GITLAB_SYNC_CONNECTION_TYPE == "ssh":
            return f"git@{self.gitlab_config.GITLAB_URL.replace('https://', '') \
                          .replace('http://', '')}:{owner}/{repo}.git"

        return f"{self.gitlab_config.GITLAB_URL}/{owner}/{repo}.git"



    def _list_repository_accessors_inherited(self,
                                        project: gitlab.v4.objects.Project,
                                        repository:CanonicalRepo) -> list[CanonicalRepoMembership]:
        """List all those repository accessors that are inherited from a
           group in the hierarchy to which the project belongs"""

        repo_accessors_members : list[CanonicalRepoMembership] = []
        try:
            for group in self._iter_all_groups_of_project(project):
                # retrieve the full group object so we can get the members.
                group = self.gitlab_api.groups.get(group.get_id())
                root_hierarchy = [HierarchyNode(name=group.path)]
                repo_accessors_members += self._process_group(repository=repository,
                                                              group=group,
                                                              hierarchy=root_hierarchy)

        except IterativeFetchError:
            fg_print.error(f"Failed to load all Groups for Project {project.path}."
                           " Import will need to be run again for Repository Accessors")
        return repo_accessors_members


    def _process_group(self, repository : CanonicalRepo,
                       group:gitlab.v4.objects.Group,
                       hierarchy : list[HierarchyNode]
                       ) -> list[CanonicalRepoMembership]:
        """A recursive trawler of groups, descendant and sub groups"""
        group_id = group.get_id()
        repo_accessors_members : list[CanonicalRepoMembership] = []
        # retrieve the full group object so we can get the members.
        group = self.gitlab_api.groups.get(group_id)

        fg_print.debug(f"Loading inherited users from owner group {group_id}")
        # For every user that has access to this group
        try:
            for group_member in self._iter_all_members_of_group(group=group):
                if self._is_ignore_gitlab_user(group_member.username):
                    if self.gitlab_migration_config.IGNORE_GITLAB_SYSTEM_USERS is True:
                        fg_print.warning(f"Ignored a GitLab specific system user "
                                            f"{group_member.username}. If this is incorrect"
                                            ", rerun import permitting system user cloning")
                        continue
                    else:
                        fg_print.warning(f"Likely a GitLab specific system user "
                                            f"{group_member.username}. "
                                            "Can possibly be deleted after import")

                repo_accessors_members.append(CanonicalRepoMembership(
                                                username = group_member.username,
                                                repository = repository,
                                                hierarchy=hierarchy,
                                                access_level = group_member.access_level))

            depth = len(hierarchy)
            if depth <= self.gitlab_config.MAX_DESCENDANT_GROUP_DEPTH:

                for descendant_group in self._iter_all_descendant_groups_of_group(group=group):
                    desc_hierarchy = copy(hierarchy)
                    desc_hierarchy.append(HierarchyNode(
                                                name=descendant_group.path,
                                                relation=HierarchyNode.RelationEnum.DESCENDANT))
                    descendant_group_id = descendant_group.get_id()
                    descendant_group = self.gitlab_api.groups.get(descendant_group_id)
                    repo_accessors_members += self._process_group(
                                                        repository=repository,
                                                        group=descendant_group,
                                                        hierarchy=desc_hierarchy)
            if depth <= self.gitlab_config.MAX_SUB_GROUP_DEPTH:
                for sub_group in self._iter_all_sub_groups_of_group(group=group):
                    sub_hierarchy = copy(hierarchy)
                    sub_hierarchy.append(HierarchyNode(
                                                name=sub_group.path,
                                                relation=HierarchyNode.RelationEnum.SUB))
                    sub_group_id = sub_group.get_id()
                    sub_group = self.gitlab_api.groups.get(sub_group_id)
                    repo_accessors_members += self._process_group(
                                                        repository=repository,
                                                        group=sub_group,
                                                        hierarchy=sub_hierarchy)

        except IterativeFetchError:
            fg_print.error(f"Failed to load all Group Members for Group {group.name}."
                            " Import will need to be run again for Repository Accessors")
        return repo_accessors_members



    def _list_repository_accessors_direct(self,
                                        project: gitlab.v4.objects.Project,
                                        repository:CanonicalRepo) -> list[CanonicalRepoMembership]:
        """List all those repository accessors that are directly added to this project"""
        repo_accessors_members : list[CanonicalRepoMembership] = []

        project_member : gitlab.v4.objects.ProjectMember

        try:
            for project_member in self._iter_all_members_of_project(project=project):
                if self._is_ignore_gitlab_user(project_member.username):
                    if self.gitlab_migration_config.IGNORE_GITLAB_SYSTEM_USERS is True:
                        fg_print.warning("Ignored a GitLab specific system user "
                                         f"{project_member.username}. If this is incorrect, rerun "
                                         "import permitting system user cloning")
                        continue
                    else:
                        fg_print.warning("Likely a GitLab specific system user "
                                         f"{project_member.username}. "
                                         "Can possibly be deleted after import")
                fg_print.debug(f"Added accessor {project_member.username}"
                               f" for project {project.path}")
                repo_accessors_members.append(CanonicalRepoMembership(
                                                        username = project_member.username,
                                                        repository =repository,
                                                        hierarchy=None,
                                                        access_level = project_member.access_level))
        except IterativeFetchError:
            fg_print.error(f"Failed to load all Project Members for Project {project.path}."
                           " Import will need to be run again for Repository Accessors")
        # always return what we have.
        return repo_accessors_members


    @override
    def list_repository_accessors(self, repo:CanonicalRepo) -> CanonicalRepoMemberships:
        # gitlab project = forgejo repo
        project: gitlab.v4.objects.Project = self.gitlab_api.projects.get(id=repo.source_id)
        fg_print.debug(f"Listing accessors for project id {repo.source_id}, "
                       f"project {project.path}  [{project.name}]")
        repo_accessors_members : list[CanonicalRepoMembership] = []
        repo_accessors = CanonicalRepoMemberships(source_system=self.source_system,
                                                  source_type="Users",
                                                  members=repo_accessors_members)

        if not repo.is_individual:
            # These are INHERITED accessors (of the gitlab group that owns this project)
            repo_accessors_members += self._list_repository_accessors_inherited(project=project,
                                                                                repository=repo)

        # These are DIRECT accessors
        repo_accessors_members += self._list_repository_accessors_direct(project=project,
                                                                         repository=repo)

        return repo_accessors



    def _build_organization_from_group(self,group:gitlab.v4.objects.Group) -> CanonicalOrganization:

        org_users: dict[str, CanonicalUser] = {}
        memberships: list[CanonicalOrganizationMembership] = []

        try:

            for member in self._iter_all_members_of_group(group=group):

                # handle ignored users
                if self._is_ignore_gitlab_user(member.username):
                    if self.gitlab_migration_config.IGNORE_GITLAB_SYSTEM_USERS is True:
                        fg_print.warning(
                            f"Ignored GitLab system user {member.username}"
                        )
                        continue
                    else:
                        fg_print.warning(
                            f"Likely GitLab system user {member.username}"
                        )

                # store user (deduplicated)
                if member.username not in org_users:
                    org_users[member.username] = CanonicalUser(
                        username=member.username
                    )

                # store membership FACT (this is the important part)
                memberships.append(
                    CanonicalOrganizationMembership(
                        org_username=group.path,
                        username=member.username,
                        access_level=str(member.access_level),
                    )
                )

        except IterativeFetchError:
            fg_print.error(
                f"Failed to load members for {self.source_system} "
                f"Group {group.path}. Skipping group membership capture."
            )
            return None

        this_org = CanonicalOrganization(
            source_system=self.source_system,
            source_type="Group",
            username=group.path,
            full_name=group.full_name,
            description=group.description,
            members=list(org_users.values()),
            memberships=memberships,
        )

        return this_org



    @override
    def list_organizations(self) -> CanonicalOrganizations:
        organizations = CanonicalOrganizations(
            source_type="Groups",
            members=[]
        )

        try:
            for group in self._iter_all_groups():

                fg_print.debug(
                    f"name={group.name} path={group.path} fullname={group.full_name}"
                )

                canonical_org = self._build_organization_from_group(group=group)
                organizations.members.append(canonical_org)

                if canonical_org.username is None:
                    os.sys.exit(1)


        except IterativeFetchError:
            fg_print.error(
                "Failed to load all Groups. Import incomplete for Organizations."
            )

        return organizations



    @override
    def list_system_users(self) -> list[CanonicalSystemUser]:
        # users: list[gitlab.v4.objects.User] = self.gitlab_api.users.list(get_all=True)
        canonical_users : list[CanonicalSystemUser] = []
        try:
            for user in self._iter_all_users():
                if self._is_ignore_gitlab_user(user.username):
                    if self.gitlab_migration_config.IGNORE_GITLAB_SYSTEM_USERS is True:
                        fg_print.warning(f"Ignored a GitLab specific system user {user.username}."
                                         " If this is incorrect, rerun import permitting"
                                         " system user cloning")
                        continue
                    else:
                        fg_print.warning(f"Likely a GitLab specific system user {user.username}."
                                         " Can possibly be deleted after import")

                # gpg_keys : list[gitlab.v4.objects.UserGPGKey] = user.gpgkeys.list(get_all=True)
                # keys: list[gitlab.v4.objects.UserKey] = user.keys.list(get_all=True)

                avatar_url : str | None
                try:
                    avatar_url = user.avatar_url
                except AttributeError:
                    avatar_url = None

                email_address : str = self._build_or_extract_email(user)
                try:
                    canonical_keys = [CanonicalKey(name=key.title, key=key.key)
                                      for key in self._iter_all_public_keys_of_user(user)]

                    canonical_gpg_keys : list[CanonicalGpgKey] = []
                    for gpg_key in self._iter_all_gpg_keys_of_user(user):
                        key_id = getattr(gpg_key, "key_id", None)

                        key_content = (getattr(gpg_key, "public_key", None)
                                    or getattr(gpg_key, "key", None))
                        canonical_gpg_keys.append(CanonicalGpgKey(name=key_id,
                                                                  armored_public_key=key_content,
                                                                  armored_signature=None))
                except IterativeFetchError:
                    fg_print.error("Failed to load keys for User, User will not be imported and "
                                   "import will need to be run again for Users.")
                    continue

                canonical_users.append(CanonicalSystemUser(gpg_keys=canonical_gpg_keys,
                                                           keys=canonical_keys,
                                                           email=email_address,
                                                           full_name=user.name,
                                                           password=None,
                                                           username=user.username,
                                                           source_system=self.source_system,
                                                           avatar_url=avatar_url))
        except IterativeFetchError:
            fg_print.error("Failed to load all Users, import will need to be run again for Users.")

        return canonical_users



    @override
    def get_repository_role(self, source_access_level:str) -> ForgejoRepositoryRole:
        """Get a predefined ForgejoRepositoryRole or give a unique string to identify a role type
           that should be used for this access level"""
        gitlab_access_level : int = int(source_access_level)
        role = self.access_level_role_map.get(gitlab_access_level)
        if role is None:
            fg_print.error(f"{self.source_system} Access_Level:Role "
                           f"Mapping missing for {source_access_level}")
            role_id = f"{self.source_system}_Role_{source_access_level}"
            fg_print.info(f"Created new {self.source_system} role type : {role_id}")
            role = ForgejoRepositoryRole(id=role_id, is_custom=True)
            self.access_level_role_map[gitlab_access_level] = role
        return role


    @override
    def get_nearest_repository_role(self, source_access_level:str,
                                 allow_downgrade:bool,
                                 allow_upgrade:bool) -> ForgejoRepositoryRole | None:
        """Used when a new role type has had to be created.
           Get the closest defined role for this access level following the rules.
           The result willl be assigned to be used whenever the custom role type is used"""
        access_level_int = int(source_access_level)
        known_access_levels = sorted(self.access_level_role_map.keys())
        closest_access_level: int | None = None

        # Because we cache the custom roles created, the nearest role
        # may be one we've already custom created

        if allow_upgrade:
            larger = min((x for x in known_access_levels if x > access_level_int), default=None)
            if not larger is None:
                closest_access_level = larger
        if allow_downgrade:
            smaller = max((x for x in known_access_levels if x < access_level_int), default=None)
            if not smaller is None:
                if (closest_access_level is None
                    or abs(closest_access_level - access_level_int)
                        > abs(smaller - access_level_int)):
                    closest_access_level = smaller

        if closest_access_level is None:
            return None

        return self.get_repository_role(str(closest_access_level))
