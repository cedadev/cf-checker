# CF Checker Changes

See https://github.com/cedadev/cf-checker/milestones?state=closed for full details of each release.

-----------------------------------------------------------------
## May 2021

CF Checker release 4.1.0

Development release to include additional checks for CF-1.8
  
* [#80](https://github.com/cedadev/cf-checker/issues/80): Geometries
* Note this does not yet include support for NetCDF groups.

Various bug fixes:
  
* [#67](https://github.com/cedadev/cf-checker/issues/67): Allow use of `flag_values`/`flag_meanings` to indicate region names.

* [#83](https://github.com/cedadev/cf-checker/issues/83): Missing check on variables with `standard_name = area_type`

* [#87](https://github.com/cedadev/cf-checker/issues/87): Fix `numpy.float32` error

* [#90](https://github.com/cedadev/cf-checker/issues/90): Various minor bugfixes

## October 2019

CF Checker release 4.0.0

First official Python 3 release.

* Support for Python 3 only.
* CEDA cf-checker wrapper script removed.  Caching of standard_name, area_type and region tables has been incorporated into the checker at a previous version

## August 2019

CF Checker release 3.2.0rc1

First Python3 release candidate.
* Python 3 support only
* The Python 2 version will no longer be actively developed and will only get bugfixes.  Bugfixes will continue until sometime in 2020.

## July 2019

CF Checker release 3.1.3

This is a bug fix release

[#64](https://github.com/cedadev/cf-checker/issues/64): Required version of cfunits is v1.8 to v1.9.1

## April 2019

CF Checker release 3.1.1

This is a bug fix release.

Requires: NetCDF v4.5.1+ and netcdf4-python v1.2.5+  

Various bug fixes including:

[#45](https://github.com/cedadev/cf-checker/issues/45): Check for units in flag_masks and flag_values

[#46](https://github.com/cedadev/cf-checker/issues/46): Error checking bounds on a scalar coordinate variable

[#49](https://github.com/cedadev/cf-checker/issues/49): Checker reports error when units is "years" even if not time

[#52](https://github.com/cedadev/cf-checker/issues/52): wrong result when using auxillary coordinate with _Fillvalue

[#58](https://github.com/cedadev/cf-checker/issues/58): Checker crashes for variables with one single flag_values or flag_mask

## March 2018

CF Checker release 3.1.0

This is a development release to include addition checks for CF-1.7 comformance.

### Other Noteworthy Changes

[#35](https://github.com/cedadev/cf-checker/issues/35): Improve execution speed (See also new CL options -x, -t, --cache-dir)

[#29](https://github.com/cedadev/cf-checker/issues/29): Include checks against region names table

## 03.05.2017

CF Checker release 3.0.1

This is a bug fix release.

Various bug fixes including:
[#18](https://github.com/cedadev/cf-checker/issues/18): Pick up default Standard Name Table and Area Type table when called inline.

## 30.01.2017

CF Checker release 3.0.0

### Noteworthy Changes

[#7](https://github.com/cedadev/cf-checker/issues/7): Refactor main class so that all info, warning and error messages are accessible by caller

[#9](https://github.com/cedadev/cf-checker/pull/9): Use cfunits-python to interface to Udunits-2

[#10](https://github.com/cedadev/cf-checker/pull/10): Replace use of CDMS with netcdf4-python
