#!/usr/bin/env python
"""Module ci-scripts AppVeyor unit tests
"""

# SET=test00 in the environment (.appveyor.yml) runs the tests in this script
# all other jobs are started as compile jobs

from __future__ import print_function

import sys, os, shutil, fileinput
import distutils.util
import re
import subprocess as sp
import unittest
import logging
from argparse import Namespace

builddir = os.getcwd()

def find_in_file(regex, filename):
    file = open (filename, "r")
    for line in file:
        if re.search(regex, line):
            return True
    return False

def getStringIO():
    if (sys.version_info > (3, 0)):
        import io
        return io.StringIO()
    else:
        import StringIO
        return StringIO.StringIO()

sys.path.append('appveyor')
import do

# we're working with tags (detached heads) a lot: suppress advice
do.call_git(['config', '--global', 'advice.detachedHead', 'false'])

class TestSourceSet(unittest.TestCase):

    def setUp(self):
        os.environ['SETUP_PATH'] = '.:appveyor'
        if 'BASE' in os.environ:
            del os.environ['BASE']
        do.clear_lists()
        os.chdir(builddir)

    def test_EmptySetupDirsPath(self):
        del os.environ['SETUP_PATH']
        self.assertRaisesRegexp(NameError, '\(SETUP_PATH\) is empty', do.source_set, 'test01')

    def test_InvalidSetupName(self):
        self.assertRaisesRegexp(NameError, 'does not exist in SETUP_PATH', do.source_set, 'xxdoesnotexistxx')

    def test_ValidSetupName(self):
        capturedOutput = getStringIO()
        sys.stdout = capturedOutput
        do.source_set('test01')
        sys.stdout = sys.__stdout__
        self.assertEqual(do.setup['BASE'], '7.0', 'BASE was not set to \'7.0\'')

    def test_SetupDoesNotOverridePreset(self):
        os.environ['BASE'] = 'foo'
        capturedOutput = getStringIO()
        sys.stdout = capturedOutput
        do.source_set('test01')
        sys.stdout = sys.__stdout__
        self.assertEqual(do.setup['BASE'], 'foo',
                         'Preset BASE was overridden by test01 setup (expected \'foo\' got {0})'
                         .format(do.setup['BASE']))

    def test_IncludeSetupFirstSetWins(self):
        capturedOutput = getStringIO()
        sys.stdout = capturedOutput
        do.source_set('test02')
        sys.stdout = sys.__stdout__
        self.assertEqual(do.setup['BASE'], 'foo',
                         'BASE set in test02 was overridden by test01 setup (expected \'foo\' got {0})'
                         .format(do.setup['BASE']))
        self.assertEqual(do.setup['FOO'], 'bar', 'Setting of single word does not work')
        self.assertEqual(do.setup['FOO2'], 'bar bar2', 'Setting of multiple words does not work')
        self.assertEqual(do.setup['FOO3'], 'bar bar2', 'Indented setting of multiple words does not work')
        self.assertEqual(do.setup['SNCSEQ'], 'R2-2-7', 'Setup test01 was not included')

    def test_DoubleIncludeGetsIgnored(self):
        capturedOutput = getStringIO()
        sys.stdout = capturedOutput
        do.source_set('test03')
        sys.stdout = sys.__stdout__
        self.assertRegexpMatches(capturedOutput.getvalue(), 'Ignoring already included setup file')

class TestUpdateReleaseLocal(unittest.TestCase):

    release_local = os.path.join(do.cachedir, 'RELEASE.local')

    def setUp(self):
        if os.path.exists(self.release_local):
            os.remove(self.release_local)
        os.chdir(builddir)

    def test_SetModule(self):
        do.update_release_local('MOD1', '/foo/bar')
        found = 0
        for line in fileinput.input(self.release_local, inplace=1):
            if 'MOD1=' in line:
                self.assertEqual(line.strip(), 'MOD1=/foo/bar', 'MOD1 not set correctly')
                found += 1
        fileinput.close()
        self.assertEqual(found, 1, 'MOD1 not written once to RELEASE.local (found {0})'.format(found))

    def test_SetBaseAndMultipleModules(self):
        do.update_release_local('EPICS_BASE', '/bar/foo')
        do.update_release_local('MOD1', '/foo/bar')
        do.update_release_local('MOD2', '/foo/bar2')
        do.update_release_local('MOD1', '/foo/bar1')
        found = {}
        foundat = {}
        for line in fileinput.input(self.release_local, inplace=1):
            if 'MOD1=' in line:
                self.assertEqual(line.strip(), 'MOD1=/foo/bar1',
                                 'MOD1 not set correctly (expected \'MOD1=/foo/bar1\' found \'{0}\')'
                                 .format(line))
                if 'mod1' in found:
                    found['mod1'] += 1
                else:
                    found['mod1'] = 1
                foundat['mod1'] = fileinput.filelineno()
            if 'MOD2=' in line:
                self.assertEqual(line.strip(), 'MOD2=/foo/bar2',
                                 'MOD2 not set correctly (expected \'MOD2=/foo/bar2\' found \'{0}\')'
                                 .format(line))
                if 'mod2' in found:
                    found['mod2'] += 1
                else:
                    found['mod2'] = 1
                foundat['mod2'] = fileinput.filelineno()
            if 'EPICS_BASE=' in line:
                self.assertEqual(line.strip(), 'EPICS_BASE=/bar/foo',
                                 'EPICS_BASE not set correctly (expected \'EPICS_BASE=/bar/foo\' found \'{0}\')'
                                 .format(line))
                if 'base' in found:
                    found['base'] += 1
                else:
                    found['base'] = 1
                foundat['base'] = fileinput.filelineno()
        fileinput.close()
        self.assertEqual(found['mod1'], 1,
                         'MOD1 does not appear once in RELEASE.local (found {0})'.format(found['mod1']))
        self.assertEqual(found['mod2'], 1,
                         'MOD2 does not appear once in RELEASE.local (found {0})'.format(found['mod2']))
        self.assertEqual(found['base'], 1,
                         'EPICS_BASE does not appear once in RELEASE.local (found {0})'.format(found['base']))
        self.assertGreater(foundat['base'], foundat['mod2'],
                           'EPICS_BASE (line {0}) appears before MOD2 (line {1})'
                           .format(foundat['base'], foundat['mod2']))
        self.assertGreater(foundat['mod2'], foundat['mod1'],
                           'MOD2 (line {0}) appears before MOD1 (line {1})'.format(foundat['mod2'], foundat['mod1']))

class TestAddDependencyUpToDateCheck(unittest.TestCase):

    hash_3_15_6 = "ce7943fb44beb22b453ddcc0bda5398fadf72096"
    location = os.path.join(do.cachedir, 'base-R3.15.6')
    licensefile = os.path.join(location, 'LICENSE')
    checked_file = os.path.join(location, 'checked_out')
    release_file = os.path.join(location, 'configure', 'RELEASE')

    def setUp(self):
        os.environ['SETUP_PATH'] = '.:appveyor'
        if os.path.exists(self.location):
            shutil.rmtree(self.location, onerror=do.remove_readonly)
        do.clear_lists()
        os.chdir(builddir)
        do.source_set('defaults')
        do.complete_setup('BASE')

    def test_MissingDependency(self):
        do.setup['BASE'] = 'R3.15.6'
        do.add_dependency('BASE')
        self.assertTrue(os.path.exists(self.licensefile), 'Missing dependency was not checked out')
        self.assertTrue(os.path.exists(self.checked_file), 'Checked-out commit marker was not written')
        with open(self.checked_file, 'r') as bfile:
            checked_out = bfile.read().strip()
        bfile.close()
        self.assertEqual(checked_out, self.hash_3_15_6,
                         'Wrong commit of dependency checked out (expected=\"{0}\" found=\"{1}\")'
                         .format(self.hash_3_15_6, checked_out))
        self.assertFalse(find_in_file('include \$\(TOP\)/../RELEASE.local', self.release_file),
                         'RELEASE in Base includes TOP/../RELEASE.local')

    def test_UpToDateDependency(self):
        do.setup['BASE'] = 'R3.15.6'
        do.add_dependency('BASE')
        os.remove(self.licensefile)
        do.add_dependency('BASE')
        self.assertFalse(os.path.exists(self.licensefile), 'Check out on top of existing up-to-date dependency')

    def test_OutdatedDependency(self):
        do.setup['BASE'] = 'R3.15.6'
        do.add_dependency('BASE')
        os.remove(self.licensefile)
        with open(self.checked_file, "w") as fout:
            print('XXX not the right hash XXX', file=fout)
        fout.close()
        do.add_dependency('BASE')
        self.assertTrue(os.path.exists(self.licensefile), 'No check-out on top of out-of-date dependency')
        with open(self.checked_file, 'r') as bfile:
            checked_out = bfile.read().strip()
        bfile.close()
        self.assertEqual(checked_out, self.hash_3_15_6,
                         "Wrong commit of dependency checked out (expected='{0}' found='{1}')"
                         .format(self.hash_3_15_6, checked_out))

def is_shallow_repo(place):
    check = sp.check_output(['git', 'rev-parse', '--is-shallow-repository'], cwd=place).strip()
    if check == '--is-shallow-repository':
        if os.path.exists(os.path.join(place, '.git', 'shallow')):
            check = 'true'
        else:
            check = 'false'
    return check == 'true'

class TestAddDependencyOptions(unittest.TestCase):

    location = os.path.join(do.cachedir, 'mcoreutils-master')
    testfile = os.path.join(location, '.ci', 'LICENSE')

    def setUp(self):
        os.environ['SETUP_PATH'] = '.:appveyor'
        if os.path.exists(do.cachedir):
            shutil.rmtree(do.cachedir, onerror=do.remove_readonly)
        do.clear_lists()
        do.source_set('defaults')
        do.complete_setup('MCoreUtils')
        do.setup['MCoreUtils'] = 'master'

    def test_Default(self):
        do.add_dependency('MCoreUtils')
        self.assertTrue(os.path.exists(self.testfile),
                        'Submodule (.ci) not checked out recursively (requested: default=YES')
        self.assertTrue(is_shallow_repo(self.location),
                        'Module not checked out shallow (requested: default=5)')

    def test_SetRecursiveNo(self):
        do.setup['MCoreUtils_RECURSIVE'] = 'NO'
        do.add_dependency('MCoreUtils')
        self.assertFalse(os.path.exists(self.testfile), 'Submodule (.ci) checked out recursively')

    def test_SetDepthZero(self):
        do.setup['MCoreUtils_DEPTH'] = '0'
        do.add_dependency('MCoreUtils')
        self.assertFalse(is_shallow_repo(self.location), 'Module checked out shallow (requested full)')

    def test_SetDepthThree(self):
        do.setup['MCoreUtils_DEPTH'] = '3'
        do.add_dependency('MCoreUtils')
        self.assertTrue(is_shallow_repo(self.location),
                        'Module not checked out shallow (requested: default=5)')

    def test_AddMsiTo314(self):
        do.complete_setup('BASE')
        do.setup['BASE'] = 'R3.14.12.1'
        msifile = os.path.join(do.cachedir, 'base-R3.14.12.1', 'src', 'dbtools', 'msi.c')
        do.add_dependency('BASE')
        self.assertTrue(os.path.exists(msifile), 'MSI was not added to Base 3.14')

def repo_access(dep):
    do.set_setup_from_env(dep)
    do.setup.setdefault(dep + "_DIRNAME", dep.lower())
    do.setup.setdefault(dep + "_REPONAME", dep.lower())
    do.setup.setdefault('REPOOWNER', 'epics-modules')
    do.setup.setdefault(dep + "_REPOOWNER", do.setup['REPOOWNER'])
    do.setup.setdefault(dep + "_REPOURL", 'https://github.com/{0}/{1}.git'
                     .format(do.setup[dep + '_REPOOWNER'], do.setup[dep + '_REPONAME']))
    with open(os.devnull, 'w') as devnull:
        return do.call_git(['ls-remote', '--quiet', '--heads', do.setup[dep + '_REPOURL']],
                       stdout=devnull, stderr=devnull)

class TestDefaultModuleURLs(unittest.TestCase):

    modules = ['BASE', 'PVDATA', 'PVACCESS', 'NTYPES',
               'SNCSEQ', 'STREAM', 'ASYN', 'STD',
               'CALC', 'AUTOSAVE', 'BUSY', 'SSCAN',
               'IOCSTATS', 'MOTOR', 'IPAC', ]

    def setUp(self):
        os.environ['SETUP_PATH'] = '.:appveyor'
        do.clear_lists()
        os.chdir(builddir)
        do.source_set('defaults')

    def test_Repos(self):
        for mod in self.modules:
            self.assertEqual(repo_access(mod), 0, 'Defaults for {0} do not point to a valid git repository at {1}'
                             .format(mod, do.setup[mod + '_REPOURL']))

class TestVCVars(unittest.TestCase):
    def test_vcvars(self):
        if ('CMP' in os.environ and os.environ['CMP'] in ('mingw',)) \
                or distutils.util.get_platform() != "win32":
            raise unittest.SkipTest()

        do.with_vcvars('env')

class TestSetupForBuild(unittest.TestCase):
    configuration = os.environ['CONFIGURATION']
    platform = os.environ['PLATFORM']
    cc = os.environ['CMP']
    args = Namespace(paths=[])
    do.building_base = True

    def setUp(self):
        os.environ.pop('EPICS_HOST_ARCH', None)
        do.clear_lists()

    def tearDown(self):
        os.environ['CONFIGURATION'] = self.configuration
        os.environ['PLATFORM'] = self.platform
        os.environ['CMP'] = self.cc

    def test_AddPathsOption(self):
        os.environ['FOOBAR'] = 'BAR'
        args = Namespace(paths=['/my/{FOOBAR}/dir', '/my/foobar'])
        do.setup_for_build(args)
        self.assertTrue(re.search('/my/BAR/dir', os.environ['PATH']), 'Expanded path not in PATH')
        self.assertTrue(re.search('/foobar', os.environ['PATH']), 'Plain path not in PATH')
        os.environ.pop('FOOBAR', None)

    def test_HostArchConfiguration(self):
        for config in ['dynamic', 'dynamic-debug', 'static', 'static-debug']:
            os.environ['CONFIGURATION'] = config
            do.setup_for_build(self.args)
            self.assertTrue('EPICS_HOST_ARCH' in os.environ,
                            'EPICS_HOST_ARCH is not set for Configuration={0}'.format(config))
            if re.search('static', config):
                self.assertTrue(re.search('-static$', os.environ['EPICS_HOST_ARCH']),
                                'EPICS_HOST_ARCH is not -static for Configuration={0}'.format(config))
                self.assertFalse(re.search('debug', os.environ['EPICS_HOST_ARCH']),
                                 'EPICS_HOST_ARCH is -debug for Configuration={0}'.format(config))
            elif re.search('debug', config):
                self.assertFalse(re.search('static', os.environ['EPICS_HOST_ARCH']),
                                 'EPICS_HOST_ARCH is -static for Configuration={0}'.format(config))
                self.assertTrue(re.search('-debug$', os.environ['EPICS_HOST_ARCH']),
                                'EPICS_HOST_ARCH is not -debug for Configuration={0}'.format(config))
            else:
                self.assertFalse(re.search('static', os.environ['EPICS_HOST_ARCH']),
                                 'EPICS_HOST_ARCH is -static for Configuration={0}'.format(config))
                self.assertFalse(re.search('debug', os.environ['EPICS_HOST_ARCH']),
                                 'EPICS_HOST_ARCH is -debug for Configuration={0}'.format(config))

    def test_HostArchPlatform(self):
        for platform in ['x86', 'x64', 'X64']:
            for cc in ['vs2019', 'mingw']:
                os.environ['PLATFORM'] = platform
                os.environ['CMP'] = cc
                os.environ['CONFIGURATION'] = 'dynamic'
                do.setup_for_build(self.args)
                self.assertTrue('EPICS_HOST_ARCH' in os.environ,
                                'EPICS_HOST_ARCH is not set for {0} / {1}'.format(cc, platform))
                if platform == 'x86':
                    self.assertTrue(re.search('^win32-x86', os.environ['EPICS_HOST_ARCH']),
                                    'EPICS_HOST_ARCH is not win32-x86 for {0} / {1}'.format(cc, platform))
                else:
                    self.assertTrue(re.search('^windows-x64', os.environ['EPICS_HOST_ARCH']),
                                    'EPICS_HOST_ARCH is not windows-x64 for {0} / {1}'.format(cc, platform))
                if cc == 'mingw':
                    self.assertTrue(re.search('-mingw$', os.environ['EPICS_HOST_ARCH']),
                                    'EPICS_HOST_ARCH is not -mingw for {0} / {1}'.format(cc, platform))
                    if platform == 'x86':
                        pattern = 'mingw32'
                    else:
                        pattern = 'mingw64'
                    self.assertTrue(re.search(pattern, os.environ['PATH']),
                                    'Binary location for {0} not in PATH'.format(pattern))
                    self.assertTrue(re.search(pattern, os.environ['INCLUDE']),
                                    'Include location for {0} not in INCLUDE'.format(pattern))

    def test_StrawberryInPath(self):
        os.environ['CMP'] = 'vs2019'
        do.setup_for_build(self.args)
        self.assertTrue(re.search('strawberry', os.environ['PATH'], flags=re.IGNORECASE),
                        'Strawberry Perl location not in PATH for vs2019')

    def setBase314(self, yesno):
        cfg_base_version = os.path.join('configure', 'CONFIG_BASE_VERSION')
        fout = open(cfg_base_version, 'w')
        print('# test file for base version detection', file=fout)
        print('BASE_3_14={0}'.format(yesno), file=fout)
        fout.close()

    def setTestResultsTarget(self, target):
        rules_build = os.path.join('configure', 'RULES_BUILD')
        fout = open(rules_build, 'w')
        print('# test file for target detection', file=fout)
        print('{0}: something'.format(target), file=fout)
        fout.close()

    def test_DetectionBase314No(self):
        self.setBase314('NO')
        do.setup_for_build(self.args)
        self.assertFalse(do.isbase314, 'Falsely detected Base 3.14')

    def test_DetectionBase314Yes(self):
        self.setBase314('YES')
        do.setup_for_build(self.args)
        self.assertTrue(do.isbase314, 'Base 3.14 = YES not detected')

    def test_DetectionTestResultsTarget314No(self):
        self.setBase314('YES')
        self.setTestResultsTarget('nottherighttarget')
        do.setup_for_build(self.args)
        self.assertFalse(do.has_test_results, 'Falsely detected test-results target')

    def test_DetectionTestResultsTarget314Yes(self):
        self.setBase314('YES')
        self.setTestResultsTarget('test-results')
        do.setup_for_build(self.args)
        self.assertFalse(do.has_test_results, 'Falsely found test-results on Base 3.14')

    def test_DetectionTestResultsTargetNot314Yes(self):
        self.setBase314('NO')
        self.setTestResultsTarget('test-results')
        do.setup_for_build(self.args)
        self.assertTrue(do.has_test_results, 'Target test-results not detected')

if __name__ == "__main__":
    if 'VV' in os.environ and os.environ['VV'] == '1':
        logging.basicConfig(level=logging.DEBUG)
        do.silent_dep_builds = False

    do.host_info()
    if sys.argv[1:]==['env']:
        # testing with_vcvars
        [print(K,'=',V) for K, V in os.environ.items()]
    else:
        unittest.main()
