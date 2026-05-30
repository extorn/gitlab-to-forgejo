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
import configparser
import typing

from docopt import docopt
import requests
from httpx import Client as HttpxClient

import gitlab  # pip install python-gitlab
import gitlab.v4.objects
import pyforgejo  # pip install pyforgejo (https://github.com/h44z/pyforgejo)

from pyforgejo import PyforgejoApi

from fg_migration.canonical_types import MigrationSource
from fg_migration.config_types import ForgejoConfig, ForgejoMigrationConfig, GitlabConfig, GitlabMigrationConfig, MigrationConfig
from fg_migration.forgjo import ForgejoMigrator
from fg_migration.gitlab import GitlabMigrationSource
from fg_migration.migrator import Migrator

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
migration_config = MigrationConfig(config=config)
forgejo_config = ForgejoConfig(config=config)
migration_config_forgejo = ForgejoMigrationConfig(config=config)
gitlab_config = GitlabConfig(config=config)
migration_config_gitlab = GitlabMigrationConfig(config=config)

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
    if(gitlab_config.GITLAB_CLIENT_AUTH_CERT != None and gitlab_config.GITLAB_CLIENT_AUTH_KEY != None):
        cert_path = gitlab_config.GITLAB_CLIENT_AUTH_CERT
        key_path = gitlab_config.GITLAB_CLIENT_AUTH_KEY
        session.cert = (cert_path, key_path)
    # private token or personal token authentication
    gl = gitlab.Gitlab(url = gitlab_config.GITLAB_URL, private_token=gitlab_config.GITLAB_TOKEN, session=session)
    try:
        gl.auth()
    except gitlab.GitlabAuthenticationError:
        fg_print.error("Failed to authenticate with Gitlab! Check access token and client authentication settings in .migrate.ini")
        os.sys.exit()
    except Exception as e:
        fg_print.error(f"Failed to connect to Gitlab! {e}")
        os.sys.exit()
    assert isinstance(gl.user, gitlab.v4.objects.CurrentUser)
    fg_print.info(f"Connected to Gitlab, version: {gl.version()[0]}")

    fg = _build_forgejo_api_client(forgejo_config)
    try:
        response = fg.miscellaneous.get_version()
    except Exception as e:
        detail = ForgejoMigrator._get_exception_detail(e)
        fg_print.error(f"Failed to connect to Forgejo! {detail}")
        os.sys.exit()
    fg_ver = response.version
    
    fg_print.info(f"Connected to Forgejo, version: {fg_ver}")

    migration_source : MigrationSource = GitlabMigrationSource(gitlab_api=gl, gitlab_config=gitlab_config)

    migrator = Migrator(migration_config=migration_config, migration_source=migration_source, fg_api=ForgejoMigrator(fg_api=fg))

    # IMPORT System users
    if args["users"] or args["all"]:
        migrator.import_users()
    # IMPORT Organizations
    if args["groups"] or args["all"]:
         # Note, import_groups uses the gitlab projects object because they're intrinsically linked really.
        migrator.import_organizations()
    # IMPORT Repositories
    if args["projects"] or args["all"]:
        migrator.import_repos()
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

def _build_httpx_client(config: ForgejoConfig, timeout: typing.Optional[float]=60, follow_redirects: typing.Optional[bool] = True) -> HttpxClient:
    client = None
    if(config.FORGEJO_CLIENT_AUTH_CERT != None and config.FORGEJO_CLIENT_AUTH_KEY != None):
        cert_path = config.FORGEJO_CLIENT_AUTH_CERT
        key_path = config.FORGEJO_CLIENT_AUTH_KEY
        cert = (cert_path, key_path)
        client = HttpxClient(cert=cert, timeout=timeout,follow_redirects=follow_redirects)
    return client



def _build_forgejo_api_client(config: ForgejoConfig) -> pyforgejo.PyforgejoApi:
    return PyforgejoApi(base_url=config.FORGEJO_API_URL, api_key=config.forgejo_api_key, httpx_client = _build_httpx_client(config=config))



if __name__ == "__main__":
    main()
