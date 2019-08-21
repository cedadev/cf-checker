# CF Checker

The CF Checker is a utility that checks the contents of a NetCDF file complies with the Climate and Forecasts (CF) Metadata Convention.

## Dependencies

* The package runs on [**Linux**](http://en.wikipedia.org/wiki/Linux)
  and [**Mac OS**](http://en.wikipedia.org/wiki/Mac_OS) operating systems.

* [Python 3.x](https://www.python.org/)

* [netcdf4-python](https://pypi.python.org/pypi/netCDF4) at version 1.2.5 or newer. This package requires [netCDF](https://www.unidata.ucar.edu/software/netcdf/), [HDF5](https://www.hdfgroup.org/solutions/hdf5/) and [zlib](ftp://ftp.unidata.ucar.edu/pub/netcdf/netcdf-4) libraries.

* [cfunits-python](https://bitbucket.org/cfpython/cfunits-python) package version 3.0.0 or newer

* [numpy](https://pypi.python.org/pypi/numpy) version 1.15 or newer

## Installation

To install from [PyPI](https://pypi.python.org/pypi/cfchecker):

    pip install cfchecker

Alternatively, to install from source:

1. Download the cfchecker package from [cfchecker releases](https://github.com/cedadev/cf-checker/releases)

2. Unpack the library:

        tar -zxf cfchecker-${version}.tar.gz

        cd cfchecker-${version}

3. Install the package:

   * To install to a central location:

            python setup.py install

   * To install to a non standard location:

            python setup.py install --prefix=<directory>

     If directory you are installing into is not on PYTHONPATH you will need to add it.
     
## Running the CF Checker

`cfchecks [-a <area-types.xml>] [-r <regions.xml>] [-s <std_names.xml>] [-v <CFVersion>] [-x] [-t <cache_time_days>] file1 [file2...]`

For further details and for other available command line options please see the help by running `cfchecks -h`

### Environment Variables

The following parameters can be set on the command-line or through environment variables:

1. `CF_STANDARD_NAMES` or (CL option `-s`) : The path or URL to the CF standard names table
2. `CF_AREA_TYPES` or (CL option `-a`) : The path or URL to the CF area types table
3. `CF_REGION_NAMES` or (CL option `-r`): The path or URL to the CF region names table


### Running the Test script

In the release tarball there is a `test_files` directory containing a `test.sh` script which runs a series of test files through the CF Checker and confirms the checker is working as expected.  It is a very elementary system, which will be rewritten soon.  Before running it you will need to edit the location of the cfchecks script in the `tests.sh` file:

    cfchecker="<location of cfchecks>"

Then just run the `tests.sh` script:

    ./tests.sh
    
