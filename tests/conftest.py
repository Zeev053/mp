#  pytest

import os
from pathlib import Path, PurePath
import platform
import shlex
import shutil
import subprocess
import sys
import textwrap
from rich import print as rprint

from west import configuration as config
import pytest

GIT = shutil.which('git')

# Git capabilities are discovered at runtime in
# _check_git_capabilities().

# This will be set to True if 'git init --branch' is available.
#
# This feature was available from git release v2.28 and was added in
# commit 32ba12dab2acf1ad11836a627956d1473f6b851a ("init: allow
# specifying the initial branch name for the new repository") as part
# of the git community's choice to avoid a default initial branch
# name.
GIT_INIT_HAS_BRANCH = False

# If you change this, keep the docstring in repos_tmpdir() updated also.
MANIFEST_TEMPLATE = '''\
manifest:
  group-filter:
  - -F_M1
  - -F_M2

########################## MPV Commands ##########################
  projects:
  - name: mpv-git-west-commands
    path: GIT-MNGR/mpv-git-west-commands
    revision: main
    url: THE_URL_BASE/mpv-git-west-commands
    west-commands: mpv-commands.yml

########################## Module 1 ##########################

  - name: module1-src
    path: MODULE1/module1-src
    revision: main
    url: THE_URL_BASE/module1-src
    groups:
    - F_M1

  - name: module1-data
    path: MODULE1/module1-data
    revision: main
    url: THE_URL_BASE/module1-data
    clone-depth: 1
    groups:
    - F_M1

########################## Module 2 ##########################

  - name: module2-src
    path: MODULE2/module2-src
    revision: main
    url: THE_URL_BASE/module2-src
    clone-depth: 1
    groups:
    - F_M2

  - name: module2-data
    path: MODULE2/module2-data
    revision: main
    url: THE_URL_BASE/module2-data
    groups:
    - F_M2

########################## External ##########################

  - name: external1
    path: EXTERNAL/external1
    revision: tag_1
    url: THE_URL_BASE/external1
    clone-depth: 1
    groups:
    - F_M1
    - F_M2

########################## All_Projects ##########################

  - name: proj_common
    path: PROJECTS_COMMON/proj_common
    revision: develop
    url: THE_URL_BASE/proj_common
    groups:
    - F_M1
    - F_M2

# ########################## Import (Nested West) ##########################

  # - name: nested-modules-git-manager
    # path: nested-modules-git-manager
    # revision: tag_nested
    # url: THE_URL_BASE/nested-modules-git-manager
    # import:
        # path-prefix: EXTERNAL/NESTED
'''

# MANIFEST_NESTED_TEMPLATE = '''\
# manifest:

  # projects:
  
  # - name: module1-nested-src
    # path: NESTED_MODULE/module1-nested-src
    # revision: main
    # url: THE_URL_BASE/module1-nested-src
    # groups:
    # - F_M1

  # - name: module1-nested-data
    # path: NESTED_MODULE/module1-nested-data
    # revision: main
    # url: THE_URL_BASE/module1-nested-data
    # groups:
    # - F_M1
# '''

MPV_TEMPLATE = '''
manifest:
  projects:
  - name: mpv-git-west-commands
    content: COMMANDS

  - name: module1-src
    content: SOURCE
  - name: module1-data
    content: DATA

  - name: module2-src
    content: SOURCE
  - name: module2-data
    content: DATA

  - name: external1
    content: EXTERNAL

  - name: proj_common
    content: ALL_PROJECTS

  # - name: nested-modules-git-manager
    # content: EXTERNAL

  self:
    merge-method: SOURCE_DATA
'''

WINDOWS = (platform.system() == 'Windows')


#
# Test fixtures
#

# def pytest_addoption(parser):
    # parser.addoption("--mpv-address", help="Address of mpv-git-west-commands git repository")


# @pytest.fixture
# def mpv(request):
    # return request.config.getoption("--mpv-address")


@pytest.fixture(scope='session', autouse=True)
def _check_git_capabilities(tmp_path_factory):
    # Do checks for git behaviors. Right now this is limited to
    # deciding whether or not 'git init --branch' is supported.
    #
    # We aren't using WestCommand._parse_git_version() here just to
    # try to keep the conftest behavior independent of the code being
    # tested.
    global GIT_INIT_HAS_BRANCH

    tmpdir = tmp_path_factory.mktemp("west-check-git-caps-tmpdir")

    try:
        subprocess.run([GIT, 'init', '--initial-branch', 'foo',
                        os.fspath(tmpdir)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True)
        GIT_INIT_HAS_BRANCH = True
    except subprocess.CalledProcessError:
        pass


@pytest.fixture(scope='session')
def _session_repos(tmp_path_factory):
    '''Just a helper, do not use directly.'''

    # It saves time to create repositories once at session scope, then
    # clone the results as needed in per-test fixtures.
    # session_repos = os.path.join(os.environ['TOXTEMPDIR'], 'session_repos')
    session_repos = tmp_path_factory.mktemp("session_repos")
    print('initializing session repositories in', session_repos)
    shutil.rmtree(session_repos, ignore_errors=True)

    # Create the repositories.
    rp = {}  # individual repository paths
    for repo in \
            'mpv-test-git-manager', \
            'mpv-git-west-commands', \
            'module1-src', \
            'module1-data', \
            'module2-src', \
            'module2-data', \
            'external1', \
            'proj_common':
            # 'nested-modules-git-manager', \
            # 'module1-nested-src', \
            # 'module1-nested-data':
        path = os.path.join(session_repos, repo)
        rp[repo] = path
        create_repo(path)

    # The caller needs to add west.yml with the right url-base.

    # Initialize the "module1-src" repository.
    add_commit(rp['module1-src'], 'base module1-src commit',
               files={'main.cpp': '''
                #pragma once
                #include <iostream>
                '''})

    add_commit(rp['module2-src'], 'base module2-src commit',
               files={'main.cpp': '''
                #pragma once
                #include <iostream>
                '''})

    add_tag(rp['external1'], 'tag_1')

    add_commit(rp['external1'], 'external1 after tag_1 commit',
               files={'main.cpp': '''
                after tag_1
                #pragma once
                #include <iostream>
                '''})

    add_commit(rp['external1'], 'external1 commit after after tag_1 commit',
               files={'main.cpp': '''
                after after tag_1
                #pragma once
                #include <iostream>
                '''})


    add_tag(rp['external1'], 'tag_3')

    add_commit(rp['proj_common'], 'proj_common in main branch commit',
               files={'main.cpp': '''
                #pragma once
                #include <iostream>
                // ###############################3
                // MAIN branch commit
                // ###############################3
                // Common file to all projects
                '''})


    create_branch(rp['proj_common'], 'develop', True)
    add_commit(rp['proj_common'], 'proj_common in develop branch commit',
               files={'main.cpp': '''
                #pragma once
                #include <iostream>
                // Common file to all projects
                '''})
    # to the check in manifest update by folder
    add_tag(rp['proj_common'], 'tag_1')


    # Path of mpv-git-west-commands:
    mpv_path = Path(__file__).parent.parent
    des_path = Path(rp['mpv-git-west-commands'])
    shutil.copytree(mpv_path.joinpath('scripts'), des_path.joinpath('scripts'))
    shutil.copyfile(mpv_path.joinpath('mpv-commands.yml'), des_path.joinpath('mpv-commands.yml'))
    shutil.copytree(mpv_path.joinpath('git-hook'), des_path.joinpath('git-hook'))

    # commit the copy source_branch in mpv-git-west-commands
    subprocess.check_call(
        [GIT, 'add', '.'], cwd=rp['mpv-git-west-commands'])
    subprocess.check_call(
        [GIT, 'commit', '-m', f'Add mpv sources from current source in {mpv_path}'], cwd=rp['mpv-git-west-commands'])

    # Return the top-level temporary directory. Don't clean it up on
    # teardown, so the contents can be inspected post-portem.
    print('finished initializing session repositories')
    return session_repos


@pytest.fixture
def repos_tmpdir(tmp_path, _session_repos):
    '''Fixture for tmpdir with "remote" repositories.

    These can then be used to bootstrap a workspace and run
    project-related commands on it with predictable results.

    Switches directory to, and returns, the top level tmpdir -- NOT
    the subdirectory containing the repositories themselves.

    Initializes placeholder upstream repositories in tmpdir with the
    following contents:

    repos/
    ├───EXTERNAL
    │   ├───external1
    ├───GIT-MNGR
    │   └───mpv-git-west-commands
    ├───MODULE1
    │   ├───module1-data
    │   └───module1-src
    ├───MODULE2
    │   ├───module2-data
    │   └───module2-src
    ├───PROJECTS_COMMON
    │   └───proj_common    
    └───mpv-test-git-manager

    '''

    mpv_test_git_manager, mpv_git_west_commands, module1_src, module1_data, module2_src, module2_data, external1, proj_common = [
        os.path.join(_session_repos, x) for x in
        ['mpv-test-git-manager', 'mpv-git-west-commands', 'module1-src', 'module1-data',
        'module2-src', 'module2-data', 'external1',
         'proj_common']]
    repos = tmp_path / 'repos'
    repos.mkdir()
    print(f"")
    print(f"repos_tmpdir() - repos: {repos}")
    os.chdir(repos)
    for r in [mpv_test_git_manager, mpv_git_west_commands, module1_src, module1_data,
    module2_src, module2_data, external1, proj_common]:
        subprocess.check_call([GIT, 'clone', r])
        repo_name=os.path.basename(r)
        repo_full_dir = repos / repo_name
        print(f"repos_tmpdir() - repo_name: {repo_name}, repo_full_dir = {repo_full_dir}")
        os.chdir(repo_full_dir)
        print(f"repos_tmpdir() - os.getcwd(): {os.getcwd()}")
        subprocess.check_call([GIT, 'config', 'receive.denyCurrentBranch', 'updateInstead'])
        subprocess.check_call([GIT, 'config', '--get', 'receive.denyCurrentBranch'])
        os.chdir(repos)

    # checkout main in order to create local main branch
    # (If not - after the clone in workspace - the main branch will not be)
    checkout_branch(repos.joinpath('proj_common'), "main")

    # mpv-command = Path(__file__).parents()
    manifest = MANIFEST_TEMPLATE.replace('THE_URL_BASE',
                                         str(repos.as_posix()))
    #manifest = manifest.replace('MPV_COMMANDS_URL', mpv)

    add_commit(str(repos.joinpath('mpv-test-git-manager')), 'add manifest',
               files={'west.yml': manifest,
                      'mpv.yml': MPV_TEMPLATE})

    # manifest_nested = MANIFEST_NESTED_TEMPLATE.replace('THE_URL_BASE',
                                         # str(repos.as_posix()))

    # add_commit(str(repos.joinpath('nested-modules-git-manager')), 'add manifest',
               # files={'west.yml': manifest_nested})
    
    # add_tag(str(repos.joinpath('nested-modules-git-manager')), 'tag_nested')


    return tmp_path


@pytest.fixture
def west_init_tmpdir(repos_tmpdir):
    '''Fixture for a tmpdir with 'remote' repositories and 'west init' run.

    Uses the remote repositories from the repos_tmpdir fixture to
    create a west workspace using west init.

    The contents of the west workspace aren't checked at all.
    This is left up to the test cases.

    The directory that 'west init' created is returned as a
    py.path.local, with the current working directory set there.'''
    print("")
    print("west_init_tmpdir()")
    west_tmpdir = repos_tmpdir / 'workspace'
    manifest = repos_tmpdir / 'repos' / 'mpv-test-git-manager'
    cmd(f'init -m "{manifest}" --mr main "{west_tmpdir}"')
    os.chdir(west_tmpdir)
    config.read_config()
    return west_tmpdir


#
# Helper functions
#

def check_output(*args, **kwargs):
    # Like subprocess.check_output, but returns a string in the
    # default encoding instead of a byte array.
    try:
        out_bytes = subprocess.check_output(*args, **kwargs)
    except subprocess.CalledProcessError as e:
        rprint('*** check_output: nonzero return code', e.returncode,
              file=sys.stderr)
        rprint('cwd =', os.getcwd(), 'args =', args,
              'kwargs =', kwargs, file=sys.stderr)
        rprint('subprocess output:', file=sys.stderr)
        rprint(e.output.decode(), file=sys.stderr)
        raise
    return out_bytes.decode(sys.getdefaultencoding())


def cmd(cmd, cwd=None, stderr=None, env=None):
    # Run a west command in a directory (cwd defaults to os.getcwd()).
    #
    # This helper takes the command as a string.
    #
    # This helper relies on the test environment to ensure that the
    # 'west' executable is a bootstrapper installed from the current
    # west source_branch code.
    #
    # stdout from cmd is captured and returned. The command is run in
    # a python subprocess so that program-level setup and teardown
    # happen fresh.
    cmd = 'west -v ' + cmd
    if not WINDOWS:
        cmd = shlex.split(cmd)
    rprint('running:', cmd)
    if env:
        rprint('with non-default environment:')
        for k in env:
            if k not in os.environ or env[k] != os.environ[k]:
                rprint(f'\t{k}={env[k]}')
        for k in os.environ:
            if k not in env:
                rprint(f'\t{k}: deleted, was: {os.environ[k]}')
    if cwd is not None:
        cwd = os.fspath(cwd)
        rprint(f'in {cwd}')
    try:
        return check_output(cmd, cwd=cwd, stderr=stderr, env=env)
    except subprocess.CalledProcessError:
        rprint('cmd: west:', shutil.which('west'), file=sys.stderr)
        raise


def create_workspace(workspace_dir, and_git=True):
    # Manually create a bare-bones west workspace inside
    # workspace_dir. The manifest.path config option is 'mp'. The
    # manifest repository directory is created, and the git
    # repository inside is initialized unless and_git is False.
    if not os.path.isdir(workspace_dir):
        workspace_dir.mkdir()
    dot_west = workspace_dir / '.west'
    dot_west.mkdir()
    with open(dot_west / 'config', 'w') as f:
        f.write('[manifest]\n'
                'path = mp')
    mp = workspace_dir / 'mp'
    mp.mkdir()
    if and_git:
        create_repo(mp)


def create_repo(path, initial_branch='main'):
    # Initializes a Git repository in 'path', and adds an initial
    # commit to it in a new branch 'initial_branch'. We're currently
    # keeping the old default initial branch to keep assumptions made
    # elsewhere in the test code working with newer versions of git.
    path = os.fspath(path)

    if GIT_INIT_HAS_BRANCH:
        subprocess.check_call([GIT, 'init', '--initial-branch', initial_branch,
                               path])
    else:
        subprocess.check_call([GIT, 'init', path])
        # -B instead of -b because on some versions of git (at
        # least 2.25.1 as shipped by Ubuntu 20.04), if 'git init path'
        # created an 'initial_branch' already, we get errors that it
        # already exists with plain '-b'.
        subprocess.check_call([GIT, 'checkout', '-B', initial_branch],
                              cwd=path)

    config_repo(path)
    add_commit(path, 'initial')


def config_repo(path):
    # Set name and email. This avoids a "Please tell me who you are" error when
    # there's no global default.
    print(f"config_repo() - path: {path}")
    subprocess.check_call([GIT, 'config', 'user.name', 'West Test'], cwd=path)
    subprocess.check_call([GIT, 'config', 'user.email',
                           'west-test@example.com'],
                          cwd=path)


def create_branch(path, branch, checkout=False):
    subprocess.check_call([GIT, 'branch', branch], cwd=path)
    if checkout:
        checkout_branch(path, branch)


def checkout_branch(path, branch, detach=False):
    detach = ['--detach'] if detach else []
    subprocess.check_call([GIT, 'checkout', branch] + detach, cwd=path)


def add_commit(repo, msg, files=None, reconfigure=True):
    # Adds a commit with message 'msg' to the repo in 'repo'
    #
    # If 'files' is given, it must be a dictionary mapping files to
    # edit to the contents they should contain in the new
    # commit. Otherwise, the commit will be empty.
    #
    # If 'reconfigure' is True, the user.name and user.email git
    # configuration variables will be set in 'repo' using config_repo().
    print(f"add_commit() - locals: {locals()}")

    print(f"add_commit() - repo: {repo}")
    repo = os.fspath(repo)
    print(f"add_commit() - after fspath: {repo}")

    if reconfigure:
        config_repo(repo)

    # Edit any files as specified by the user and add them to the index.
    if files:
        for path, contents in files.items():
            if not isinstance(path, str):
                path = str(path)
            dirname, basename = os.path.dirname(path), os.path.basename(path)
            fulldir = os.path.join(repo, dirname)
            if not os.path.isdir(fulldir):
                # Allow any errors (like trying to create a directory
                # where a file already exists) to propagate up.
                os.makedirs(fulldir)
            with open(os.path.join(fulldir, basename), 'w') as f:
                f.write(contents)
            subprocess.check_call([GIT, 'add', path], cwd=repo)

    # The extra '--no-xxx' flags are for convenience when testing
    # on developer workstations, which may have global git
    # configuration to sign commits, etc.
    #
    # We don't want any of that, as it could require user
    # intervention or fail in environments where Git isn't
    # configured.
    subprocess.check_call(
        [GIT, 'commit', '-a', '--allow-empty', '-m', msg, '--no-verify',
         '--no-gpg-sign', '--no-post-rewrite'], cwd=repo)


def add_tag(repo, tag, commit='HEAD', msg=None):
    repo = os.fspath(repo)

    if msg is None:
        msg = 'tag ' + tag

    # Override tag.gpgSign with --no-sign, in case the test
    # environment has that set to true.
    subprocess.check_call([GIT, 'tag', '-m', msg, '--no-sign', tag, commit],
                          cwd=repo)


def rev_parse(repo: object, revision: object) -> object:
    repo = os.fspath(repo)
    out = subprocess.check_output([GIT, 'rev-parse', revision], cwd=repo)
    ret = out.decode(sys.getdefaultencoding()).strip()
    print(f"rev_parse() - repo: {repo}, revision: {revision} -> ret: {ret}")
    return ret


def check_proj_consistency(actual, expected):
    # Check equality of all project fields (projects themselves are
    # not comparable), with extra semantic consistency checking
    # for paths.
    assert actual.name == expected.name

    assert actual.path == expected.path
    if actual.topdir is None or expected.topdir is None:
        assert actual.topdir is None and expected.topdir is None
        assert actual.abspath is None and expected.abspath is None
        assert actual.posixpath is None and expected.posixpath is None
    else:
        assert actual.topdir and actual.abspath and actual.posixpath
        assert expected.topdir and expected.abspath and expected.posixpath
        a_top, e_top = PurePath(actual.topdir), PurePath(expected.topdir)
        a_abs, e_abs = PurePath(actual.abspath), PurePath(expected.abspath)
        a_psx, e_psx = PurePath(actual.posixpath), PurePath(expected.posixpath)
        assert a_top.is_absolute()
        assert e_top.is_absolute()
        assert a_abs.is_absolute()
        assert e_abs.is_absolute()
        assert a_psx.is_absolute()
        assert e_psx.is_absolute()
        assert a_top == e_top
        assert a_abs == e_abs
        assert a_psx == e_psx

    assert (actual.url == expected.url or
            (WINDOWS and Path(expected.url).is_dir() and
             (PurePath(actual.url) == PurePath(expected.url))))
    assert actual.clone_depth == expected.clone_depth
    assert actual.revision == expected.revision
    assert actual.west_commands == expected.west_commands
