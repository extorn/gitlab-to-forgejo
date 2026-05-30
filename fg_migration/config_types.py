
import configparser
from dataclasses import dataclass


@dataclass
class MigrationConfig:
    ADD_EMPTY_TEAMS:bool
    ADD_EMPTY_TEAMS_TO_REPOS:bool
    IS_FUZZY_TEAMS_ALLOWED:bool
    IS_FUZZY_USERS_ALLOWED:bool
    ALLOW_FUZZY_AUTH_DOWNGRADE:bool
    ALLOW_FUZZY_AUTH_UPGRADE:bool

    def __init__(self, config:configparser.RawConfigParser, section:str = "migrate"):
        self.ADD_EMPTY_TEAMS = config.getboolean(section, "add_empty_teams_to_organizations", fallback=False)
        self.ADD_EMPTY_TEAMS_TO_REPOS = config.getboolean(section, "add_empty_teams_to_repos", fallback=False)
        self.IS_FUZZY_TEAMS_ALLOWED = config.getboolean(section, "allow_fuzzy_teams", fallback=False)
        self.IS_FUZZY_USERS_ALLOWED = config.getboolean(section, "allow_fuzzy_users", fallback=False)
        self.ALLOW_FUZZY_AUTH_DOWNGRADE = config.getboolean(section, "allow_fuzzy_auth_downgrade", fallback=False)
        self.ALLOW_FUZZY_AUTH_UPGRADE = config.getboolean(section, "allow_fuzzy_auth_upgrade", fallback=False)

@dataclass
class ForgejoConfig:
    # This is the name that Forgejo assigns the initial Team for an organization with the role Owners
    FORGEJO_DEFAULT_OWNERS_TEAM_NAME="Owners"

    FORGEJO_CLIENT_AUTH_CERT : str | None
    FORGEJO_CLIENT_AUTH_KEY : str | None
    FORGEJO_URL : str
    FORGEJO_API_URL : str
    FORGEJO_TOKEN : str
    # Not used. The script uses a personal access token for authentication
    FORGEJO_USER : str | None
    FORGEJO_PASSWORD : str | None

    def __init__(self, config:configparser.RawConfigParser, section:str = "forgejo"):
        self.FORGEJO_CLIENT_AUTH_CERT = config.get(section, "forgejo_client_auth_cert", fallback=None)
        self.FORGEJO_CLIENT_AUTH_KEY = config.get(section, "forgejo_client_auth_key", fallback=None)
        self.FORGEJO_URL = config.get(section, "forgejo_url")
        self.FORGEJO_API_URL = f"{self.FORGEJO_URL}/api/v1"
        self.FORGEJO_TOKEN = config.get(section, "forgejo_token")
        # Not used. The script uses a personal access token for authentication
        self.FORGEJO_USER = config.get(section, "forgejo_admin_user")
        self.FORGEJO_PASSWORD = config.get(section, "forgejo_admin_pass")

@dataclass
class ForgejoMigrationConfig:
    
    ORG_TEAM_OWNERS_NAME : str
    ORG_TEAM_MAINTAINERS_NAME :str
    ORG_TEAM_DEVELOPERS_NAME : str
    ORG_TEAM_REPORTERS_NAME : str
    ORG_TEAM_GUESTS_NAME : str
    ORG_TEAM_OWNERS_DESCRIPTION : str
    ORG_TEAM_MAINTAINERS_DESCRIPTION : str
    ORG_TEAM_DEVELOPERS_DESCRIPTION : str
    ORG_TEAM_REPORTERS_DESCRIPTION : str
    ORG_TEAM_GUESTS_DESCRIPTION : str

    def __init__(self, config:configparser.RawConfigParser, section:str = "migrate.forgejo"):
        self.ORG_TEAM_OWNERS_NAME = ForgejoConfig.FORGEJO_DEFAULT_OWNERS_TEAM_NAME # MUST NOT change, hardcoded in Forgejo code. config.get("migrate", "org_team_owners_name", fallback="Owners")
        self.ORG_TEAM_MAINTAINERS_NAME = config.get(section, "org_team_maintainers_name", fallback="Maintainers")
        self.ORG_TEAM_DEVELOPERS_NAME = config.get(section, "org_team_developers_name", fallback="Developers")
        self.ORG_TEAM_REPORTERS_NAME = config.get(section, "org_team_reporters_name", fallback="Reporters")
        self.ORG_TEAM_GUESTS_NAME = config.get(section, "org_team_guests_name", fallback="Guests")
        self.ORG_TEAM_OWNERS_DESCRIPTION = config.get(section, "org_team_owners_description", fallback=self.ORG_TEAM_OWNERS_DESCRIPTION)
        self.ORG_TEAM_MAINTAINERS_DESCRIPTION = config.get(section, "org_team_maintainers_description", fallback=self.ORG_TEAM_MAINTAINERS_DESCRIPTION)
        self.ORG_TEAM_DEVELOPERS_DESCRIPTION = config.get(section, "org_team_developers_description", fallback=self.ORG_TEAM_DEVELOPERS_DESCRIPTION)
        self.ORG_TEAM_REPORTERS_DESCRIPTION = config.get(section, "org_team_reporters_description", fallback=self.ORG_TEAM_REPORTERS_DESCRIPTION)
        self.ORG_TEAM_GUESTS_DESCRIPTION = config.get(section, "org_team_guests_description", fallback=self.ORG_TEAM_GUESTS_DESCRIPTION)

@dataclass
class GitlabConfig:
    GITLAB_CLIENT_AUTH_CERT : str | None
    GITLAB_CLIENT_AUTH_KEY : str | None
    GITLAB_URL : str
    GITLAB_TOKEN : str | None
    GITLAB_ADMIN_USER : str | None
    GITLAB_ADMIN_PASS : str | None

    def __init__(self, config:configparser.RawConfigParser, section:str = "gitlab"):
        self.GITLAB_CLIENT_AUTH_CERT = config.get(section, "gitlab_client_auth_cert", fallback=None)
        self.GITLAB_CLIENT_AUTH_KEY = config.get(section, "gitlab_client_auth_key", fallback=None)
        self.GITLAB_URL = config.get(section, "gitlab_url")
        self.GITLAB_TOKEN = config.get(section, "gitlab_token", fallback=None)
        self.GITLAB_ADMIN_USER = config.get(section, "gitlab_admin_user", fallback=None)
        self.GITLAB_ADMIN_PASS = config.get(section, "gitlab_admin_pass", fallback=None)

@dataclass
class GitlabMigrationConfig:
    IGNORE_GITLAB_SYSTEM_USERS : bool
    IGNORED_GITLAB_SYSTEM_USERS : set[str]

    _DEFAULT_IGNORED_USERS : set[str] = {
        "GitLab-Admin-Bot",
        "ghost",
        "support-bot",
        "alert-bot",
        "GitLabDuo",
    }

    def __init__(self, config:configparser.RawConfigParser, section:str = "migrate.gitlab"):
        self.IGNORE_GITLAB_SYSTEM_USERS = config.getboolean(section, "ignore_gitlab_system_users", fallback=False)
        raw_users = config.get(section,"gitlab_system_users",fallback=",".join(self._DEFAULT_IGNORED_USERS),
        )
        self.IGNORED_GITLAB_SYSTEM_USERS: set[str] = {user.strip()
                                         for user in raw_users.split(",")
                                         if user.strip()
                                        }