"""Contains the ForgejoPurger class"""
import os

from pyforgejo import Organization, PyforgejoApi, User
from pyforgejo.core import ApiError
from requests import RequestException

from fg_migration.utils import fg_print
from fg_migration.core.config_types import ForgejoConfig


class ForgejoPurger:
    """A way of purging data from a Forgejo instance, useful if testing modes of migration"""
    forgejo_api : PyforgejoApi
    forgejo_config : ForgejoConfig


    def __init__(self, fg_api:PyforgejoApi, forgejo_config: ForgejoConfig):
        self.forgejo_config = forgejo_config
        self.forgejo_api = fg_api



    def close(self) -> None:
        """tidy up the API"""
        #self.forgejo_api.close()



    def _get_exception_detail(self, e: Exception) -> str:
        if isinstance(e, ApiError):
            body = getattr(e, "body", None)
            detail = body.get("message") if isinstance(body, dict) else str(body)
            if "token does not have at least one of required scope" in detail:
                fg_print.error(f"Trapped Error {detail}")
                fg_print.error("ERROR: Access Token used MUST have read+write permission "
                               "on everything (permission:all) and be admin. Please "
                               "create a new one and update the .migrate.ini file.")
                os.sys.exit(1)
        else:
            detail = str(e)
        return detail



    def del_orgs_repos(self, page: int=1) -> None:
        """Delete all repositories in all organizations"""

        while True:
            orgs = self.forgejo_api.organization.org_get_all(page=page)
            page+=1
            if len(orgs) == 0:
                break
            for org in orgs:
                self.delete_all_repos_for_org(org=org)


    def delete_all_repos_for_org(self, org:Organization, page:int=1):
        """delete all repositories for organization"""
        while True:
            repos = self.forgejo_api.organization.org_list_repos(org=org.username,
                                                                 page=page)
            page+=1
            if len(repos) == 0:
                break
            for repo in repos:
                try:
                    self.forgejo_api.repository.repo_delete(owner=org.username,
                                                            repo=repo.name)
                    fg_print.info(f"Repository {repo.name} deleted on Forgejo"
                                    f" for {org.username}")
                except (ApiError, RequestException) as e:
                    detail = self._get_exception_detail(e)
                    fg_print.error(f"Error deleting repository {repo.name}"
                                    f" on Forgejo for {org.username}: {detail}")



    def del_orgs(self, page: int=1) -> None:
        """Delete all organizations"""

        while True:
            orgs = self.forgejo_api.organization.org_get_all(page=page)
            page+=1
            if len(orgs) == 0:
                break
            for org in orgs:
                try:
                    self.forgejo_api.organization.org_delete(org=org.username)
                    fg_print.info(f"Organization {org.username} deleted on Forgejo")
                except (ApiError, RequestException) as e:
                    detail = self._get_exception_detail(e)
                    fg_print.error(f"Error deleting organization {org.name} on Forgejo: {detail}")



    def del_all_user_repos(self, page: int=1) -> None:
        """Delete all user repositories"""
        while True:
            users = self.forgejo_api.admin.search_users(page=page)
            page+=1
            if len(users) == 0:
                break
            for user in users:
                fg_print.debug(f"deleting repos for user {user.login}")
                self.del_all_repos_for_user(user=user)


    def del_all_repos_for_user(self, user:User, page:int=1):
        """Delete all repos for user"""

        while True:
            fg_print.debug(f"Retrieving repos for {user.login}")
            repos = self.forgejo_api.user.list_repos(username=user.login, page=page)
            page+=1
            if len(repos) == 0:
                break
            for repo in repos:
                try:
                    fg_print.info(f"Deleting repo {repo.name}")
                    self.forgejo_api.repository.repo_delete(owner=user.login,
                                                            repo=repo.name)
                    fg_print.info(f"Repository {repo.name} deleted "
                                    f"on Forgejo for {user.login}")
                except (ApiError, RequestException) as e:
                    detail = self._get_exception_detail(e)
                    fg_print.error(f"Error deleting repository {repo.name}"
                                    f" on Forgejo for {user.login}: {detail}")



    def del_current_user_repos(self, page: int=1) -> None:
        """Delete all current user repositories"""

        while True:
            repos = self.forgejo_api.user.current_list_repos(page=page)
            page+=1
            if len(repos) == 0:
                break
            user = self.forgejo_api.user.get_current()
            for repo in repos:
                if repo.owner.id != user.id:
                    fg_print.debug(f"Skipping repository {repo.name} not owned"
                                   f" by user {user.login}")
                try:
                    self.forgejo_api.repository.repo_delete(org_name=user.login,
                                                            repo_name=repo.name)
                    fg_print.info(f"Repository {repo.name} deleted on Forgejo for {user.login}")
                except (ApiError, RequestException) as e:
                    detail = self._get_exception_detail(e)
                    fg_print.error(f"Error deleting repository {repo.name}"
                                   f" on Forgejo for {user.login}: {detail}")



    def del_users(self, purge: bool, page:int=1) -> None:
        """Delete all users"""
        while True:
            users = self.forgejo_api.admin.search_users(page=page)
            page+=1
            if len(users) == 0:
                break
            for user in users:
                try:
                    if user.login != "aliens":
                        self.forgejo_api.admin.delete_user(username=user.login, purge=purge)
                        fg_print.info(f"User {user.login} deleted on Forgejo")
                except (ApiError, RequestException) as e:
                    detail = self._get_exception_detail(e)
                    fg_print.error(f"Error deleting user {user.login} on Forgejo: {detail}")

