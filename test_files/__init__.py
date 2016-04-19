"""
A reduced version of Ros' test suite to keep the size of the tarball
down.  These tests should be considered just a sanity check.

This module also tests the existence of the environment variable
UDUNITS2_HOME and only runs the tests if it is present.

"""

import sys, os, logging
log = logging.getLogger(__name__)

import tempfile, glob
import difflib
from subprocess import Popen, PIPE
import re

here = os.path.dirname(__file__)

# Ignore all except v1.0 tests
ignore = ['badc_units.nc', 'stdName_test.nc']
version_map = {
    'CF_1_2.nc': '1.2',
    'flag_tests.nc': '1.3',
    'Trac049_test1.nc': '1.4',
    'Trac049_test2.nc': '1.4',
    }


## Use local tables

#cf_table = 'http://cf-pcmdi.llnl.gov/documents/cf-standard-names/standard-name-table/current/cf-standard-name-table.xml'
#area_table = 'http://cf-pcmdi.llnl.gov/documents/cf-standard-names/area-type-table/current/area-type-table.xml'
cf_table = os.path.join(here, 'cf-standard-name-table.xml')
area_table = os.path.join(here, 'area-type-table.xml')


checker_args = ['-s', cf_table, '-a', area_table]
try:
    udunits2_xml = os.environ['UDUNITS']
except KeyError:
    udunits2_xml = None
else:
    checker_args += ['-u', udunits2_xml]



def _clean_lines(lines):
    """
    Remove lines from a cfchecks report that are not relevant to testing.  

    Removals include:
     1. Version tags of the tables used
     2. Warnings from cdms2.

    This eases testing when all that's changed is the table version.
    
    """
    new_lines = []
    for line in lines:
        match = re.match(r'Using .* Table Version .*', line)

        #!TODO: Verify whether this line is really not important.
        if not match:
            match = re.match(r'ncvarget: ncid \d+; varid \d+: NetCDF: Index exceeds dimension bound', line)

        if not match:
            new_lines.append(line)


    return new_lines

def _do_test(filename, checkfilename, version='1.0'):
    exe = sys.executable
    temp = tempfile.TemporaryFile()

    p1 = Popen([exe, '-c', 'import cfchecker as c; c.cfchecks_main()'] + checker_args + ['-v', version] + [filename],
               stdout=temp,
               )
    p1.communicate()
    temp.seek(0)

    check_lines = _clean_lines(open(checkfilename).readlines())
    test_lines = _clean_lines(temp.readlines())

    diff = list(difflib.unified_diff(test_lines, check_lines))
    
    if len(diff) > 0:
        for line in diff:
            print line,
        assert False


def test():
    # We must be in the test directory for these to work.  However nose
    # does wierd things with current directories so be smart.
    try:
        here = os.getcwd()
    except OSError:
        here = '.'
    try:
        os.chdir(os.path.dirname(__file__))
        for file in glob.glob('*.nc'):
            if file in ignore:
                continue
            version = version_map.get(file, '1.0')

            checkfile = os.path.splitext(file)[0]+'.check'
            yield _do_test, file, checkfile, version
    finally:
        os.chdir(here)




