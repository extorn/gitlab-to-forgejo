"""A series of classes involved in the interaction with the PyForgejo API"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
import os
import re
import time
from typing import Callable, TypeVar, Iterator, override
# Forgejo API imports:
from pyforgejo import PyforgejoApi, Team
from pyforgejo.core.api_error import ApiError
from requests import Session


from fg_migration.utils import fg_print
from fg_migration.core.config_types import ForgejoConfig
from fg_migration.utils.utils import diff_dataclasses, diff_dicts
from httpx import Client as HttpxClient, HTTPError

class ForgejoPermission(StrEnum):
    """Enum duplication of the PyForgeJoApi Union type TeamPermission"""
    OWNER = "owner"
    ADMIN = "admin"
    WRITE = "write"
    READ  = "read"
    NONE  = "none" # Note, this is included within TeamPermission, so
                   # added in case later permitted during create/update

class ForgejoApiBuilder:
    """A builder for the PyForgejoApi, configuring authentication etc in a central way"""
    config : ForgejoConfig

    def __init__(self, forgejo_config:ForgejoConfig):
        self.config = forgejo_config

    def build_forgejo_api_client(self, api_key: str | None = None) -> PyforgejoApi:
        """Build a Forgejo API Client using either the API key provided, or the default API key"""
        api_token : str
        if api_key is None:
            api_token = self.config.FORGEJO_API_TOKEN
        else:
            api_token = api_key
        return PyforgejoApi(base_url=self.config.FORGEJO_API_URL,
                            api_key=api_token,
                            httpx_client = self._build_httpx_client())


    def build_session(self, username:str, password:str) -> Session:
        """Build a raw requests session"""
        session = Session()
        session.auth = (username, password)
        if(self.config.FORGEJO_CLIENT_AUTH_CERT is not None
           and self.config.FORGEJO_CLIENT_AUTH_KEY is not None):
            cert_path = self.config.FORGEJO_CLIENT_AUTH_CERT
            key_path = self.config.FORGEJO_CLIENT_AUTH_KEY
            session.cert = (cert_path, key_path)
        return session


    def _build_httpx_client(self, timeout: float = 60,
                            follow_redirects: bool = True) -> HttpxClient:
        """Build a custom instance of the HttpxClient, adding support for
           client certificate authentication"""

        client = None
        if(self.config.FORGEJO_CLIENT_AUTH_CERT is not None
           and self.config.FORGEJO_CLIENT_AUTH_KEY is not None):
            cert_path = self.config.FORGEJO_CLIENT_AUTH_CERT
            key_path = self.config.FORGEJO_CLIENT_AUTH_KEY
            cert = (cert_path, key_path)
            client = HttpxClient(cert=cert, timeout=timeout,follow_redirects=follow_redirects)
        return client

    def test_forgejo_connection(self, fg_api:PyforgejoApi) -> bool:
        """Run an API call to ensure the connection was successful"""

        try:
            response = fg_api.miscellaneous.get_version()
        except (ApiError, HTTPError) as e:
            fg_print.error(f"Failed to connect to Forgejo! {e}")
            return False
        fg_ver = response.version

        fg_print.info(f"Connected to Forgejo, version: {fg_ver}")
        return True



@dataclass(frozen=True)
class ForgejoRepositoryRole():
    """A type to pass around a finite set of Roles used for access to repositories
       If the role has been auto created using fuzzy matching to an existing role
       the is_custom will be true"""
    id: str
    is_custom: bool = False


@dataclass
class ForgejoRolePermissionDefinition:
    """Maps a Forgejo role to a set of permissions on the Forgejo server"""
    role : ForgejoRepositoryRole
    can_create_org_repo:bool = False
    includes_all_repositories:bool = False
    permission : ForgejoPermission = ForgejoPermission.NONE
    # use of field here ensures new instance for every instance of the class
    units_map: dict[str,str] = field(default_factory=dict)

    def diff(self, other:ForgejoRolePermissionDefinition) -> str :
        """Provide an equality check against an-other role permission. Just
           the differences are shown which makes it easier to see what has changed"""
        return diff_dataclasses(self,other)

@dataclass
class ForgejoTeamDefinition:
    """A definition for a Forgejo team, which may be used to create new teams or compare
       with existing ones.
       Note that a team name is its ID, but it is only unique in a given organization.
       Technically two identically named teams could exist in separate organizations with
       different permissions
       This is not currently handled in the code, but it is something to be aware of."""
    name: str
    description: str
    permissions: ForgejoRolePermissionDefinition
    allow_empty: bool | None # Only None when built from an existing team

    @staticmethod
    def from_team(team:Team, role_builder:ForgejoTeamRoleBuilder,
                 require_exact:bool=False) -> ForgejoTeamDefinition:
        """Will find a team definition closest matching the team provided according
           to the rules in role_builder.
           If require_exact is true, then if none are found, one will be created"""

        if role_builder:
            role,_ = role_builder.get_role_matching_team_permission(team=team,
                                                               require_exact=require_exact)


            role_permissions = role_builder.get_role_permissions(role)

            # we don't cache these because teams are only unique in a given organization.
             # Allow empty is only used when deciding on creating new teams so any value is safe.
            return ForgejoTeamDefinition(name = team.name,
                                         description = team.description,
                                         permissions = role_permissions,
                                         allow_empty = None)

        raise ValueError("Role builder not available")

    def diff(self, other:ForgejoTeamDefinition) -> str :
        """Provide an equality check against an-other role permission. Just
           the differences are shown which makes it easier to see what has changed"""
        return diff_dataclasses(self,other)

class ForgejoTeamRoleBuilder:
    """Interface for a ForgejoTeamRole provider"""
    @abstractmethod
    @override
    def get_role_matching_permission(self, permission:ForgejoPermission) -> ForgejoRepositoryRole:
        """Retrieve the Forgejo role permissions applicable for this role"""

    @abstractmethod
    def get_role_matching_team_permission(self, team:Team,
                                     require_exact:bool=False) -> tuple[ForgejoRepositoryRole,bool]:
        """Retrieve the Forgejo role permissions applicable for this role
           Note; this is used only when retrieving existing teams from the Forgejo server at present
           @return tuple[role:ForgejoRepositoryRole,is_exact_match:bool]
        """

    @abstractmethod
    def get_role_permissions(self, role:ForgejoRepositoryRole) -> ForgejoRolePermissionDefinition:
        """Retrieve the Forgejo role permissions applicable for this role
           Note; this is used only when retrieving existing teams from the Forgejo server at present
        """


class ForgejoTeamRoleMapper(ForgejoTeamRoleBuilder):
    """An implementation of ForgejoTeamRoleBuilder that Provides Roles from a map of
       available options. Custom roles can be generated and will then be available in
       the cache for future requests"""

    role_definitions : dict[ForgejoRepositoryRole,ForgejoRolePermissionDefinition]
    custom_role_count: dict[ForgejoRepositoryRole, int] = {}
    CUSTOM_ROLE_PATTERN = re.compile(r"^Custom_(.+?)_(\d+)$")

    def __init__(self, role_definitions:dict[ForgejoRepositoryRole,
                                            ForgejoRolePermissionDefinition]):
        self.role_definitions = role_definitions



    @override
    def get_role_permissions(self, role:ForgejoRepositoryRole) -> ForgejoRolePermissionDefinition:
        #fg_print.debug(f"Selecting from roles : {set(self.role_definitions.keys())}")
        match= self.role_definitions.get(role)
        #fg_print.debug(f"match = {match}")
        return match



    @override
    def get_role_matching_permission(self, permission:ForgejoPermission) -> ForgejoRepositoryRole:
        for role, perm_def in self.role_definitions.items():
            # Exact match shortcut
            if perm_def.permission.value == permission:
                fg_print.debug(f"SUCCESS: Exact match for permission {permission}: {role}")
                return role
        raise ValueError(f"Missing role mapping for Forgejo Permission {permission}")


    @override
    def get_role_matching_team_permission(self, team:Team,
                                     require_exact:bool=False) -> tuple[ForgejoRepositoryRole,bool]:

        best_role = None
        best_perm_def = None
        best_score = float("-inf")
        debug_log = []

        for role, perm_def in self.role_definitions.items():

            # Exact match shortcut
            if (
                perm_def.permission.value == team.permission
                and perm_def.units_map == team.units_map
            ):
                fg_print.debug(f"SUCCESS: Exact match for team {team.name}: {role}")
                return role,True

            score = 0

            # Permission match is important
            if perm_def.permission.value == team.permission:
                score += 10

            # Compare unit permissions
            all_units = set(perm_def.units_map) | set(team.units_map)

            for unit in all_units:
                expected = perm_def.units_map.get(unit)
                actual = team.units_map.get(unit)

                if expected == actual:
                    score += 1
                else:
                    score -= 1

            debug_log.append(f"Role {role} scored {score} for team {team.name}")

            if score > best_score:
                best_score = score
                best_role = role
                best_perm_def = perm_def

        #best_definition = self.role_definitions[best_role]
        fg_print.debug("\n".join(debug_log))
        if team.permission != best_perm_def.permission:
            perm_diff_dict = {'permission':{'forgejo':team.permission,
                                            'closest':best_perm_def.permission.value}}
            perm_diff = f"\n{perm_diff_dict}"
        else:
            perm_diff = ""
        if team.units_map != best_perm_def.units_map:
            diff_dicts(first=team.units_map, second=best_perm_def.units_map,
                                first_heading="forgejo", second_heading="closest")
            units_diff = f"\n{perm_diff_dict}"
        else:
            units_diff = ""

        fg_print.warning(
            f"No exact role match found for existing Forejo team {team.name}. "
            f"Closest role is {best_role}, "
            f"{perm_diff}"
            f"{units_diff}"
        )

        role = best_role
        if require_exact:
            role = self._add_custom_forgejo_role(team=team, closest_existing_role=best_role)
            return role,True
        return role,False



    def _update_get_custom_role_count(self, role: ForgejoRepositoryRole | None) -> int:

        key = role if role is not None else ForgejoRepositoryRole(id = "UNKNOWN")

        self.custom_role_count[key] = (
            self.custom_role_count.get(key, 0) + 1
        )

        return self.custom_role_count[key]



    def _is_custom_role(self, role_id: str) -> bool:
        return bool(self.CUSTOM_ROLE_PATTERN.match(role_id))



    def _get_custom_role_base(self, role_id: str) -> str:
        match = self.CUSTOM_ROLE_PATTERN.match(role_id)
        return match.group(1) if match else role_id



    def _build_custom_role_id(self, base_name: str, num: int) -> str:
        return f"Custom_{base_name}_{num}"



    def _add_custom_forgejo_role(self, team: Team,
                                closest_existing_role: ForgejoRepositoryRole | None,
                                ) -> ForgejoRepositoryRole:
        """Based on the role provided, create and store a new role in the cache"""

        num = self._update_get_custom_role_count(role=closest_existing_role)
        base_name = ("Role"
                        if closest_existing_role is None
                        else self._get_custom_role_base(closest_existing_role.id)
                    )

        new_role_id = self._build_custom_role_id(base_name=base_name, num=num,)

        role = ForgejoRepositoryRole(new_role_id)

        self.role_definitions[role] = ForgejoRolePermissionDefinition(
            role=role,
            can_create_org_repo=team.can_create_org_repo,
            includes_all_repositories=team.includes_all_repositories,
            permission=ForgejoPermission(team.permission),
            units_map=dict(team.units_map),
        )

        return role

class IterativeFetchError(Exception):
    """Raised when the ApiPaginator fails to retrieve the next page of data for some reason"""


T = TypeVar("T")

class ApiPaginator:
    """Wraps the PyforgejoApi with pagination support where errors are logged"""
    fg_api:PyforgejoApi
    max_page_size:int
    items_type:str
    retrieval_detail:str

    def __init__(self, fg_api:PyforgejoApi, page_size:int=50,
                 items_type:str="Items", retrieval_detail:str=""):
        self.fg_api = fg_api
        self.max_page_size = page_size
        self.items_type = items_type
        self.retrieval_detail = retrieval_detail

    def iterate(self, fetch_page_from_api: Callable[[PyforgejoApi, int, int], list[T]],
        ) -> Iterator[T]:
        """Create the API pagination wrapped in an Iterator"""

        page_idx = 1
        try:
            while True:
                page_of_data : list
                for attempt in range(3):
                    try:
                        page_of_data = fetch_page_from_api(self.fg_api, page_idx,
                                                           self.max_page_size)
                        break
                    except TimeoutError:
                        if attempt == 2:
                            raise
                        time.sleep(2 ** attempt)
                yield from page_of_data
                page_idx += 1
                if len(page_of_data) < self.max_page_size:
                    # no more to load
                    break
        except Exception as e:
            detail = self._get_exception_detail(e)
            msg = f"Failed to retrieve existing {self.items_type} page[{page_idx}]" \
                  f"{self.retrieval_detail} {detail}"
            fg_print.error(msg)
            raise IterativeFetchError(msg) from e



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
