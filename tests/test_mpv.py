# How to run: 
# pytest -s -k test_mpv_merge --junit-xml=junit.xml
# When:
# -s -> No capture, print all to screen
# -k test_mpv_merge -> Run only this test


import collections
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path, PurePath
from rich import print as rprint


import yaml

import pytest

from west import configuration as config
from west.manifest import Manifest, ManifestProject, Project, \
    ManifestImportFailed
from west.manifest import ImportFlag as MIF
from conftest import create_branch, create_workspace, create_repo, \
    add_commit, add_tag, check_output, cmd, GIT, rev_parse, \
    check_proj_consistency, checkout_branch

# assert 'TOXTEMPDIR' in os.environ, "you must run these tests using tox"

#
# Helpers
#

# A container for the remote locations of the repositories involved in
# a west update. These attributes may be None.
UpdateRemotes = collections.namedtuple('UpdateRemotes',
                                       'net_tools kconfiglib tagged_repo')

# A container type which holds the remote and local repository paths
# used in tests of 'west update'. This also contains manifest-rev
# branches and HEAD commits before (attributes ending in _0) and after
# (ending in _1) the 'west update' is done by update_helper().
#
# These may be None.
#
# See conftest.py for details on the manifest used in west update
# testing, and update_helper() below as well.
UpdateResults = collections.namedtuple('UpdateResults',
                                       'nt_remote nt_local '
                                       'kl_remote kl_local '
                                       'tr_remote tr_local '
                                       'nt_mr_0 nt_mr_1 '
                                       'kl_mr_0 kl_mr_1 '
                                       'tr_mr_0 tr_mr_1 '
                                       'nt_head_0 nt_head_1 '
                                       'kl_head_0 kl_head_1 '
                                       'tr_head_0 tr_head_1')


#
# Test fixtures
#

@pytest.fixture
def mpv_update_tmpdir(west_init_tmpdir):
    # Like west_init_tmpdir, but also runs west update
    print("")
    print("mpv_update_tmpdir()")
    cmd('update', cwd=str(west_init_tmpdir))
    cmd('mpv-update --full-clone', cwd=str(west_init_tmpdir))
    return west_init_tmpdir


@pytest.fixture
def mpv_update_tmpdir_f_m1(west_init_tmpdir):
    # Like west_init_tmpdir, but also runs west update only for F_M1 group
    cmd('update', cwd=str(west_init_tmpdir))
    cmd('mpv-update -c F_M1', cwd=str(west_init_tmpdir))
    return west_init_tmpdir


@pytest.fixture
def mpv_update_tmpdir_f_m2(west_init_tmpdir):
    # Like west_init_tmpdir, but also runs west update only for F_M2 group
    cmd('update', cwd=str(west_init_tmpdir))
    cmd('mpv-update -c F_M2', cwd=str(west_init_tmpdir))
    return west_init_tmpdir


@pytest.fixture
def mpv_update_tmpdir_clone_depth(west_init_tmpdir):
    # Like west_init_tmpdir, but also runs west update only for F_M2 group
    cmd('update', cwd=str(west_init_tmpdir))
    cmd('mpv-update', cwd=str(west_init_tmpdir))
    return west_init_tmpdir


@pytest.fixture
def mpv_init_tmpdir(mpv_update_tmpdir):
    # Create new project with name proj_1, and version 1.0.0
    print("")
    print("mpv_init_tmpdir()")
    print("Create new project with name proj_1, and version 1.0.0:")
    cmd('mpv-init proj_1 1.0.0', cwd=str(mpv_update_tmpdir))
    return mpv_update_tmpdir


@pytest.fixture
def mpv_new_proj_tmpdir(mpv_init_tmpdir):
    # Call mpv-update for the project proj_1__1.0.0_dev, 
    # and add new project with name dummy_d, and version 1.0.0
    print("")
    print(f"mpv_new_proj_tmpdir() - mpv_init_tmpdir: {mpv_init_tmpdir}")

    cmd('mpv-update --full-clone --mr proj_1__1.0.0_dev', cwd=str(mpv_init_tmpdir))

    module1_src_apath = mpv_init_tmpdir.joinpath("MODULE1/module1-src")
    module2_data_apath = mpv_init_tmpdir.joinpath("MODULE2/module2-data")
    # external1_apath = mpv_init_tmpdir.joinpath("EXTERNAL/external1")

    add_commit(module1_src_apath, 'In method mpv_new_proj_tmpdir',
               files={'src1_conflict.cpp': '''
                #pragma once
                // conflict line 11
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module1_src_apath)

    add_commit(module2_data_apath, 'In method mpv_new_proj_tmpdir',
               files={'data2_conflict.cpp': '''
                #pragma once
                // conflict line 11
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module2_data_apath)

    print("Create dummy_d 1.0.0")
    cmd('mpv-new-proj proj_1__1.0.0_dev dummy_d 1.0.0', cwd=str(mpv_init_tmpdir))

    print("Create dummy_s 1.0.0")
    cmd('mpv-new-proj -t s proj_1__1.0.0_dev dummy_s 1.0.0', cwd=str(mpv_init_tmpdir))

    return mpv_init_tmpdir

    
@pytest.fixture
def mpv_merge_tmpdir(mpv_new_proj_tmpdir):
    # Create commits and several branches, for testing the merge
    print("")
    print(f"mpv_merge_tmpdir() - mpv_new_proj_tmpdir: {mpv_new_proj_tmpdir}")

    git_manager_apath = mpv_new_proj_tmpdir.joinpath("mpv-test-git-manager")
    module1_src_apath = mpv_new_proj_tmpdir.joinpath("MODULE1/module1-src")
    module2_data_apath = mpv_new_proj_tmpdir.joinpath("MODULE2/module2-data")
    external1_apath = mpv_new_proj_tmpdir.joinpath("EXTERNAL/external1")

    ######################################
    ### Take care to proj_1__1.0.0_dev,
    #####################################
    cmd('mpv-update --full-clone --mr proj_1__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    print(f"mpv_merge_tmpdir() - update west.yml with tag2 for external1, and add commit to: mpv-test-git-manager, in proj_1__1.0.0_dev")
    source_file = git_manager_apath.joinpath("west.yml")
    source_data = source_file.read_text()
    source_data = yaml.safe_load(source_data)
    source_data['manifest']['projects'][5]['revision']='tag_2'
    manifest_fd = open(git_manager_apath.joinpath("west.yml"), "w")
    manifest_fd.write(yaml.safe_dump(source_data))
    manifest_fd.close()
    subprocess.check_call([GIT, 'commit', '-a', '-m', "In method mpv_merge_tmpdir - proj_1__1.0.0_dev"], cwd=git_manager_apath)
    subprocess.check_call([GIT, 'push'], cwd=git_manager_apath)

    print(f"mpv_merge_tmpdir() - add commit to: MODULE1/module1-src, in proj_1__1.0.0_dev")
    add_commit(module1_src_apath, 'In method mpv_merge_tmpdir - proj_1__1.0.0_dev',
               files={'src1_conflict.cpp': '''
                #pragma once
                // conflict line old proj_1 1.0.0
                #include <iostream>
                ''',
                'src1_oldfile.cpp': '''
                // Old file src1
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module1_src_apath)
                
                
    print(f"mpv_merge_tmpdir() - add commit to: MODULE2/module2-data, in proj_1__1.0.0_dev")
    add_commit(module2_data_apath, 'In method mpv_merge_tmpdir - proj_1__1.0.0_dev',
               files={'data2_conflict.cpp': '''
                #pragma once
                // conflict line old proj_1 1.0.0
                #include <iostream>
                ''',
                'data2_oldfile.cpp': '''
                // Old file data2
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module2_data_apath)

    print(f"mpv_merge_tmpdir() - add commit and tag: tag_2 to: EXTERNAL/external1, in proj_1__1.0.0_dev")
    checkout_branch(external1_apath, 'main')
    add_commit(external1_apath, 'In method mpv_new_proj_tmpdir',
               files={'external.cpp': '''
                #pragma once
                // tag_2
                #include <iostream>
                '''})
    add_tag(external1_apath, 'tag_2')
    subprocess.check_call([GIT, 'push','--tags'], cwd=external1_apath)

    #####################################
    ### Take care to dummy_d__1.0.0_dev
    #####################################
    print(f"mpv_merge_tmpdir() - call 'mpv-update --mr dummy_d__1.0.0_dev'")
    cmd('mpv-update --full-clone --mr dummy_d__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    print(f"mpv_merge_tmpdir() - add commit to: MODULE2/module2-data, in dummy_d__1.0.0_dev")
    add_commit(module2_data_apath, 'In method mpv_merge_tmpdir - dummy_d__1.0.0_dev',
               files={'data2_conflict.cpp': '''
                #pragma once
                // conflict line new dummy_d__1.0.0
                #include <iostream>
                ''',
                'data2_newfile.cpp': '''
                // New file data2 dummy_d__1.0.0
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module2_data_apath)


    #####################################
    ### Take care to dummy_s__1.0.0_dev
    #####################################
    print(f"mpv_merge_tmpdir() - call 'mpv-update --mr dummy_s__1.0.0_dev'")
    cmd('mpv-update --full-clone --mr dummy_s__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    print(f"mpv_merge_tmpdir() - add commit to: MODULE1/module1-src, in dummy_s__1.0.0_dev")
    add_commit(module1_src_apath, 'In method mpv_merge_tmpdir - dummy_s__1.0.0_dev',
               files={'src1_conflict.cpp': '''
                #pragma once
                // conflict line new dummy_s__1.0.0
                #include <iostream>
                ''',
                'src1_newfile.cpp': '''
                // New file src1 dummy_s__1.0.0
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module1_src_apath)

    print(f"mpv_merge_tmpdir() - add commit to: MODULE2/module2-data, in dummy_s__1.0.0_dev")
    add_commit(module2_data_apath, 'In method mpv_merge_tmpdir - dummy_s__1.0.0_dev',
               files={'data2_conflict.cpp': '''
                #pragma once
                // conflict line new dummy_s__1.0.0
                #include <iostream>
                ''',
                'data2_newfile.cpp': '''
                // New file data2 dummy_s__1.0.0
                #include <iostream>
                '''})
    subprocess.check_call([GIT, 'push'], cwd=module2_data_apath)

    return mpv_new_proj_tmpdir



def remove_space(string):
    new_string = string.replace("\r", "")
    new_string = new_string.replace("\n", "")
    new_string = new_string.replace(" ", "")
    new_string = new_string.replace('"', "")
    return new_string


#
# Test cases
#


def test_mpv_update(mpv_update_tmpdir):
    print("\n\n\n\n--------------------------------")
    print(f"west_update_tmpdir: {mpv_update_tmpdir}")
    wct = mpv_update_tmpdir

    # Validate that all repositories cloned to the workspace
    assert wct.exists()
    assert wct.is_dir()
    assert wct.joinpath("MODULE1/module1-src").is_dir()
    assert wct.joinpath("MODULE1/module1-src/main.cpp").is_file()
    assert wct.joinpath("MODULE1/module1-data").is_dir()
    assert wct.joinpath("MODULE2/module2-src").is_dir()
    assert wct.joinpath("MODULE2/module2-src/main.cpp").is_file()
    assert wct.joinpath("MODULE2/module2-data").is_dir()
    assert wct.joinpath("EXTERNAL/external1").is_dir()
    assert wct.joinpath("PROJECTS_COMMON/proj_common").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/nested-modules-git-manager").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-data").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-src").is_dir()
    assert wct.joinpath("mpv-test-git-manager").is_dir()

    # Validate that the revision in all repositories is correct
    actual = cmd('list -f "{name} {revision} {path} {cloned} {clone_depth}"')
    return
    
    
    ##################
    # TODO: Continue
    ##################

    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=str(mpv_update_tmpdir))
    external1_revision = remove_space(external1_revision)
    assert external1_revision == 'main'
    module1_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-src'],
                                        cwd=str(mpv_update_tmpdir))
    module1_src_revision = remove_space(module1_src_revision)
    assert module1_src_revision == 'main'
    module1_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-data'],
                                         cwd=str(mpv_update_tmpdir))
    module1_data_revision = remove_space(module1_data_revision)
    assert module1_data_revision == 'main'
    module2_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-src'],
                                        cwd=str(mpv_update_tmpdir))
    module2_src_revision = remove_space(module2_src_revision)
    assert module2_src_revision == 'main'
    module2_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-data'],
                                         cwd=str(mpv_update_tmpdir))
    module2_data_revision = remove_space(module2_data_revision)
    assert module2_data_revision == 'main'
    # nested_modules_git_manager_revision = check_output(
        # ['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'],
        # cwd=str(mpv_update_tmpdir))
    # nested_modules_git_manager_revision = remove_space(nested_modules_git_manager_revision)
    # assert nested_modules_git_manager_revision == 'main'
    # module1_nested_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-nested-src'],
                                               # cwd=str(mpv_update_tmpdir))
    # module1_nested_src_revision = remove_space(module1_nested_src_revision)
    # assert module1_nested_src_revision == 'main'
    # module1_nested_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-nested-data'],
                                                # cwd=str(mpv_update_tmpdir))
    # module1_nested_data_revision = remove_space(module1_nested_data_revision)
    # assert module1_nested_data_revision == 'main'


def test_mpv_update_f_m1(mpv_update_tmpdir_f_m1):
    print("\n\n\n\n--------------------------------")
    print(f"west_update_tmpdir_f_m1: {mpv_update_tmpdir_f_m1}")
    wct = mpv_update_tmpdir_f_m1

    # Validate that only repositories of F_M1 group where clone (include in nested west.yml)
    assert wct.exists()
    assert wct.is_dir()
    assert wct.joinpath("MODULE1/module1-src").is_dir()
    assert wct.joinpath("MODULE1/module1-src/main.cpp").is_file()
    assert wct.joinpath("MODULE1/module1-data").is_dir()
    assert not wct.joinpath("MODULE2/module2-src").is_dir()
    assert not wct.joinpath("MODULE2/module2-src/main.cpp").is_file()
    assert not wct.joinpath("MODULE2/module2-data").is_dir()
    assert wct.joinpath("EXTERNAL/external1").is_dir()
    assert wct.joinpath("PROJECTS_COMMON/proj_common").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/nested-modules-git-manager").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-data").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-src").is_dir()
    assert wct.joinpath("mpv-test-git-manager").is_dir()

    # Validate that the revision in cloned repositories is correct
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'],
                                      cwd=str(mpv_update_tmpdir_f_m1))
    external1_revision = remove_space(external1_revision)
    assert external1_revision == 'tag_1'

    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'],
                                      cwd=str(mpv_update_tmpdir_f_m1)).strip(' "\n\r')
    assert proj_common_revision == 'develop'

    module1_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-src'],
                                        cwd=str(mpv_update_tmpdir_f_m1))
    module1_src_revision = remove_space(module1_src_revision)
    assert module1_src_revision == 'main'
    module1_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-data'],
                                         cwd=str(mpv_update_tmpdir_f_m1))
    module1_data_revision = remove_space(module1_data_revision)
    assert module1_data_revision == 'main'
    # nested_modules_git_manager_revision = check_output(
        # ['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'],
        # cwd=str(mpv_update_tmpdir_f_m1))
    # nested_modules_git_manager_revision = remove_space(nested_modules_git_manager_revision)
    # assert nested_modules_git_manager_revision == 'tag_nested'
    # module1_nested_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-nested-src'],
                                               # cwd=str(mpv_update_tmpdir_f_m1))
    # module1_nested_src_revision = remove_space(module1_nested_src_revision)
    # assert module1_nested_src_revision == 'main'
    # module1_nested_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-nested-data'],
                                                # cwd=str(mpv_update_tmpdir_f_m1))
    # module1_nested_data_revision = remove_space(module1_nested_data_revision)
    # assert module1_nested_data_revision == 'main'


def test_mpv_update_f_m2(mpv_update_tmpdir_f_m2):
    print("\n\n\n\n--------------------------------")
    print(f"west_update_tmpdir_f_m2: {mpv_update_tmpdir_f_m2}")
    wct = mpv_update_tmpdir_f_m2

    # Validate that only repositories of F_M2 group where clone (include in nested west.yml)
    assert wct.exists()
    assert wct.is_dir()
    assert not wct.joinpath("MODULE1/module1-src").is_dir()
    assert not wct.joinpath("MODULE1/module1-src/main.cpp").is_file()
    assert not wct.joinpath("MODULE1/module1-data").is_dir()
    assert wct.joinpath("MODULE2/module2-src").is_dir()
    assert wct.joinpath("MODULE2/module2-src/main.cpp").is_file()
    assert wct.joinpath("MODULE2/module2-data").is_dir()
    assert wct.joinpath("EXTERNAL/external1").is_dir()
    assert wct.joinpath("PROJECTS_COMMON/proj_common").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/nested-modules-git-manager").is_dir()
    # assert not wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-data").is_dir()
    # assert not wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-src").is_dir()
    assert wct.joinpath("mpv-test-git-manager").is_dir()

    # Validate that the revision in cloned repositories is correct
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'],
                                      cwd=str(mpv_update_tmpdir_f_m2))
    external1_revision = remove_space(external1_revision)
    assert external1_revision == 'tag_1'
    
    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'],
                                      cwd=str(mpv_update_tmpdir_f_m2)).strip(' "\n\r')
    assert proj_common_revision == 'develop'
    
    module2_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-src'],
                                        cwd=str(mpv_update_tmpdir_f_m2))
    module2_src_revision = remove_space(module2_src_revision)
    assert module2_src_revision == 'main'
    module2_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-data'],
                                         cwd=str(mpv_update_tmpdir_f_m2))
    module2_data_revision = remove_space(module2_data_revision)
    assert module2_data_revision == 'main'
    # nested_modules_git_manager_revision = check_output(
        # ['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'],
        # cwd=str(mpv_update_tmpdir_f_m2))
    # nested_modules_git_manager_revision = remove_space(nested_modules_git_manager_revision)
    # assert nested_modules_git_manager_revision == 'tag_nested'



# mpv_update_tmpdir_clone_depth
def test_mpv_update_clone_depth(mpv_update_tmpdir_clone_depth):
    print("\n\n\n\n--------------------------------")
    print(f"test_mpv_update_clone_depth: {test_mpv_update_clone_depth}")
    wct = mpv_update_tmpdir_clone_depth

    module1_src_apath = wct.joinpath("MODULE1/module1-src")
    module1_data_apath = wct.joinpath("MODULE1/module1-data")
    module2_src_apath = wct.joinpath("MODULE2/module2-src")
    module2_data_apath = wct.joinpath("MODULE2/module2-data")
    external1_apath = wct.joinpath("EXTERNAL/external1")

    # Validate that only repositories of F_M2 group where clone (include in nested west.yml)
    assert wct.exists()
    assert wct.is_dir()
    assert (module1_src_apath).is_dir()
    assert wct.joinpath("MODULE1/module1-src/main.cpp").is_file()
    assert (module1_data_apath).is_dir()
    assert (module2_src_apath).is_dir()
    assert wct.joinpath("MODULE2/module2-src/main.cpp").is_file()
    assert (module2_data_apath).is_dir()
    assert wct.joinpath("EXTERNAL/external1").is_dir()
    assert wct.joinpath("PROJECTS_COMMON/proj_common").is_dir()
    # assert wct.joinpath("EXTERNAL/NESTED/nested-modules-git-manager").is_dir()
    # assert not wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-data").is_dir()
    # assert not wct.joinpath("EXTERNAL/NESTED/NESTED_MODULE/module1-nested-src").is_dir()
    assert wct.joinpath("mpv-test-git-manager").is_dir()

    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'],
                                      cwd=str(wct)).strip(' "\n\r')
    assert proj_common_revision == 'develop'
    
    #########################
    ### check module1_src ###
    module1_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-src'],
                                        cwd=str(wct))
    module1_src_revision = remove_space(module1_src_revision)
    assert module1_src_revision == 'main'
    # check clone depth of module1_src - should be false
    is_shallow_module1_src = check_output(["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(module1_src_apath)).strip(' "\n\r')
    assert is_shallow_module1_src == 'false'
    module1_src_depth = check_output(['west', 'list', '-f "{clone_depth}"', 'module1-src'],
                                        cwd=str(wct)).strip(' "\n\r')
    assert module1_src_depth == 'None'

    ##########################
    ### check module1_data ###
    module1_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module1-data'],
                                         cwd=str(mpv_update_tmpdir_clone_depth))
    module1_data_revision = remove_space(module1_data_revision)
    assert module1_data_revision == 'main'
    # check clone depth of module1_data - should be true
    is_shallow_module1_data = check_output(["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(module1_data_apath)).strip(' "\n\r')
    assert is_shallow_module1_data == 'true'
    module1_data_depth = check_output(['west', 'list', '-f "{clone_depth}"', 'module1-data'],
                                        cwd=str(wct)).strip(' "\n\r')
    assert module1_data_depth == '1'


    #########################
    ### check module2_src ###
    module2_src_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-src'],
                                        cwd=str(mpv_update_tmpdir_clone_depth))
    module2_src_revision = remove_space(module2_src_revision)
    assert module2_src_revision == 'main'
    # check clone depth of module2_src - should be true
    is_shallow_module2_src = check_output(["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(module2_src_apath)).strip(' "\n\r')
    assert is_shallow_module2_src == 'true'
    module2_src_depth = check_output(['west', 'list', '-f "{clone_depth}"', 'module2-src'],
                                        cwd=str(wct)).strip(' "\n\r')
    assert module2_src_depth == '1'


    ##########################
    ### check module2_data ###
    module2_data_revision = check_output(['west', 'list', '-f "{revision}"', 'module2-data'],
                                        cwd=str(mpv_update_tmpdir_clone_depth))
    module2_data_revision = remove_space(module2_data_revision)
    assert module2_data_revision == 'main'
    # check clone depth of module2_data - should be false
    is_shallow_module2_data = check_output(["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(module2_data_apath)).strip(' "\n\r')
    assert is_shallow_module2_data == 'false'
    module2_data_depth = check_output(['west', 'list', '-f "{clone_depth}"', 'module2-data'],
                                        cwd=str(wct)).strip(' "\n\r')
    assert module2_data_depth == 'None'


    ##########################
    ### check external1 ###
    # Validate that the revision in cloned repositories is correct
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'],
                                      cwd=str(wct))
    external1_revision = remove_space(external1_revision)
    assert external1_revision == 'tag_1'
    # check clone depth of external1 - should be false
    is_shallow_external1 = check_output(["git", "rev-parse", "--is-shallow-repository"],
        cwd=str(external1_apath)).strip(' "\n\r')
    assert is_shallow_external1 == 'true'
    external1_depth = check_output(['west', 'list', '-f "{clone_depth}"', 'external1'],
                                        cwd=str(wct)).strip(' "\n\r')
    assert external1_depth == '1'
    # TODO: Currently all tags are clone, consider download only out tag with --narrow
    #       and then update the test on external1

    # TODO: Add test to branches test to check that the only the remote branch exist








    # nested_modules_git_manager_revision = check_output(
        # ['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'],
        # cwd=str(mpv_update_tmpdir_f_m2))
    # nested_modules_git_manager_revision = remove_space(nested_modules_git_manager_revision)
    # assert nested_modules_git_manager_revision == 'tag_nested'



def test_mpv_init(mpv_init_tmpdir):
    # Validate that the type of the project is source_data in mpv.yml
    print("\n\n\n\n--------------------------------")
    with open('mpv-test-git-manager/mpv.yml', 'r') as file:
        mpv_yaml = yaml.safe_load(file)
    assert mpv_yaml['manifest']['self']['merge-method'] == 'SOURCE_DATA'

    # all the repositories and the branches
    repo = ['MODULE1/module1-src', 'MODULE1/module1-data', 'MODULE2/module2-src',
            'MODULE2/module2-data']
    sub_branch = ['main', 'proj_1__1.0.0_dev', 'proj_1__1.0.0_integ', 'proj_1__1.0.0_main']

    # Validate that all new branches are in the sha, and it equals to sha of main branch
    print("Check new branches:")
    for rep in repo:
        # Get revision of remote branch dev 
        repo_path = mpv_init_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        rev_main = rev_parse(repo_path, 'remotes/origin/main')
        print(f"rev_main of {'remotes/origin/main'} is {rev_main}")

        # Validate the revision from remote is the for all branches
        # rep-depth = check_output(['west', 'list', '-f " {revision}"', f'{rep}']
        for sub in sub_branch:
            # If repo depth is 1 - there is no main branch
            # if rep-depth != '1':
            assert rev_main == rev_parse(repo_path, sub) 
            assert rev_main == rev_parse(repo_path, 'remotes/origin/' + sub)

    # Validate that the revision of repositories of type external is the same tag as exist in west.yml of main branch
    print(f"Validate external repos {repo_path}") 
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=mpv_init_tmpdir)
    # nested_modules_revision = check_output(['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'], cwd=mpv_init_tmpdir)
    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'],
                                      cwd=str(mpv_init_tmpdir))

    external1_tag = check_output(['git', 'describe'], cwd=mpv_init_tmpdir.joinpath('EXTERNAL/external1'))
    # nested_modules_tag = check_output(['git', 'describe'], cwd=mpv_init_tmpdir.joinpath('EXTERNAL/NESTED/nested-modules-git-manager'))
    assert external1_revision.strip(' "\n\r') == external1_tag.strip(' "\n\r')
    # assert nested_modules_revision.strip(' "\n\r') == nested_modules_tag.strip(' "\n\r')
    assert proj_common_revision.strip(' "\n\r') == 'develop'

    proj_common_repo_status = check_output(['git', 'status', '-bz'], cwd=mpv_init_tmpdir.joinpath('PROJECTS_COMMON/proj_common'))
    assert "develop" in proj_common_repo_status


def test_mpv_new_proj(mpv_new_proj_tmpdir):
    print("\n\n\n\n--------------------------------")
    print(f"test_mpv_new_proj: {mpv_new_proj_tmpdir}")

    ################ Test dummy_s__1.0.0 ############################
    print("The fixture mpv_new_proj_tmpdir finish with create dummy_s 1.0.0 - check it first")
    # Validate that the type of the project is data in mpv.yml
    print("Validate that the type of the repo is SOURCE_DATA:")
    with open('mpv-test-git-manager/mpv.yml', 'r') as file:
        mpv_yaml = yaml.safe_load(file)
    assert mpv_yaml['manifest']['self']['merge-method'] == 'SOURCE_DATA'

    # all the repositories and the branches
    repo = ['MODULE1/module1-src', 'MODULE1/module1-data', 'MODULE2/module2-src',
            'MODULE2/module2-data']
    sub_branch = ['proj_1__1.0.0_dev', 'dummy_s__1.0.0_dev', 'dummy_s__1.0.0_integ', 'dummy_s__1.0.0_main']

    # Validate that all new branches are in the sha, and it equals to sha of main branch
    print("Check new branches of dummy_s__1.0.0:")
    for rep in repo:
        # Get revision of remote branch dev 
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        rev_proj_100 = rev_parse(repo_path, 'remotes/origin/proj_1__1.0.0_dev')
        print(f"rev_proj_100 of {'remotes/origin/proj_1__1.0.0_dev'} is {rev_proj_100}")

        # Validate the revision from remote is the for all branches
        for sub in sub_branch:
            assert rev_proj_100 == rev_parse(repo_path, sub) 
            assert rev_proj_100 == rev_parse(repo_path, 'remotes/origin/' + sub)

    # Validate that the revision of repositories of type external is the same tag as exist in west.yml of main branch
    print(f"Validate external repos {repo_path}") 
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=mpv_new_proj_tmpdir)
    # nested_modules_revision = check_output(['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'], cwd=mpv_new_proj_tmpdir)

    external1_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/external1'))
    # nested_modules_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/NESTED/nested-modules-git-manager'))
    assert external1_revision.strip(' "\n\r') == external1_tag.strip(' "\n\r')
    # assert nested_modules_revision.strip(' "\n\r') == nested_modules_tag.strip(' "\n\r')

    proj_common_repo_status = check_output(['git', 'status', '-bz'], cwd=mpv_new_proj_tmpdir.joinpath('PROJECTS_COMMON/proj_common'))
    assert "develop" in proj_common_repo_status

    ################ Test dummy_d__1.0.0 ############################

    print("Check dummy_d 1.0.0")
    print("Call mpv-update to dummy_d__1.0.0_dev")
    cmd('mpv-update --full-clone --mr dummy_d__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    # Validate that the type of the project is data in mpv.yml
    with open('mpv-test-git-manager/mpv.yml', 'r') as file:
        mpv_yaml = yaml.safe_load(file)
    assert mpv_yaml['manifest']['self']['merge-method'] == 'DATA'

    # all the repositories and the branches
    repo_data = ['MODULE1/module1-data', 'MODULE2/module2-data']
    repo_src = ['MODULE1/module1-src', 'MODULE2/module2-src']
    sub_branch_data = ['proj_1__1.0.0_dev', 'dummy_d__1.0.0_dev', 'dummy_d__1.0.0_integ', 'dummy_d__1.0.0_main']

    # Validate that all new branches in data repos are in the sha, and it equals to sha of main branch
    print("Check new branches of dummy_d__1.0.0 in data repos:")
    for rep in repo_data:
        # Get revision of remote branch dev 
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        rev_proj_100 = rev_parse(repo_path, 'remotes/origin/proj_1__1.0.0_dev')
        print(f"rev_proj_100 of {'remotes/origin/proj_1__1.0.0_dev'} is {rev_proj_100}")

        # Validate the revision from remote is the for all branches
        for sub in sub_branch:
            assert rev_proj_100 == rev_parse(repo_path, sub)
            assert rev_proj_100 == rev_parse(repo_path, 'remotes/origin/' + sub)

    # Validate that source repos don't have new branches, 
    # but only sha as origin branch - proj_1__1.0.0_dev
    print("Check repos of source for dummy_d__1.0.0 project:")
    for rep in repo_src:
        # Validate the repo is in "detached HEAD"
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        repo_status = check_output(['git', 'status', '-bz'], cwd=repo_path)
        repo_status_expected = "## HEAD (no branch)"
        assert repo_status.strip("\x00") == repo_status_expected
        
        # Validate that the revision of current working tree is save as proj_1__1.0.0_dev
        rev_proj_100 = rev_parse(repo_path, 'remotes/origin/proj_1__1.0.0_dev')
        rev_HEAD = rev_parse(repo_path, 'HEAD')
        assert rev_proj_100 == rev_HEAD

        # Validate that the repo doesn't have branches of dummy_d
        repo_branch = check_output(['git', 'branch', '-a'], cwd=repo_path)
        assert "dummy_d" not in repo_branch
        


    # Validate that the revision of repositories of type external is the same tag as exist in west.yml of main branch
    print(f"Validate external repos {repo_path}") 
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=mpv_new_proj_tmpdir)
    # nested_modules_revision = check_output(['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'], cwd=mpv_new_proj_tmpdir)

    external1_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/external1'))
    # nested_modules_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/NESTED/nested-modules-git-manager'))
    assert external1_revision.strip(' "\n\r') == external1_tag.strip(' "\n\r')
    # assert nested_modules_revision.strip(' "\n\r') == nested_modules_tag.strip(' "\n\r')

    proj_common_repo_status = check_output(['git', 'status', '-bz'], cwd=mpv_new_proj_tmpdir.joinpath('PROJECTS_COMMON/proj_common'))
    assert "develop" in proj_common_repo_status


def test_mpv_new_proj_tag(mpv_new_proj_tmpdir):
    print("\n\n\n\n--------------------------------")
    print(f"test_mpv_new_proj_tag: {mpv_new_proj_tmpdir}")

    git_manager_apath = mpv_new_proj_tmpdir.joinpath("mpv-test-git-manager")

    print("Call mpv-update to dummy_d__1.0.0_dev")
    cmd('mpv-update --full-clone --mr dummy_d__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    full_tag = "mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj"
    print(f"test_mpv_new_proj_tag() - Create the tag: {full_tag}")
    cmd('mpv-tag -m "tag from test_mpv_tag in branch dummy_d__1.0.0_dev" mpv_test_new_proj', cwd=str(mpv_new_proj_tmpdir))

    print("Call mpv-update to mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj")
    cmd(f'mpv-update --full-clone --mr {full_tag}', cwd=str(mpv_new_proj_tmpdir))

    ################ Test tag_d 1.0.0 ############################

    print("Create new project tag_d 1.0.0 from the tag {full_tag}")
    cmd(f'mpv-new-proj {full_tag} tag_d 1.0.0', cwd=str(mpv_new_proj_tmpdir))
    print("Call mpv-update to tag_d 1.0.0")
    cmd('mpv-update --full-clone --mr tag_d__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    # Validate that the type of the repo is DATA
    print("Validate that the type of the repo is DATA:")
    with open('mpv-test-git-manager/mpv.yml', 'r') as file:
        mpv_yaml = yaml.safe_load(file)
    assert mpv_yaml['manifest']['self']['merge-method'] == 'DATA'

    # all the repositories and the branches
    repo_data = ['MODULE1/module1-data', 'MODULE2/module2-data']
    repo_src = ['MODULE1/module1-src', 'MODULE2/module2-src']
    sub_branch_data = ['tag_d__1.0.0_dev', 'tag_d__1.0.0_integ', 'tag_d__1.0.0_main']

    # Validate that all new branches in data repos are in the sha, and it equals to sha of main branch
    print("Check new branches of tag_d__1.0.0 in data repos:")
    for rep in repo_data:
        # Get revision of remote branch dev 
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        # Use ^{commit} - to dereference to the commit SHA (and not the tag SHA)
        rev_proj_100 = rev_parse(repo_path, f'tags/{full_tag}^{{commit}}')
        print(f"rev_proj_100 of tags/{full_tag} is {rev_proj_100}")

        # Validate the revision from remote is the for all branches
        for sub in sub_branch_data:
            assert rev_proj_100 == rev_parse(repo_path, sub)
            assert rev_proj_100 == rev_parse(repo_path, 'remotes/origin/' + sub)

    # Validate that source repos don't have new branches, 
    # but only sha as origin tag: mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj
    print("Check repos of source for tag_d__1.0.0 project:")
    for rep in repo_src:
        # Validate the repo is in "detached HEAD"
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        repo_status = check_output(['git', 'status', '-bz'], cwd=repo_path)
        repo_status_expected = "## HEAD (no branch)"
        assert repo_status.strip("\x00") == repo_status_expected
        
        # Validate that the revision of current working tree is save as mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj
        rev_proj_100 = rev_parse(repo_path, f'tags/{full_tag}^{{commit}}')
        rev_HEAD = rev_parse(repo_path, 'HEAD')
        assert rev_proj_100 == rev_HEAD

        # Validate that the repo doesn't have branches of dummy_d
        repo_branch = check_output(['git', 'branch', '-a'], cwd=repo_path)
        assert "tag_d__1.0.0" not in repo_branch

    # Validate that the revision of repositories of type external is the same tag as exist in west.yml of main branch
    print(f"Validate external repos {repo_path}") 
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=mpv_new_proj_tmpdir)
    # nested_modules_revision = check_output(['west', 'list', '-f "{revision}"', 'nested-modules-git-manager'], cwd=mpv_new_proj_tmpdir)

    external1_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/external1'))
    # nested_modules_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/NESTED/nested-modules-git-manager'))
    assert external1_revision.strip(' "\n\r') == external1_tag.strip(' "\n\r')
    assert external1_revision.strip(' "\n\r') == "tag_1"
    # assert nested_modules_revision.strip(' "\n\r') == nested_modules_tag.strip(' "\n\r')

    # proj common should be in original tag (mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj), 
    # because the original status should not be changed
    proj_common_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('PROJECTS_COMMON/proj_common'))
    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'], cwd=mpv_new_proj_tmpdir)
    assert proj_common_tag.strip(' "\n\r') == proj_common_revision.strip(' "\n\r')
    assert proj_common_revision.strip(' "\n\r') == full_tag


    ################ Test tag_s 1.0.0 ############################

    print("Create new project tag_s 1.0.0 from the tag {full_tag}")
    cmd(f'mpv-new-proj -t s {full_tag} tag_s 1.0.0', cwd=str(mpv_new_proj_tmpdir))
    print("Call mpv-update to tag_s 1.0.0")
    cmd('mpv-update --full-clone --mr tag_s__1.0.0_dev', cwd=str(mpv_new_proj_tmpdir))

    print("Validate that the type of the repo is SOURCE_DATA:")
    with open('mpv-test-git-manager/mpv.yml', 'r') as file:
        mpv_yaml = yaml.safe_load(file)
    assert mpv_yaml['manifest']['self']['merge-method'] == 'SOURCE_DATA'

    # all the repositories and the branches
    repo = ['MODULE1/module1-src', 'MODULE1/module1-data', 'MODULE2/module2-src',
            'MODULE2/module2-data']
    sub_branch = ['tag_s__1.0.0_dev', 'tag_s__1.0.0_integ', 'tag_s__1.0.0_main']

    print("Check new branches of tag_s__1.0.0:")
    for rep in repo:
        # Get revision of remote branch dev 
        repo_path = mpv_new_proj_tmpdir.joinpath(rep)
        print(f"path of repo is {repo_path}") 
        rev_proj_100 = rev_parse(repo_path, f'tags/{full_tag}^{{commit}}')
        print(f"rev_proj_100 of tags/{full_tag} is {rev_proj_100}")

        # Validate the revision from remote is the for all branches
        for sub in sub_branch:
            assert rev_proj_100 == rev_parse(repo_path, sub) 
            assert rev_proj_100 == rev_parse(repo_path, 'remotes/origin/' + sub)

    # Validate that the revision of repositories of type external is the same tag as exist in west.yml of main branch
    print(f"Validate external repos {repo_path}") 
    external1_revision = check_output(['west', 'list', '-f "{revision}"', 'external1'], cwd=mpv_new_proj_tmpdir)

    external1_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/external1'))
    # nested_modules_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('EXTERNAL/NESTED/nested-modules-git-manager'))
    assert external1_revision.strip(' "\n\r') == external1_tag.strip(' "\n\r')
    assert external1_revision.strip(' "\n\r') == "tag_1"
    # assert nested_modules_revision.strip(' "\n\r') == nested_modules_tag.strip(' "\n\r')

    # proj common should be in original tag (mpv-tag_br-dummy_d__1.0.0_dev__mpv_test_new_proj), 
    # because the original status should not be changed
    proj_common_tag = check_output(['git', 'describe'], cwd=mpv_new_proj_tmpdir.joinpath('PROJECTS_COMMON/proj_common'))
    proj_common_revision = check_output(['west', 'list', '-f "{revision}"', 'proj_common'], cwd=mpv_new_proj_tmpdir)
    assert proj_common_tag.strip(' "\n\r') == proj_common_revision.strip(' "\n\r')
    assert proj_common_revision.strip(' "\n\r') == full_tag



def test_mpv_merge(mpv_merge_tmpdir):
    '''
    The files that should be validate are:
    1. mpv-test-git-manager -> west.yml 
        a. in data merge: MODULE1/module1-src -> src1_conflict.cpp: sha from proj_1__1.0.0_dev
           in data source_branch merge: should be the branch
        b. EXTERNAL/external1 -> external.cpp: tag_2
    2. MODULE1/module1-src -> src1_conflict.cpp (from proj_1__1.0.0_dev)
                              src1_oldfile.cpp  (new file from proj_1__1)
       in source_branch merge: validate that the sha of MODULE1/module1-src is the same as sha_module1_src
       in data merge: should be like module2-data
    3. MODULE2/module2-data -> data2_conflict.cpp (merge conflict)
                               data2_newfile.cpp (only in this branch)
                               data2_oldfile.cpp (new file from proj_1__1)
    4. EXTERNAL/external1 -> external.cpp (tag_2)
    '''
    print("\n\n\n\n--------------------------------")
    print("")
    print(f"test_mpv_merge(): mpv_merge_tmpdir: {mpv_merge_tmpdir}")

    #########################################
    ### Validate merge to dummy_d__1.0.0_dev
    #########################################
    print(f"test_mpv_merge: first check dummy_d__1.0.0_dev")
    cmd('mpv-merge proj_1__1.0.0_dev dummy_d__1.0.0_dev', cwd=mpv_merge_tmpdir)
    
    print(f"call validate_merge() for data merge")
    validate_merge(mpv_merge_tmpdir, True)

    #########################################
    ### Validate merge to dummy_s__1.0.0_dev
    #########################################
    print(f"before mpv update to dummy_s - reset all repos")
    cmd('forall -c "git reset --hard"', cwd=mpv_merge_tmpdir)

    print(f"test_mpv_merge_to_data: first check dummy_s__1.0.0_dev")
    cmd('mpv-merge proj_1__1.0.0_dev dummy_s__1.0.0_dev', cwd=mpv_merge_tmpdir)

    print(f"call validate_merge() for data merge")
    validate_merge(mpv_merge_tmpdir, False)



def validate_merge(base_path, merge_data: bool):
    '''
    The notes to test_mpv_merge() method, 
    detail all expected merge results
    '''

    # The output of git status -s return string like:
    # AA src1_conflict.cpp
    # The first 2 chars can be one of: D or A or U.
    # So, build regular expression for conflict string that say:
    # The characters D or A or U ("[DAU]") must be in the first element to second element of the string ("{2}"):
    p = re.compile("[DAU]{2}")
    
    print("")
    print(f"validate_merge(): base_path: {base_path}, type of merge, merge_data: {merge_data}")

    git_manager_apath = base_path.joinpath("mpv-test-git-manager")
    module1_src_apath = base_path.joinpath("MODULE1/module1-src")
    module2_data_apath = base_path.joinpath("MODULE2/module2-data")
    external1_apath = base_path.joinpath("EXTERNAL/external1")
    proj_common_apath = base_path.joinpath("PROJECTS_COMMON/proj_common")
    
    #########
    # 1. mpv-test-git-manager -> west.yml 
    # a. MODULE1/module1-src -> src1_conflict.cpp: sha from proj_1__1.0.0_dev
    source_file = git_manager_apath.joinpath("west.yml")
    source_data = source_file.read_text()
    source_data = yaml.safe_load(source_data)
    
    sha_module1_src_west = source_data['manifest']['projects'][1]['revision']
    print(f"sha of MODULE1/module1-src in west.yml: {sha_module1_src_west}")
    if merge_data == True:
        print(f"In data merge (copy sha), check only sha of the repo MODULE1/module1-src")
        sha_module1_src = rev_parse('MODULE1/module1-src', 'proj_1__1.0.0_dev')
        print(f"sha of MODULE1/module1-src, proj_1__1.0.0_dev: {sha_module1_src}")
        assert sha_module1_src_west == sha_module1_src
    else:
        print(f"In source_branch merge, check that the revision is the branch")
        assert sha_module1_src_west == "dummy_s__1.0.0_dev"
    
    # b. EXTERNAL/external1 -> external.cpp: tag_2
    external1_tag_west = source_data['manifest']['projects'][5]['revision']
    print(f"external1_tag_west = {external1_tag_west} (should be tag_2)")
    assert external1_tag_west == 'tag_2'
    
    # TODO: add validation to proj_common

    #########
    # 2. MODULE1/module1-src:
    # src1_conflict.cpp (from proj_1__1.0.0_dev)
    # data2_oldfile.cpp (new file from proj_1__1)
    if merge_data == True:
        print(f"In data merge (copy sha), check only sha of the repo MODULE1/module1-src")
        # validate that the sha of MODULE1/module1-src is the same as sha_module1_src
        sha_module1_src_head = rev_parse('MODULE1/module1-src', 'HEAD')
        assert sha_module1_src == sha_module1_src_head
    else:
        print(f"In source_branch merge (regual git merge), check results of git merge")
        src1_conflict_status = check_output([GIT, 'status', 'src1_conflict.cpp', '-s'], cwd=str(module1_src_apath))
        src1_conflict_status_sub = src1_conflict_status[0:2]
        #src1_conflict_expected = "AA src1_conflict.cpp"
        print(f"git status of src1_conflict.cpp: {src1_conflict_status}")
        print(f"2 first chars of git status of src1_conflict.cpp: {src1_conflict_status_sub}")
        #print(f"git status of src1_conflict.cpp should be: {src1_conflict_expected}")
        
        # src1_newfile.cpp (only in this branch - empty string)
        src1_newfile_status = check_output([GIT, 'status', 'src1_newfile.cpp', '-s'], cwd=str(module1_src_apath))
        src1_newfile_expected = ""
        print(f"git status of src1_newfile.cpp: {src1_newfile_status}")
        print(f"git status of src1_newfile.cpp should be: {src1_newfile_expected}")
        
        # data2_oldfile.cpp (new file from proj_1__1 - A)
        src1_oldfile_status = check_output([GIT, 'status', 'src1_oldfile.cpp', '-s'], cwd=module1_src_apath)
        src1_oldfile_expected = "A  src1_oldfile.cpp"
        print(f"git status of src1_oldfile.cpp: {src1_oldfile_status}")
        print(f"git status of src1_oldfile.cpp should be: {src1_oldfile_expected}")

        #assert src1_conflict_status.strip() == src1_conflict_expected
        assert p.match(src1_conflict_status_sub) != None
        assert src1_newfile_status.strip() == src1_newfile_expected
        assert src1_oldfile_status.strip() == src1_oldfile_expected
            
    
    ########
    # 3. MODULE2/module2-data:
    # data2_conflict.cpp (merge conflict - AA)
    data2_conflict_status = check_output([GIT, 'status', 'data2_conflict.cpp', '-s'], cwd=str(module2_data_apath))
    data2_conflict_status_sub = data2_conflict_status[0:2]
    # data2_conflict_expected = "AA data2_conflict.cpp"
    print(f"git status of data2_conflict.cpp: {data2_conflict_status}")
    print(f"2 first chars of git status of data2_conflict.cpp: {data2_conflict_status_sub}")
    #print(f"git status of data2_conflict.cpp should be: {data2_conflict_expected}")
    
    # data2_newfile.cpp (only in this branch - empty string)
    data2_newfile_status = check_output([GIT, 'status', 'data2_newfile.cpp', '-s'], cwd=str(module2_data_apath))
    data2_newfile_expected = ""
    print(f"git status of data2_newfile.cpp: {data2_newfile_status}")
    print(f"git status of data2_newfile.cpp should be: {data2_newfile_expected}")
    
    # data2_oldfile.cpp (new file from proj_1__1 - A)
    data2_oldfile_status = check_output([GIT, 'status', 'data2_oldfile.cpp', '-s'], cwd=module2_data_apath)
    data2_oldfile_expected = "A  data2_oldfile.cpp"
    print(f"git status of data2_oldfile.cpp: {data2_oldfile_status}")
    print(f"git status of data2_oldfile.cpp should be: {data2_oldfile_expected}")
    
    assert p.match(data2_conflict_status_sub) != None
    assert data2_newfile_status.strip() == data2_newfile_expected
    assert data2_oldfile_status.strip() == data2_oldfile_expected

    ########
    # 4. EXTERNAL/external1 -> external.cpp (tag_2)
    #external1_status_b = check_output([GIT, 'status', '-b'], cwd=external1_apath)
    external1_tag = check_output([GIT, 'describe'], cwd=external1_apath)
    
    print(f"git describe (the tag) of external1 is: {external1_tag}")
    print(f"tag of  external1 is: {external1_tag_west}")
    assert external1_tag_west in external1_tag

    # TODO: add validation to proj_common




#####################################


def test_mpv_params_merge(mpv_merge_tmpdir):
    '''
    The files that should be validate are:
    1. mpv-test-git-manager -> west.yml 
        a. in data merge: MODULE1/module1-src -> src1_conflict.cpp: sha from proj_1__1.0.0_dev
           in data source_branch merge: should be the branch
        b. EXTERNAL/external1 -> external.cpp: tag_2
    2. MODULE1/module1-src -> src1_conflict.cpp (from proj_1__1.0.0_dev)
                              src1_oldfile.cpp  (new file from proj_1__1)
       in source_branch merge: validate that the sha of MODULE1/module1-src is the same as sha_module1_src
       in data merge: should be like module2-data
    3. MODULE2/module2-data -> data2_conflict.cpp (merge conflict)
                               data2_newfile.cpp (only in this branch)
                               data2_oldfile.cpp (new file from proj_1__1)
    4. EXTERNAL/external1 -> external.cpp (tag_2)
    '''
    print("\n\n\n\n--------------------------------")
    print(f"test_mpv_params_merge(): mpv_merge_tmpdir: {mpv_merge_tmpdir}")

    #####################################################
    ### Validate merge to dummy_d__1.0.0_dev with params
    #####################################################
    print(f"test_mpv_params_merge: first check dummy_d__1.0.0_dev")
    print('Run the command: mpv-merge -o module2-data "-s ours" -t DATA proj_1__1.0.0_dev dummy_d__1.0.0_dev')
    cmd('mpv-merge -o module2-data "-s ours" -t DATA -t module1-src proj_1__1.0.0_dev dummy_d__1.0.0_dev', cwd=mpv_merge_tmpdir)
    
    print(f"call validate_params_merge() for data merge")
    validate_params_merge(mpv_merge_tmpdir)


def validate_params_merge(base_path):
    '''
    The notes to validate_params_merge() method, 
    detail all expected merge results
    '''

    # The output of git status -s return string like:
    # AA src1_conflict.cpp
    # The first 2 chars can be one of: D or A or U.
    # So, build regular expression for confliect string that say:
    # The characters D or A or U ("[DAU]") must be in the first element to secone element of the string ("{2}"):
    p = re.compile("[DAU]{2}")
    
    print("")
    print(f"validate_params_merge(): base_path: {base_path}")

    git_manager_apath = base_path.joinpath("mpv-test-git-manager")
    module2_src_apath = base_path.joinpath("MODULE2/module2-src")
    module2_data_apath = base_path.joinpath("MODULE2/module2-data")
    external1_apath = base_path.joinpath("EXTERNAL/external1")
    proj_common_apath = base_path.joinpath("PROJECTS_COMMON/proj_common")
    
    #########
    # 1. mpv-test-git-manager -> west.yml 
    # a. MODULE1/module1-src -> src1_conflict.cpp: sha from proj_1__1.0.0_dev
    source_file = git_manager_apath.joinpath("west.yml")
    source_data = source_file.read_text()
    source_data = yaml.safe_load(source_data)
    
    sha_module1_src_west = source_data['manifest']['projects'][1]['revision']
    print(f"sha of MODULE1/module1-src in west.yml: {sha_module1_src_west}")
#    if merge_data == True:
    print(f"In merge of DATA only (copy sha), check that sha of the repo MODULE1/module1-src didn't changed - get the previous SHA")
    sha_module1_src = rev_parse('MODULE1/module1-src', 'proj_1__1.0.0_dev')
    print(f"sha of MODULE1/module1-src, proj_1__1.0.0_dev: {sha_module1_src}")
    assert sha_module1_src_west == sha_module1_src
    
    # b. EXTERNAL/external1 -> external.cpp: tag_1
    external1_tag_west = source_data['manifest']['projects'][5]['revision']
    print(f"external1_tag_west = {external1_tag_west} (should be tag_1)")
    assert external1_tag_west == 'tag_1'
    
    # TODO: add validation to proj_common

    #########
    # TODO: check if this should be true: it might be that we should move all repos to dest branch,
    #       include the repos that should not merge now.
    # ##. MODULE2/module2-src:
    print(f"MODULE2/module2-src - because this repo don't merge - the branch shouldn't change")
    # validate that MODULE2/module2-src is still in the branch.
    src2_branch = check_output([GIT, 'status', '-sb'], cwd=str(module2_src_apath))
    last_sr2_branch = "dummy_s__1.0.0_dev"
    assert last_sr2_branch in src2_branch
            
    
    ########
    # 3. MODULE2/module2-data:
    # data2_conflict.cpp (shouldn't has merge conflict - because using -s ours)
    data2_conflict_status = check_output([GIT, 'status', 'data2_conflict.cpp', '-s'], cwd=str(module2_data_apath))
    #data2_conflict_status_sub = data2_conflict_status[0:2]
    data2_conflict_expected = ""
    print(f"git status of data2_conflict.cpp: {data2_conflict_status}")
    #print(f"2 first chars of git status of data2_conflict.cpp: {data2_conflict_status_sub}")
    print(f"git status of data2_conflict.cpp should be: {data2_conflict_expected}")
    
    # data2_newfile.cpp (only in this branch - empty string)
    data2_newfile_status = check_output([GIT, 'status', 'data2_newfile.cpp', '-s'], cwd=str(module2_data_apath))
    data2_newfile_expected = ""
    print(f"git status of data2_newfile.cpp: {data2_newfile_status}")
    print(f"git status of data2_newfile.cpp should be: {data2_newfile_expected}")
    
    # data2_oldfile.cpp (should not take the new file from proj_1__1 - because using - "s ours")
    data2_oldfile_status = check_output([GIT, 'status', 'data2_oldfile.cpp', '-s'], cwd=module2_data_apath)
    data2_oldfile_expected = ""
    print(f"git status of data2_oldfile.cpp: {data2_oldfile_status}")
    print(f"git status of data2_oldfile.cpp should be: {data2_oldfile_expected}")
    
    assert data2_conflict_status.strip() ==  data2_conflict_expected
    assert data2_newfile_status.strip() == data2_newfile_expected
    assert data2_oldfile_status.strip() == data2_oldfile_expected

    ########
    # 4. EXTERNAL/external1 -> external.cpp (tag_1)
    external1_tag = check_output([GIT, 'describe'], cwd=external1_apath)
    print(f"git describe of external1 is: {external1_tag}")
    print(f"tag of  external1 is: {external1_tag_west}")
    assert external1_tag_west in external1_tag



###########################################################################################
def test_mpv_tag(mpv_update_tmpdir):
    print("\n\n\n\n--------------------------------")
    print("test_mpv_tag()")
    
    manifest_apath = mpv_update_tmpdir.joinpath("mpv-test-git-manager")
    mpv_git_west_commands_apath = mpv_update_tmpdir.joinpath("GIT-MNGR/mpv-git-west-commands")
    module1_src_apath = mpv_update_tmpdir.joinpath("MODULE1/module1-src")
    module1_data_apath = mpv_update_tmpdir.joinpath("MODULE1/module1-data")
    module2_src_apath = mpv_update_tmpdir.joinpath("MODULE2/module2-src")
    module2_data_apath = mpv_update_tmpdir.joinpath("MODULE2/module2-data")
    external1_apath = mpv_update_tmpdir.joinpath("EXTERNAL/external1")
    proj_common_apath = mpv_update_tmpdir.joinpath("PROJECTS_COMMON/proj_common")

    rprint("test_mpv_tag() - print west.yml:")
    west_file = manifest_apath.joinpath("west.yml")
    west_file_fd = open(west_file, "r+")
    rprint(f"{west_file_fd.read()}")
    west_file_fd.close()

    proj_mainfest_repo_status = check_output(['git', 'status'], cwd=manifest_apath)
    rprint(f"BEFORE tag proj_mainfest_repo_status: {proj_mainfest_repo_status}")

    full_tag = "mpv-tag_br-main__mpv_tag1"
    print(f"test_mpv_tag() - Create the tag: {full_tag}")
    cmd('mpv-tag -m "tag from test_mpv_tag" mpv_tag1', cwd=str(mpv_update_tmpdir))

    print(f"test_mpv_tag() - Call mpv-update to set tag: {full_tag}")
    cmd(f'mpv-update --mr {full_tag}', cwd=str(mpv_update_tmpdir))

    # Validate that each repo checkout to the correct tag,
    # and the the tag come from previous branch
    
    #########################
    # mpv-test-git-manager 
    print("test_mpv_tag() - Check mpv-test-git-manager repo")
    manifest_tag = check_output([GIT, 'describe'], cwd=str(manifest_apath))
    assert f"{full_tag}" in manifest_tag
    sha_prev = rev_parse(manifest_apath, 'main')
    sha_current = rev_parse(manifest_apath, 'HEAD')
    sha_prev_prev = rev_parse(manifest_apath, 'main~')
    assert sha_prev != sha_current
    assert sha_prev_prev == sha_current

    # mpv_git_west_commands_tag = check_output([GIT, 'describe'], cwd=str(mpv_git_west_commands_apath))
    # assert f"{full_tag}" in mpv_git_west_commands_tag

    #########################
    # MODULE1/module1-src
    print("test_mpv_tag() - Check module1_src repo")
    module1_src_tag = check_output([GIT, 'describe'], cwd=str(module1_src_apath))
    assert f"{full_tag}" in module1_src_tag
    sha_prev = rev_parse(module1_src_apath, 'main')
    sha_current = rev_parse(module1_src_apath, 'HEAD')
    assert sha_prev == sha_current

    #########################
    # MODULE1/module1_data
    print("test_mpv_tag() - Check module1_data repo")
    module1_data_tag = check_output([GIT, 'describe'], cwd=str(module1_data_apath))
    assert f"{full_tag}" in module1_data_tag
    sha_prev = rev_parse(module1_data_apath, 'main')
    sha_current = rev_parse(module1_data_apath, 'HEAD')
    assert sha_prev == sha_current

    #########################
    # MODULE2/module2_src
    print("test_mpv_tag() - Check module2_src repo")
    module2_src_tag = check_output([GIT, 'describe'], cwd=str(module2_src_apath))
    assert f"{full_tag}" in module2_src_tag
    sha_prev = rev_parse(module2_src_apath, 'main')
    sha_current = rev_parse(module2_src_apath, 'HEAD')
    assert sha_prev == sha_current

    #########################
    # MODULE2/module2_data
    print("test_mpv_tag() - Check module2_data repo")
    module2_data_tag = check_output([GIT, 'describe'], cwd=str(module2_data_apath))
    assert f"{full_tag}" in module2_data_tag
    sha_prev = rev_parse(module2_data_apath, 'main')
    sha_current = rev_parse(module2_data_apath, 'HEAD')
    assert sha_prev == sha_current

    #########################
    # EXTERNAL/external1
    print("test_mpv_tag() - Check external1 repo")
    external1_tag = check_output([GIT, 'describe'], cwd=str(external1_apath))
    assert f"tag_1" in external1_tag
    # The current tag should be the same as previous tag - no need to check SHA

    #########################
    # PROJECTS_COMMON/proj_common
    print("test_mpv_tag() - Check proj_common repo")
    proj_common_tag = check_output([GIT, 'describe'], cwd=str(proj_common_apath))
    assert f"{full_tag}" in proj_common_tag
    sha_prev = rev_parse(proj_common_apath, 'develop')
    sha_current = rev_parse(proj_common_apath, 'HEAD')
    assert sha_prev == sha_current


def test_mpv_manifest(mpv_init_tmpdir):
    print("\n\n\n\n--------------------------------")
    print("test_mpv_manifest()")

    print("Call mpv-manifest")
    # cmd('mpv-manifest -a module2-data clonee-depth 1', cwd=str(mpv_init_tmpdir))
    before_command_list = cmd('list -f "{name} {clone_depth}"')
    cmd('-v mpv-manifest -a module2-data clone-depth 1 -a mpv-git-west-commands clone-depth 1', cwd=str(mpv_init_tmpdir))

    sub_branch = ['main', 'proj_1__1.0.0_dev', 'proj_1__1.0.0_integ', 'proj_1__1.0.0_main']

    for branch in sub_branch:
        print(f"Checkout to {branch}")
        manifest_apath = mpv_init_tmpdir.joinpath("mpv-test-git-manager")
        checkout_branch(manifest_apath, branch)

        after_command_list = cmd('list -f "{name} {clone_depth}"')
        assert after_command_list != before_command_list

        adapt_before_list = before_command_list.replace("module2-data None", "module2-data 1").replace("mpv-git-west-commands None", "mpv-git-west-commands 1")
        assert after_command_list == adapt_before_list


