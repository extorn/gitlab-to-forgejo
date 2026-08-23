#!/usr/bin/env python3
#
# imports projects, users, groups, issues, labels, milestones, keys
# and collaborators from GitLab to Forgejo
#
"""
Usage: migrate.py [--debug] [--users] [--groups] [--projects] [--membership] [--all] [--notify]
       migrate.py --help

Migration script to import users, groups, projects, and group/user membership
of projects from any Source System to Forgejo.

Options
  -h, --help    Show this screen
  --debug       show extra debug output
  --users       migrate users
  --groups      migrate groups
  --projects    migrate projects
  --membership  migrate project membership
  --all         migrate all
  --notify      send notification to users
"""
import os
import configparser

from docopt import docopt


from fg_migration.adapters.forgejo_types import ForgejoApiBuilder
from fg_migration.core.migration_source import SourceFactory
from fg_migration.core.config_types import (ForgejoConfig, MigrationConfig)
from fg_migration.adapters.destination_forgejo import ForgejoDestination
from fg_migration.services.migrator import Migrator

from fg_migration.utils import fg_print

SCRIPT_VERSION = "1.0.0"


def main() -> int:
    """Main function"""

    #######################
    # CONFIG SECTION START
    #######################
    if not os.path.exists(".migrate.ini"):
        fg_print.error("Please create .migrate.ini as explained in the README")
        return 1

    config = configparser.RawConfigParser()
    config.read(".migrate.ini")
    migration_config = MigrationConfig.from_config(config=config)
    forgejo_config = ForgejoConfig.from_config(config=config)

    #######################
    # CONFIG SECTION END
    #######################

    args = docopt(__doc__)
    # control debug logging
    if args["--debug"]:
        fg_print.IS_DEBUG = True

    fg_print.print_color(
        fg_print.Bcolors.HEADER, "---=== Migration to Forgejo ===---"
    )
    fg_print.info(f"Version: {SCRIPT_VERSION}\n")


    try:
        migration_source = SourceFactory.build_migration_source(config=config,
                                                                migration_config=migration_config)
    except ValueError as e:
        fg_print.error(f"{e}")
        return 1
    except ConnectionError:
        return 2

    fg_api_builder = ForgejoApiBuilder(forgejo_config=forgejo_config)
    fg_api = fg_api_builder.build_forgejo_api_client()
    fg_conn_success= fg_api_builder.test_forgejo_connection(fg_api=fg_api)

    if not fg_conn_success:
        return 1

    migration_dest : ForgejoDestination = ForgejoDestination(fg_api=fg_api,
                                                             forgejo_config=forgejo_config)
    migrator = Migrator(migration_config=migration_config,
                        migration_source=migration_source,
                        migration_dest=migration_dest,
                        fg_api_builder=fg_api_builder)

    run_users = args["--users"] or args["--all"]
    run_groups = args["--groups"] or args["--all"]
    run_projects = args["--projects"] or args["--all"]
    run_membership = args["--membership"] or args["--all"]

    # IMPORT NOTHING ?
    if not (run_users or run_groups or run_projects or run_membership):
        fg_print.info("")
        fg_print.warning("No migration option(s) selected, nothing to do")
        return 0

    try:
        # IMPORT System Users
        if run_users:
            notify=bool(args["--notify"])
            migrator.import_users(notify=notify)
        # IMPORT Organizations and Teams (Groups and their member Users)
        if run_groups:
            # Note, import_groups uses the gitlab projects object
            # because they're intrinsically linked really.
            migrator.import_organizations()
        # IMPORT Repositories (Projects) AND OR Collaborators (Memberships of Projects)
        if run_projects or run_membership:
            migrator.import_repos(import_repo_content=run_projects)
    except Exception as e:
        fg_print.error(str(e))
        return 1
    finally:
        migrator.close()

    fg_print.info("")
    if fg_print.GLOBAL_ERROR_COUNT == 0:
        fg_print.success("Migration finished with no errors")
    else:
        fg_print.error(f"Migration finished with {fg_print.GLOBAL_ERROR_COUNT} errors")
        fg_print.info("Failed elements:")
        print(*fg_print.GLOBAL_ERROR_LIST, sep="\n")
        return 1
    return 0



#
# Data loading helpers for Forgejo
#




if __name__ == "__main__":
    raise SystemExit(main())
