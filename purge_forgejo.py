#!/usr/bin/env python3
#
"""
Usage: purge_forgejo.py [--orgs-repos] [--orgs] [--user-repos] [--users]
       purge_forgejo.py --help

Purge repositories and/or users from Forgejo.

Options
  -h, --help    Show this screen
  --orgs-repos  delete organizations repositories
  --orgs        delete organizations
  --user-repos  delete user repositories
  --users       delete users
  --purge       delete all data for the user
"""
import os
import configparser
import requests
from docopt import docopt
from click import confirm
from fg_migration import fg_print

#######################
# CONFIG SECTION START
#######################
if not os.path.exists(".migrate.ini"):
    fg_print.error("Please create .migrate.ini as explained in the README!")
    os.sys.exit()

config = configparser.RawConfigParser()
config.read(".migrate.ini")
GITLAB_URL = config.get("migrate", "gitlab_url")
GITLAB_TOKEN = config.get("migrate", "gitlab_token")
GITLAB_ADMIN_USER = config.get("migrate", "gitlab_admin_user")
GITLAB_ADMIN_PASS = config.get("migrate", "gitlab_admin_pass")
FORGEJO_URL = config.get("migrate", "forgejo_url")
FORGEJO_API_URL = f"{FORGEJO_URL}/api/v1"
FORGEJO_HOST = FORGEJO_URL.split("/")[-1]
FORGEJO_USER = config.get("migrate", "forgejo_admin_user")
FORGEJO_PASSWORD = config.get("migrate", "forgejo_admin_pass")
FORGEJO_TOKEN = config.get("migrate", "forgejo_token")
FORGEJO_PREFIX_URL = f"https://{FORGEJO_USER}:{FORGEJO_PASSWORD}@{FORGEJO_HOST}"
session = requests.Session()
session.auth = (FORGEJO_USER, FORGEJO_PASSWORD)
#######################
# CONFIG SECTION END
#######################


def ask_confirmation() -> None:
    """Ask for confirmation before proceeding"""
    fg_print.info("This script deletes your data. Use it with a grain of salt!")
    choice = confirm("Do you want continue?")
    if not choice:
        fg_print.info("OK. See you next time!")
        os.sys.exit()


def del_orgs_repos(page: int=1) -> None:
    """Delete all repositories in all organizations"""
    all_orgs = []
    url = f"{FORGEJO_API_URL}/orgs"
    while True:
        orgs_dict = session.get(url, params={'page': page}).json()
        org_names = [org["name"] for org in orgs_dict]
        page += 1
        if org_names == []:
            break
        all_orgs.extend(org_names)

    for org in all_orgs:
        all_orgs_repos = []
        page = 1
        url = f"{FORGEJO_API_URL}/orgs/{org}/repos"
        while True:
            orgs_repos_dict = session.get(url, params={'page': page}).json()
            org_repos = [repo["name"] for repo in orgs_repos_dict]
            page += 1
            if org_repos == []:
                break
            all_orgs_repos.extend(org_repos)
        for repo_name in all_orgs_repos:
            url = f"{FORGEJO_API_URL}/repos/{org}/{repo_name}"
            response: requests.Response = session.delete(url, timeout=20)
            if response.ok:
                fg_print.info(f"Repository {repo_name} deleted on Forgejo for {org}")
            else:
                fg_print.error(
                    f"Error deleting repository {repo_name} on Forgejo for {org}",
                    f"Error deleting repository {repo_name} for {org}",
                )


def del_orgs(page: int=1) -> None:
    """Delete all organizations"""
    all_orgs = []
    url = f"{FORGEJO_API_URL}/orgs"
    while True:
        orgs_dict = session.get(url, params={'page': page}).json()
        org_names = [org["name"] for org in orgs_dict]
        page += 1
        if org_names == []:
            break
        all_orgs.extend(org_names)
    for orgs in all_orgs:
        url = f"{FORGEJO_API_URL}/orgs/{orgs}"
        response: requests.Response = session.delete(url, timeout=20)
        if response.ok:
            fg_print.info(f"Organization {orgs} deleted on Forgejo")
        else:
            fg_print.error(
                f"Error deleting organization {orgs} on Forgejo",
                f"Error deleting organization {orgs}",
            )


def del_user_repos(page: int=1) -> None:
    """Delete all user repositories"""
    all_user_repos = []
    url = f"{FORGEJO_API_URL}/user/repos"
    while True:
        user_repos_dict = session.get(url, params={'page': page}).json()
        user_repos = [user_repo["full_name"] for user_repo in user_repos_dict]
        page += 1
        if user_repos == []:
            break
        all_user_repos.extend(user_repos)
    for repo in all_user_repos:
        url = f"{FORGEJO_API_URL}/repos/{repo}"
        response: requests.Response = session.delete(url, timeout=20)
        if response.ok:
            fg_print.info(f"Repository {repo} deleted on Forgejo")
        else:
            fg_print.error(
                f"Error deleting repository {repo} on Forgejo",
                f"Error deleting repository {repo}",
            )


def del_users(purge: str, page: int=1) -> None:
    """Delete all users"""
    all_users = []
    url = f"{FORGEJO_API_URL}/admin/users"
    while True:
        users_dict = session.get(url, params={'page': page}).json()
        user_names = [user["username"] for user in users_dict]
        page += 1
        if user_names == []:
            break
        all_users.extend(user_names)
    for user in all_users:
        url = f"{FORGEJO_API_URL}/admin/users/{user}"
        response: requests.Response = session.delete(url, params={'purge': purge}, timeout=20)
        if response.ok:
            fg_print.info(f"User {user} deleted on Forgejo")
        else:
            fg_print.error(
                f"Error deleting user {user} on Forgejo",
                f"Error deleting user {user}",
            )


if __name__ == "__main__":

    args = docopt(__doc__)
    if not any([args["--orgs-repos"], args["--orgs"], args["--user-repos"], args["--users"]]):
        fg_print.error("Please specify what to delete! You can use --help for more information.")
        os.sys.exit()

    ask_confirmation()

    if args["--orgs-repos"]:
        del_orgs_repos()
    if args["--user-repos"]:
        del_user_repos()
    if args["--orgs"]:
        del_orgs()
    if args["--users"]:
        PURGE_OPT = "true" if args["--purge"] else "false"
        del_users(PURGE_OPT)

    session.close()
    ERR_COUNT = fg_print.GLOBAL_ERROR_COUNT
    if ERR_COUNT == 0:
        fg_print.success("\nMigration finished with no errors!")
    else:
        fg_print.error(f"\nMigration finished with {ERR_COUNT} errors!")
        print("Failed elements:")
        print(*fg_print.GLOBAL_ERROR_LIST, sep="\n")
