# CF Checker Changes

See https://github.com/cedadev/cf-checker/milestones?state=closed for full details of each release.

-----------------------------------------------------------------
## July 2019

CF Checker release 3.1.2

This is a bug fix release

[#64](https://github.com/cedadev/cf-checker/issues/64): Required version of cfunits is v1.8 to v1.9.1

[#65](https://github.com/cedadev/cf-checker/issues/65): Checker not giving a warning when variable is type int and scale_factor/add_offset are float

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
