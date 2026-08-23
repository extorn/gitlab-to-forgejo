#!/usr/bin/env python3
#
# pylint: disable=line-too-long
"""
Usage: create_push_mirrors.py [--debug] (--to-forgejo | --to-gitlab | --all) (--create | --delete)
       create_push_mirrors.py --help

Create push mirrors from GitLab to Forgejo and vice versa.

Options
  -h, --help     Show this screen
  --debug        extra detailed console logging
  --to-forgejo   create mirrors from GitLab to Forgejo
  --to-gitlab    create mirrors from Forgejo to GitLab
  --all          create mirrors in both directions
  --create       create mirrors
  --delete       delete mirrors
"""
# pylint: enable=line-too-long

import configparser
import os

from docopt import docopt

from fg_migration.adapters.gitlab_types import GitLabApiBuilder
from fg_migration.utils import fg_print
from fg_migration.core.config_types import ForgejoConfig, GitLabConfig
from fg_migration.adapters.forgejo_types import ForgejoApiBuilder
from fg_migration.services.push_mirror_creator import PushMirrorCreator

SCRIPT_VERSION = "0.2"


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
    forgejo_config = ForgejoConfig.from_config(config=config)
    gitlab_config = GitLabConfig.from_config(config=config)

    #######################
    # CONFIG SECTION END
    #######################

    args = docopt(__doc__)
    # control debug logging
    fg_print.IS_DEBUG = bool(args["--debug"])

    fg_print.print_color(
        fg_print.Bcolors.HEADER,
        "---=== GitLab <-> Forgejo Push Mirror Management ===---",
    )

    fg_print.info(f"Version: {SCRIPT_VERSION}\n")

    gl_api_builder = GitLabApiBuilder(gitlab_config)
    gl_api = gl_api_builder.build_gitlab_api_client()
    gl_conn_success = gl_api_builder.test_gitlab_connection(gl_api)

    fg_api_builder = ForgejoApiBuilder(forgejo_config=forgejo_config)
    fg_api = fg_api_builder.build_forgejo_api_client()
    fg_conn_success = fg_api_builder.test_forgejo_connection(fg_api=fg_api)

    if not (gl_conn_success and fg_conn_success):
        return 1


    #
    # Execute actions
    #

    pmc = PushMirrorCreator(fg_api=fg_api, gl_api=gl_api, forgejo_config=forgejo_config,
                            gitlab_config=gitlab_config)

    try:
        projects = pmc.load_gitlab_projects()

        if args["--create"]:

            fg_print.info("Creating mirrors")

            if args["--to-forgejo"] or args["--all"]:
                pmc.to_forgejo(projects)

            if args["--to-gitlab"] or args["--all"]:
                pmc.to_gitlab(projects)

        elif args["--delete"]:

            fg_print.info("Deleting mirrors")

            if args["--to-forgejo"] or args["--all"]:
                pmc.delete_to_forgejo(projects)

            if args["--to-gitlab"] or args["--all"]:
                pmc.delete_to_gitlab(projects)

        else:
            raise RuntimeError("unreachable")
    except RuntimeError as e:
        fg_print.error(str(e))
        return 1
    finally:
        pmc.close()
    #
    # Summary
    #

    err_count = fg_print.GLOBAL_ERROR_COUNT

    if err_count == 0:
        fg_print.success(
            "\nMirror management finished with no errors"
        )
    else:
        fg_print.error(
            f"\nMirror management finished with "
            f"{err_count} errors"
        )

        fg_print.info("Failed elements:")

        print(*fg_print.GLOBAL_ERROR_LIST, sep="\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
