#!/usr/bin/env python3
#
# imports projects, users, groups, issues, labels, milestones, keys
# and collaborators from Gitlab to Forgejo
#
"""
Usage: migrate.py [--users] [--groups] [--projects] [--all] [--notify]
       migrate.py --help

Migration script to import projects, users, groups, from Gitlab to Forgejo.

Options
  -h, --help  Show this screen
  --users     migrate users
  --groups    migrate groups
  --projects  migrate projects
  --all       migrate all
  --notify    send notification to users
"""
import os
import json
import re
import random
import string
import configparser
from typing import Dict
from typing import List
import typing
from pyforgejo.core import RequestOptions
from typing_extensions import deprecated

from docopt import docopt
import requests
import dateutil.parser
from httpx import Client as HttpxClient

import gitlab  # pip install python-gitlab
import gitlab.v4.objects
import pyforgejo  # pip install pyforgejo (https://github.com/h44z/pyforgejo)

# Forgejo API imports:
from pyforgejo import ConflictError, GpgKey, Issue, Label, Milestone, NotFoundError, PublicKey, PyforgejoApi, Repository, Team, TeamPermission, User
from pyforgejo.core.api_error import ApiError

from fg_migration import fg_print

SCRIPT_VERSION = "0.5"

#######################
# CONFIG SECTION START
#######################
if not os.path.exists(".migrate.ini"):
    fg_print.info("Please create .migrate.ini as explained in the README!")
    os.sys.exit()

config = configparser.RawConfigParser()
config.read(".migrate.ini")
GITLAB_CLIENT_AUTH_CERT = config.get("migrate", "gitlab_client_auth_cert", fallback=None)
GITLAB_CLIENT_AUTH_KEY = config.get("migrate", "gitlab_client_auth_key", fallback=None)
GITLAB_URL = config.get("migrate", "gitlab_url")
GITLAB_TOKEN = config.get("migrate", "gitlab_token", fallback=None)
GITLAB_ADMIN_USER = config.get("migrate", "gitlab_admin_user", fallback=None)
GITLAB_ADMIN_PASS = config.get("migrate", "gitlab_admin_pass", fallback=None)
FORGEJO_CLIENT_AUTH_CERT = config.get("migrate", "forgejo_client_auth_cert", fallback=None)
FORGEJO_CLIENT_AUTH_KEY = config.get("migrate", "forgejo_client_auth_key", fallback=None)
FORGEJO_URL = config.get("migrate", "forgejo_url")
FORGEJO_API_URL = f"{FORGEJO_URL}/api/v1"
FORGEJO_TOKEN = config.get("migrate", "forgejo_token")
# Not used. The script uses a personal access token for authentication
#FORGEJO_USER = config.get("migrate", "forgejo_admin_user")
#FORGEJO_PASSWORD = config.get("migrate", "forgejo_admin_pass")
#######################
# CONFIG SECTION END
#######################


def main():
    """Main function"""
    _args = docopt(__doc__)
    args = {k.replace("--", ""): v for k, v in _args.items()}

    fg_print.print_color(
        fg_print.Bcolors.HEADER, "---=== Gitlab to Forgejo migration ===---"
    )
    fg_print.info(f"Version: {SCRIPT_VERSION}\n")
    

    session = requests.Session()
    # add client authentication if cert and key are provided in the config
    if(GITLAB_CLIENT_AUTH_CERT != None and GITLAB_CLIENT_AUTH_KEY != None):
        cert_path = GITLAB_CLIENT_AUTH_CERT
        key_path = GITLAB_CLIENT_AUTH_KEY
        session.cert = (cert_path, key_path)
    # private token or personal token authentication
    gl = gitlab.Gitlab(url = GITLAB_URL, private_token=GITLAB_TOKEN, session=session)
    try:
        gl.auth()
    except gitlab.GitlabAuthenticationError:
        fg_print.error("Failed to authenticate with Gitlab! Check access token and client authentication settings in .migrate.ini")
        os.sys.exit()
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to connect to Gitlab! {detail}")
        os.sys.exit()
    assert isinstance(gl.user, gitlab.v4.objects.CurrentUser)
    fg_print.info(f"Connected to Gitlab, version: {gl.version()[0]}")

    fg = _build_forgejo_api_client(FORGEJO_TOKEN)
    try:
        response = fg.miscellaneous.get_version()
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to connect to Forgejo! {detail}")
        os.sys.exit()
    fg_ver = response.version
    
    fg_print.info(f"Connected to Forgejo, version: {fg_ver}")

    # IMPORT USERS
    if args["users"] or args["all"]:
        import_users(gl, fg)
    # IMPORT GROUPS
    if args["groups"] or args["all"]:
        import_groups(gl, fg)
    # IMPORT PROJECTS
    if args["projects"] or args["all"]:
        import_projects(gl, fg)
    # IMPORT NOTHING ?
    if (
        not args["users"]
        and not args["groups"]
        and not args["projects"]
        and not args["all"]
    ):
        fg_print.info()
        fg_print.warning("No migration option(s) selected, nothing to do!")
        os.sys.exit()

    fg_print.info("")
    if fg_print.GLOBAL_ERROR_COUNT == 0:
        fg_print.success("Migration finished with no errors!")
    else:
        fg_print.error(f"Migration finished with {fg_print.GLOBAL_ERROR_COUNT} errors!")
        fg_print.info("Failed elements:")
        print(*fg_print.GLOBAL_ERROR_LIST, sep="\n")


#
# Data loading helpers for Forgejo
#

def _get_exception_detail(e: Exception) -> str:
    if isinstance(e, ApiError):
        body = getattr(e, "body", None)
        detail = body.get("message") if isinstance(body, dict) else str(body)
    else:
        detail = str(e)
    return detail

def name_clean(name):
    """Cleans a name for usage in Forgejo"""
    new_name = name.replace(" ", "_")
    new_name = re.sub(r"[^a-zA-Z0-9_\.-]", "-", new_name)

    if new_name.lower() == "plugins":
        return f"{new_name}-user"

    return new_name

def _build_httpx_client(timeout: typing.Optional[float]=60, follow_redirects: typing.Optional[bool] = True) -> HttpxClient:
    client = None
    if(FORGEJO_CLIENT_AUTH_CERT != None and FORGEJO_CLIENT_AUTH_KEY != None):
        cert_path = FORGEJO_CLIENT_AUTH_CERT
        key_path = FORGEJO_CLIENT_AUTH_KEY
        cert = (cert_path, key_path)
        client = HttpxClient(cert=cert, timeout=timeout,follow_redirects=follow_redirects)
    return client

def _build_forgejo_api_client(forgejo_api_key: str) -> pyforgejo.PyforgejoApi:
    return PyforgejoApi(base_url=FORGEJO_API_URL, api_key=forgejo_api_key, httpx_client = _build_httpx_client())


def _get_forgejo_labels(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str) -> List[Label]:
    """get labels for a repository"""
    
    try:
        existing_labels = fg_api.issue.list_labels(owner, repo)
        return existing_labels
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load existing labels for project {repo}! {detail}")
        return []


def _get_forgejo_milestones(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str) -> List[Milestone]:
    """get milestones for a repository"""

    try:
        existing_milestones : List[Milestone] = fg_api.issue.get_milestones_list(owner, repo)  # workaround to ensure labels are loaded, otherwise the label existence check does not work for some reason
        return existing_milestones
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load existing milestones for project {repo}! {detail}")
        return []


def _get_forgejo_issues(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str) -> List[Issue]:
    """get issues for a repository"""

    try:
        existing_issues = fg_api.issue.list_issues(owner, repo)  # workaround to ensure issues are loaded, otherwise the issue existence check does not work for some reason
        return existing_issues
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load existing issues for project {repo}! {detail}")
        return []


def _get_forgejo_teams(fg_api: pyforgejo.PyforgejoApi, orgname: str) -> List[Team]:
    """get teams for an organization"""

    try:
        existing_teams = fg_api.organization.org_list_teams(orgname)  # workaround to ensure teams are loaded, otherwise the team existence check does not work for some reason
        return existing_teams
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load existing teams for organization {orgname}! {detail}")
        return []
    


def _get_forgejo_team_members(fg_api: pyforgejo.PyforgejoApi, teamid: int) -> List[User]:
    """get members for a team"""

    try:
        members = fg_api.organization.org_list_team_members(teamid)
        return members
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load team members for team {teamid}! {detail}")
        return []

def _get_forgejo_collaborators(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str) -> List[User]:
    """get collaborators for a repository"""

    try:
        collaborators = fg_api.repository.repo_list_collaborators(owner, repo)  # workaround to ensure collaborators are loaded, otherwise the collaborator existence check does not work for some reason
        return collaborators
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load collaborators for repo {repo}! {detail}")
        return []


def _get_forgejo_user_keys(fg_api: pyforgejo.PyforgejoApi, username : str) -> List[PublicKey] :
    """get public keys for a user"""

    try:
        keys = fg_api.user.list_keys(username)
        return keys
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load public keys for user {username}! {detail}")
    return []

def _get_forgejo_user_gpg_keys(fg_api: pyforgejo.PyforgejoApi, username : str) -> List[GpgKey] :
    """get gpg keys for a user"""

    try:
        keys = fg_api.user.user_list_gpg_keys(username)
        return keys
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load gpg keys for user {username}! {detail}")
        
    return []

#TODO references to gitlab in comments inside forgejo function.
def _get_forgejo_organization(fg_api: pyforgejo.PyforgejoApi, projectName: str, org_name: str) -> User:
    
    try:
        #fg_print.info(f"Trying to load forgejo organization {possible_org} for gitlab project {project.name}...")
        org = fg_api.organization.org_get(org_name)
        fg_print.info(f"loaded organization {org.full_name} for gitlab project {projectName}!")
        return org
    except Exception as e:
        if isinstance(e, NotFoundError):
            fg_print.error(f"Failed to load forgejo organization {org_name} for gitlab project {projectName}! {e.body['message']}")
        else:
            fg_print.error(f"Failed to load forgejo organization {org_name} for gitlab project {projectName}! {e}")    
            
    return None

#TODO references to gitlab in comments inside forgejo function.
def _get_forgejo_user(fg_api: pyforgejo.PyforgejoApi, projectName: str, username: str) -> User:
    """get user by name"""
    try:
        user = fg_api.user.get(username)  # workaround to ensure collaborators are loaded, otherwise the collaborator existence check does not work for some reason
        fg_print.info(f"loaded user {user.username} for gitlab project {projectName}!")
        return user
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load user {username} for gitlab project {projectName}! {detail}")
    return None


def _forgejo_user_exists(fg_api: pyforgejo.PyforgejoApi, username: str) -> bool:
    """check if a user exists"""
    try:
        user = fg_api.user.get(username)
        fg_print.warning(f"User {username} already exists in Forgejo, skipping!")
        return True
    except NotFoundError:
        return False
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.info(f"User {username} not found in Forgejo, importing! {detail}")
        return False





def _forgejo_organization_exists(fg_api: pyforgejo.PyforgejoApi, orgname: str) -> bool:
    """check if an organization exists"""
    try:
        org = fg_api.organization.org_get(orgname)
        fg_print.warning(f"Group {orgname} already exists in Forgejo, skipping!")
        return True
    except NotFoundError:
        return False
    except Exception as e:
        fg_print.info(f"Group {orgname} not found in Forgejo, importing!")
        return False


def _forgejo_team_member_exists(fg_api: pyforgejo.PyforgejoApi, username: str, teamid: int) -> bool:
    """check if a member exists in a team"""
    existing_members = _get_forgejo_team_members(fg_api, teamid)
    if existing_members:
        
        existing_member = next(
            (item for item in existing_members if item.username == username), None
        )

        if existing_member:
            fg_print.warning(
                f"Member {username} is already in team {teamid}, skipping!"
            )
            return True

        fg_print.info(f"Member {username} is not in team {teamid}, importing!")
        return False

    fg_print.info(f"No members in team {teamid}, importing!")
    return False


def _forgejo_collaborator_exists(fg_api: pyforgejo.PyforgejoApi, _owner: str, repo: str, username: str) -> bool:
    """check if a collaborator exists in a repository"""
    try:
        collaborators : List[User] = fg_api.repository.repo_list_collaborators(_owner, repo)  # workaround to ensure collaborators are loaded, otherwise the collaborator existence check does not work for some reason
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
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to list collaborators for project {repo} for owner {_owner} {detail}!")
        return False



def _forgejo_repo_exists(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str) -> bool:
    """check if a repository exists"""
    try:
        fg_print.info(f"Checking if project {repo} exists in Forgejo for owner {owner}...")
        repository = fg_api.repository.repo_get(owner=owner, repo=repo)
        if repository is not None:
            fg_print.warning(f"Project {repo} already exists in Forgejo, skipping!")
            return True
    except Exception as e:
        if isinstance(e, NotFoundError):
            fg_print.info(f"Project {repo} not found in Forgejo, importing!")
            return False
        else:
            detail = _get_exception_detail(e)
            fg_print.error(f"Failed to check if project {repo} exists in Forgejo for owner {owner}! {detail}")

    
    fg_print.info(f"Project {repo} not found in Forgejo, importing!")
    return False


def _forgejo_label_exists(
    fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str, labelname: str
) -> bool:
    """check if a label exists in a repository"""
    #issues = fg_api.issue.list_issues(owner, repo)  # workaround to ensure labels are loaded, otherwise the label existence check does not work for some reason
    existing_labels = fg_api.issue.list_labels(owner, repo)
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


def _forgejo_issue_exists(existing_issues : List[Issue], repo: str, issue: str) -> bool:
    """check if an issue exists in a repository"""
    
    if existing_issues:
        existing_issue = next(
            (item for item in existing_issues if item.title == issue), None
        )

        if existing_issue is not None:
            fg_print.warning(
                f"Issue {issue} already exists in project {repo}, skipping!"
            )
            return True

        fg_print.info(f"Issue {issue} does not exist in project {repo}, importing!")
        return False

    fg_print.info(f"No issues in project {repo}, importing!")
    return False

def _find_forgejo_milestone_id_by_title(forgejo_milestones: List[Milestone], title: str) -> int:
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


def _find_forgejo_milestone_by_title(
    existing_milestones : List[Milestone], title: str
) -> bool:
    """check if a milestone exists in a repository"""
    
    if existing_milestones:
        existing_milestone = next(
            (item for item in existing_milestones if item.title == title), None
        )

        return existing_milestone
    
    return None


def _forgejo_add_collaborator(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str, username: str, permission: str) -> bool:
    """add a collaborator to a repository"""
    try:
        fg_api.repository.repo_add_collaborator(owner = owner, 
                                                repo = repo, 
                                                collaborator = username, 
                                                permission = permission)
        fg_print.info(f"Collaborator {username} imported!")
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
                f"Collaborator {username} import failed: {detail}",
                f"Collaborator {username} already exists in project {repo}, skipping!: {detail}"
            )
        return False
    # return true even if the collaborator already exists in the repository, because the existence of the collaborator in the repository is not a failure for the import of the project, we just skip it and continue with the import of the other collaborators
    return True

#TODO gitlab username references in forgejo function
def _forgejo_add_user(fg_api: pyforgejo.PyforgejoApi, gitlab_username: str, username: str, full_name: str, email: str, notify: bool) -> bool:
    """add a user to Forgejo, return True if user created or already exists"""

    if not _forgejo_user_exists(fg_api, username): # need this because status 422 returned for conflict, not 409 
        rnd_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        tmp_password = f"Tmp1!{rnd_str}"
        try:
            fg_api.admin.create_user(
                email=email,
                full_name=full_name,
                login_name=username,
                password=tmp_password,
                send_notify=notify,
                source_id=0,  # local user
                username=username,
            )
            fg_print.info(f"User {gitlab_username} imported as {username}, temporary password: {tmp_password}")
            return True
        except ConflictError:
            return True # already exists
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(f"Adding User {gitlab_username} as {username} failed: {detail}",
                            f"failed to import user {gitlab_username} as {username} in Forgejo: {detail}",
            )
            return False
    return True


def _forgejo_add_user_key(fg_api: pyforgejo.PyforgejoApi, username : str, key_name : str, key_content : str) -> PublicKey :
    """Add a public key to the user"""
    try:
        # fg_print.info(f"Importing public key {key_name} for user {username}...")
        new_key = fg_api.admin.create_public_key(
            username=username,
            key=key_content,
            read_only=True,
            title=key_name,
        )
        fg_print.info(f"Public key {key_name} imported for user {username}!")
        return new_key
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"Public key {key_name} import failed: {detail}",
            f"failed to import Public key '{key_name}' for user {username}",
        )
        return None

def _build_forgejo_sudo_request_options(username:str) -> RequestOptions :
    headers : Dict = { "Sudo" : username }
    request_options : RequestOptions = RequestOptions(additional_headers=headers)
    return request_options

def _forgejo_add_gpg_key(fg_api: pyforgejo.PyforgejoApi, username : str, key_id : str, key_content : str) -> GpgKey :
    """Add a GPG key to the user"""
    
    try:
        new_key = fg_api.user.user_current_post_gpg_key (
            armored_public_key=key_content,
            request_options=_build_forgejo_sudo_request_options(username)
        )
        fg_print.info(f"GPG key {key_id} imported for user {username}!")
        return new_key
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"GPG key {key_id} import failed: {e}",
            f"failed to import GPG key '{key_id}' for user {username} {detail}",
        )
        return None

@deprecated("This cannot be used to create api tokens when the API was authorised using an access token")
def _forgeo_delete_temp_api_token_for_user(fg_api: pyforgejo.PyforgejoApi, username:str, token_name:str):
    """Delete an Access Token for the user (if using sudo)"""
    try:
        fg_api.user.delete_access_token(username=username, token=token_name)
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"Delete temporary user api token {token_name} of user {username} failed: {detail}",
        )

@deprecated("This cannot be used to create api tokens when the API was authorised using an access token")
def _forgejo_add_temp_api_token_for_user(fg_api: pyforgejo.PyforgejoApi, username:str, token_name:str, desired_scopes:Dict[str] = None) -> str:
    """Create an Access Token for the user (if using sudo)"""
    #Example desired_scopes=["read:user","write:user"]
    # A full list is here: https://forgejo.org/docs/latest/user/token-scope/
    try:
        fg_print.info(f"Creating access token for user {username} {token_name} with scope {desired_scopes}")
        user_api_token = fg_api.user.create_token(username=username, name=token_name, scopes=desired_scopes)
    except Exception as e:
        fg_print.warning(f"Creating access token for user {username} {token_name} with scope {desired_scopes} failed...")
        detail = _get_exception_detail(e)
        try:
            fg_api.user.delete_access_token(username=username, token=token_name)
            user_api_token = fg_api.user.create_token(username=username, name=token_name, scopes=desired_scopes)
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(f"Error creating temporary API token {token_name} for user {username} {detail}")
            return None
    return user_api_token

def _forgejo_add_organization(fg_api: pyforgejo.PyforgejoApi, orgname: str, full_name: str, description: str) -> bool:
    """add a group as organization in Forgejo"""
    if not _forgejo_organization_exists(fg_api, orgname): # need this because status 422 returned for conflict, not 409 
        try:
            fg_api.organization.org_create(
                description=description,
                full_name=full_name,
                location="",
                username=orgname,
                website="",
            )
            fg_print.info(f"Group {orgname} imported!")
        except ConflictError:
            return True # already exists
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(
                f"Adding organization {orgname} import failed: {e} {detail}",
                f"failed to import group {orgname} as organization in Forgejo: {detail}",
            )
            return False
    # return true even if the organization already exists, because the existence of the organization is not a failure for the import of the group, we just skip it and continue with the import of the group members and projects
    return True


def _forgejo_add_user_to_group_team(fg_api: pyforgejo.PyforgejoApi, username: str, groupname: str, teamid: int) -> bool:
    """add a user to a team for a group"""
    if not _forgejo_team_member_exists(fg_api, username, teamid):
        try:
            fg_api.organization.org_add_team_member(teamid, username)
            fg_print.info(
                f"Member {username} added to group {groupname}!"
            )
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(
                f"Adding user {username} to group {groupname} import failed: {detail}",
                f"Failed to add member {username} to team {teamid} for group {groupname} in Forgejo: {detail}",
            )
            return False
    # return true even if the member already exists in the team, because the existence of the member in the team is not a failure for the import of the group, we just skip it and continue with the import of the other members
    return True


def _forgejo_add_milestone(fg_api: pyforgejo.PyforgejoApi, owner: str, repo: str, forgejo_milestones:List[Milestone], title: str, description: str, due_date: str, state: str) -> bool:
    """add a milestone to a repository"""
    forgejo_milestone : Milestone = _find_forgejo_milestone_by_title(forgejo_milestones, title)

    # if the milestone doesn't exist in the list
    if forgejo_milestone == None:
        if due_date:
            due_date = dateutil.parser.parse(due_date).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        try:
            forgejo_milestones.append(
                fg_api.issue.create_milestone(owner, repo, title=title, description=description, due_on=due_date, state=state)
            )
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(
                f"Milestone {title} import failed: {detail}",
                f"Failed to import milestone {title} for project {repo} in Forgejo {detail}",
            )
            return False
    return True

#
# Gitlab helper functions
#


def get_forgejo_owner_id_for_gitlab_project(fg_api: pyforgejo.PyforgejoApi, project: gitlab.v4.objects.Project) -> int:
    ownerId: int = None
    if project.namespace["kind"] == "user":
        projectOwnerSlug = _get_gitlab_project_owner_slug(project)
        if user := _get_forgejo_user(fg_api, username=projectOwnerSlug, projectName=project.name):
            ownerId = user.id
        else:
            fg_print.error(f"Failed to load project owner for project {project.name}, skipping import!")
    elif project.namespace["kind"] == "group":
        org_name = _get_gitlab_project_owner_slug(project)
        if org := _get_forgejo_organization(fg_api, projectName= project.name, org_name = org_name):
            ownerId = org.id
        else:
            fg_print.error(f"Failed to load project organization for project {project.name}, skipping import!")
    else:
        fg_print.error(f"Unsupported namespace kind {project.namespace['kind']} for project {project.name}, skipping import!")
    
    return ownerId

def _get_forgejo_owner_username_for_gitlab_project(fg_api: pyforgejo.PyforgejoApi, project: gitlab.v4.objects.Project) -> str:
    username: str = None
    user_or_org_name = name_clean(_get_gitlab_project_owner_slug(project))
    if project.namespace["kind"] == "user":
        if user := _get_forgejo_user(fg_api, projectName=project.name, username=user_or_org_name):
            username = user.username
        else:
            fg_print.error(f"Failed to load project owner for project {project.name}, skipping import!")
    elif project.namespace["kind"] == "group":
        if org := _get_forgejo_organization(fg_api, projectName= project.name, org_name = user_or_org_name):
            username = org.username
        else:
            fg_print.error(f"Failed to load project organization for project {project.name}, skipping import!")
    else:
        fg_print.error(f"Unsupported namespace kind {project.namespace['kind']} for project {project.name}, skipping import!")
    
    return username

def _get_gitlab_project_owner_slug(project: gitlab.v4.objects.Project) -> str:
    if project.namespace["kind"] == "user":
        return project.namespace["path"]
    elif project.namespace["kind"] == "group":
        return name_clean(project.namespace["name"])
    else:
        fg_print.error(f"Unsupported namespace kind {project.namespace['kind']} for project {project.name}, skipping import!")
        return None


def _convert_gitlab_permission_to_forgejo(gitlab_access_level: int) -> str:
    """convert gitlab permission level to forgejo permission level"""
    permission = "read"
    if gitlab_access_level == 10:  # guest access
        permission = "read"
    elif gitlab_access_level == 20:  # reporter access
        permission = "read"
    elif gitlab_access_level == 30:  # developer access
        permission = "write"
    elif gitlab_access_level == 40:  # maintainer access
        permission = "admin"
    elif gitlab_access_level == 50:  # owner access (only for group owned projects)
        # this is the project creator. In Gitlab, the project creator can be a member of the 
        # owning group with owner access, but in Forgejo the project creator is always the 
        # repo owner and cannot be a collaborator at the same time. Therefore, we check if 
        # the collaborator with owner access is the same as the repo owner, if yes, we skip 
        # adding them as collaborator, if not, we set their permissions to admin as fallback 
        # and print a warning, because there is no equivalent permission level for group 
        # owners in Forgejo.
        permission = "owner"
    else:
        fg_print.warning(
            f"Unsupported access level {gitlab_access_level}, "
            + "setting permissions to 'read'!"
        )
    return permission



def _build_or_extract_email(user: gitlab.v4.objects.User) -> str:
    """build an email address for a user, if the email is not available, we use a dummy email address based on the username"""
    
    # Some gitlab instances do not publish user emails, so we use a dummy email
    
    try:
        emails : list[gitlab.v4.objects.UserEmail] = user.emails.list(get_all=True)
    except AttributeError:
        emails = []
    
    if emails and len(emails) > 0:
        tmp_email = emails[0].email
    else:
        tmp_email = f"{user.username}@noemail-git.local"
    try:
        tmp_email = user.email
    except AttributeError:
        pass
    return tmp_email

#
# Import functions
#


def _import_project_labels(
    fg_api: pyforgejo.PyforgejoApi,
    labels: List[gitlab.v4.objects.ProjectLabel],
    owner: str,
    repo: str,
):
    """import labels for a repository"""
    for label in labels:
        if not _forgejo_label_exists(fg_api, owner, repo, label.name):  # need this because status 422 returned for conflict, not 409 
            try:
                fg_api.issue.create_label(owner, repo, name=label.name, color=label.color, description=label.description)
                fg_print.info(f"Label {label.name} imported!")
            except ConflictError:
                continue # already exists :-)
            except Exception as e:
                detail = _get_exception_detail(e)
                fg_print.error(
                    f"Label {label.name} import failed: {detail}",
                    f"Failed to import label {label.name} for project {repo} in Forgejo: {detail}",
                )
                continue



def _import_project_milestones(
    fg_api: pyforgejo.PyforgejoApi,
    milestones: List[gitlab.v4.objects.ProjectMilestone],
    owner: str,
    repo: str,
):
    """import milestones for a repository"""
    forgejo_milestones = _get_forgejo_milestones(fg_api, owner, repo)
    for milestone in milestones:
        # Note: _forgejo_add_milestone appends to the cached list of forgejo_milestones too for efficiency.
        success = _forgejo_add_milestone(fg_api, owner, repo, forgejo_milestones, milestone.title, milestone.description, milestone.due_date, milestone.state)
        if not success:
            continue


def _import_project_issues(
    fg_api: pyforgejo.PyforgejoApi,
    issues: List[gitlab.v4.objects.ProjectIssue],
    owner: str,
    repo: str,
):
    # reload all existing milestones and labels, needed for assignment in issues
    forgejo_milestones = _get_forgejo_milestones(fg_api, owner, repo)
    forgejo_labels = _get_forgejo_labels(fg_api, owner, repo)
    # get a list of all existing forgejo issues
    forgejo_issues = _get_forgejo_issues(fg_api, owner, repo)
    
    for issue in issues:
        if not _forgejo_issue_exists(forgejo_issues, repo, issue.title):
            due_date = ""
            if issue.due_date is not None:
                due_date = dateutil.parser.parse(issue.due_date).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            # extract assignee, mapping to forgejo safe username
            assignee = None
            if issue.assignee is not None:
                assignee = name_clean(issue.assignee["username"])

            # extract list of assignees, mapping to forgejo safe username
            assignees : List[str] = []
            for tmp_assignee in issue.assignees:
                assignees.append(name_clean(tmp_assignee["username"]))

            # Get milestone id for the issue, if milestone is assigned to the issue in Gitlab.
            # # We need to get the milestone id for the milestone title from Forgejo, because the 
            # milestone id in Gitlab is not the same as the milestone id in Forgejo, and we need 
            # the milestone id for the assignment of the milestone to the issue in Forgejo. 
            # If there is no milestone with the same title in Forgejo, we do not assign a milestone 
            # to the issue in Forgejo, because there is no equivalent milestone in Forgejo.
            forgejo_milestoneId = None
            missing_milestone = False
            if issue.milestone is not None:
                forgejo_milestoneId = _find_forgejo_milestone_id_by_title(forgejo_milestones, issue.milestone["title"]) # N.b. gitlab issue so dict
                if forgejo_milestoneId is None:
                    # if this happens, something went wrong with the milestone import, because the milestone assigned to the issue in Gitlab should have been imported to Forgejo in the milestone import step before the issue import step, so we print an error and skip the milestone assignment for this issue, but we continue with the import of the issue without the milestone assignment, because the existence of the milestone is not a failure for the import of the issue, we just skip the milestone assignment for this issue and continue with the import of the issue without the milestone assignment.
                    fg_print.error(
                        f"Milestone {issue.milestone['title']} assigned to issue {issue.title} does not exist in Forgejo, skipping milestone assignment for this issue!",
                        f"Failed to import issue {issue.title} for project {repo} in Forgejo",
                    )
                    missing_milestone = True
            if missing_milestone:
                continue # stop the import of this issue (to allow milestone import to be fixed and re-run not to create duplicate issues)


            missing_label = False
            forgejo_issue_label_ids : List[int] = []
            for label in issue.labels:
                existing_label : Label = None
                existing_label = next(
                    (item for item in forgejo_labels if item.name == label), None
                )
                if existing_label:
                    forgejo_issue_label_ids.append(existing_label.id)
                else:
                    fg_print.error(
                        f"Label {label} assigned to issue {issue.title} does not exist in Forgejo, skipping label assignment for this issue!",
                        f"Failed to import issue {issue.title} for project {repo} in Forgejo",
                    )
                    missing_label = True
                    break
            if missing_label:
                continue # stop the import of this issue (to allow milestone import to be fixed and re-run not to create duplicate issues)
                

            try:
                fg_api.issue.create_issue(owner, repo,
                                        title=issue.title,
                                        body=issue.description,
                                        assignee=assignee,
                                        assignees=assignees,
                                        milestone=forgejo_milestoneId,
                                        labels=forgejo_issue_label_ids,
                                        due_on=due_date,
                                        closed=issue.state == "closed")
                fg_print.info(f"Issue {issue.title} imported!")
            except Exception as e:
                detail = _get_exception_detail(e)
                fg_print.error(
                    f"Issue {issue.title} import failed: {detail}"
                    f"Failed to import issue {issue.title} for project {repo} in Forgejo: {detail}",
                )

def _import_project_repo(fg_api: pyforgejo.PyforgejoApi, project: gitlab.v4.objects.Project):
    project_name = name_clean(project.name)
    
    username: str = _get_forgejo_owner_username_for_gitlab_project(fg_api, project)

    if username is None:
        fg_print.error(f"Failed to determine project owner for project {project.name}, skipping import!")
        return

    if not _forgejo_repo_exists(fg_api, username, project_name):
        clone_url = project.web_url
        if GITLAB_ADMIN_PASS == "" and GITLAB_ADMIN_USER == "":
            clone_url = project.http_url_to_repo

        fg_print.info(f"Importing project {project.name} from {clone_url}...")
        private = project.visibility == "private" or project.visibility == "internal"

        owner_uid: int = get_forgejo_owner_id_for_gitlab_project(fg_api, project)
        
        if owner_uid is None:
            fg_print.error(
                f"Failed to load project owner for project {project.name}, skipping import!",
                f"project {project.name} failed to load owner, skipping import!",
            )
            return

        proj_name = name_clean(project.name)
        if owner_uid:
            try:
                repo : Repository
                repo =fg_api.repository.repo_migrate(
                        auth_password=GITLAB_ADMIN_PASS,
                        auth_username=GITLAB_ADMIN_USER,
                        auth_token=GITLAB_TOKEN,
                        clone_addr=clone_url,
                        description=project.description,
                        service="gitlab",
                        issues=True,
                        labels=True,
                        milestones=True,
                        mirror=False,
                        pull_requests=True,
                        releases=True,
                        private=private,
                        repo_name=proj_name,
                        uid=owner_uid,
                        wiki=True,
                )
                fg_print.info(f"Project {proj_name} imported {clone_url}!")
            except Exception as e:
                detail = _get_exception_detail(e)
                fg_print.error(f"project {proj_name} import failed from url {clone_url} : {detail}")
        else:
            fg_print.error(
                f"Failed to load project owner for project {proj_name}",
                f"project {proj_name} failed to load owner",
            )

def _import_project_repo_collaborators(
    fg_api: pyforgejo.PyforgejoApi,
    collaborators: List[gitlab.v4.objects.ProjectMember],
    project: gitlab.v4.objects.Project,
):  # workaround to ensure collaborators are loaded, otherwise the collaborator existence check does not work for some reason

    """import collaborators for a repository"""
    owner_user_or_org_name = name_clean(_get_gitlab_project_owner_slug(project))
    project_name = name_clean(project.name)

    if(project.namespace["kind"] == "group"):
        fg_print.info(f"\nImporting collaborators for group project {project_name}...")
    else:
        fg_print.info(f"\nImporting collaborators for personal project {project_name}...")
    
    if(len(collaborators) == 0):
        fg_print.info(f"No collaborators found for project {project_name}, skipping!")
        return
    
    repo : Repository = None
    repo_owner_username : str = None
    try:
        repo = fg_api.repository.repo_get(owner = owner_user_or_org_name, repo = project_name)
        repo_owner_username = repo.owner.username
        fg_print.info(f"Loaded repository {project_name} for owner {owner_user_or_org_name} to import collaborators!")
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(f"Failed to load repository {project_name} for owner {owner_user_or_org_name} to import collaborators! {detail}")
        return
    
    is_owner_user = False
    is_owner_org = False
    try:
        # Check users
        user = fg_api.user.get(repo_owner_username)
        is_owner_user = user.id == repo.owner.id
    except Exception as e:
        if isinstance(e, NotFoundError):
            try:
                # Check organisations
                org = fg_api.organization.org_get(repo_owner_username)
                is_owner_org = org.id == repo.owner.id
            except Exception as e:
                if isinstance(e, NotFoundError):
                    fg_print.info(f"Failed to locate repository owner {repo_owner_username}. Forgejo data might be corrupt, check manually.") # should be impossible.
                else:
                    detail = _get_exception_detail(e)
                    fg_print.error(f"Error locating repository owner {repo_owner_username} {detail}",
                                f"Error locating repository owner {repo_owner_username} {detail}")
                os.sys.exit()
        else:
            detail = _get_exception_detail(e)
            fg_print.error(f"Error locating repository owner {repo_owner_username} {detail}",
                        f"Error locating repository owner {repo_owner_username} {detail}")
            os.sys.exit()

    if is_owner_org:
        fg_print.info(f"Owner of repository {project_name} is an organization {repo_owner_username}")
    elif is_owner_user:
        fg_print.info(f"Owner of repository {project_name} is a user {repo_owner_username}")
    else:
        fg_print.error(f"Owner of repository {project_name} is neither a user nor an organization in Forgejo, this should not happen! Owner: {repo_owner_username}")

    for collaborator in collaborators:

        forgejo_safe_username = name_clean(collaborator.username)
        try:
            user = fg_api.user.get(forgejo_safe_username)
        except Exception as e:
            detail = _get_exception_detail(e)
            fg_print.error(f"Matching user account for collaborator {collaborator.username} not found. Skipping collaborator import! {detail}",
                             f"Matching user account for collaborator {collaborator.username} not found. Skipping collaborator import! {detail}")
            continue
        if forgejo_safe_username == owner_user_or_org_name:
            fg_print.info(f"Ignoring collaborator as they are the owner (cannot be both on Forgejo), skipping import!")
            continue

        fg_print.info(f"Marking user {user.username} as collaborator on project {project_name} : {user.full_name}...")
        
        
        if not _forgejo_collaborator_exists(fg_api, _owner = owner_user_or_org_name, 
                                   repo = project_name, 
                                   username = forgejo_safe_username):
            
            permission : str = _convert_gitlab_permission_to_forgejo(collaborator.access_level)
            if(permission is None):
                fg_print.error(f"Unsupported gitlab permission level {collaborator.access_level} for collaborator {collaborator.username} on project {project_name}, skipping collaborator import!",
                               f"Unsupported gitlab permission level {collaborator.access_level} for collaborator {collaborator.username} on project {project_name}, skipping collaborator import!")
                continue

            added = _forgejo_add_collaborator(fg_api, owner_user_or_org_name, project_name, forgejo_safe_username, permission)
            if not added:
                continue



def _import_users(
    fg_api: pyforgejo.PyforgejoApi, users: List[gitlab.v4.objects.User], notify: bool = False):
    """import users and their public keys"""

    temp_token_name = "temporary_gitlab_import_token"

    redirect_username = name_clean("redirect")
    isAdded = _forgejo_add_user(fg_api, gitlab_username = redirect_username, username = redirect_username, full_name = redirect_username, email = f"{redirect_username}@noemail-git.local", notify = notify)
    
    user : gitlab.v4.objects.User
    for user in users:
        gpg_keys : List[gitlab.v4.objects.UserGPGKey] = user.gpgkeys.list(get_all=True)
        keys: List[gitlab.v4.objects.UserKey] = user.keys.list(get_all=True)

        fg_print.info(f"Importing user {user.username}...")
        BOT_REGEX = re.compile(r"^project_\d{2}_bot_[a-zA-Z0-9]{32}$")

        if (user.username in {"GitLab-Admin-Bot", "ghost", "support-bot", "alert-bot", "GitlabDuo"}
            or BOT_REGEX.match(user.username)):
            fg_print.warning(f"Likely a Gitlab specific system user {user.username}. Can possibly be deleted after import!")
            # don't block the import of this user for now.
            #continue

        fg_print.info(f"Found {len(gpg_keys)} gpg keys for user {user.username}")
        fg_print.info(f"Found {len(keys)} public keys for user {user.username}")

        forgejo_safe_username = name_clean(user.username)
        if not _forgejo_user_exists(fg_api, forgejo_safe_username):  # need this because status 422 returned for conflict, not 409 
            emailAddress : str = _build_or_extract_email(user)
            isAdded = _forgejo_add_user(fg_api, gitlab_username = user.username, username = forgejo_safe_username, full_name = user.name, email = emailAddress, notify = notify)
            if not isAdded:
                # something went wrong with the user import. can't do any more for this user.
                continue

        # import public keys if possible
        _import_user_keys(fg_api, keys, gpg_keys, user.username)


def _import_user_keys(
    fg_api: pyforgejo.PyforgejoApi,
    keys: List[gitlab.v4.objects.UserKey],
    gpg_keys : List[gitlab.v4.objects.UserGPGKey],
    username: str,
):
    """import public keys for a user"""
    forgejo_safe_username = name_clean(username)
    forgejo_keys = _get_forgejo_user_keys(fg_api, forgejo_safe_username)
    forgejo_gpg_keys = _get_forgejo_user_gpg_keys(fg_api, forgejo_safe_username)

    #
    # SSH keys
    #
    for key in keys:
        key_name = key.title
        key_content = key.key
        existing_key = next(
            (item for item in forgejo_keys if item.title == key_name), None
        )
        if existing_key is None:
            # Import key
            new_key = _forgejo_add_user_key(fg_api, forgejo_safe_username, key_name, key_content)
            if new_key is not None:
                forgejo_keys.append(new_key)

    #
    # GPG keys
    #
    for gpg_key in gpg_keys:
        key_id = getattr(gpg_key, "key_id", None)
        
        key_content = (getattr(gpg_key, "public_key", None) 
                       or getattr(gpg_key, "key", None))
        existing_key = next(
            (item for item in forgejo_gpg_keys if item.key_id == key_id), None
        )
        if existing_key is None:
            # Import key
            new_key = _forgejo_add_gpg_key(fg_api, key_id, key_content)
            if new_key is not None:
                forgejo_gpg_keys.append(new_key)



def _import_groups(fg_api: pyforgejo.PyforgejoApi, groups: List[gitlab.v4.objects.Group]):
    """import groups and their members"""
    fg_print.info(f"Found {len(groups)} gitlab groups")

    group_names = [obj.name for obj in groups]
    fg_print.info(f"Importing groups... {group_names}")
    for group in groups:
        members: List[gitlab.v4.objects.GroupMember] = group.members.list(get_all=True)

        # create the Forgejo organization (gitlab group)
        forgejo_safe_group_name = name_clean(group.name)
        fg_print.info(f"Importing group {forgejo_safe_group_name} as Forgejo organization...")
        added_org = _forgejo_add_organization(fg_api, forgejo_safe_group_name, group.full_name, group.description)
        if not added_org:
            fg_print.warning(f"Group members may fail to import due to organization not being created!")
            continue
        # import group members
        fg_print.info(f"Found {len(members)} gitlab members for group {forgejo_safe_group_name}")
        _import_group_members(fg_api, members, group)
        


def _import_group_members(
    fg_api: pyforgejo.PyforgejoApi,
    members: List[gitlab.v4.objects.GroupMember],
    group: gitlab.v4.objects.Group,
):
    """import members to a group"""
    # ? TODO: create teams based on gitlab permissions (access_level of group member)
    forgejo_safe_group_name = name_clean(group.name)
    existing_teams = _get_forgejo_teams(fg_api, forgejo_safe_group_name)
    owner_team = existing_teams[0] # Add the gitlab repo creator in here
    admin_team = next((team for team in existing_teams if team.permission == "admin"), None)
    developer_team = next((team for team in existing_teams if team.permission == "write"), None)
    reporter_team = next((team for team in existing_teams if team.permission == "read"), None)
    guest_team = next((team for team in existing_teams if team.permission == "read"), None)

    if existing_teams:
        first_team : Team = existing_teams[0]

        fg_print.info(f"First team for group {forgejo_safe_group_name} is {first_team.name} with id {first_team.id}")
        first_team_name = first_team.name
        first_team_id = first_team.id
        fg_print.info(
            f"Organization teams fetched, importing users to first team: {first_team_name}"
        )

        member : gitlab.v4.objects.GroupMember
        for member in members:
            forgejo_safe_username = name_clean(member.username)
            _forgejo_add_user_to_group_team(fg_api, forgejo_safe_username, forgejo_safe_group_name, first_team_id)
    else:
        fg_print.error(
            f"Failed to import members to group {forgejo_safe_group_name}: no teams found!",
            f"Failed to import members to group {forgejo_safe_group_name}: no teams found in Forgejo for group {forgejo_safe_group_name}!",
        )


def import_users(gitlab_api: gitlab.Gitlab, fg_api: pyforgejo.PyforgejoApi, notify=False):
    """import all users and groups"""
    # read all users
    users: List[gitlab.v4.objects.User] = gitlab_api.users.list(get_all=True)

    fg_print.info(f"Found {len(users)} gitlab users as user {gitlab_api.user.username}")

    # import all non existing users
    _import_users(fg_api, users, notify)


def import_groups(gitlab_api: gitlab.Gitlab, fg_api: pyforgejo.PyforgejoApi):
    """import all users and groups"""
    # read all users
    groups: List[gitlab.v4.objects.Group] = gitlab_api.groups.list(get_all=True)

    # import all non existing groups
    _import_groups(fg_api, groups)


def import_projects(gitlab_api: gitlab.Gitlab, fg_api: pyforgejo.PyforgejoApi):
    """read all projects and their issues"""
    projects: gitlab.v4.objects.Project = gitlab_api.projects.list(get_all=True)

    fg_print.info(f"Found {len(projects)} gitlab projects as user {gitlab_api.user.username}")

    project : gitlab.v4.objects.Project
    for project in projects:
        collaborators: List[gitlab.v4.objects.ProjectMember] = project.members.list(
            all=True
        )
        labels: List[gitlab.v4.objects.ProjectLabel] = project.labels.list(get_all=True)
        milestones: List[gitlab.v4.objects.ProjectMilestone] = project.milestones.list(
             all=True
        )
        issues: List[gitlab.v4.objects.ProjectIssue] = project.issues.list(get_all=True)

        project_owner_name = _get_gitlab_project_owner_slug(project)
        project_name = name_clean(project.name)
        
        if(project.namespace["kind"] == "group"):
            fg_print.info(f"Importing project {project_name} from owner {project_owner_name}")
            fg_print.info(f"Project {project.name} is in group namespace, this will be imported as a repository under the organization corresponding to the group in Forgejo")
        else:
            fg_print.info(f"Importing project {project_name} from owner {project_owner_name}")
        
        fg_print.info(f"Found {len(collaborators)} collaborators for project {project_name}")
        fg_print.info(f"Found {len(labels)} labels for project {project_name}")
        fg_print.info(f"Found {len(milestones)} milestones for project {project_name}")
        fg_print.info(f"Found {len(issues)} issues for project {project_name}")

        # import project repo
        _import_project_repo(fg_api, project)

        # import collaborators
        _import_project_repo_collaborators(fg_api, collaborators, project)

        # import labels
        _import_project_labels(
            fg_api, labels, project_owner_name, project_name
        )

        # import milestones
        _import_project_milestones(
           fg_api, milestones, project_owner_name, project_name
        )

        # import issues
        _import_project_issues(
           fg_api, issues, project_owner_name, project_name
        )




if __name__ == "__main__":
    main()
