# CF Checker

The CF Checker is a utility that checks the contents of a NetCDF file complies with the Climate and Forecasts (CF) Metadata Convention.

## Prerequisites

* [Python 2.6](https://www.python.org/) or newer (not yet tested with Python 3.x)

* [netcdf4-python](https://pypi.python.org/pypi/netCDF4)

* [cfunits-python](https://bitbucket.org/cfpython/cfunits-python) package version 1.1.4 or newer

* [numpy](https://pypi.python.org/pypi/numpy) version 1.7 or newer

## Installation

To install from [PyPI](https://pypi.python.org/pypi/cfchecker):

    pip install cfchecker

Alternatively, to install from source:

1. Download the cfchecker package from [cfchecker releases](https://github.com/cedadev/cf-checker/releases)

2. Unpack the library:

        tar -zxf cfchecker-3.0.0.tar.gz
        cd cfchecker-3.0.0

3. Install the package:

   * To install to a central location:

            python setup.py install

   * To install to a non standard location:

            python setup.py --prefix=<directory>

## Running the CF Checker

`cfchecks [-a|--area_types area_types.xml] [-s|--cf_standard_names standard_names.xml] [-v|--version CFVersion] file1 [file2...]`

### Environment Variables

The following parameters can be set on the command-line or through environment variables:

1. `CF_STANDARD_NAMES` (or CL option `-s`) : The path or URL to the CF standard names table
2. `CF_AREA_TYPES` or (CL option `-a`) : The path or URL to the CF area types tables

### Wrapper script

A wrapper to cfchecks, called `cf-checker`, is provided in the `src/` directory, which will maintain local copies of the standard names table and the area types table, and will refresh these local copies only if the age of the file (based on its modification time) is more than a specified maximum, defaulting to 1 day.  This allows for running the checker repeatedly without refetching the tables on each invocation, while still keeping them reasonably up to date.

For a usage message, type `cf-checker -h`

Note that the wrapper defaults to storing the downloaded files in `/var/spool/cf-checker`, so if the script is used unmodified then this directory should be created or else an alternative value should be passed as a command line option (`-d`).  Ensure either that all users have write permission to the directory used, or else that a user that does have write permission runs a cron job to refresh the tables.  For the latter purpose, it is permissible to run the wrapper without specifying any data files to check, in which it will do no more than update the tables; this is still conditional on age, so for this purpose it is recommended to run the wrapper with a maximum age of zero (`-t 0`), and to run the cron job at intervals not exceeding the
default maximum age.

The wrapper is maintained by CEDA and not by NCAS CMS.

### Running the Test script

In the release tarball there is a `test_files` directory containing a `test.sh` script which runs a series of test files through the CF Checker and confirms the checker is working as expected.  It is a very elementary system, which will be rewritten soon.  Before running it you will need to edit the location of the cfchecker script in the `tests.sh` file:

    cfchecker="<location of cfchecks>"

Then just run the `tests.sh` script:

    ./tests.sh
    
