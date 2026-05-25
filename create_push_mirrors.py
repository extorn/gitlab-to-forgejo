#!/usr/bin/env python3
#
# pylint: disable=line-too-long
"""
Usage: create_push_mirrors.py [--to-forgejo] [--to-gitlab] [--all] [--limit LIMIT] (--create | --delete)
       create_push_mirrors.py --help

Create push mirrors from Gitlab to Forgejo and vice versa.

Options
  -h, --help     Show this screen
  --to-forgejo   create mirrors from Gitlab to Forgejo
  --to-gitlab    create mirrors from Forgejo to Gitlab
  --all          create mirrors in both directions
  --limit LIMIT  limit number of projects [default: 100000]
  --create       create mirrors
  --delete       delete mirrors
"""
# pylint: enable=line-too-long

import os
import configparser
from typing import List, Optional

from docopt import docopt
import requests
from httpx import Client as HttpxClient

import gitlab
import gitlab.v4.objects

import pyforgejo
from pyforgejo import PushMirror, PyforgejoApi
from pyforgejo.core.api_error import ApiError

from fg_migration import fg_print

SCRIPT_VERSION = "0.2"

#######################
# CONFIG SECTION START
#######################
if not os.path.exists(".migrate.ini"):
    fg_print.error("Please create .migrate.ini as explained in the README!")
    os.sys.exit()

config = configparser.RawConfigParser()
config.read(".migrate.ini")

GITLAB_CLIENT_AUTH_CERT = config.get(
    "migrate", "gitlab_client_auth_cert", fallback=None
)
GITLAB_CLIENT_AUTH_KEY = config.get(
    "migrate", "gitlab_client_auth_key", fallback=None
)

GITLAB_URL = config.get("migrate", "gitlab_url")
GITLAB_TOKEN = config.get("migrate", "gitlab_token")
GITLAB_ADMIN_USER = config.get("migrate", "gitlab_admin_user")
GITLAB_ADMIN_PASS = config.get("migrate", "gitlab_admin_pass")
GITLAB_SYNC_CONNECTION_TYPE = config.get("migrate", 
                                         "gitlab_sync_connection_type", 
                                         fallback="https").lower() # ssh/https

FORGEJO_CLIENT_AUTH_CERT = config.get(
    "migrate", "forgejo_client_auth_cert", fallback=None
)
FORGEJO_CLIENT_AUTH_KEY = config.get(
    "migrate", "forgejo_client_auth_key", fallback=None
)

FORGEJO_URL = config.get("migrate", "forgejo_url")
FORGEJO_API_URL = f"{FORGEJO_URL}/api/v1"
FORGEJO_ADMIN_USER = config.get("migrate", "forgejo_admin_user")
FORGEJO_ADMIN_PASS = config.get("migrate", "forgejo_admin_pass")
FORGEJO_TOKEN = config.get("migrate", "forgejo_token")

if GITLAB_SYNC_CONNECTION_TYPE not in ("ssh", "https"):
    fg_print.error(
        "gitlab_sync_connection_type must be 'ssh' or 'https'"
    )
    os.sys.exit(1)

#######################
# CONFIG SECTION END
#######################


def _get_exception_detail(e: Exception) -> str:
    if isinstance(e, ApiError):
        body = getattr(e, "body", None)
        detail = body.get("message") if isinstance(body, dict) else str(body)
    else:
        detail = str(e)
    return detail


def _build_httpx_client(
    timeout: Optional[float] = 60,
    follow_redirects: Optional[bool] = True,
) -> HttpxClient:
    
    cert = None
    if (FORGEJO_CLIENT_AUTH_CERT is not None
        and FORGEJO_CLIENT_AUTH_KEY is not None):
        
        cert = (FORGEJO_CLIENT_AUTH_CERT,
                FORGEJO_CLIENT_AUTH_KEY)

    client = HttpxClient(
        cert=cert,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )

    return client


def _build_forgejo_api_client(
    forgejo_api_key: str,
) -> pyforgejo.PyforgejoApi:
    return PyforgejoApi(
        base_url=FORGEJO_API_URL,
        api_key=forgejo_api_key,
        httpx_client=_build_httpx_client(),
    )


def _list_forgejo_push_mirrors(
    fg_api: PyforgejoApi,
    owner: str,
    repo: str,
) -> List[PushMirror]:

    try:
        pushMirrors = fg_api.repository.repo_list_push_mirrors(owner=owner, repo=repo)
        return pushMirrors
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"Failed to load push mirrors for {owner}/{repo}: ",
            f"{detail}"
        )

    return []


def _create_forgejo_push_mirror(
    fg_api: PyforgejoApi,
    owner: str,
    repo: str,
) -> bool:
    try:
        use_ssh = GITLAB_SYNC_CONNECTION_TYPE == "ssh"
        result = fg_api.repository.repo_add_push_mirror(
            owner=owner,
            repo=repo,
            remote_address=_build_gitlab_repo_url(owner, repo),
            remote_username=GITLAB_ADMIN_USER,
            remote_password=GITLAB_ADMIN_PASS,
            use_ssh= use_ssh,
            interval="8h0m0s",
            sync_on_commit=True,
        )
        if result:
            fg_print.info(f"Push mirror created on Forgejo for {owner}/{repo}")
            return True
    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"Failed to create push mirror on Forgejo for "
            f"{owner}/{repo}: {detail}"
        )

    return False


def _delete_forgejo_push_mirror(
    fg_api: PyforgejoApi,
    owner: str,
    repo: str,
    remote_name: str,
) -> bool:
    try:
        fg_api.repository.repo_delete_push_mirror(owner=owner, repo=repo, name=remote_name)
        fg_print.info(
                f"Push mirror {remote_name} deleted on Forgejo "
                f"for {owner}/{repo}"
            )
        return True

    except Exception as e:
        detail = _get_exception_detail(e)
        fg_print.error(
            f"Failed to delete push mirror {remote_name} "
            f"for {owner}/{repo}: {detail}"
        )

    return False


def to_forgejo(
    gitlab_projects: List[gitlab.v4.objects.Project],
) -> None:
    """Create push mirrors from Gitlab to Forgejo"""

    fg_print.info("\nMirroring repositories from Gitlab to Forgejo")

    for project in gitlab_projects:
        proj_path = project.path_with_namespace

        fg_print.info(f"Project: {proj_path}")

        forgejo_push_url = (
            f"{FORGEJO_URL}/{proj_path}.git"
        )

        try:
            project.remote_mirrors.create(
                {
                    "url": forgejo_push_url,
                    "enabled": True,
                    "auth_method": "password",
                    "user": FORGEJO_ADMIN_USER,
                    "password": FORGEJO_ADMIN_PASS,
                }
            )

            fg_print.info(
                f"Push mirror created on Gitlab for {proj_path}"
            )

        except Exception as e:
            detail = str(e)

            fg_print.error(
                f"Error creating push mirror on Gitlab "
                f"for {proj_path}: {detail}",
                f"Error creating push mirror on Gitlab "
                f"for {proj_path}: {detail}",
            )


def delete_to_forgejo(
    gitlab_projects: List[gitlab.v4.objects.Project],
) -> None:
    """Delete push mirrors from Gitlab to Forgejo"""

    fg_print.info("\nDeleting push mirrors from Gitlab")

    for project in gitlab_projects:
        proj_path = project.path_with_namespace

        fg_print.info(f"Project: {proj_path}")

        try:
            mirrors = project.remote_mirrors.list()

            for mirror in mirrors:
                project.remote_mirrors.delete(mirror.id)

                fg_print.info(
                    f"Push mirror deleted on Gitlab for {proj_path}"
                )

        except Exception as e:
            detail = str(e)

            fg_print.error(
                f"Error deleting push mirrors on Gitlab "
                f"for {proj_path}: {detail}",
                f"Error deleting push mirrors on Gitlab "
                f"for {proj_path}: {detail}",
            )


def to_gitlab(
    fg_api: PyforgejoApi,
    gitlab_projects: List[gitlab.v4.objects.Project],
) -> None:
    """Create push mirrors from Forgejo to Gitlab"""

    fg_print.info("\nMirroring repositories from Forgejo to Gitlab")

    for project in gitlab_projects:
        proj_path = project.path_with_namespace

        fg_print.info(f"Project: {proj_path}")

        path_parts = proj_path.split("/", 1)

        if len(path_parts) != 2:
            fg_print.error(
                f"Invalid repository path: {proj_path}"
            )
            continue

        owner, repo = path_parts

        list_of_mirrors = _list_forgejo_push_mirrors(fg_api=fg_api, owner=owner, repo=repo)
        if list_of_mirrors:
            mirror = next((mirror for mirror in list_of_mirrors
                          if mirror.remote_address == _build_gitlab_repo_url(owner, repo)),
                          None)
            if mirror is not None:
                fg_print.info(f"Push mirror already exists on Forgejo for {owner}/{repo}, skipping creation")
                continue

        success = _create_forgejo_push_mirror(fg_api=fg_api, owner=owner, repo=repo)
        # if not success:
        #     fg_print.error(f"Failed mirror for {owner}/{repo}")

def _build_gitlab_repo_url(owner: str, repo: str) -> str:
    if GITLAB_SYNC_CONNECTION_TYPE == "ssh":
        return f"git@{GITLAB_URL.replace('https://', '').replace('http://', '')}:{owner}/{repo}.git"
    else:
        return f"{GITLAB_URL}/{owner}/{repo}.git"

def delete_to_gitlab(
    fg_api: PyforgejoApi,
    gitlab_projects: List[gitlab.v4.objects.Project],
) -> None:
    """Delete push mirrors from Forgejo to Gitlab"""

    fg_print.info("\nDeleting push mirrors from Forgejo")

    for project in gitlab_projects:
        proj_path = project.path_with_namespace

        fg_print.info(f"Project: {proj_path}")

        path_parts = proj_path.split("/", 1)

        if len(path_parts) != 2:
            fg_print.error(
                f"Invalid repository path: {proj_path}"
            )
            continue

        owner, repo = path_parts

        mirrors = _list_forgejo_push_mirrors(fg_api=fg_api, owner=owner, repo=repo)

        gitlab_url = _build_gitlab_repo_url(owner, repo)
        for mirror in mirrors:
            if mirror.remote_address != gitlab_url:
                continue
            
            remote_name = mirror.remote_name

            if remote_name is None:
                continue

            _delete_forgejo_push_mirror(
                fg_api=fg_api,
                owner=owner,
                repo=repo,
                remote_name=remote_name,
            )


def main():
    """Main function"""

    _args = docopt(__doc__)
    args = {k.replace("--", ""): v for k, v in _args.items()}

    fg_print.print_color(
        fg_print.Bcolors.HEADER,
        "---=== Gitlab <-> Forgejo Push Mirror Management ===---",
    )

    fg_print.info(f"Version: {SCRIPT_VERSION}\n")

    #
    # GitLab
    #

    session = requests.Session()

    if (
        GITLAB_CLIENT_AUTH_CERT is not None
        and GITLAB_CLIENT_AUTH_KEY is not None
    ):
        session.cert = (
            GITLAB_CLIENT_AUTH_CERT,
            GITLAB_CLIENT_AUTH_KEY,
        )

    gl = gitlab.Gitlab(
        url=GITLAB_URL,
        private_token=GITLAB_TOKEN,
        session=session,
    )

    try:
        gl.auth()

    except gitlab.GitlabAuthenticationError:
        fg_print.error(
            "Failed to authenticate with Gitlab!"
        )
        os.sys.exit()

    fg_print.info(
        f"Connected to Gitlab, version: {gl.version()[0]}"
    )

    #
    # Forgejo
    #

    fg_api = _build_forgejo_api_client(FORGEJO_TOKEN)

    try:
        serverVersion = fg_api.miscellaneous.get_version()

    except Exception as e:
        detail = _get_exception_detail(e)

        fg_print.error(
            f"Failed to connect to Forgejo! {detail}"
        )

        os.sys.exit()

    fg_print.info(
        f"Connected to Forgejo, version: {serverVersion.version}"
    )

    #
    # Load projects
    #

    limit = int(args["limit"])

    if limit != 100000:
        projects = gl.projects.list(
            all=False,
            per_page=limit,
            page=1,
        )
    else:
        projects = gl.projects.list(get_all=True)

    fg_print.info(f"Found {len(projects)} projects")

    #
    # Execute actions
    #

    if args["create"]:

        fg_print.info("Creating mirrors")

        if args["to-forgejo"] or args["all"]:
            to_forgejo(projects)

        if args["to-gitlab"] or args["all"]:
            to_gitlab(fg_api, projects)

    elif args["delete"]:

        fg_print.info("Deleting mirrors")

        if args["to-forgejo"] or args["all"]:
            delete_to_forgejo(projects)

        if args["to-gitlab"] or args["all"]:
            delete_to_gitlab(fg_api, projects)

    else:
        fg_print.error(
            "Please specify --create or --delete"
        )
        os.sys.exit()

    #
    # Summary
    #

    err_count = fg_print.GLOBAL_ERROR_COUNT

    if err_count == 0:
        fg_print.success(
            "\nMirror management finished with no errors!"
        )
    else:
        fg_print.error(
            f"\nMirror management finished with "
            f"{err_count} errors!"
        )

        fg_print.info("Failed elements:")

        print(*fg_print.GLOBAL_ERROR_LIST, sep="\n")


if __name__ == "__main__":
    main()