import argparse
# import os
# from pathlib import Path
# import re
# import sys
import textwrap

import re
import yaml
import enum
from typing import Any, Callable, Dict, Iterable, List, Optional
import os
from pathlib import Path
import shutil

from west import log
from west.commands import WestCommand
from west import manifest
from west.manifest import ManifestDataType
from west.manifest import ImportFlag
from west.manifest import manifest_path
from west.configuration import update_config
from west import util
from west.util import PathType
from west.app.main import WestArgumentParser
from west.app.main import WestApp

# from west.app.project import ForAll, Update
from west.app.project import Update
from west.app.project import _rev_type as rev_type

# from west.app.main import WestArgumentParser

class ManifestActionType(enum.Enum):
        NEW_DATA_PROJ = enum.auto()
        NEW_SOURCE_PROJ = enum.auto()
        NEW_OTHER_PROJ = enum.auto()
        CHANGE_PATH = enum.auto()
        CHANGE_URL = enum.auto()
        CHANGE_REVISION = enum.auto()
        CHANGE_GROUPS = enum.auto()
        CHANGE_MPV = enum.auto()
        CHANGE_COMMAND = enum.auto()
        CHANGE_TO_NESTED = enum.auto()

class BranchType(enum.Enum):
    DEVELOP = 0
    INTEGRATION = enum.auto()
    MAIN = enum.auto()


# Set the repository of ContentType.DATA type
# to be track parent tag (SOURCE_DATA) or merge from parent branch
class MergeType(enum.Enum):
    DATA = 0
    SOURCE_DATA = enum.auto()


class ContentType(enum.Enum):
    SOURCE = 0
    DATA = enum.auto()
    EXTERNAL = enum.auto()
    COMMANDS = enum.auto()
    ALL_PROJECTS = enum.auto()


def get_current_bts(project: manifest.Project):
    '''
    Return the current branch or tag or sha of the git repo
    '''
    log.dbg(f"get_current_bts() - project: {project}")
    bts = ""
    
    # 1. Check if repo is checkout to branch
    cp = project.git(f"branch --show-current",
                 capture_stdout=True, capture_stderr=True,
                 check=False)
    branch =  cp.stdout.decode('ascii').strip()
    log.dbg(f"get_current_bts() - current branch is: {branch}")

    # The branch is NULL - or empty, it might be that we should checkout tag
    if branch != None and len(branch) > 0:
        ret = branch
        bts = "br"
        log.dbg(f"get_current_bts() - found branch, return: {ret}, bts: {bts}")
        return ret, bts

    # 2. Check if repo is checkout to tag
    log.dbg(f"get_current_bts() - not in branch, try to find tag")
    cp = project.git(f"describe --tags HEAD",
                 capture_stdout=True, capture_stderr=True,
                 check=False)
    tag =  cp.stdout.decode('ascii').strip()
    log.dbg(f"get_current_bts() - current tag is: {tag}")
    if len(tag) > 0 and "fatal" not in tag:
        ret = tag
        bts = "tg"
        log.dbg(f"get_current_bts() - found tag, return: {ret}, bts: {bts}")
        return ret, bts
        
    
    # 3. Check if repo is checkout to tag
    log.dbg(f"get_current_bts() - not in tag, try to find sha")
    ret = str(project.sha("HEAD"))[0:6]
    bts = "sh"
    log.dbg(f"get_current_bts() - current sha is: {ret}, bts: {bts}")
    return ret, bts


def is_tag_branch_commit(project: manifest.Project, rev: str) -> str:
    """
    Check if the rev is "br_r", "br", "tg" or "cm", 
    and return respectively string.
    Otherwise return None
    """

    log.dbg(f"is_tag_branch_commit() - project name: {project.name}, rev: {rev}")

    # check if this is remote branch
    cp = project.git(f"show-ref --verify refs/remotes/origin/{rev}", 
                     check=False, capture_stdout=True, capture_stderr=True)
    cp_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
    if (len(cp_lines)):
        return "br_r"

    # first check for local branch
    cp = project.git(f"show-ref --verify refs/heads/{rev}", 
                     check=False, capture_stdout=True, capture_stderr=True)
    cp_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
    if (len(cp_lines)):
        return "br"

    # check if tag
    cp = project.git(f"show-ref --verify refs/tags/{rev}", 
                     check=False, capture_stdout=True, capture_stderr=True)
    cp_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
    if (len(cp_lines)):
        return "tg"

    # check if commit
    cp = project.git(f"cat-file -t {rev}", 
                     check=False, capture_stdout=True, capture_stderr=True)
    cp_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
    if (len(cp_lines)):
        return "cm"


    return None


def get_remote_branch_tag(project: manifest.Project):
    '''
    return string with all remote branches and tags
    '''
    log.dbg(f"get_remote_branch_tag() - project name: {project.name}")
    args = ["heads", "tags"]
    res_dic = {}
    # TODO: add 2 results, update code in clone depth and new project
    for arg in args:
        cp = project.git(f'ls-remote --{arg} -q', check=False, capture_stdout=True)
        cp_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
        cp__list = [line.split()[1] for line in cp_lines]
        res = ', '.join(cp__list)
        res_dic[arg] = res

    log.dbg(f"get_remote_branch_tag() - the branches of {project.name} are: {res_dic["heads"]}")
    log.dbg(f"get_remote_branch_tag() - the tags of {project.name} are: {res_dic["tags"]}")
    return res_dic["heads"], res_dic["tags"]



# TODO: check with tag and branch
def check_branch_ahead_remote(project: manifest.Project, branch: Optional[str] = None) -> int:
    log.dbg(f"check_branch_ahead_remote() - project: {project.name}, branch: {branch}")
    if branch == None:
        cp = project.git(f"branch --show-current",
                     capture_stdout=True, capture_stderr=True,
                     check=False)
        branch =  cp.stdout.decode('ascii').strip()
        log.dbg(f"check_branch_ahead_remote() - current branch is: {branch}")

    # The branch is NULL - or empty, it might be that we should checkout tag
    if branch == None or len(branch) == 0:
        return 0;
    
    cp = project.git(f"rev-list --count origin/{branch}..{branch}",
                     capture_stdout=True, capture_stderr=True,
                     check=False)
    ahead = int(cp.stdout.decode('ascii').strip())
    log.dbg(f"check_branch_ahead_remote() - in repo: {project.name}, the branch local branch: {branch} is ahead of remote branch: {ahead}")
    
    return ahead


def new_project(project: manifest.Project):
    ret = manifest.Project(project.name, 
                  project.url, 
                  project.revision, 
                  project.path,
                  submodules = project.submodules,
                  clone_depth = project.clone_depth,
                  west_commands = project.west_commands,
                  topdir= project.topdir, 
                  remote_name = project.remote_name,
                  groups = project.groups,
                  userdata = project.userdata)
    return ret


def add_project_2_manifest(project: manifest.Project, man: manifest.Manifest):
    if project.name not in man._projects_by_name:
        log.dbg(f"add_project_2_manifest() - project: {project.name} is not in _projects_by_name, append it")
        man._projects.append(project)
    else:
        log.wrn(f"add_project_2_manifest() - project: {project.name} already exist in _projects_by_name")
    
    man._projects_by_name.update({project.name: project})


def project_set_4_compare(man: manifest.Manifest):
    ''' Return set of projects for comparing between 2 manifests.
    The set contains tuples of:
    1. project name 
    2. project yaml, without the revision (exclude command project).
    '''
    log.dbg(f"project_set_4_compare: arguments: {locals()}\n")
    projects_list = list()
    log.dbg(f"man.projects length: {len(man.projects)}\n")
    
    for project in man.projects:
        log.dbg(f"  In project {project.name}")
        project_dict = project.as_dict()
        log.dbg(f"    project_dict: {project_dict}\n")
        # Remove revision
        rev = "revision"
        west_commands = 'west-commands'
        if rev in project_dict and west_commands not in project_dict:
            log.dbg(f"    Remove revision\n")
            del project_dict["revision"]
        project_pair = tuple((project.name, yaml.safe_dump(project_dict)))
        projects_list.append(project_pair)
    
    project_set = set(projects_list)
    return project_set


def mpv_branches(project: manifest.Project) -> list:
    '''
    Return the all branches which mpv created:
        1. proj__ver_dev
        2. proj__ver_integ
        3. proj__ver_main
    '''
    cp = project.git(['branch', '-r'],
                     capture_stdout=True, capture_stderr=True,
                     check=False)
    branchs = cp.stdout.decode('ascii').strip()
    log.dbg(f"branchs: {branchs}")
    branches = re.findall(r"(\S*__.*_(?:dev|integ|main))$", branchs, re.M)
    log.dbg(f"mpv_branches: The list of branches:\n{branches}")
    
    return branches


def branches_str(project: str, version: str):  # -> list[str, str, str]:
    '''
    Return list of 3 branches for project+version
        1. proj__ver_dev
        2. proj__ver_integ
        3. proj__ver_main
    '''
    # log.dbg("branches_str()")
    branches = []
    type_str = ["dev", "integ", "main"]
    for i in BranchType:
        # log.dbg(f"i: {i}, value: {i.value}")
        branch = "main"
        if (project is not None) and (version is not None):
            branch = project + "__" + version + "_" + type_str[i.value]
        # log.dbg(f"branch: {branch}")
        branches.append(branch)
    # log.dbg(f"branches_str() - branches: {branches}")
    return branches


def check_branch_exist(project: manifest.Project, branch_name: str, is_remote: bool) -> bool:
    # log.dbg(f"check_branch_exist(): arguments: {locals()}")

    # check if it tag:
    rtype = rev_type(project, branch_name)
    if rtype == "tag":
        return True
    
    remote_str = "origin/" if is_remote else ""
    cp = None
    if is_remote:
        cp = project.git(['branch', '-r', '-l', f"origin/{branch_name}"],
                         capture_stdout=True, capture_stderr=True,
                         check=False)
    else:
        cp = project.git(['branch', '-l', f"{branch_name}"],
                         capture_stdout=True, capture_stderr=True,
                         check=False)

    # log.dbg(f"cp.stdout: {cp.stdout}")
    branch_exist = True if cp.stdout else False
    # log.dbg(f"check_branch_exist() - {branch_name} exist: {branch_exist}, is remote: {is_remote}")
    return branch_exist


def get_remote_default_branch(project: manifest.Project) -> str:
    ret = None
    cp = project.git('remote show origin',
                     capture_stdout=True, capture_stderr=True,
                     check=False)
    default_branch = cp.stdout.decode('ascii').strip()
    log.dbg(f"default_branch: {default_branch}")
    m = re.search("HEAD branch: (.*)$", default_branch, re.M)
    log.dbg(f"m after search: {m}")
    if m is not None:
        log.dbg(f"groups in: {m.groups()}")
        log.dbg(f"group(1) in: {m.group(1)}")
        ret = m.group(1)

    log.dbg(f"default_branch after search: {default_branch}")

    log.dbg(f"type of ret: {type(ret)}")
    return ret


def fetch_proj_depth(project: manifest.Project, fetch_depth: str):
    '''
    fetch repo with specific depth
    '''
    log.dbg(f"fetch_proj_depth() - project: {project.name} fetch_depth: {fetch_depth}")

    # The output of git ls-remote is two columns: sha, ref
    # e.g.:
    # d377143716e7fda2400302c301ea84955789ba03	refs/heads/main
    # We need to take only the second word of each line
    
    # Find branches
    branches, tags = get_remote_branch_tag(project)
    log.dbg(f"the branches are: {branches}")
    log.dbg(f"the branches are: {tags}")

    cp = project.git(f'ls-remote --tags -q', check=False, capture_stdout=True)
    tags_lines = cp.stdout.decode('ascii', errors='ignore').strip(' "\n\r').splitlines()
    tags_list = [line.split()[1] for line in tags_lines]
    tags = ', '.join(tags_list)
    log.dbg(f"the tags are: {tags}")
    
    if f"{project.revision}" in branches:
        log.dbg(f"fetch remote branch {project.revision} with depth {fetch_depth}")
        project.git(f'fetch -f --depth {fetch_depth} -- {project.url} +refs/heads/{project.revision}:refs/remotes/origin/{project.revision}', check=True)
    elif f"{project.revision}" in tags:
        log.dbg(f"fetch remote tag {project.revision} with depth {fetch_depth}")
        project.git(f'fetch -f --depth {fetch_depth} --no-tags -- {project.url} +refs/tags/{project.revision}:refs/tags/{project.revision}', check=True)
    else:
        log.inf(f"depth: {fetch_depth}, the revision is sha: {project.revision} - already fetch by west update")
        log.dbg(f"The revision {project.revision} might be sha - do no fetch, because west update did it")


def dont_use_zephyr():
    log.dbg("Update configuration that we don't use Zephyr")
    update_config('zephyr', 'base', 'not-using-zephyr')


def filters_set_in_manifest(man: manifest.Manifest) -> set:
    log.dbg(f"In filters_set_in_manifest()")

    # Create set to be sure that no duplicate of filters exist
    filters = set()
    for project in man.projects:
        # log.dbg(f"Project {project.name} \ngroups: {project.groups}")
        # Use update, because groups is list
        filters.update(project.groups)

    log.dbg(f"filters_set_in_manifest() - filters in west manifest: {filters}")

    return filters


# Update the components that the user want to download
def update_filter_config(man: manifest.Manifest, args):
    log.dbg(f"UpdateFilterConfig(). args: {args}")
    filters_in_manifest = filters_set_in_manifest(man)

    filter_string = ""
    if (args.component is not None) and (len(args.component) > 0):
        for component in args.component:
            # In order to distinguish between RC and RCU
            if component in filters_in_manifest:
                filter_string += '+' + component + ','
            else:
                log.wrn(f"The filter {component} is not part of west.yml")
            log.dbg(f"Add component {component} to workspace")
        if len(filter_string) > 0:
            # Remove last ','
            filter_string = filter_string[:-1]
    else:
        log.dbg(f"No component was chosen, Enable all filters")
        for filt in filters_in_manifest:
            # In order to distinguish between RC and RCU
            filter_string += '+' + filt + ','
            log.dbg(f"Add component {filt} to workspace")
        filter_string = filter_string[:-1]

    log.dbg(f"update_filter_config() - filter_string: {filter_string}")
    update_config('manifest', 'group-filter', filter_string)


def update_filter_manifest(man: manifest.Manifest):
    filters_in_manifest = filters_set_in_manifest(man)

    filter_strings = []
    for filt in filters_in_manifest:
        filter_strings.append('-' + filt)

    man.group_filter = filter_strings
    log.dbg(f"update_filter_manifest() - man.group_filter: {man.group_filter}")


# Call to update command from west project
def buildin_update_command(topdir, manifest, projects_str: list = []):
    app = WestApp()
    log.inf(f"Call west update command for projects: {projects_str} - ")
    app.run(['-v','update', '-n'] + projects_str)

    # update_cmnd = Update()
    # parser = WestArgumentParser(
    #     prog='west', description='dummy parser to update command', add_help=False)
    # parser.add_argument('-v', '--verbose', default=0, action='count')
    # subparser_gen = parser.add_subparsers(metavar='<command>',dest='command')
    # update_cmnd.add_parser(subparser_gen)
    # argument = ['update', '-n'] + projects_str
    # update_args, unknown = parser.parse_known_args(argument)
    # log.inf(f"Call west update command for projects: {projects_str} - ")
    # update_cmnd.run(update_args, unknown, topdir, manifest)


class _SelfMpv:
    def __init__(self, merge_method: Optional[MergeType] = None):
        self.merge_method = merge_method or MergeType.SOURCE_DATA
        # self.project_name = "dummy-proj"

    def as_dict(self) -> Dict:
        ret: Dict = {}
        ret['merge-method'] = self.merge_method.name
        # ret['project-name'] = self.project_name

        return ret


class ProjectMpv:
    def __init__(self, name: str,
                 content: Optional[ContentType] = None):
        self.name = name
        self.content = content or ContentType.SOURCE

    def as_dict(self) -> Dict:
        ret: Dict = {'name': self.name, 'content': self.content.name}

        return ret


##########################################

class ManifestMpv:

    @staticmethod
    def from_file(**kwargs) -> 'ManifestMpv':
        # topdir = kwargs.get('topdir')

        # neither source_file nor topdir: search the filesystem
        # for the workspace and use its manifest.path.
        # topdir = util.west_topdir()
        # (mpath, mname) = manifest._mpath(topdir=topdir)

        start = Path.cwd()
        fall_back = True        
        topdir = Path(util.west_topdir(start=start,
                                       fall_back=fall_back)).resolve()
        mname = "mpv.yml"
        mpath = Path(manifest_path()).parent
        kwargs.update({
            'topdir': topdir,
            'source_file': os.path.join(topdir, mpath, mname),
            'manifest_path': mpath
        })

        return ManifestMpv(**kwargs)

    @staticmethod
    def from_data(source_data: ManifestDataType, **kwargs) -> 'ManifestMpv':
        kwargs.update({'source_data': source_data})
        return ManifestMpv(**kwargs)

    def __init__(self, source_file: Optional[PathType] = None,
                 source_data: Optional[ManifestDataType] = None,
                 manifest_path: Optional[PathType] = None,
                 topdir: Optional[PathType] = None,
                 **kwargs: Dict[str, Any]):

        self.path: Optional[str] = None
        '''Path to the file containing the manifest, or None if
        created from data rather than the file system.
        '''
        if source_file:
            source_file = Path(source_file)
            source_data = source_file.read_text()
            self.path = os.path.abspath(source_file)

        if isinstance(source_data, str):
            source_data = yaml.safe_load(source_data)

        assert isinstance(source_data, dict)

        self._projects: List[ProjectMpv] = []
        self.topdir: Optional[str] = None
        '''The west workspace's top level directory, or None.'''
        if topdir:
            self.topdir = os.fspath(topdir)

        if manifest_path:
            mpath: Optional[Path] = Path(manifest_path)
        else:
            mpath = None
        self._load(source_data['manifest'])

    def get_projects(self,
                     # any str name is also a PathType
                     project_ids: Iterable[PathType]) -> List[ProjectMpv]:
        projects = list(self.projects)
        ret: List[ProjectMpv] = []  # result list of resolved Projects
        
        # If no project_ids are specified, use all projects.
        if not project_ids:
            return projects

        # Otherwise, resolve each of the project_ids to a project,
        # returning the result or raising ValueError.
        for pid in project_ids:
            project: Optional[ProjectMpv] = None

            if isinstance(pid, str):
                project = self._projects_by_name.get(pid)

            ret.append(project)
        return ret

    def _as_dict_helper(
            self, pdict: Optional[Callable[[ProjectMpv], Dict]] = None) -> Dict:
        # pdict: returns a Project's dict representation.
        #        By default, it's Project.as_dict.
        if pdict is None:
            pdict = ProjectMpv.as_dict

        projects = list(self._projects)
        # del projects[MANIFEST_PROJECT_INDEX]
        project_dicts = [pdict(p) for p in projects]

        # This relies on insertion-ordered dictionaries for
        # predictability, which is a CPython 3.6 implementation detail
        # and Python 3.7+ guarantee.
        r: Dict[str, Any] = {}
        r['manifest'] = {}
        r['manifest']['projects'] = project_dicts
        r['manifest']['self'] = self._smpv.as_dict()

        # log.dbg(f"_as_dict_helper() - return manifest dictionary: \n{r}")

        return r

    def as_dict(self) -> Dict:
        '''Returns a dict representing self, fully resolved.

        The value is "resolved" in that the result is as if all
        projects had been defined in a single manifest without any
        import attributes.
        '''
        return self._as_dict_helper()

    def as_yaml(self, **kwargs) -> str:
        '''Returns a YAML representation for self, fully resolved.

        The value is "resolved" in that the result is as if all
        projects had been defined in a single manifest without any
        import attributes.

        :param kwargs: passed to yaml.safe_dump()
        '''
        return yaml.safe_dump(self.as_dict(), **kwargs)

    @property
    def projects(self) -> List[ProjectMpv]:
        return self._projects

    @property
    def self_mpv(self) -> _SelfMpv:
        return self._smpv

    def _load(self, man: Dict[str, Any]) -> None:

        self._smpv = self._load_self(man)

        self._projects = list()
        self._projects_by_name: Dict[str, ProjectMpv] = {}
        if 'projects' not in man:
            log.die(f"_load() - projects not in manifest")
            return

        for pd in man['projects']:
            # project = self._load_project(pd)
            name: str = pd['name']
            mt: str = pd.get('content')
            # log.dbg(f"merge-type: {mt}")
            content = ContentType[pd.get('content')]
            project = ProjectMpv(name, content)
            if project.name in self._projects_by_name:
                log.wrn(f"ManifestMpv._load() - Project {project.name} already exist, continue")
                continue
            self._projects.append(project)
            self._projects_by_name.update({name: project})

    def _load_self(self, manifest_data: Dict[str, Any]) -> _SelfMpv:
        smpv = _SelfMpv(MergeType.SOURCE_DATA)

        if 'self' not in manifest_data:
            log.dbg('_load_self() - self: unset')
            return smpv

        if 'merge-method' in manifest_data['self']:
            smpv.merge_method = MergeType[manifest_data['self']['merge-method']]

        # if 'project-name' in manifest_data['self']:
            # smpv.project_name = manifest_data['self']['project-name']

        return smpv

    # def _load_projects(self, manifest: Dict[str, Any]) -> None:

    # if 'projects' not in manifest:
    # return

    # # names = set()
    # for pd in manifest['projects']:
    # project = self._load_project(pd)
    # name = project.name
    # # names.add(name)
    # if project.name not in self._projects:
    # self._projects.append(project)

    # def _load_project(self, pd: Dict) -> ProjectMpv:
    # # pd = project data (dictionary with values parsed from the
    # # manifest)

    # name = pd['name']

    # # The name "manifest" cannot be used as a project name; it
    # ### if name == 'manifest':
    # ###    self._malformed('no project can be named "manifest"')

    # merge_type = ContentType[pd.get('merge-type')]

    # ret = ProjectMpv(name, merge_type)
    # return ret

    def add_project(self, project: ProjectMpv) -> bool:
        # Add the project to our map if we don't already know about it.
        # Return the result.

        if project.name not in self._projects:
            self._projects.append(project)
            return True
        else:
            return False

def mpv_from_yml(man: manifest.Manifest, branch: str) -> ManifestMpv:
    '''
    Read mpv.yml from branch, and return ManifestMpv 
    '''
    manifest_proj = man.get_projects(['manifest'])[0]
    mpv_str = manifest_proj.read_at("mpv.yml", branch).decode('utf-8')
    mpv_manifest = ManifestMpv.from_data(mpv_str, topdir=man.topdir)
    return mpv_manifest
 

def add_mpv_project_2_manifest(mpv_project: ProjectMpv, mpv_man: ManifestMpv):
    mpv_projects = mpv_man.projects
    mpv_names_list = [item.name for item in mpv_projects]
    
    if mpv_project.name in mpv_names_list:
        log.wrn(f"add_mpv_project_2_manifest() - mpv_project {mpv_project.name} already exist, remove it and recreate")
        index = mpv_names_list.index(mpv_project.name)
        log.dbg(f"add_mpv_project_2_manifest() - index: {index} - remove this index from mpv_projects")
        mpv_projects.pop(index)
        mpv_projects.insert
            
    
    mpv_projects.append(mpv_project)


# TODO: Should be remove after moving mpv to west.yml
def mpv_set_4_compare(mpv_manifest: ManifestMpv):
    ''' Return set of projects for comparing between 2 manifests in mpv.
    '''
    log.dbg(f"mpv_set_4_compare: arguments: {locals()}\n")
    projects_list = list()
    log.dbg(f"mpv_manifest.projects length: {len(mpv_manifest.projects)}\n")
    
    for project in mpv_manifest.projects:
        log.dbg(f"  In project {project.name}")
        project_dict = project.as_dict()
        log.dbg(f"    project_dict: {project_dict}\n")
        project_pair = tuple((project.name, yaml.safe_dump(project_dict)))
        projects_list.append(project_pair)
    
    project_set = set(projects_list)
    return project_set


################################################
# Update manifest with new west.yml for all branches of project
def update_manifest_new_branches(manifest_proj: manifest.Project,
                                 dev_manifest: manifest.Manifest,
                                 integ_manifest: manifest.Manifest,
                                 main_manifest: manifest.Manifest,
                                 mpv_manifest: ManifestMpv,
                                 projname: str,
                                 ver: str,
                                 manifest_path: str,
                                 mpv_command_name: str):
    log.dbg(f"update_manifest_new_branches(): arguments: {locals()}")

    manifest_proj.git(['fetch', '-p'])
    branches_names = branches_str(projname, ver)
    manifests_list = [(branches_names[BranchType.DEVELOP.value], dev_manifest)
        , (branches_names[BranchType.INTEGRATION.value], integ_manifest)
        , (branches_names[BranchType.MAIN.value], main_manifest)]
    # manifest_path = dev_manifest.path
    manifest_mpv_path = manifest_path.replace('west.yml', 'mpv.yml')
    log.dbg(
        f'update_manifest_new_branches(): path of manifest: {manifest_path} \npath of mpv manifest: {manifest_mpv_path}')
    default_branch = get_remote_default_branch(manifest_proj)
    log.dbg(f"default_branch: {default_branch}")
    for manifest_pair in manifests_list:
        branch_name, manifest_obj = manifest_pair
        log.inf(f"update_manifest_new_branches(): Update manifest for branch: {branch_name}")
        log.inf(f"update_manifest_new_branches(): Create new branch in manifest repo: {branch_name}")
        manifest_proj.git(['branch', f"{branch_name}", f"origin/{default_branch}"],
                          check=False)
        manifest_proj.git(['checkout', f"{branch_name}", '--'],
                          check=False)
        manifest_fd = open(manifest_path, "w")
        log.dbg(f"----------------------------------------")
        log.dbg(
            f"update_manifest_new_branches(): update west.yml, branch: {branch_name} yaml: \n {manifest_obj.as_yaml()}\n")
        manifest_fd.write(manifest_obj.as_yaml())
        manifest_fd.close()

        manifest_mpv_fd = open(manifest_mpv_path, "w")
        log.dbg(f"----------------------------------------")
        log.dbg(
            f"update_manifest_new_branches(): update mpv.yml, branch: {branch_name} yaml: \n {mpv_manifest.as_yaml()}")
        manifest_mpv_fd.write(mpv_manifest.as_yaml())
        manifest_mpv_fd.close()

        manifest_proj.git(['add', 'mpv.yml', 'west.yml'],
                          check=False)
        manifest_proj.git(['commit', '-m',
                           f'Set west.yml to use {branch_name} branches. Automatic update by running the command west {mpv_command_name}'],
                          check=False)
        manifest_proj.git(['push', '-u', 'origin', f"{branch_name}"],
                          check=False)


#############################################

def new_proj(source_branch: str, dest_proj: str, dest_ver: str, proj_type: str,
             self_manifest: manifest.Manifest, mpv_command_name: str):
    origin_branch = source_branch
    dest_branches = branches_str(dest_proj, dest_ver)
    log.dbg(f'origin_branch: {origin_branch}')
    log.dbg(f'dest_branches: {dest_branches}')

    # local_org_branch = org_branches[BranchType.MAIN.value]
    # remote_org_branch_full = f'origin/{org_branches[BranchType.MAIN.value]}'

    # if (org_proj == dest_proj):
    # log.die(f"The name of the origin project and the name of the new project are the same - exit")

    self_manifest.projects[0].git(['fetch', '-p'])
    log.dbg(f'Delete local branch - if exist')
    self_manifest.projects[0].git(
        ['branch', '-D', dest_branches[BranchType.DEVELOP.value],
         dest_branches[BranchType.INTEGRATION.value], dest_branches[BranchType.MAIN.value]],
        check=False)
    
    # Check type of revision, and update the string of remote branch accordingly
    remote_org_branch_full = f"origin/{origin_branch}"
    ver_type = is_tag_branch_commit(self_manifest.projects[0], origin_branch)
    log.dbg(f"ver_type: {ver_type}")
    if(ver_type == "tg" or ver_type == "cm"):
        remote_org_branch_full = origin_branch

    log.dbg(f"remote_origin_branch_full: {remote_org_branch_full}")

    west_str = self_manifest.projects[0].read_at("west.yml", remote_org_branch_full).decode('utf-8')
    log.dbg(f'west_str from branch {remote_org_branch_full}:\n{west_str}')

    origin_manifest = manifest.Manifest.from_data(west_str)
    dev_manifest = manifest.Manifest.from_data(west_str)
    integ_manifest = manifest.Manifest.from_data(west_str)
    main_manifest = manifest.Manifest.from_data(west_str)

    # Create new branches in all relevant repositories.
    i = 0
    manifest_len = len(self_manifest.projects)

    # List with all projects that should have branches even for data project
    mpv_manifest = ManifestMpv.from_file()

    while i < manifest_len:
        # for project in self_manifest.projects:
        project = self_manifest.projects[i]
        log.inf(f"")
        log.small_banner(f"project: {project.name}")
        log.dbg(
            f"Project {project.name} is active: {self_manifest.is_active(project)} and is cloned: {project.is_cloned()}, clone-depth: {project.clone_depth}")
        if (self_manifest.is_active(project) and
                project.is_cloned() and
                # project.name != 'mpv-git-west-commands' and
                project.name != 'manifest'):

            project_mpv = mpv_manifest.get_projects([project.name])[0]
            if project_mpv == None:
                log.wrn(f'project_mpv for project {project.name} is None - continue')
                i = i + 1
                continue
            
            log.dbg(f'project_mpv: {project_mpv}')
            content: ContentType = project_mpv.content

            # if the repository is west command project - continue
            if content == ContentType.COMMANDS:
                log.dbg(f'In command repository - continue')
                i = i + 1
                continue

            # If project is external or it common to all projects:
            # only update the manifests, but don't create new branches
            if content == ContentType.EXTERNAL or content == ContentType.ALL_PROJECTS:
                project_org = origin_manifest.projects[i]
                revision = project_org.revision
                log.dbg(f'In {content} repository {project.name}, update revision to {revision}')
                dev_manifest.projects[i].revision = revision
                integ_manifest.projects[i].revision = revision
                main_manifest.projects[i].revision = revision

            # if the type of the project is data, and repository is source_branch, take the SHA from original repository
            elif proj_type == 'd' and content == ContentType.SOURCE:
                project.git(['fetch', '-p'])
                log.dbg(f'get sha in project {project.name} in branch: {remote_org_branch_full}')
                # project_org.git(f'{remote_org_branch_full}^{{commit}}')
                sha = project.sha(remote_org_branch_full)
                log.dbg(f'sha of repository {project.name} is {sha} \nUpdate in all manifests')
                dev_manifest.projects[i].revision = sha
                integ_manifest.projects[i].revision = sha
                main_manifest.projects[i].revision = sha

            # If the repository is for data, or it is Source&Data project and it is source_branch repository -
            # create new branches:
            elif (content == ContentType.DATA or
                  (proj_type == 's' and content == ContentType.SOURCE)):
                project.git(['fetch', '-p'])

                # Validate that origin branch exist and 
                # destination branch doesn't exist
                org_exist = check_branch_exist(project, origin_branch, True)
                dest_exist = check_branch_exist(project, dest_branches[BranchType.DEVELOP.value], True)
                if not org_exist:
                    log.die(f"The origin branch {origin_branch} doesn't exist in project {project.name} - exit")

                if dest_exist == True:
                    log.die(
                        f"The destination branch {dest_branches[BranchType.DEVELOP.value]} already exist in project {project.name} - exit")

                # Create local branch
                # project.git(['branch', origin_branch],
                #           check=False)
                log.dbg(f'Delete local branch - if exist')
                project.git(
                    ['branch', '-D', dest_branches[BranchType.DEVELOP.value],
                     dest_branches[BranchType.INTEGRATION.value], dest_branches[BranchType.MAIN.value]],
                    check=False)

                log.inf(f"Create branch {dest_branches[BranchType.DEVELOP.value]} to project {project.name}")
                project.git(
                    ['branch', '--no-track', dest_branches[BranchType.DEVELOP.value], remote_org_branch_full],
                    check=False)

                log.inf(f"Create branch {dest_branches[BranchType.INTEGRATION.value]} to project {project.name}")
                project.git(['branch', '--no-track', dest_branches[BranchType.INTEGRATION.value],
                             remote_org_branch_full],
                            check=False)

                log.inf(f"Create branch {dest_branches[BranchType.MAIN.value]} to project {project.name}")
                project.git(
                    ['branch', '--no-track', dest_branches[BranchType.MAIN.value], remote_org_branch_full],
                    check=False)

                log.inf(f"Push all new branches to remote origin")
                project.git(['push', '-u', 'origin'
                                , dest_branches[BranchType.DEVELOP.value]
                                , dest_branches[BranchType.INTEGRATION.value]
                                , dest_branches[BranchType.MAIN.value]]
                            , check=False)

                # Update the revision in manifests
                dev_manifest.projects[i].revision = dest_branches[BranchType.DEVELOP.value]
                integ_manifest.projects[i].revision = dest_branches[BranchType.INTEGRATION.value]
                main_manifest.projects[i].revision = dest_branches[BranchType.MAIN.value]

            else:
                log.err(f"In project {project.name} - if we come to this point there is bug")

        i = i + 1
        # ############# Finish while loop

    log.dbg(f"--------------------------------------------------")
    log.dbg(f"dev_manifest :\n{dev_manifest}")
    log.dbg(f"--------------------------------------------------")
    log.dbg(f"integ_manifest :\n{integ_manifest}")
    log.dbg(f"--------------------------------------------------")
    log.dbg(f"main_manifest :\n{main_manifest}")
    log.dbg(f"--------------------------------------------------")

    log.small_banner(f"Update manifest project with the new branches")
    mpv_str = self_manifest.projects[0].read_at("mpv.yml", remote_org_branch_full).decode('utf-8')
    mpv_manifest = ManifestMpv.from_data(mpv_str, topdir=self_manifest.topdir)
    smpv = mpv_manifest.self_mpv
    if proj_type == 's':
        smpv.merge_method = MergeType.SOURCE_DATA
    else:
        smpv.merge_method = MergeType.DATA

    update_manifest_new_branches(self_manifest.projects[0],
                                 dev_manifest,
                                 integ_manifest,
                                 main_manifest,
                                 mpv_manifest,
                                 dest_proj,
                                 dest_ver,
                                 self_manifest.path,
                                 mpv_command_name)


class MpvUpdate(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-update',
            'Update the workspace with the components configure to download',
            textwrap.dedent('''\
                Update workspace with to the components that developer want to use.
                Add the components to use with -c flag.
                The components to choose can be find in west.yml - 
                in groups field of each project:

                If no component is chosen - ALL components will be use.
                By default, the command call fetch --prune in all repos,
                but it dosen't delete local branch that their upstream was gone.
                In order to delete the local branch that their upstream was gone,
                use --prune_all.
                
                The checkout branches will be as defined in the manifest file: west.yml''')
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        # filters_list = filters_lists_in_manifest(self.manifest)
        parser.add_argument('-c',
                            dest='component',
                            action='append',
                            default=[],
                            help='''Determine which components should be clone to workspace;
                                    Should be one of groups field from west.yml file. 
                                    May be given more than once''')

        parser.add_argument('--mr', '--manifest-rev', dest='manifest_rev',
                            help='''The version of manifest repository,
                            that contain the version of all the repos.
                            This version can also define with west init command.''')

        parser.add_argument('--prune-all', dest='prune_all', action='store_true', 
                            help='''Delete the local branch that their upstream was gone.''')
        
        parser.add_argument('--full-clone', dest='full_clone', action='store_true', 
                            help='''clone or fetch all commits from remote, 
                                    and ignore clone-depth field in west.yml.
                                    Can not define with --depth-1''')

        parser.add_argument('--depth-1', dest='depth_1', action='store_true', 
                            help='''clone or fetch all commits from remote, 
                                    and use depth=1 for **ALL** repos.
                                    Can not define with --full-clone''')

        return parser


    def do_run(self, args, unknown):
        log.banner(f"Update workspace: {util.west_topdir()}")
        log.dbg(f"args: {args}")

        # Update we don't Zephyr project
        dont_use_zephyr()

        # Update the components that the user want to download
        update_filter_config(self.manifest, args)

        if args.depth_1==True and args.full_clone==True:
            log.die("Can not define simultaneously --depth-1 and full-clone")

        log.banner(f"Update west.yml in manifest repository")
        log.dbg(f"args.manifest_rev: {args.manifest_rev}")
        manifest_proj = self.manifest.get_projects(['manifest'])[0]
        manifest_proj.git(['fetch', '-t', '-f', '--all'])

        # Set manifest project to the request revision
        if args.manifest_rev is not None:
            log.inf(f"Set manifest project to revision: {args.manifest_rev}")
            manifest_proj.git(['checkout', args.manifest_rev, "--"])
        else:
            log.dbg(f"args.manifest_rev is None: {args.manifest_rev}")


        # Check that we not ahead of remote branch.
        # If we ahead - our branch is more up-to-date than remote,
        # and the pull will not update our branch.
        # It that case - ask the user to push the branch, 
        # or to pull -f from remote.
        #
        # git rev-list --count origin/main..main
        ######################################################
        # TODO: Add unit test for this case
        ######################################################
        ahead = check_branch_ahead_remote(manifest_proj)
        if ahead > 0:
            log.die(f"The manifest repo ({manifest_proj.name}) is more update than your remote.\nFirst call git push from manifest repo, \nand than call mpv-update again.")

        log.dbg(f"call manifest_proj - git pull")
        # TODO: if in tag - don't do pull
        manifest_proj.git('pull', check=False)
        self.manifest = manifest.Manifest.from_file()

        # Call to west update build-in command
        # TODO: consider call west update with -n (--narrow),
        #       then the tags will not download
        buildin_update_command(self.topdir, self.manifest)

        log.banner(f"Checkout projects to the revision in manifest file")
        mpv_manifest = mpv_from_yml(self.manifest, "HEAD")
        for project in self.manifest.projects:
            log.banner(f"project: {project.name}")
            log.inf(f"project location: {project.abspath}")
            log.dbg(
                f"Project {project.name} is active: {self.manifest.is_active(project)} and is cloned: {project.is_cloned()}, clone-depth: {project.clone_depth}")
            project_mpv = mpv_manifest.get_projects([project.name])[0]

            content: ContentType = None
            if project_mpv == None:
                log.wrn(f'project_mpv for project {project.name} is None - continue')
            else:
                content = project_mpv.content

            if (self.manifest.is_active(project) and
                    project.is_cloned() and
                    content != ContentType.COMMANDS and
                    project.name != 'manifest'):

                # Do full clone only if clone depth is less then 1 or argument full-clone exist
                # Else - Use the already clone or fetch that west update did
                if (args.depth_1 == False and ((project.clone_depth == None or project.clone_depth < 1) or args.full_clone == True)):
                    log.inf(f"fetch all content")
                    project.git(['fetch', '--prune', '-t', '-f', '--all'], check=False)
                    if args.prune_all == True:
                        log.dbg(f"prune_all==True, remove local branch with gone upstream")
                        cp = project.git('branch --format="%(if:equals=[gone])%(upstream:track)%(then)%(refname:short)%(end)"',
                                        capture_stdout=True, capture_stderr=True,
                                        check=False)
                        branch2del = cp.stdout.decode('ascii').strip(' "\n\r').splitlines()
                        # Remove empty strings:
                        branch2del = list(filter(None, branch2del))
                        log.inf(f"list of branch to delete: \n{branch2del}")
                        if len(branch2del) > 0:
                            branch2del = ' '.join(branch2del)
                            log.inf(f"delete the local branch without upstream: \n{branch2del}")
                            project.git(f"branch -D {branch2del}",
                                check=False)
                    log.inf(f"git checkout to {project.revision}")
                    project.git(['checkout', project.revision, "--"])
                    cp = project.git(['branch', '--show-current'], capture_stdout=True, capture_stderr=True, check=False)
                    current_branch = cp.stdout.decode('ascii', errors='ignore').strip()
                    if len(current_branch) == 0:
                        log.dbg(f"Not in branch (call git fetch): result of 'git branch--show-current' is: {current_branch}")
                        project.git(['fetch'],
                                check=False)
                    else:
                        log.dbg(f"In branch  (call git pull): result of 'git branch--show-current' is: {current_branch}")
                        project.git(['pull'],
                                check=False)
                    
                elif args.depth_1 == True:
                    fetch_proj_depth(project, 1)
                else:
                    fetch_proj_depth(project, project.clone_depth)
            elif project.name == 'manifest':
                log.inf(f"Skipped manifest project")
            else:
                log.inf(f"Project {project.name} is not active or not cloned")


class MpvMerge(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-merge',
            'Merge between branches of mpv',
            textwrap.dedent('''\
                Merge between branches of mpv.
                
                There are 3 type of merge to repository:
                1. Regular git merge - if in DATA repository 
                   or in SOURCE repository and merge method of SOURCE_DATA
                2. sha merge; take the sha of parent branch - 
                   if in SOURCE repository and merge method of DATA 
                   and merge method of original branch is SOURCE_DATA
                3. Copy revision merge; take the revision name (should be tag or sha) into destination - 
                   if in EXTERNAL repository or ALL_PROJECTS repository 
                   or SOURCE repository in merge method of SOURCE_DATA or 
                   or SOURCE repository in merge method of DATA 
                   and merge method of original branch is DATA


                In regular git merge, the merge performed in each repo that has the origin branch and destination branch.
                The merge performed between main branch in the origin to dev branch in the destination.
                
                PAID ATTENTION: After running this command, and after take care to merge conflicts,
                                you should push all repo back to gitlab.
                                The mpv-merge DON'T push by itself.
                      
                Examples:
                    Merge from branch proj_1__4.2.9_dev (proj 1, version 4.2.9) to proj_2__4.2.9_dev (proj 2 version 4.2.9):
                    west mpv-merge proj_1__4.2.9_dev proj_2__4.2.9_dev

                    Merge from branch proj_1__4.3.1_dev (proj 1, version 4.3.1, dev) to
                    proj_1__4.3.1_integ (proj 1, version 4.3.1, integ), 
                    only to DATA type of repos, 
                    and add the option "-s ours" to repo foo_repo:
                    west mpv-merge -t DATA -o foo_repo "-s ours" proj_1__4.3.1_dev proj_1__4.3.1_integ
                    ''')

        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        parser.add_argument(
            'branch_from',
            help='''Name of the origin branch, to merge from it.''')

        parser.add_argument(
            'branch_to',
            help='''Name of the destination branch, to merge to it.''')

        parser.add_argument('-o', action='append', default=[], nargs=2,
                            metavar=('REPO_NAME_OR_TYPE', 'MERGE_OPTIONS'),
                            help='''Additional option to git merge.
                                    First argument of the flag is the repo name or type of repos (type is: 'DATA', 'SOURCE', 'EXTERNAL', 'ALL_PROJECTS'),
                                    Second argument of the flag is string of additional option to git merge.
                                    May be given more than once.
                                    If no type is declare, use git merge '--no-ff
                                    ''')

        parser.add_argument('-t', action='append', default=[],
                            metavar=('REPO_NAME_OR_TYPE'),
                            help='''The repo name or type of (type is: 'DATA', 'SOURCE', 'EXTERNAL', 'ALL_PROJECTS') 
                                    that should merge.
                                    May be given more than once.
                                    If no type is declare, make merge to all repos
                                    ''')


        return parser

    def do_run(self, args, unknown):
        log.banner(f"Merge from branch {args.branch_from} to branch {args.branch_to}")

        log.dbg(f"args: {args}")

        log.dbg(f"branch_from: {args.branch_from}")
        log.dbg(f"branch_to: {args.branch_to}")
        log.dbg(f"o: {args.o}")
        log.dbg(f"t: {args.t}")

        # log.dbg(f"type o: {type(args.o)}")
        # log.dbg(f"type t: {type(args.t)}")
       
        manifest_proj = self.manifest.projects[0]
        # local_org_branch = org_branches[BranchType.MAIN.value]
        # remote_org_branch_full
        remote_branch_from = f"origin/{args.branch_from}"
        # Check if branch_from is tag:
        r_type = rev_type(manifest_proj, args.branch_from)
        if r_type == 'tag':
            remote_branch_from = f"refs/tags/{args.branch_from}"

        # local_dest_branch = dest_branches[BranchType.DEVELOP.value]
        # remote_dest_branch_full = f"origin/{dest_branches[BranchType.DEVELOP.value]}"
        remote_branch_to = f"origin/{args.branch_to}"
        # internal_merge = False

        # Check if both branches are the same one
        if (args.branch_from == args.branch_to):
            log.die(f"Can't to merge from branch to itself (branch name: {args.branch_to})")

        # Check if to merge in the project itself
        log.dbg(f'fetch manifest project and checkout to {args.branch_to}')
        manifest_proj.git(['fetch', '-p'])
        manifest_proj.git(['fetch', '-t'])
        manifest_proj.git(['checkout', args.branch_to, "--"])

        # Check that we not ahead of remote branch.
        # If we ahead - our branch is more up-to-date than remote,
        # and the pull will not update our branch.
        # It that case - ask the user to push the branch, 
        # or to pull -f from remote.
        #
        # git rev-list --count origin/main..main
        ######################################################
        # TODO: Add unit test for this case
        ######################################################
        ahead = check_branch_ahead_remote(manifest_proj, args.branch_to)
        if ahead > 0:
            log.die(f"The manifest repo ({manifest_proj.name}) is more update than your remote.\nFirst call git push from manifest repo, \nand than call mpv-update again.")
        manifest_proj.git(['pull'])

        log.dbg(f'get mpv.yml from destination branch: {args.branch_to}')
        dest_mpv_str = manifest_proj.read_at("mpv.yml", args.branch_to).decode('utf-8')
        dest_mpv_manifest = ManifestMpv.from_data(dest_mpv_str, topdir=self.manifest.topdir)
        log.dbg(f'dest_mpv_manifest from branch {args.branch_to}: \n{dest_mpv_manifest.as_yaml()}\n')

        log.dbg(f'get west.yml from destination branch: {args.branch_to}')
        local_dest_west_str = manifest_proj.read_at("west.yml", args.branch_to).decode('utf-8')
        dest_manifest = manifest.Manifest.from_data(local_dest_west_str)
        log.dbg(f"dest_manifest BEFORE changes: \n{dest_manifest.as_yaml()}\n")

        log.dbg(f'get mpv.yml from parent branch: {remote_branch_from}')
        remote_org_mpv_str = manifest_proj.read_at("mpv.yml", remote_branch_from).decode('utf-8')
        org_mpv_manifest = ManifestMpv.from_data(remote_org_mpv_str, topdir=self.manifest.topdir)
        log.dbg(f'org_mpv_manifest from branch {remote_branch_from}: \n{org_mpv_manifest.as_yaml()}\n')

        log.dbg(f'get west.yml from parent branch: {remote_branch_from}')
        remote_org_west_str = manifest_proj.read_at("west.yml", remote_branch_from).decode('utf-8')
        org_manifest = manifest.Manifest.from_data(remote_org_west_str)
        log.dbg(f'org_manifest: \n{org_manifest.as_yaml()}\n')

        org_merge_method: MergeType = org_mpv_manifest.self_mpv.merge_method
        log.inf(f'merge method of : {org_merge_method}')

        merge_method: MergeType = dest_mpv_manifest.self_mpv.merge_method
        log.inf(f'merge method: {merge_method}')


        # Indicate if to update west.yml in destination
        manifest_change = False

        # There are 3 type of merge to repository:
        # 1. Regular git merge - if in DATA repository 
        #    or in SOURCE repository and merge method of SOURCE_DATA
        # 2. sha merge; take the sha of parent branch - 
        #    if in SOURCE repository and merge method of DATA 
        #    and merge method of original branch is SOURCE_DATA
        # 3. Copy revision merge; take the revision name (should be tag or sha) into destination - 
        #    if in EXTERNAL repository or ALL_PROJECTS repository 
        #    or SOURCE repository in merge method of SOURCE_DATA or 
        #    or SOURCE repository in merge method of DATA 
        #    and merge method of original branch is DATA
        #
        # Go over all repositories and merge them
        for project in self.manifest.projects:
            log.inf('')
            log.small_banner(f"project: {project.name}")
            if project.name == 'manifest':
                log.dbg('Take care to manifest later...')
                continue

            project_mpv = dest_mpv_manifest.get_projects([project.name])[0]
            if project_mpv == None:
                log.wrn(f'project_mpv for project {project.name} is None - continue')
                continue

            content = project_mpv.content
            log.dbg(
                f"Project {project.name} is active: {self.manifest.is_active(project)}, and is cloned: {project.is_cloned()}, mpv content = {content}, clone-depth: {project.clone_depth}")

            # check if argument -t filter this repo from merge:
            if len(args.t) and not (content.name in args.t or project.name in args.t):
                log.inf(f"The repo {project.name} is filter by -t flag, continue")
                continue

            merge_opt = ""
            if len(args.o) > 0:
                for repo_opt in args.o:
                    if content.name == repo_opt[0] or project.name == repo_opt[0]:
                        merge_opt += repo_opt[1] + " "
                        log.dbg(f"Add merge option: {repo_opt[1]} - for repo: {project.name}, repo_opt: {repo_opt}")
            log.dbg(f"repo: {project.name}, merge_opt: {merge_opt}")

            if (self.manifest.is_active(project) and
                    project.is_cloned() and
                    content != ContentType.COMMANDS):
                log.dbg(f"git fetch")
                project.git(['fetch', '-p'],
                            capture_stdout=True, capture_stderr=True,
                            check=False)

                local_org_exist = check_branch_exist(project, args.branch_from, False)
                log.dbg(f"{args.branch_from} exist: {local_org_exist}")

                remote_org_exist = check_branch_exist(project, args.branch_from, True)
                log.dbg(f"{remote_branch_from} exist: {remote_org_exist}")

                local_dest_exist = check_branch_exist(project, args.branch_to, False)
                log.dbg(f"{args.branch_to} exist: {local_dest_exist}")

                remote_dest_exist = check_branch_exist(project, args.branch_to, True)
                log.dbg(f"{remote_branch_to} exist: {remote_dest_exist}")

                dest_project = dest_manifest.get_projects([project.name])[0]
                org_project = org_manifest.get_projects([project.name])[0]

                # 1. Regular git merge - if in DATA repository 
                #    or in SOURCE repository and merge method of SOURCE_DATA
                if (content == ContentType.DATA or
                        content == ContentType.SOURCE and merge_method == MergeType.SOURCE_DATA):
                    log.inf(f'1. Regular git merge to repository: {project.name}')

                    if remote_org_exist == False or remote_dest_exist == False:
                        log.die(f'remote_org_exist ({remote_org_exist}) not exist'
                                f'\nor remote_dest_exist ({remote_dest_exist}) not exist'
                                '\nAbort!!!')

                    log.inf(f"checkout {args.branch_to}")
                    project.git(['checkout', args.branch_to, "--"], check=False)
                    if local_dest_exist:
                        log.dbg(f"pull {args.branch_to}")
                        project.git(['pull'], check=False)
                    # In regular repo
                    log.inf(f"merge branch {remote_branch_from} to checkout branch {args.branch_to}")
                    project.git(f"merge {merge_opt} --no-ff --no-edit {remote_branch_from}", check=False)

                # 2. sha merge; take the sha of parent branch - 
                #    if in SOURCE repository and merge method of DATA 
                #    and merge method of original branch is SOURCE_DATA
                ######################################################
                # TODO: Add unit test for case where in DATA merge method and original branch is also DATA merge method - take the SHA
                ######################################################
                elif (content == ContentType.SOURCE and
                      merge_method == MergeType.DATA and
                      org_merge_method == MergeType.SOURCE_DATA):
                    log.inf(f'2. sha merge to repository: {project.name}')

                    log.dbg(f'Take parent sha of branch: {remote_branch_from}')
                    sha = project.sha(remote_branch_from)
                    log.dbg(
                        f'the revision of project {project.name} in parent branch: {remote_branch_from} is: \n{sha}')
                    log.dbg(f'current revision in destination branch: {args.branch_to}: \n{dest_project.revision}')

                    log.dbg(f'Check revision of destination')
                    if dest_project.revision != sha:
                        log.dbg(f'Replace revision of project {project.name} with: \n{sha}')
                        dest_project.revision = sha
                        manifest_change = True
                        log.inf(f'Checkout project {project.name} to sha:\n{sha}')
                        project.git(['checkout', '-f', sha], check=False)
                    else:
                        log.dbg(f'Revision did not change, do not update sha')

                # 3. Copy revision merge; take the revision name (should be tag or sha) into destination - 
                #    if in EXTERNAL repository or ALL_PROJECTS repository 
                #    or SOURCE repository in merge method of SOURCE_DATA or 
                #    or SOURCE repository in merge method of DATA 
                #    and merge method of original branch is DATA
                else:
                    log.inf(f'3. Copy revision merge to repository: {project.name}')
                    log.dbg(
                        f'revision of parent: {org_project.revision} \nrevision of destination: {dest_project.revision}')

                    if org_project.revision != dest_project.revision:
                        log.dbg(f'Replace revision of project {project.name} with: \n{org_project.revision}')
                        dest_project.revision = org_project.revision
                        manifest_change = True
                        log.inf(f'Checkout project {project.name} to org_project.revision:\n{org_project.revision}')
                        project.git(['checkout', '-f', org_project.revision, "--"], check=False)
                    else:
                        log.dbg(f'Revision did not change, do not update revision (tag)')
        # ### Finish project loop ###
#
        # Update manifest if required
        if manifest_change == True:
            log.inf("")
            log.inf(f'manifest has updates, west.yml should be update in branch: {args.branch_to}')
            log.dbg(f"dest_manifest AFTER changes: \n{dest_manifest.as_yaml()}")
            manifest_fd = open(self.manifest.path, "w")
            manifest_fd.write(dest_manifest.as_yaml())
            manifest_fd.close()
            manifest_proj.git(['commit', '-a', '-m',
                               f"In mpv-merge west command: update west.yml from branch {remote_branch_from} to branche {args.branch_to}"],
                              check=False)
        else:
            log.dbg(f'manifest did not change. not change west.yml branch in {args.branch_to}')

        log.inf("")


class MpvNewProj(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-new-proj',
            'Create new project or new version with all required branches',
            textwrap.dedent('''\
                Create new project with all needed branches.
                The new branches create from the branch 
                that supplied in the first argument source_branch.
                
                There are two types of projects:
                1. Data project - Project that change only the data of the parent project (-t d). Default
                2. Source&Data project - Project that change the data and the source_branch code of the parent project (-t s)

                The first type (data project) create new branches for the new project
                only in repositories that set as DATA in mpv.yml file:
                Other repositories take the revision of the parent project, 
                EXTERNAL and ALL_PROJECTS repositories the parent tag, and SOURCE repositories the parent sha)
                
                The second type (Source&Data project) create new branches in all repositories,
                Except to tools repos that will take the revision of the parent project
                      
                Example:
                    Create new project with dummy_d name, that create from branch proj_1__4.2.9_dev.
                    The project is Data project, because the -t flag didn't define:
                    west mpv-new-proj proj_1__4.2.9_dev dummy_d 4.2.9

                    Create new project with dummy_s name, that create from proj_1__4.2.9_main.
                    The project is Source&Data project, according to the "-t s":
                    west mpv-new-proj -t s proj_1__4.2.9_main dummy_s 4.2.9

                    Create new version from dummy_s:4.2.9 project to dummy_s__100.9.9_main.
                    The project is Source&Data project, according to the "-t s":
                    west mpv-new-proj -t s dummy_s__100.9.9_main dummy_s 100.9.9
                    ''')

        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        parser.add_argument(
            'source_branch',
            help='''Name of the origin project. Should be branch/commit/tag.''')

        # parser.add_argument(
            # 'org_ver',
            # help='''Name of the origin version.''')

        parser.add_argument(
            'dest_proj',
            help='''Name of the destination project.''')

        parser.add_argument(
            'dest_ver',
            help='''Name of the destination version.''')

        parser.add_argument('-t',
                            choices=['d', 's'],
                            dest='proj_type',
                            default='d',
                            help='''The type of the project, d Data project and s to Source&Data project''')
        return parser

    def do_run(self, args, unknown):
        log.banner(
            f'Create new project {args.dest_proj}:{args.dest_ver} from branch {args.source_branch},'
            f'Project type: {args.proj_type}')

        log.dbg(f"args: {args}")

        new_proj(args.source_branch, args.dest_proj, args.dest_ver, args.proj_type,
                 self.manifest, 'mpv-new-proj')


# Debug the command mpv-new-proj
# west -v mpv-new-proj proj_1 4.2.9 dummy_d
#
# Delete all branches: local and remote
# west forall -c "git push -d origin dummy_d__4.2.9_dev dummy_d__4.2.9_integ dummy_d__4.2.9_main" ; west forall -c "git branch  -D  dummy_d__4.2.9_dev dummy_d__4.2.9_integ dummy_d__4.2.9_main" ; git push -d origin dummy_d__4.2.9_dev dummy_d__4.2.9_integ dummy_d__4.2.9_main ; git branch  -D  dummy_d__4.2.9_dev dummy_d__4.2.9_integ dummy_d__4.2.9_main


# Debug the command mpv-new-proj
# west -v mpv-new-proj -t s proj_1 4.2.9 dummy_s
#
# Delete all production of the command
# west forall -c "git push -d origin dummy_s__4.2.9_dev dummy_s__4.2.9_integ dummy_s__4.2.9_main" ; west forall -c "git branch  -D  dummy_s__4.2.9_dev dummy_s__4.2.9_integ dummy_s__4.2.9_main" ; git push -d origin dummy_s__4.2.9_dev dummy_s__4.2.9_integ dummy_s__4.2.9_main ; git branch  -D  dummy_s__4.2.9_dev dummy_s__4.2.9_integ dummy_s__4.2.9_main

# cd D:\snap\146
# python delete_branches.py *************** 1929 dummy_d__4.2.9_dev
# python delete_branches.py *************** 1929 dummy_d__4.2.9_integ
# python delete_branches.py *************** 1929 dummy_d__4.2.9_main
# python delete_branches.py *************** 1929 dummy_d__4.3.0_dev
# python delete_branches.py *************** 1929 dummy_d__4.3.0_integ
# python delete_branches.py *************** 1929 dummy_d__4.3.0_main


class MpvTag(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-tag',
            'Create tags with the same name to all projects, and create west.yml with the new tags',
            textwrap.dedent('''\
                Create new tag in each repository.
                The tag name consist prefix of the current branch name and 
                continue with user specific string.
                In the end of the command execution, all repositories that are not tools,
                will have a new tag, and finally a new west.yml with the all new tags will be created.
                This west.yml will also save in new tag.
                
                BE CAREFUL: If the request tag name exist - it will be REPLACE.
                      
                Example:
                west mpv-tag -m "message added to tag" "test-tag"
                ''')

        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        parser.add_argument(
            'postfix',
            help='''End of the tag name.''')

        parser.add_argument('-m', dest='message',
                            help='''Message for tag. Will be added to all new tags''')

        return parser

    def do_run(self, args, unknown):
        log.banner(
            f"Create new tag that end with {args.postfix}, with message: {args.message}")

        log.dbg(f"args: {args}")

        manifest_proj = self.manifest.get_projects(['manifest'])[0]
        log.dbg(f"Update manifest (git pull)")
        manifest_proj.git('pull', check=False)

        # Call to west update build-in command
        ws_rev, bts = get_current_bts(manifest_proj)
        log.dbg(f"current branch/commit/tag of manifest: {ws_rev}, type of bts: {bts}")
        
        tag_full = "mpv-tag_" + bts + "-" + ws_rev + "__" + args.postfix
        log.inf(f"tag name: {tag_full}")

        log.inf(f"Call mpv-update for current revision: {ws_rev}")
        buildin_update_command(self.topdir, self.manifest)

        west_str = manifest_proj.read_at("west.yml", "HEAD").decode('utf-8')
        manifest_update = manifest.Manifest.from_file()
        
        message = ""
        if args.message == None or len(args.message) == 0:
            message = "NO USER MESSAGE"
        else:
            message = f"Create by mpv-tag command \nUser message: " + args.message
        log.dbg(f"tag message: {message}")

        # manifest_proj = self.manifest.get_projects(['manifest'])[0]
        # mpv_str = manifest_proj.read_at("mpv.yml", "HEAD").decode('utf-8')
        # mpv_manifest = ManifestMpv.from_data(mpv_str, topdir=self.manifest.topdir)
        mpv_manifest = mpv_from_yml(self.manifest, "HEAD")
        manifest_len = len(self.manifest.projects)
        i = 0

        while (i < manifest_len):
            # for project in self.manifest.projects:
            project = self.manifest.projects[i]
            if project.name == "manifest":
                log.dbg(f"manifest project - will take care later, continue")
                i = i + 1
                continue
            
            mpv_proj = mpv_manifest.get_projects([project.name])[0]
            if mpv_proj == None:
                log.wrn(f'mpv_proj for project {project.name} is None - continue')
                i = i + 1
                continue
            
            log.dbg(f"project: {project.name}, mpv_proj: {mpv_proj.name}")

            log.inf('')
            log.small_banner(f"Project {project.name}:")
            if self.manifest.is_active(project) and project.is_cloned():
                if mpv_proj.content != ContentType.COMMANDS and mpv_proj.content != ContentType.EXTERNAL:

                    # check current branch name
                    # git branch --show-current
                    cp = project.git(['branch', '--show-current'],
                                     capture_stdout=True, capture_stderr=True,
                                     check=False)
                    current_branch = cp.stdout.decode('ascii', errors='ignore').strip()
                    log.dbg(f"in project: {project.name}, current_branch: current_branch")
                    log.inf(f"repo: {project.name}, create tag: {tag_full}")
                    project.git(['tag', '-f', '-a', tag_full, '-m', message],
                                check=False)
                    project.git(['push', 'origin', tag_full, '--force'],
                                check=False)
                    manifest_update.projects[i].revision = tag_full
                else:
                    log.dbg(f"Project {project.name} is infrastructure project - don't create specific tag")
            else:
                log.inf(f"Project {project.name} is not active or not cloned")
            i = i + 1

        
        manifest_fd = open(self.manifest.path, "w+")
        manifest_fd.seek(0)
        log.dbg(f"west.yml after open it with w+: \n{manifest_fd.read()}")
#         manifest_fd.seek(0)
#        manifest_fd.truncate()
        log.dbg(f"----------------------------------------")
        log.dbg(f"mpv-tag - write new west.yml: \n{manifest_update.as_yaml()}")
        manifest_fd.write(manifest_update.as_yaml())
        manifest_fd.seek(0)
        log.dbg(f"west.yml after writing it it with w+: \n{manifest_fd.read()}")
#        manifest_fd.seek(0)
        manifest_fd.close()

        manifest_proj.git(['commit', '-a', '-m',
                           f"mpv-tag - set west.yml with tag {tag_full}"],
                          check=False)
        log.inf(f"tag project {manifest_proj.name} with tag: {tag_full}")
        manifest_proj.git(['tag', '-f', '-a', tag_full, '-m', message],
                          check=False)
        if bts == "br":
            log.inf(f"Create new commit with the previous west.yml")
            manifest_fd = open(self.manifest.path, "w+")
            # manifest_fd.seek(0)
            # manifest_fd.truncate()
            manifest_fd.seek(0)
            log.dbg(f"previous branch, west.yml after open it with w+: \n{manifest_fd.read()}")
            log.dbg(f"----------------------------------------")
            log.dbg(f"mpv-tag - write new west.yml: \n{manifest_update.as_yaml()}")
            manifest_fd.write(west_str)
#           manifest_fd.seek(0)
            manifest_fd.seek(0)
            log.dbg(f"previous branch, west.yml after writing it it with w+: \n{manifest_fd.read()}")
            manifest_fd.close()
            manifest_proj.git(['commit', '-a', '-m',
                               f"mpv-tag - return to previous west.yml, before create the tag: {tag_full}"],
                              check=False)

        log.inf(f"Push tag {tag_full}, for project {manifest_proj.name}")
        manifest_proj.git(['push', 'origin', tag_full, '--force'],
                          check=False)
        manifest_proj.git(['push'],
                          check=False)

        manifest_proj.git(f'checkout {tag_full}',
                          check=False)


# Debug the command mpv-tag
# west -v mpv-tag -m "message added to tag" "test-tag"
#
# Delete all production of the command
# west forall -c "git push -d origin  proj_1__4.2.9_dev__test-tag" ; west forall -c "git tag -d proj_1__4.2.9_dev__test-tag"


##########################################


class MpvInit(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-init',
            'Initialize new project from scratch',
            textwrap.dedent('''Initialize new project from scratch.
                In the repository with west.yml file should be:
                1. branch with name main 
                2. west.yml file with all repositories that ara part of the project
                3. (Should move to west.yml) mpv.yml file
                
                The command create 3 initial branches for first version:
                1. <project-name>__<first-version>_dev
                2. <project-name>__<first-version>_integ
                3. <project-name>__<first-version>_main
                
                The <project-name> and the <first-version> are arguments of the command.
                The merge-method of the first version must be SOURCE_DATA.
                
                Example:
                west mpv-init proj_1 1.0.0
                ''')
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        parser.add_argument(
            'project_name',
            help='''String of the first project name for the project.''')

        parser.add_argument(
            'first_version',
            help='''String of the first version for the project.''')

        return parser

    def do_run(self, args, _):
        # 1. Update all repositories (west mpv-update)
        log.banner("1. Call to mpv-update")
        mpv_update_cmnd = MpvUpdate()
        update_cmnd_parser = argparse.ArgumentParser(description='dummy parser to mpv-update command')
        update_cmnd_parser.add_argument('-v', '--verbose', default=0, action='count')
        update_cmnd_parser.add_argument('--full-clone', dest='full_clone', action='store_true')
        update_cmnd_parser.verbose = args.verbose
        subparser_gen = update_cmnd_parser.add_subparsers(metavar='<command>', dest='command')
        mpv_update_cmnd.add_parser(subparser_gen)
        update_args = update_cmnd_parser.parse_args(['mpv-update', '--full-clone'])
        # log.dbg(f"unknown: {unknown}")
        log.inf("Call west mpv-update command:")
        mpv_update_cmnd.run(update_args, None, self.topdir, self.manifest)

        # 2. Create branches from the version exist in west.yml
        log.banner("2. Create new branches to project")
        # mpv_main_str = self.manifest.projects[0].read_at("mpv.yml", 'main').decode('utf-8')
        # log.dbg(f"ManifestMpv of main: \n{mpv_main_str}")
        # mpv_main_manifest = ManifestMpv.from_data(mpv_main_str)
        # project_name = mpv_main_manifest.self_mpv.project_name
        # log.dbg(f"project_name (from mpv.yml): {project_name}")
        new_proj("main", args.project_name, args.first_version, 's',
                 self.manifest, 'mpv-init')


### To test:
# west -v mpv-init 1.0.0

### To delete test production
# west forall -c "git checkout main"  
# west forall -c "git branch -D mpv-test__1.0.0_dev mpv-test__1.0.0_integ mpv-test__1.0.0_main"
# west forall -c "git push -d origin mpv-test__1.0.0_dev mpv-test__1.0.0_integ mpv-test__1.0.0_main"  

#################################################################\


class MpvManifest(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-manifest',
            'Update the manifest (west.yml) with new one',
            textwrap.dedent('''Update the manifest (west.yml and mpv.yml).
            The command receive a new folder with update west.yml and mpv.yml,
            and compare the current manifest files with the new ones.
            All changes between the old and new manifests are update.
            
            NOTICE: The current manifests are taken from ***default branch*** (usually main or master).
            
            The command assume that the origin/main branch is update 
            with the current west.yml and mpv.yml .
            
            Example:
            To update the manifests with new files exist in folder C:\\temp\\mpv-test-git-manager\\temp WITH DRY RUN:
            west -v mpv-manifest --dr "C:\\temp\\mpv-test-git-manager\\temp"

            To update the manifests with new files exist in folder C:\\temp\\mpv-test-git-manager\\temp:
            west -v mpv-manifest "C:\\temp\\mpv-test-git-manager\\temp"
            ''')
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        # Remember to update west-completion.bash if you add or remove
        # flags
        parser.add_argument('--dr', '--dry-run', action='store_true',
                            help='''Semmary what is going to add,
                            and what is going to be delete from the workspace''')

        parser.add_argument(
            'manifes_folder',
            help='''Folder with new manifest files (west.yml and mpv.yml).''')

        return parser



    def do_run(self, args, unknown):
        log.banner(f'Update manifest from {args.manifes_folder}')
        log.dbg(f"args: {args}")

        # TODO: Call fetch --prune for all projects to remove deleted remote branches
        

        # 1. Read the new manifests and the old manifests (validate that is OK)
        manifes_folder = Path(args.manifes_folder)

        # 1.1 Get new west
        new_west_filename = manifes_folder.joinpath("west.yml")
        log.dbg(f'get west.yml from file: {new_west_filename}')
        new_west_str = new_west_filename.read_text()
        new_west_manifest = manifest.Manifest.from_data(new_west_str, import_flags=ImportFlag.IGNORE)
        log.dbg(f"new_west_manifest:\n{new_west_manifest.as_yaml()}")
        # log.dbg(f"new_west_manifest from file {new_west_filename}: \n{new_west_manifest.as_yaml()}\n")
        new_west_projects_set = project_set_4_compare(new_west_manifest)
        log.dbg(f"new_west_projects_set: {new_west_projects_set}\n")
        new_projects_names_in_west = set(proj[0] for proj in new_west_projects_set)
        log.dbg(f"new_projects_names_in_west: {new_projects_names_in_west}\n")

        # 1.2 Get new mpv
        new_mpv_filename = manifes_folder.joinpath("mpv.yml")
        log.dbg(f'get mpv.yml from file: {new_mpv_filename}')
        new_mpv_str = new_mpv_filename.read_text()
        new_mpv_manifest = ManifestMpv.from_data(new_mpv_str, topdir=self.manifest.topdir)
        # log.dbg(f"new_mpv_manifest from file {new_mpv_filename}: \n{new_mpv_manifest.as_yaml()}\n")
        new_mpv_projects_set = mpv_set_4_compare(new_mpv_manifest)
        #new_mpv_projects_set = set(new_mpv_manifest.projects)
        log.dbg(f"new_mpv_projects_set: {new_mpv_projects_set}\n")
        new_projects_names_in_mpv = set(proj[0] for proj in new_mpv_projects_set)
        log.dbg(f"new_projects_names_in_mpv: {new_projects_names_in_mpv}\n")

        # Check if mpv.yml and west.yml have difference
        # (^ is for symmetric difference between both sets - item that are not union)
        sym_diff_new = new_projects_names_in_west ^ new_projects_names_in_mpv
        log.dbg(f"sym_diff_new: {sym_diff_new}\n")
        if len(sym_diff_new) > 0 and list(sym_diff_new)[0] != 'manifest':
            log.die(f"There are difference between west.yml and mpv.yml, sym_diff_new: {sym_diff_new}")

        # 1.3 Get default branch
        manifest_proj = self.manifest.get_projects(['manifest'])[0]
        default_branch = get_remote_default_branch(manifest_proj)
        log.dbg(f"default_branch: {default_branch}")

        # 1.4 Get current west
        log.dbg(f'get west.yml from default_branch: origin/{default_branch}')
        current_west_str = manifest_proj.read_at("west.yml", f"origin/{default_branch}").decode('utf-8')
        current_west_manifest = manifest.Manifest.from_data(current_west_str, import_flags=ImportFlag.IGNORE)
        # log.dbg(f"current_west_manifest from branch {default_branch}: \n{current_west_manifest.as_yaml()}")
        current_west_projects_set = project_set_4_compare(current_west_manifest)
        log.dbg(f"current_west_projects_set: {current_west_projects_set}\n")
        current_projects_names_in_west = set(proj[0] for proj in current_west_projects_set)
        log.dbg(f"current_projects_names_in_west: {current_projects_names_in_west}")

        # 1.5 Get current mpv
        log.dbg(f'get mpv.yml from default_branch: origin/{default_branch}')
        current_mpv_str = manifest_proj.read_at("mpv.yml", f"origin/{default_branch}").decode('utf-8')
        current_mpv_manifest = ManifestMpv.from_data(current_mpv_str, topdir=self.manifest.topdir)
        # log.dbg(f'current_mpv_manifest from branch {default_branch}: \n{current_mpv_manifest.as_yaml()}\n')
        current_mpv_projects_set = mpv_set_4_compare(current_mpv_manifest)
        current_projects_names_in_mpv = set(proj[0] for proj in current_mpv_projects_set)
        log.dbg(f"current_projects_names_in_mpv: {current_projects_names_in_mpv}\n")


        # 2. Compare the current west.yml and mpv.yml with the new one,
        # and save the changes.

        # 2.1 Find new and change project from west.yml
        new_change_projects_in_west = new_west_projects_set - current_west_projects_set
        log.dbg(f"new_change_projects_in_west: {new_change_projects_in_west}\n")
        new_change_projects_names_in_west = set(proj[0] for proj in new_change_projects_in_west)
        log.dbg(f"new_change_projects_names_in_west: {new_change_projects_names_in_west}\n")

        # 2.2 Find new and change project from mpv.yml
        new_change_projects_in_mpv = new_mpv_projects_set - current_mpv_projects_set
        log.dbg(f"new_change_projects_in_mpv: {new_change_projects_in_mpv}\n")
        new_change_projects_names_in_mpv = set(proj[0] for proj in new_change_projects_in_mpv)
        log.dbg(f"new_change_projects_names_in_mpv: {new_change_projects_names_in_mpv}\n")
        
        delete_project_names_in_west = current_projects_names_in_west - new_change_projects_names_in_west - new_projects_names_in_west
        log.dbg(f"delete_project_names_in_west: {delete_project_names_in_west}")
        
        delete_project_names_in_mpv = current_projects_names_in_mpv - new_change_projects_names_in_mpv - new_projects_names_in_mpv
        log.dbg(f"delete_project_names_in_mpv: {delete_project_names_in_mpv}")

        only_new_project_names_in_new_west = new_projects_names_in_west - current_projects_names_in_west
        log.dbg(f"only_new_project_names_in_new_west: {only_new_project_names_in_new_west}")
        
        # 3 Check all the changes in all repos
        actions = dict()
        
        log.inf(f"\n\nGo over all new and change project, and check the changes:\n")
        for proj_name in new_change_projects_names_in_west:
            log.dbg(f"\nTake care to project: {proj_name}")
            # Check the type of the new project in mpv
            new_project_mpv = new_mpv_manifest.get_projects([proj_name])[0]
            new_project_type = new_project_mpv.content
            actions[proj_name] = list()
                
            # Take care to new projects
            if proj_name not in current_projects_names_in_west:
                log.dbg(f"Project {proj_name} is a new project of type {new_project_type}")

                # For repos that only the west.yml and mpv.yml should be update,
                # inform the user:
                log.inf(f"New project {proj_name} of type {new_project_type}")
                
                if new_project_type == ContentType.DATA:
                    log.dbg(f"Take action NEW_DATA_PROJ for project {proj_name}")
                    actions[proj_name].append(ManifestActionType.NEW_DATA_PROJ)

                elif new_project_type == ContentType.SOURCE:
                    log.dbg(f"Take action NEW_SOURCE_PROJ for project {proj_name}")
                    actions[proj_name].append(ManifestActionType.NEW_SOURCE_PROJ)
                else:
                    log.dbg(f"Take action NEW_OTHER_PROJ for project {proj_name}")
                    actions[proj_name].append(ManifestActionType.NEW_OTHER_PROJ)
                

            # Take care to existing projects that have changes
            # Check what was change:
            # 1. mpv type
            # 2. url
            # 3. revision (for COMMAND repo)
            # 4. groups
            # 5. path
            # 6. command
            # 7. nested
            else:
                log.dbg(f"Project {proj_name} is a project of type {new_project_type} that have changes")
                log.dbg(f"Check the changes for project {proj_name}")

                # 1. mpv type
                current_project_mpv = current_mpv_manifest.get_projects([proj_name])[0]
                current_project_type = current_project_mpv.content
                if current_project_type != new_project_type:
                    log.dbg(f"Project {proj_name} has change in mpv")
                    log.dbg(f"Project {proj_name}: current_project_type: {current_project_type}. new_project_type: {new_project_type}")
                    actions[proj_name].append(ManifestActionType.CHANGE_MPV)
                
                new_project_west = new_west_manifest.get_projects([proj_name])[0]
                current_project_west = current_west_manifest.get_projects([proj_name])[0]

                # 2. url                
                if current_project_west.url != new_project_west.url:
                    log.dbg(f"Project {proj_name} has change in url")
                    log.dbg(f"Project {proj_name}: current url: {current_project_west.url}. new url: {new_project_west.url}")
                    actions[proj_name].append(ManifestActionType.CHANGE_URL)
                
                # 3. revision (for COMMAND repo)
                if current_project_west.revision != new_project_west.revision and current_project_west.west_commands != None:
                    log.dbg(f"Project {proj_name} has change in revision in command repo")
                    log.dbg(f"Project {proj_name}: current revision: {current_project_west.revision}. new revision: {new_project_west.revision}")
                    actions[proj_name].append(ManifestActionType.CHANGE_REVISION)
                
                # 4. groups 
                set_current_groups = set(current_project_west.groups)
                set_new_groups = set(new_project_west.groups)
                if set_current_groups != set_new_groups:
                    log.dbg(f"Project {proj_name} has change in groups ")
                    log.dbg(f"Project {proj_name}: current groups: {set_current_groups}. new group: {set_new_groups}")
                    actions[proj_name].append(ManifestActionType.CHANGE_GROUPS)

                # 5. path
                if current_project_west.path != new_project_west.path: 
                    log.dbg(f"Project {proj_name} has change in path")
                    log.dbg(f"Project {proj_name}: current path: {current_project_west.path}. new path: {new_project_west.path}")
                    actions[proj_name].append(ManifestActionType.CHANGE_PATH)
            
                # 6. command
                if current_project_west.west_commands != new_project_west.west_commands: 
                    log.dbg(f"Project {proj_name} has change in command")
                    log.dbg(f"Project {proj_name}: current commands: {current_project_west.west_commands}. new commands: {new_project_west.west_commands}")
                    actions[proj_name].append(ManifestActionType.CHANGE_COMMAND)

                # 7. TODO: nested (Should check the west.yml itself)
                # if current_project_west.west_commands != new_project_west.west_commands: 
                    # log.dbg(f"Project {proj_name} has change in command")
                    # log.dbg(f"Project {proj_name}: current commands: {current_project_west.west_commands}. new commands: {new_project_west.west_commands}")
                    # actions[proj_name] = actions[proj_name] | ManifestActionType.CHANGE_TO_NESTED

        # Check if there are changes and continue, or exit
        if len(delete_project_names_in_west) == 0 and len(delete_project_names_in_mpv) == 0 and len(actions) == 0:
            log.die(f"\nThere is no any update - exit")

        


        # 4 Perform the actions (if dry run - only inform user)
        
        # First, clone the new repos
        log.inf(f"\n\nClone the new repos")
        new_proj_list = list(only_new_project_names_in_new_west)
        log.dbg(f"The new repos to clone: {new_proj_list}")
        buildin_update_command(self.topdir, new_west_manifest, new_proj_list)
        
        log.dbg(f"Fetch the new repos: {new_proj_list}")
        for proj_new in new_proj_list:
            proj_obj = new_west_manifest.get_projects([proj_new])[0]
            log.dbg(f"Fetch repos: {proj_new}")
            proj_obj.git(['fetch'])

        # 4.1 Copy west.yml and mpv.yml to default branch
        log.inf(f"\n-----------------------------------------------------")
        log.inf(f"Update west.yml and mpv.yml in default branch")
        if args.dr == False:
            manifest_proj.git(['checkout', default_branch, "--"])

            des_west_file = self.manifest.path
            log.dbg(f"des_west_file: {des_west_file}")
            shutil.copyfile(new_west_filename, des_west_file)
            des_west_file_fd = open(des_west_file, "r")
            log.dbg(f"des_west_file: {des_west_file} - \n{des_west_file_fd.read()}")
            des_west_file_fd.close()

            des_mpv_file = des_west_file.replace('west.yml', 'mpv.yml')
            log.dbg(f"des_mpv_file: {des_mpv_file}")
            shutil.copyfile(new_mpv_filename, des_mpv_file)
            des_mpv_file_fd = open(des_mpv_file, "r")
            log.dbg(f"des_mpv_file: {des_mpv_file} - \n{des_mpv_file_fd.read()}")
            des_mpv_file_fd.close()
            
            manifest_proj.git(['add', 'mpv.yml', 'west.yml'])
            manifest_proj.git(['commit', '-m',
                               f'Update new west.yml and mpv.yml in default branch {default_branch}. Automatic update by running the command west mpv-manifest'])
            manifest_proj.git(['push', 'origin', f"{default_branch}"])
            log.dbg(f"Finish commit")
        else:
            log.inf(f"Dry run: branch {default_branch} should be updated with west.yml and mpv.yml from {manifes_folder}\n")

        # 4.2 Update west.yml and mpv.yml in all mpv branches
        log.dbg(f"\n\nAll actions are: {actions}")
        log.inf("Over all branches and update according to update manifests")
        current_manifest_branches = mpv_branches(manifest_proj)
        log.dbg(f"current_manifest_branches: {current_manifest_branches}")
        
        for branch in current_manifest_branches:
            log.dbg(f"Check if to update manifest of branch {branch}.")
            branch = os.path.basename(branch)
            log.dbg(f"After remove origin from branch name branch is: {branch}.")

            addition_actions = dict()
            
            # 4.2.1. Take current west.yml and mpv.yml
            log.dbg(f"Checkout manifest to branch: {branch}.")
            manifest_proj.git(['checkout', branch, "--"])
            manifest_proj.git(['pull'])

            log.dbg(f"Load west.yml current branch: {branch}.")
            current_branch_west_str = manifest_proj.read_at("west.yml", "HEAD").decode('utf-8')
            current_branch_west_manifest = manifest.Manifest.from_data(current_branch_west_str, import_flags=ImportFlag.IGNORE)

            log.dbg(f"Load mpv.yml current branch: {branch}.")
            current_branch_mpv_str = manifest_proj.read_at("mpv.yml", "HEAD").decode('utf-8')
            current_branch_mpv_manifest = ManifestMpv.from_data(current_branch_mpv_str, topdir=self.manifest.topdir)

            ##################################################################

            # Check if there are differences between current branch and default branch 
            # in west.yml and mpv.yml.
            # Only warn if there is a problem
            current_branch_west_projects_set = project_set_4_compare(current_branch_west_manifest)
            log.dbg(f"current_branch_west_projects_set (branch: {branch}): {current_branch_west_projects_set}\n")
            current_branch_projects_names_in_west = set(proj[0] for proj in current_branch_west_projects_set)
            log.dbg(f"current_branch_projects_names_in_west (branch: {branch}): {current_branch_projects_names_in_west}\n")

            current_branch_mpv_projects_set = mpv_set_4_compare(current_branch_mpv_manifest)
            log.dbg(f"current_branch_mpv_projects_set (branch: {branch}): {current_branch_mpv_projects_set}\n")
            current_branch_projects_names_in_mpv = set(proj[0] for proj in current_branch_mpv_projects_set)
            log.dbg(f"current_branch_projects_names_in_mpv (branch: {branch}): {current_branch_projects_names_in_mpv}\n")

            # Remove from mpv.yml the project that are not exist in west.yml in the current branch
            sym_diff_current_branch = current_branch_projects_names_in_west ^ current_branch_projects_names_in_mpv
            log.dbg(f"sym_diff_current_branch (branch: {branch}): {sym_diff_current_branch}\n")
            if len(sym_diff_current_branch) > 0 and list(sym_diff_current_branch)[0] != 'manifest':
                log.wrn(f"There are difference between west.yml and mpv.yml, (branch: {branch}), sym_diff_current_branch: {sym_diff_current_branch}\n")
                only_in_mpv_current_branch = current_branch_projects_names_in_mpv - current_branch_projects_names_in_west
                log.dbg(f"Projects that exist in mpv.yml and not in west.yml are (branch: {branch}): {only_in_mpv_current_branch}\n")
                if len(only_in_mpv_current_branch) > 0:
                    for only_mpv_proj_name in only_in_mpv_current_branch:
                        mpv_proj_2_remove = current_branch_mpv_manifest.get_projects([only_mpv_proj_name])[0]
                        log.dbg(f"   Delete repo: name of mpv project to delete: {mpv_proj_2_remove.name}, branch: {branch}")
                        current_branch_mpv_manifest.projects.remove(mpv_proj_2_remove)
                    
                    log.dbg(f"After delete from mpv projects that are not exist in west.yml - update sets. (branch: {branch})\n")
                    current_branch_mpv_projects_set = mpv_set_4_compare(current_branch_mpv_manifest)
                    log.dbg(f"AFTER DELETE UNWANTED PROJECTS: current_branch_mpv_projects_set (branch: {branch}): {current_branch_mpv_projects_set}\n")
                    current_branch_projects_names_in_mpv = set(proj[0] for proj in current_branch_mpv_projects_set)
                    log.dbg(f"AFTER DELETE UNWANTED PROJECTS: current_branch_projects_names_in_mpv (branch: {branch}): {current_branch_projects_names_in_mpv}\n")

    


            # Check if mpv.yml and west.yml of current branch is different from default branch 
            # (^ is for symmetric difference between both sets - item that are not union)
            sym_diff_west_current = current_projects_names_in_west ^ current_branch_projects_names_in_west
            log.dbg(f"\nsym_diff_west_current: {sym_diff_west_current}")
            if len(sym_diff_west_current) > 0:
                log.wrn(f"There are differences between west.yml of default branch and current branch: {branch}")

            sym_diff_mpv_current = current_projects_names_in_mpv ^ current_branch_projects_names_in_mpv
            log.dbg(f"\nsym_diff_mpv_current: {sym_diff_mpv_current}")
            if len(sym_diff_mpv_current) > 0:
                log.wrn(f"There are differences between mpv.yml of default branch and current branch: {branch}")

            # Add action of new project to the action list,
            # in order to add the project to the current branch.
            # The action should be only if the repo is not going to be deleted
            for proj_name_diff in sym_diff_west_current:
                # if the repo exist in deleted repositories - continue
                if proj_name_diff in delete_project_names_in_west:
                    continue

                # if the diff repo doesn't exist in current branch west - 
                # add new action to add it
                if proj_name_diff not in current_branch_projects_names_in_west:
                    log.dbg(f"The project {proj_name_diff} only exist in default branch and not in branch: {branch} - add new repo action")
                    try:
                        proj_diff_mpv = current_mpv_manifest.get_projects([proj_name_diff])[0]
                        proj_diff_mpv_type = proj_diff_mpv.content
                        log.dbg(f"Type of repo: {proj_name_diff} is {proj_diff_mpv_type}, branch: {branch}")

                        addition_actions[proj_name_diff] = list()
                        if proj_diff_mpv_type == ContentType.DATA:
                            log.dbg(f"Take action NEW_DATA_PROJ for project {proj_name_diff}")
                            addition_actions[proj_name_diff].append(ManifestActionType.NEW_DATA_PROJ)
                        elif proj_diff_mpv_type == ContentType.SOURCE:
                            log.dbg(f"Take action NEW_SOURCE_PROJ for project {proj_name_diff}")
                            addition_actions[proj_name_diff].append(ManifestActionType.NEW_SOURCE_PROJ)
                        else:
                            log.dbg(f"Take action NEW_OTHER_PROJ for project {proj_name_diff}")
                            addition_actions[proj_name_diff].append(ManifestActionType.NEW_OTHER_PROJ)        

                    except Exception as e:
                        log.wrn(f"  Failed to add new action. proj_name_diff: {proj_name_diff}, branch: {branch}, Exception: {e}")
                        continue

            ##################################################################

                
            # 4.2.2. Check the type of the current branch (Data or Source)
            west_mpv_projects = current_branch_mpv_manifest.projects
            # smpv is MergeType.SOURCE_DATA or MergeType.DATA
            smpv = current_branch_mpv_manifest.self_mpv
            log.dbg(f"  smpv.merge_method: {smpv.merge_method}, in branch: {branch}")
            
            # 4.2.3. If there are repo to delete - delete it from west.yml and mpv.yml
            # Remove west projects that should be deleted 
            west_projects = current_branch_west_manifest.projects
            west_projects_len = len(west_projects)
            i = 0
            log.dbg(f"  check for delete repos in west.yml in branch: {branch}")
            for proj_name_2_delete in delete_project_names_in_west:
                proj_2_delete = None
                try:
                    proj_2_delete = current_branch_west_manifest.get_projects([proj_name_2_delete])[0]
                except Exception as e:
                    log.wrn(f"The command get_projects to project: {proj_name_2_delete} failed, \nThe project {proj_name_2_delete} mark to be deleted, but not exist in workspace (=current manifest) -> continue, branch: {branch}, Exception: {e}")
                    continue
                
                log.dbg(f"   Delete repo: {proj_2_delete.name} from current west.yml in branch: {branch}")
                west_projects.remove(proj_2_delete)
                mpv_proj_2_remove = current_branch_mpv_manifest.get_projects([proj_2_delete.name])[0]
                log.dbg(f"   Delete repo: name of mpv project to delete: {mpv_proj_2_remove.name}")
                west_mpv_projects.remove(mpv_proj_2_remove)

            # 4.2.4. Go over the actions:
            log.inf(f"\n-----------------------------------------------------")
            log.inf(f"Go over the all actions. branch: {branch}")
            merge_actions = {**addition_actions, **actions}
            log.dbg(f"merge_actions: {merge_actions}, branch: {branch}")
            for proj_name, action_list in merge_actions.items():
                log.dbg(f"  \nPerfrom actions to {proj_name} in branch: {branch}")
                log.dbg(f"  Actions of {proj_name}: \n  {action_list}")
                new_proj = new_west_manifest.get_projects([proj_name])[0]
                # Save the revision of the new repo, becasue it might change when assignment to c_proj
                new_proj_revision = new_proj.revision
                new_mpv_proj = new_mpv_manifest.get_projects([proj_name])[0]
                log.dbg(f"new_proj: {new_proj}, [proj_name: {proj_name} branch: {branch}] ")
                log.dbg(f"new_proj revision: {new_proj.revision}, new_proj_revision (original before update  c_proj): {new_proj_revision} [proj_name: {proj_name} branch: {branch}] ")
                log.dbg(f"new_mpv_proj: {new_mpv_proj}, [proj_name: {proj_name} branch: {branch}] ")
                
                change_enum_list = [
                    ManifestActionType.CHANGE_PATH,
                    ManifestActionType.CHANGE_URL,
                    ManifestActionType.CHANGE_REVISION, 
                    ManifestActionType.CHANGE_GROUPS,
                    ManifestActionType.CHANGE_MPV,
                    ManifestActionType.CHANGE_COMMAND,
                    ManifestActionType.CHANGE_TO_NESTED]

                c_proj = None
                c_mpv_proj = None
                for action in action_list:
                    log.dbg(f"    Take care to action: {action}, in project {proj_name} in branch: {branch}")
                    if action in change_enum_list:
                        c_proj = current_branch_west_manifest.get_projects([proj_name])[0]
                        c_mpv_proj = current_branch_mpv_manifest.get_projects([proj_name])[0]

                    #  CHANGE_PATH (Update west.yml)
                    if action == ManifestActionType.CHANGE_PATH:
                        c_proj.path = new_proj.path
                        log.dbg(f"    Update path of poject {proj_name} in branch {branch} to {c_proj.path}, as the path in new poject: {new_proj.path}")

                    #  CHANGE_URL (Update west.yml)
                    if action == ManifestActionType.CHANGE_URL:
                        c_proj.url = new_proj.url
                        log.dbg(f"    Update url of poject {proj_name} in branch {branch} to {c_proj.url}, as the url in new poject: {new_proj.url}")

                    #  CHANGE_REVISION (Update west.yml and mpv.yml - check that mpv type is command)
                    if action == ManifestActionType.CHANGE_REVISION and len(new_proj.west_commands) != 0:
                        if new_mpv_proj.content == ContentType.COMMANDS:
                            c_proj.west_commands = new_proj.west_commands
                            c_proj.revision = new_proj.revision
                            c_mpv_proj.content = new_mpv_proj.content
                            log.dbg(f"    Update west-command of poject {proj_name} in branch {branch} to west_commands: {c_proj.west_commands}, revision: {c_proj.revision} as the west-command in new poject: {new_proj.west_commands}")
                        else:
                            log.wrn(f"    Try to update west-command of poject {proj_name} in branch {branch} to {c_proj.west_commands}, BUT the mpv content is {new_mpv_proj.content} and not ContentType.COMMANDS")
                        
                    #  CHANGE_GROUPS (Update west.yml)
                    if action == ManifestActionType.CHANGE_GROUPS:
                        c_proj.groups = new_proj.groups
                        log.dbg(f"    Update groups of poject {proj_name} in branch {branch} to {c_proj.groups}, as the groups in new poject: {new_proj.groups}")

                    #  CHANGE_MPV:  
                    #       (If it become Data from Source - create branch in each source repo
                    #       If it become Source from Data - Update repo in west.yml to the correct sha
                    #       If it become Command - validate that new west.yml has command - update west.yml
                    # orig_mpv_content = c_mpv_proj.content
                    if action == ManifestActionType.CHANGE_MPV:
                        c_mpv_proj.content = new_mpv_proj.content
                        log.dbg(f"    Update mpv content of poject {proj_name} in branch {branch} to {new_mpv_proj.content}, as the mpv content in new poject: {c_mpv_proj.content}")

                        if c_mpv_proj.content == ContentType.DATA or (c_mpv_proj.content == ContentType.SOURCE and smpv.merge_method == MergeType.SOURCE_DATA):
                            c_proj.revision = branch
                            log.dbg(f"    DATA or SOURCE with MergeType.SOURCE_DATA repo - Update revision of poject {proj_name} in branch {branch} to {c_proj.revision}")

                        if c_mpv_proj.content == ContentType.SOURCE and smpv.merge_method == MergeType.DATA:
                            log.dbg(f"    Try to find sha of revision: {new_proj_revision} [c_proj name: {c_proj.name} branch {branch}]")
                            c_proj.revision = c_proj.sha(f"origin/{new_proj_revision}")
                            log.dbg(f"    SOURCE repo with MergeType.DATA - Update revision of poject {proj_name} in branch {branch} to sha: {c_proj.revision}")
                            

                        # If it the content is not source or data update the revision
                        # For data and source - it will be update in next lines, 
                        # with the new project of data or source
                        if c_mpv_proj.content != ContentType.DATA and                            c_mpv_proj.content != ContentType.SOURCE:
                            c_proj.revision = new_proj.revision
                            log.dbg(f"    Also, update revision to {new_proj.revision}, as the revision content in new poject: {c_proj.revision}")
                                
                    # NEW_OTHER_PROJ (Add project to west.yml and mpv.yml)
                    if action == ManifestActionType.NEW_OTHER_PROJ:
                        c_proj = new_project(new_proj)
                        c_proj.topdir = self.manifest.topdir
                        c_mpv_proj = new_mpv_proj
                        # west_projects.append(c_proj)
                        add_project_2_manifest(c_proj, current_branch_west_manifest)
                        west_mpv_projects.append(c_mpv_proj)
                        log.dbg(f"    Add a new {proj_name} in branch {branch} to west.yml: {c_proj}, and to mpv.yml: {c_mpv_proj}")

                    #  NEW_DATA_PROJ or NEW_SOURCE_PROJ with project type to SOURCE_DATA (Add project to west.yml and mpv.yml,
                    #  and create branch in the new repo)
                    if action == ManifestActionType.NEW_DATA_PROJ or (action == ManifestActionType.NEW_SOURCE_PROJ and smpv.merge_method == MergeType.SOURCE_DATA):
                        c_proj = new_project(new_proj)
                        c_proj.topdir = self.manifest.topdir
                        c_proj.revision = branch
                        c_mpv_proj = new_mpv_proj
                        # west_projects.append(c_proj)
                        add_project_2_manifest(c_proj, current_branch_west_manifest)
                        west_mpv_projects.append(c_mpv_proj)
                        log.dbg(f"    Add a new {proj_name} in branch {branch} to west.yml: {c_proj}, and to mpv.yml: {c_mpv_proj}")

                    #  NEW_SOURCE_PROJ with project type to DATA (Add project to west.yml and mpv.yml,
                    #  and create branch in the new repo)
                    if action == ManifestActionType.NEW_SOURCE_PROJ and smpv.merge_method == MergeType.DATA:
                        c_proj = new_project(new_proj)
                        c_proj.topdir = self.manifest.topdir
                        log.dbg(f"    Try to find sha of revision: {new_proj_revision} [c_proj name: {c_proj.name} branch {branch}]")
                        c_proj.revision = c_proj.sha(f"origin/{new_proj_revision}")
                        c_mpv_proj = new_mpv_proj
                        # west_projects.append(c_proj)
                        add_project_2_manifest(c_proj, current_branch_west_manifest)
                        west_mpv_projects.append(c_mpv_proj)
                        log.dbg(f"    Add a new {proj_name} in branch {branch} to west.yml: {c_proj}, and to mpv.yml: {c_mpv_proj}")

                    # in the next lines we create new branches in the new repos.
                    # The update should be for NEW data repo or CHANGE to data repo,
                    # or to for NEW source repo or CHANGE to source repo 
                    # (in case of source project),
                    # In case 
                    if action == ManifestActionType.NEW_DATA_PROJ or \
                        (action == ManifestActionType.NEW_SOURCE_PROJ and smpv.merge_method == MergeType.SOURCE_DATA) or \
                        (action == ManifestActionType.CHANGE_MPV and c_mpv_proj.content == ContentType.DATA) or \
                        (action == ManifestActionType.CHANGE_MPV and c_mpv_proj.content == ContentType.SOURCE and smpv.merge_method == MergeType.SOURCE_DATA):
                        
                        # log.dbg(f"current_branch_west_manifest.projects: \n{current_branch_west_manifest.projects}\n\n")
                        # log.dbg(f"current_branch_west_manifest.get_projects(): \n{current_branch_west_manifest.get_projects([])}\n\n")
                        log.inf(f"Create new branch {branch} in repo {proj_name} from version: origin/{new_proj.revision}")
                        data_proj = current_branch_west_manifest.get_projects([f"{proj_name}"], only_cloned=False)[0]
                        branch_exist = check_branch_exist(data_proj, branch, True)
                        log.dbg(f"branch_exist: {branch_exist}. branch {branch}")
                        if branch_exist == True:
                            log.inf(f"In project data {data_proj.name} the branch {branch} exit - dont create again. smpv.merge_method: {smpv.merge_method}")
                        elif args.dr == False:
                            log.inf(f"In project data {data_proj.name} create the branch {branch}. smpv.merge_method: {smpv.merge_method}")
                            data_proj.git(['branch', branch, f"origin/{new_proj.revision}"],
                            check=False)
                            data_proj.git(['push', '-u', 'origin', branch], check=False)
                        else:
                            log.inf(f"Dry run: in project data {data_proj.name} the branch {branch} should be created. smpv.merge_method: {smpv.merge_method}")

                    log.dbg(f"\nFinish take care to action: {action}. project name: {proj_name}  branch: {branch} \n--------------------\n\n")

                log.dbg(f"\nFinish take care to project name: {proj_name}. branch: {branch}\n--------------------\n\n")

            update_filter_manifest(current_branch_west_manifest)
            
            log.inf(f"\nwest.yml after finish to take care to branch: {branch}: \n{current_branch_west_manifest.as_yaml()}\n")
            log.inf(f"\nmpv.yml after finish to take care to branch: {branch}: \n{current_branch_mpv_manifest.as_yaml()}")

            if args.dr == False:
                log.dbg(f"----------------------------------------")
                west_file = self.manifest.path
                log.dbg(f"west_file: {west_file}. branch: {branch}")
                west_file_fd = open(west_file, "r+")
                log.dbg(f"west_file BEFORE change: {west_file} (branch: {branch})- \n{west_file_fd.read()}")
                # log.inf(f"update west.yml, branch: {branch} yaml: \n {manifest_obj.as_yaml()}\n")
                west_file_fd.seek(0)
                west_file_fd.truncate()
                west_file_fd.write(current_branch_west_manifest.as_yaml())
                west_file_fd.seek(0)
                log.dbg(f"west_file AFTER change: {west_file} (branch: {branch})- \n{west_file_fd.read()}")
                west_file_fd.close()

                log.dbg(f"----------------------------------------")
                mpv_file = west_file.replace('west.yml', 'mpv.yml')
                log.dbg(f"mpv_file: {mpv_file}. branch: {branch}")
                mpv_file_fd = open(mpv_file, "r+")
                log.dbg(f"mpv_file BEFORE change: {mpv_file} (branch: {branch})- \n{mpv_file_fd.read()}")
                mpv_file_fd.seek(0)
                mpv_file_fd.truncate()
                log.inf(f"update mpv.yml, branch: {branch}\n")
                mpv_file_fd.write(current_branch_mpv_manifest.as_yaml())
                mpv_file_fd.seek(0)
                log.dbg(f"mpv_file AFTER change: {mpv_file} (branch: {branch})- \n{mpv_file_fd.read()}")
                mpv_file_fd.close()

                manifest_proj.git(['add', 'mpv.yml', 'west.yml'],
                                  check=False)
                manifest_proj.git(['commit', '-m',
                                   f'In mpv-manifest - Update from {args.manifes_folder}. Automatic update by running the command'], check=False)
                manifest_proj.git(['push', 'origin', f"{branch}"], check=False)


            else:
                log.inf(f"Dry run: in branch {branch}, the west.yml and mpv.yml should be commit and push")


            log.dbg(f"\n\nFinish take care to branch name: {branch}\n--------------------\n\n")



#################################################################


class MpvTemp(WestCommand):
    def __init__(self):
        super().__init__(
            'mpv-temp',
            'For development purpose only',
            textwrap.dedent('''For development purpose only''')
        )

    def do_add_parser(self, parser_adder):
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description,
            formatter_class=argparse.RawDescriptionHelpFormatter)

        return parser



    def do_run(self, args, _):
        # manifest_proj = self.manifest.get_projects(['manifest'])[0]
        # branches = mpv_branches(manifest_proj)
        # log.dbg(f"branches: {branches}\n\n")

        app = WestApp()
        app.run(['-v','update'])
        return
    


        for proj in self.manifest.projects:
            ret = is_tag_branch_commit(proj, "3dc28f85f8b6d80f945114af62759e08b5d1a757")
            log.inf(f"ret of {proj.name}: {ret}")
        return 
        
        # git branch  --format="%(if:equals=[gone])%(upstream:track)%(then)%(refname:short)%(end)"
        for proj in self.manifest.projects:
            check_branch_ahead_remote(proj, "main")
            cp = proj.git('branch  --format="%(if:equals=[gone])%(upstream:track)%(then)%(refname:short)%(end)"',
                             capture_stdout=True, capture_stderr=True,
                             check=False)
            branch2del = cp.stdout.decode('ascii').strip(' "\n\r').splitlines()
            # Remove empty strings:
            branch2del = list(filter(None, branch2del))
            log.dbg(f"proj: {proj.name} branch2del: \n{branch2del}")


