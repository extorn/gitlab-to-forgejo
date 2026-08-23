"""For creation of PushMirrors"""
import os
from typing import Iterator

import gitlab  # pip install python-gitlab
import gitlab.v4 # pylint: disable=no-name-in-module
import gitlab.v4.objects
from pyforgejo import PushMirror, PyforgejoApi
from pyforgejo.core import ApiError
from requests import RequestException

from fg_migration.adapters.forgejo_types import IterativeFetchError
from fg_migration.adapters.gitlab_types import GitLabApiPaginator
from fg_migration.utils import fg_print
from fg_migration.core.config_types import ForgejoConfig, GitLabConfig


class PushMirrorCreator:
    """For creation of PushMirrors"""
    fg_api : PyforgejoApi
    gl_api : gitlab.Gitlab
    forgejo_config : ForgejoConfig
    gitlab_config : GitLabConfig

    def __init__(self, fg_api:PyforgejoApi, gl_api:gitlab.Gitlab,
                 forgejo_config: ForgejoConfig, gitlab_config : GitLabConfig):
        self.gl_api = gl_api
        self.forgejo_config = forgejo_config
        self.gitlab_config = gitlab_config
        self.forgejo_api = fg_api


    def _iter_all_projects(self) -> Iterator[gitlab.v4.objects.Project]:
        paginator = GitLabApiPaginator(gl_api=self.gl_api,
                                       page_size=self.gitlab_config.API_MAX_PAGE_SIZE,
                                       items_type="Projects")
        return paginator.iterate(fetch_page_from_api=
            lambda gl_api, page, limit: gl_api.projects.list(
                page=page,
                per_page=limit,
            )
        )


    def load_gitlab_projects(self) -> list[gitlab.v4.objects.Project]:
        """Load All Gitlab projects"""
        all_projects : list[gitlab.v4.objects.Project] = []
        try:
            for project in self._iter_all_projects():
                all_projects.append(project)
        except IterativeFetchError:
            fg_print.error("Failed to load all Projects. "
                           "Push Mirror will need to be run again")
            raise

        fg_print.info(f"Found {len(all_projects)} projects")

        return all_projects



    def close(self) -> None:
        """Close the API interface (permanent)"""
        #self.forgejo_api.close()



    def _get_exception_detail(self, e: Exception) -> str:
        if isinstance(e, ApiError):
            body = getattr(e, "body", None)
            detail = body.get("message") if isinstance(body, dict) else str(body)
            if "token does not have at least one of required scope" in detail:
                fg_print.error(f"Trapped Error {detail}")
                fg_print.error("ERROR: Access Token used MUST have read+write permission on "
                               "everything (permission:all) and be admin. Please create a new "
                               "one and update the .migrate.ini file.")
                os.sys.exit(1)
        else:
            detail = str(e)
        return detail



    def _list_forgejo_push_mirrors(self,
        owner: str,
        repo: str,
    ) -> list[PushMirror]:

        try:
            push_mirrors = self.fg_api.repository.repo_list_push_mirrors(owner=owner, repo=repo)
            return push_mirrors
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to load push mirrors for {owner}/{repo}: ",
                f"{detail}"
            )

        return []


    def _create_forgejo_push_mirror(self, owner: str, repo: str,) -> bool:
        try:
            use_ssh = self.gitlab_config.GITLAB_SYNC_CONNECTION_TYPE == "ssh"
            result = self.fg_api.repository.repo_add_push_mirror(
                owner=owner,
                repo=repo,
                remote_address=self._build_gitlab_repo_url(owner, repo),
                remote_username=self.gitlab_config.GITLAB_ADMIN_USER,
                remote_password=self.gitlab_config.GITLAB_ADMIN_PASS,
                use_ssh=use_ssh,
                interval="8h0m0s",
                sync_on_commit=True,
            )
            if result:
                fg_print.info(f"Push mirror created on Forgejo for {owner}/{repo}")
                return True
        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to create push mirror on Forgejo for "
                f"{owner}/{repo}: {detail}"
            )

        return False


    def _delete_forgejo_push_mirror(
        self,
        owner: str,
        repo: str,
        remote_name: str,
    ) -> bool:
        try:
            self.fg_api.repository.repo_delete_push_mirror(owner=owner, repo=repo, name=remote_name)
            fg_print.info(
                    f"Push mirror {remote_name} deleted on Forgejo "
                    f"for {owner}/{repo}"
                )
            return True

        except (ApiError, RequestException) as e:
            detail = self._get_exception_detail(e)
            fg_print.error(
                f"Failed to delete push mirror {remote_name} "
                f"for {owner}/{repo}: {detail}"
            )

        return False


    def to_forgejo(self, gitlab_projects: list[gitlab.v4.objects.Project], ) -> None:
        """Create push mirrors from GitLab to Forgejo"""

        fg_print.info("\nMirroring repositories from GitLab to Forgejo")

        for project in gitlab_projects:
            proj_path = project.path_with_namespace

            fg_print.info(f"Project: {proj_path}")

            forgejo_push_url = (
                f"{self.forgejo_config.FORGEJO_URL}/{proj_path}.git"
            )

            try:
                #TODO see if we can use a Forgejo auth token instead.
                project.remote_mirrors.create(
                    {
                        "url": forgejo_push_url,
                        "enabled": True,
                        "auth_method": "password",
                        "user": self.forgejo_config.FORGEJO_ADMIN_USER,
                        "password": self.forgejo_config.FORGEJO_ADMIN_PASS,
                    }
                )

                fg_print.info(
                    f"Push mirror created on GitLab for {proj_path}"
                )

            except (gitlab.exceptions.GitlabError, RequestException) as e:
                detail = str(e)

                fg_print.error(
                    f"Error creating push mirror on GitLab "
                    f"for {proj_path}: {detail}",
                    f"Error creating push mirror on GitLab "
                    f"for {proj_path}: {detail}",
                )


    def delete_to_forgejo(self,
        gitlab_projects: list[gitlab.v4.objects.Project]
    ) -> None:
        """Delete push mirrors from GitLab to Forgejo"""

        fg_print.info("\nDeleting push mirrors from GitLab")

        for project in gitlab_projects:
            proj_path = project.path_with_namespace

            fg_print.info(f"Project: {proj_path}")

            try:
                mirrors = project.remote_mirrors.list()

                for mirror in mirrors:
                    project.remote_mirrors.delete(mirror.id)

                    fg_print.info(
                        f"Push mirror deleted on GitLab for {proj_path}"
                    )

            except (gitlab.exceptions.GitlabError, RequestException) as e:
                detail = str(e)

                fg_print.error(
                    f"Error deleting push mirrors on GitLab "
                    f"for {proj_path}: {detail}",
                    f"Error deleting push mirrors on GitLab "
                    f"for {proj_path}: {detail}",
                )


    def to_gitlab(self,
        gitlab_projects: list[gitlab.v4.objects.Project],
    ) -> None:
        """Create push mirrors from Forgejo to GitLab"""

        fg_print.info("\nMirroring repositories from Forgejo to GitLab")

        for project in gitlab_projects:
            owner, repo = self._get_project_owner_and_repo(project)

            list_of_mirrors = self._list_forgejo_push_mirrors(owner=owner, repo=repo)
            if list_of_mirrors:
                mirror = next((mirror for mirror in list_of_mirrors
                            if mirror.remote_address == self._build_gitlab_repo_url(owner, repo)),
                            None)
                if mirror is not None:
                    fg_print.info("Push mirror already exists on Forgejo "
                                  f"for {owner}/{repo}, skipping creation")
                    continue

            success = self._create_forgejo_push_mirror(owner=owner, repo=repo)
            if not success:
                fg_print.warning(f"Failed mirror for {owner}/{repo}")



    def _build_gitlab_repo_url(self, owner: str, repo: str) -> str:
        if self.gitlab_config.GITLAB_SYNC_CONNECTION_TYPE == "ssh":
            return f"git@{self.gitlab_config.GITLAB_URL
                          .replace('https://', '').replace('http://', '')}:{owner}/{repo}.git"
        else:
            return f"{self.gitlab_config.GITLAB_URL}/{owner}/{repo}.git"



    def _get_project_owner_and_repo(self, project:
                                    gitlab.v4.objects.Project) -> tuple[str, str] | None:
        proj_path = project.path_with_namespace

        fg_print.info(f"Project: {proj_path}")

        path_parts = proj_path.split("/", 1)

        if len(path_parts) != 2:
            fg_print.error(
                f"Invalid repository path: {proj_path}"
            )
            return None

        return path_parts[0], path_parts[1]



    def delete_to_gitlab(self,
        gitlab_projects: list[gitlab.v4.objects.Project],
    ) -> None:
        """Delete push mirrors from Forgejo to GitLab"""

        fg_print.info("\nDeleting push mirrors from Forgejo")

        for project in gitlab_projects:
            owner,repo = self._get_project_owner_and_repo(project)

            mirrors = self._list_forgejo_push_mirrors(owner=owner, repo=repo)

            gitlab_url = self._build_gitlab_repo_url(owner, repo)
            for mirror in mirrors:
                if mirror.remote_address != gitlab_url:
                    continue

                remote_name = mirror.remote_name

                if remote_name is None:
                    continue

                self._delete_forgejo_push_mirror(owner=owner, repo=repo, remote_name=remote_name)
