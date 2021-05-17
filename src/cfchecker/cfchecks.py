#!/usr/bin/env python
# -------------------------------------------------------------
# Name: cfchecks.py
#
# Author: Rosalyn Hatcher - Met Office, UK
#
# Maintainer: Rosalyn Hatcher - NCAS-CMS, Univ. of Reading, UK
#
# Date: February 2003
#
# File Revision: $Revision: 200 $
#
# CF Checker Version: See __version__
#
# -------------------------------------------------------------
""" cfchecks [OPTIONS] file1 [file2...]

Description:
 The CF Checker checks NetCDF files for compliance to the CF standard.
 
Options:
 -a or --area_types:
       the location of the CF area types table (xml)
       
 -h or --help: Prints this help text

 -r or --region_names:
       the location of the CF standardized region names table (xml)

 -s or --cf_standard_names:
       the location of the CF standard name table (xml)

 -t or --cache_time_days <days>:
       set the cache retention period in days [default 10 days].

 -v or --version: 
       CF version to check against, use auto to auto-detect the file version.

 -x or --cache_tables:
       cache the standard name, area type and region name tables.

 --cache_dir:
       directory in which to store cached tables

"""
from __future__ import print_function

from builtins import str
from builtins import next
from builtins import map
from past.builtins import basestring
from builtins import object

import numpy
import os
import re
import string
import sys
import time

if sys.version_info[:2] < (2, 7):
    from ordereddict import OrderedDict
else:
    from collections import OrderedDict
    from collections import defaultdict

# Ignore Future warnings in numpy for now
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import netCDF4

from cfunits import Units

# Version is imported from the package module cfchecker/__init__.py
from cfchecker import __version__

STANDARDNAME = 'http://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml'
AREATYPES = 'http://cfconventions.org/Data/area-type-table/current/src/area-type-table.xml'
REGIONNAMES = 'http://cfconventions.org/Data/standardized-region-list/standardized-region-list.xml'

# -----------------------------------------------------------
from xml.sax import ContentHandler
from xml.sax import make_parser
from xml.sax.handler import feature_namespaces


def normalize_whitespace(text):
    """Remove redundant whitespace from a string."""
    return ' '.join(text.split())


def isnt_str_or_basestring(thing):
    """
    check if the passed in thing is a str, or if running under python 2,
    a basestring
    """

    if sys.version_info[:2] < (3,0):
        return not isinstance(thing, str) and not isinstance(thing, basestring)
    else:
        return not isinstance(thing, str)


def is_str_or_basestring(thing):
    """
    check if the passed in thing is a str, or if running under python 2,
    a basestring
    """

    return not isnt_str_or_basestring(thing)


class CFVersion(object):
    """A CF version number, stored as a tuple, that can be instantiated with 
    a tuple or a string, written out as a string, and compared with another version"""

    def __init__(self, value=()):
        """Instantiate CFVersion with a string or with a tuple of ints"""
        if isinstance(value, str):
            if value.startswith("CF-"):
                value = value[3:]
            self.tuple = tuple(map(int, value.split(".")))
        else:
            self.tuple = value

    def __bool__(self):
        if self.tuple:
            return True
        else:
            return False

    def __str__(self):
        return "CF-%s" % ".".join(map(str, self.tuple))

    def __cmp__(self, other):

        # maybe overkill but allow for different lengths in future e.g. 3.2 and 3.2.1
        pos = 0
        while True:
            in_s = (pos < len(self.tuple))
            in_o = (pos < len(other.tuple))
            if in_s:
                if in_o:
                    c = (self.tuple[pos] > other.tuple[pos]) - (self.tuple[pos] < other.tuple[pos])
                    if c != 0:
                        return c  # e.g. 1.x <=> 1.y
                else:  # in_s and not in_o
                    return 1  # e.g. 3.2.1 > 3.2
            else:
                if in_o:  # and not in_s
                    return -1  # e.g. 3.2 < 3.2.1
                else:  # not in_s and not in_o
                    return 0  # e.g. 3.2 == 3.2
            pos += 1

    def __eq__(self, other):
        return self.tuple == other.tuple

    def __ge__(self, other):
        if self.__cmp__(other) >= 0:
            return True
        return False

    def __lt__(self, other):
        if self.__cmp__(other) < 0:
            return True
        return False


vn1_0 = CFVersion((1, 0))
vn1_1 = CFVersion((1, 1))
vn1_2 = CFVersion((1, 2))
vn1_3 = CFVersion((1, 3))
vn1_4 = CFVersion((1, 4))
vn1_5 = CFVersion((1, 5))
vn1_6 = CFVersion((1, 6))
vn1_7 = CFVersion((1, 7))
vn1_8 = CFVersion((1, 8))
cfVersions = [vn1_0, vn1_1, vn1_2, vn1_3, vn1_4, vn1_5, vn1_6, vn1_7, vn1_8]
newest_version = max(cfVersions)


class ConstructDict(ContentHandler):
    """Parse the xml standard_name table, reading all entries into a dictionary;
       storing standard_name and units.

       If useShelve is True, a python shelve file will be used. If the file is
       present and less than 600 seconds old, the existing contents will be used,
       otherwise the standard name table will be parsed and written to the shelf 
       file.
    """
    def __init__(self, useShelve=False, shelveFile=None, cacheTime=0, cacheDir='/tmp'):
        self.inUnitsContent = 0
        self.inEntryIdContent = 0
        self.inVersionNoContent = 0
        self.inLastModifiedContent = 0
        self.current = False
        self.useShelve = useShelve

        if useShelve:
            import shelve
            if shelveFile is None:
                self.shFile = os.path.join(cacheDir, 'cfexpr_cache')
            else:
                self.shFile = os.path.join(cacheDir, shelveFile)
            now = time.time()
            exists = os.path.isfile(self.shFile) or os.path.isfile('%s.dat' % self.shFile)
            self.dict = shelve.open(self.shFile)

            if exists:
                ctime = self.dict['__contentTime__']
                self.current = (now-ctime) < cacheTime
            else:
                self.current = False
            if self.current:
                self.version_number, self.last_modified = self.dict['__info__']
            else:
                self.dict['__contentTime__'] = now
        else:
            self.dict = {}
    
    def close(self):
        if self.useShelve:
            self.dict['__info__'] = (self.version_number, self.last_modified)
            self.dict.close()
            
    def startElement(self, name, attrs):
        # If it's an entry element, save the id
        if name == 'entry':
            id = normalize_whitespace(attrs.get('id', ""))
            self.this_id = str(id)

        # If it's the start of a canonical_units element
        elif name == 'canonical_units':
            self.inUnitsContent = 1
            self.units = ""

        elif name == 'alias':
            id = normalize_whitespace(attrs.get('id', ""))
            self.this_id = str(id)

        elif name == 'entry_id':
            self.inEntryIdContent = 1
            self.entry_id = ""

        elif name == 'version_number':
            self.inVersionNoContent = 1
            self.version_number = ""

        elif name == 'last_modified':
            self.inLastModifiedContent = 1
            self.last_modified = ""

    def characters(self, ch):
        if self.inUnitsContent:
            self.units = self.units + ch

        elif self.inEntryIdContent:
            self.entry_id = self.entry_id + ch

        elif self.inVersionNoContent:
            self.version_number = self.version_number + ch

        elif self.inLastModifiedContent:
            self.last_modified = self.last_modified + ch

    def endElement(self, name):
        # If it's the end of the canonical_units element, save the units
        if name == 'canonical_units':
            self.inUnitsContent = 0
            self.units = normalize_whitespace(self.units)
            self.dict[self.this_id] = self.units
            
        # If it's the end of the entry_id element, find the units for the self.alias
        elif name == 'entry_id':
            self.inEntryIdContent = 0
            self.entry_id = str(normalize_whitespace(self.entry_id))
            try: 
                self.dict[self.this_id] = self.dict[self.entry_id]
            except KeyError:
                self._add_warn("Error in standard_name table:  entry_id '%s' not found. "
                               "Please contact Rosalyn Hatcher (r.s.hatcher@reading.ac.uk)" %
                               self.entry_id)

        # If it's the end of the version_number element, save it
        elif name == 'version_number':
            self.inVersionNoContent = 0
            self.version_number = normalize_whitespace(self.version_number)

        # If it's the end of the last_modified element, save the last modified date
        elif name == 'last_modified':
            self.inLastModifiedContent = 0
            self.last_modified = normalize_whitespace(self.last_modified)


class ConstructList(ContentHandler):
    """Parse the xml area_type table, reading all area_types 
       into a list.
    """
    def __init__(self, useShelve=False, shelveFile=None, cacheTime=0, cacheDir='/tmp'):
        self.inVersionNoContent = 0
        self.inLastModifiedContent = 0
        self.current = False
        self.useShelve = useShelve

        if useShelve:
            import shelve
            if shelveFile is None:
                self.shFile = os.path.join(cacheDir, 'cfexpr_cachel')
            else:
                self.shFile = os.path.join(cacheDir, shelveFile)
            now = time.time()
            exists = os.path.isfile(self.shFile) or os.path.isfile('%s.dat' % self.shFile)
            self.list = shelve.open(self.shFile)

            if exists:
                ctime = self.list['__contentTime__']
                self.current = (now-ctime) < cacheTime
            else:
                self.current = False
            if self.current:
                self.version_number, self.last_modified = self.list['__info__']
            else:
                self.list['__contentTime__'] = now

        else:
            self.list = set()

    def close(self):
        if self.useShelve:
            self.list['__info__'] = (self.version_number,self.last_modified)
            self.list.close()
        
    def startElement(self, name, attrs):
        # If it's an entry element, save the id
        if name == 'entry':
            id = str( normalize_whitespace(attrs.get('id', "")))
            if self.useShelve:
              self.list[id] = id
            else:
              self.list.add(id)

        elif name == 'version_number':
            self.inVersionNoContent = 1
            self.version_number = ""

        elif name == 'date':
            self.inLastModifiedContent = 1
            self.last_modified = ""

    def characters(self, ch):
        if self.inVersionNoContent:
            self.version_number = self.version_number + ch

        elif self.inLastModifiedContent:
            self.last_modified = self.last_modified + ch

    def endElement(self, name):
        # If it's the end of the version_number element, save it
        if name == 'version_number':
            self.inVersionNoContent = 0
            self.version_number = normalize_whitespace(self.version_number)

        # If it's the end of the date element, save the last modified date
        elif name == 'date':
            self.inLastModifiedContent = 0
            self.last_modified = normalize_whitespace(self.last_modified)

            
def check_derived_name(name):
    """Checks whether name is a derived standard name and adheres
       to the transformation rules. See CF standard names document
       for more information.
    """
    if re.search("^(direction|magnitude|square|divergence)_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^rate_of_change_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^(grid_)?(northward|southward|eastward|westward)_derivative_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^product_of_[a-zA-Z][a-zA-Z0-9_]*_and_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^ratio_of_[a-zA-Z][a-zA-Z0-9_]*_to_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^derivative_of_[a-zA-Z][a-zA-Z0-9_]*_wrt_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^(correlation|covariance)_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*_and_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^histogram_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^probability_distribution_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0

    if re.search("^probability_density_function_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$", name):
        return 0
    
    # Not a valid derived name
    return 1


class FatalCheckerError(Exception):
    pass


# ======================
# Checking class
# ======================
class CFChecker(object):
    
    def __init__(self, uploader=None, useFileName="yes", badc=None, coards=None,
                 cfStandardNamesXML=STANDARDNAME, cfAreaTypesXML=AREATYPES,
                 cfRegionNamesXML=REGIONNAMES, cacheTables=False, cacheTime=0,
                 cacheDir='/tmp', version=newest_version, debug=False, silent=False):
        self.uploader = uploader
        self.useFileName = useFileName
        self.badc = badc
        self.coards = coards
        self.standardNames = cfStandardNamesXML
        self.areaTypes = cfAreaTypesXML
        self.regionNames = cfRegionNamesXML
        self.cacheTables = cacheTables
        self.cacheTime = cacheTime
        self.cacheDir = cacheDir
        self.version = version
        self.all_results = OrderedDict()  # dictionary of results sorted by file and then by globals / variable
                                          # and then by category
        self.all_messages = []  # list of all messages in the order they were printed
        self.cf_roleCount = 0          # Number of occurrences of the cf_role attribute in the file
        self.raggedArrayFlag = 0       # Flag to indicate if file contains any ragged array representations
        self.debug = debug
        self.silent = silent

        self.categories = ("FATAL", "ERROR", "WARN", "INFO", "VERSION")
        if debug:
            self.categories += ("DEBUG",)

        if not isinstance(self.version, CFVersion):
            self.version = CFVersion(self.version)

    def checker(self, file):

        self._init_results(file)

        if self.uploader:
            realfile = string.split(file, ".nc")[0]+".nc"
            self._add_version("CHECKING NetCDF FILE: %s" % realfile)
        elif self.useFileName == "no":
            self._add_version("CHECKING NetCDF FILE")
        else:
            self._add_version("CHECKING NetCDF FILE: %s" % file)
    
        if not self.silent:
            print("=====================")

        # Check for valid filename
        if not file.endswith('.nc'):
            self._fatal("Filename must have .nc suffix", code="2.1")

        # Read in netCDF file
        try:
            self.f = netCDF4.Dataset(file, "r")
        except RuntimeError as e:
            self._fatal("%s: %s" % (e, file))

        #if 'auto' version, check the CF version in the file
        #if none found, use the default
        if not self.version:
            self.version = self.getFileCFVersion()
            if not self.version:
                self._add_warn("Cannot determine CF version from the Conventions attribute; checking against latest CF version: %s" % newest_version)
                self.version = newest_version

        # Set up dictionary of all valid attributes, their type and use
        self.setUpAttributeList()
        self.validGridMappingAttributes()

        # Set up dictionary of standard_names and their assoc. units
        parser = make_parser()
        parser.setFeature(feature_namespaces, 0)
        self.std_name_dh = ConstructDict(useShelve=self.cacheTables, cacheTime=self.cacheTime,
                                         cacheDir=self.cacheDir)

        if not self.std_name_dh.current:
            parser.setContentHandler(self.std_name_dh)
            parser.parse(self.standardNames)

        if self.version >= vn1_4:
            # Set up list of valid area_types
            self.area_type_lh = ConstructList(useShelve=self.cacheTables, shelveFile='cfarea_cache',
                                              cacheTime=self.cacheTime, cacheDir=self.cacheDir)
            if not self.area_type_lh.current:
                parser.setContentHandler(self.area_type_lh)
                parser.parse(self.areaTypes)

        # Set up list of valid region_names
        self.region_name_lh = ConstructList(useShelve=self.cacheTables, shelveFile='cfregion_cache',
                                            cacheTime=self.cacheTime, cacheDir=self.cacheDir)
        if not self.region_name_lh.current:
            parser.setContentHandler(self.region_name_lh)
            parser.parse(self.regionNames)
    
        self._add_version("Using CF Checker Version %s" % __version__)
        if not self.version:
            self._add_version("Checking against CF Version (auto)")
        else:
            self._add_version("Checking against CF Version %s" % self.version)

        self._add_version("Using Standard Name Table Version %s (%s)" %
                       (self.std_name_dh.version_number, self.std_name_dh.last_modified))

        if self.version >= vn1_4:
            self._add_version("Using Area Type Table Version %s (%s)" %
                           (self.area_type_lh.version_number, self.area_type_lh.last_modified))

        self._add_version("Using Standardized Region Name Table Version %s (%s)" %
                          (self.region_name_lh.version_number, self.region_name_lh.last_modified))

        if not self.silent:
            print("")

        try:
            return self._checker()
        finally:
            self.f.close()
            self.std_name_dh.close()
            self.region_name_lh.close()
            if self.version >= vn1_4:
                self.area_type_lh.close()

    def _init_results(self, filename):
        """
        Add a results dictionary to all_results, and for the time being point 
        self.results at it, so that _add_error() and other methods will update 
        results for the current file
        """
        self.results = {"global": self._get_empty_results(),
                        "variables": OrderedDict()}
        self.all_results[filename] = self.results

    def _get_empty_results(self):
        return dict([(cat, []) for cat in self.categories])

    def _init_var_results(self, var):
        vars_dict = self.results["variables"]
        if var not in vars_dict:
            vars_dict[var] = self._get_empty_results()

    def _fatal(self, *args, **kwargs):
        """
        Add a fatal error message.  Arguments are as per _add_error below, and the error message 
        is therefore stored, but primarily a fatal error message aborts the checking of the file,
        raising a FatalCheckerError.  The caller can of course trap this and not exit.
        """
        self._add_message("FATAL", *args, **kwargs)
        self.show_counts(append_to_all_messages=True)
        raise FatalCheckerError
        
    def _add_error(self, *args, **kwargs):
        """
        Add an error message to the output 
        (for the filename for which _init_results() was most recently called)
        This will cause the message to be stored in self.all_results and self.all_messages,
        and also printed (unless instantiated with silent=True)

        Usage:  self._add_error(message) - adds an error in global section
                self._add_error(message, varname) - adds an error in variables section

        optional argument code='...' specifies the error code e.g. '1.1.1'
        """
        self._add_message("ERROR", *args, **kwargs)

    def _add_warn(self, *args, **kwargs):
        """"as _add_error but for warnings"""
        self._add_message("WARN", *args, **kwargs)

    def _add_info(self, *args, **kwargs):
        """as _add_error but for informational messages"""
        self._add_message("INFO", *args, **kwargs)

    def _add_version(self, *args, **kwargs):
        """as _add_error but for informational messages"""
        self._add_message("VERSION", *args, **kwargs)
        
    def _add_debug(self, *args, **kwargs):
        """
        As _add_error but for debug messages. Does nothing unless debug has been set to True,
        e.g. by adding the -d command-line flag if instantiating via main()
        """
        if not self.debug:
            return
        self._add_message("DEBUG", *args, **kwargs)

    def _add_message(self, category, msg, var=None, code=None):
        """
        add the message - generic helper for _add_error etc.
        """
        assert category in self.categories
        if code:
            code_report = "(%s)" % code
        else:
            code_report = None
        if var:
            if var not in self.results["variables"]:
                self._init_var_results(var)
                self._add_debug("logging result for unexpected var: %s - check code" % var)
            results_dict = self.results["variables"][var]
            var_report = "variable %s" % var
        else:
            results_dict = self.results["global"]
            var_report = None
        results_dict[category].append(self._join_strings([code_report, msg]))
        msg_print = self._join_strings([category, code_report, var_report, msg])
        if not self.silent:
            #print msg_print
            if category == "VERSION":
                print(self._join_strings([code_report, msg]))
            else:
                print(self._join_strings([category, code_report, msg]))

        self.all_messages.append(msg_print)

    def _join_strings(self, list_):
        """
        filter out None from lists and join the rest
        """
        return ": ".join([x for x in list_ if x is not None])

    def get_total_counts(self):
        """
        Get counts totalled over all files checked.
        """
        grand_totals = self._get_zero_counts()
        for results in list(self.all_results.values()):
            counts = self.get_counts(results)
            for category in self.categories:
                grand_totals[category] += counts[category]
        return grand_totals

    def _get_zero_counts(self):
        return OrderedDict([(cat, 0) for cat in self.categories])

    def get_counts(self, results=None):
        """
        get OrderedDict of number of errors, warnings, info messages
        This will be for most recently checked file, unless 'results' is passed in 
        (in which case, it should be a value from the self.all_results dictionary
        where corresponding key is the filename).
        """
        if results == None:
            results = self.results
        counts = self._get_zero_counts()
        self._update_counts(counts, results["global"])
        for res in list(results["variables"].values()):
            self._update_counts(counts, res)
        return counts

    def _update_counts(self, counts, results):
        """
        helper for _get_counts()
        """
        for category in self.categories:
            counts[category] += len(results[category])

    def show_counts(self, results=None, append_to_all_messages=False):
        descriptions = {"FATAL": "FATAL ERRORS",
                        "ERROR": "ERRORS detected",
                        "WARN": "WARNINGS given",
                        "INFO": "INFORMATION messages",
                        "DEBUG": "DEBUG messages",
                        "VERSION": "VERSION information"}
        for category, count in list(self.get_counts(results).items()):
            # A FATAL error is really the inability of the checker to perform the checks.
            # Only show this if it actually occurred.
            if category == "FATAL" and count == 0:
                continue
            if category == "VERSION":
                continue
            line = "%s: %s" % (descriptions[category], count)
            if not self.silent:
                print(line)

            if append_to_all_messages:
                self.all_messages.append(line)
  
    def _checker(self):
        """
        Main implementation of checker assuming self.f exists.
        """
        lowerVars = []
        for var in map(str, list(self.f.variables.keys())):
            self._init_var_results(var)

        # Check global attributes
        self.chkGlobalAttributes()

        (coordVars, auxCoordVars, boundsVars, climatologyVars,
         geometryContainerVars, gridMappingVars, nodeCoordinateVars) = self.getCoordinateDataVars()

        self.coordVars = coordVars
        self.auxCoordVars = auxCoordVars
        self.boundsVars = boundsVars
        self.climatologyVars = climatologyVars
        self.geometryContainerVars = geometryContainerVars
        self.gridMappingVars = gridMappingVars
        self.nodeCoordinateVars = nodeCoordinateVars

        self._add_debug("Auxillary Coordinate Vars: %s" % list(map(str, auxCoordVars)))
        self._add_debug("Coordinate Vars: %s" % list(map(str, coordVars)))
        self._add_debug("Boundary Vars: %s" % list(map(str, boundsVars)))
        self._add_debug("Climatology Vars: %s" % list(map(str, climatologyVars)))
        self._add_debug("Geometry Container Vars: %s" % list(map(str, geometryContainerVars.keys())))
        self._add_debug("Grid Mapping Vars: %s" % list(map(str, gridMappingVars)))

        allCoordVars = coordVars[:]
        allCoordVars[len(allCoordVars):] = auxCoordVars[:]

        self.setUpFormulas()

        axes = list(self.f.dimensions.keys())

        self._add_debug("Axes: %s" % axes)

        valid_types = [numpy.character,
                       numpy.dtype('c'),
                       numpy.dtype('b'),
                       numpy.dtype('i4'),
                       numpy.int32,
                       numpy.float32,
                       numpy.double,
                       'int16',
                       'float32']

        # Check each variable
        for var in list(self.f.variables.keys()):

            if not self.silent:
                print("")
                print("------------------")
                print("Checking variable: %s" % var)
                print("------------------")

            if not self.validName(var):
                self._add_warn("Variable names should begin with a letter and be composed "
                               "of letters, digits and underscores", var, code='2.3')

            dt = self.f.variables[var].dtype
            if dt not in valid_types:
                try:
                    if isinstance(self.f.variables[var].datatype, netCDF4.VLType):
                        self._add_error("Invalid variable type: {} (vlen types not supported)".format(self.f.variables[var].datatype),
                                        var,
                                        code="2.2")
                except:
                    self._add_error("Invalid variable type: {}".format(dt), var, code="2.2")

            # Check to see if a variable with this name already exists (case-insensitive)
            lowerVar = var.lower()
            if lowerVar in lowerVars:
                self._add_warn("variable clash", var, code='2.3')
            else:
                lowerVars.append(lowerVar)

            if var not in axes:
                # Non-coordinate variable
                self.chkDimensions(var, allCoordVars)

            self.chkDescription(var)

            for attribute in map(str, self.f.variables[var].ncattrs()):
                self.chkAttribute(attribute, var, allCoordVars, geometryContainerVars)

            self.chkUnits(var, allCoordVars)
            self.chkValidMinMaxRange(var)
            self.chk_FillValue(var)
            self.chkAxisAttribute(var)
            self.chkPositiveAttribute(var)
            self.chkCellMethods(var)
            self.chkCellMeasures(var)
            self.chkFormulaTerms(var, allCoordVars)
            self.chkCompressAttr(var)
            self.chkPackedData(var)

            if self.version >= vn1_3:
                # Additional conformance checks from CF-1.3 onwards
                self.chkFlags(var)

            if self.version >= vn1_6:
                # Additional conformance checks from CF-1.6 onwards
                self.chkCFRole(var)
                self.chkRaggedArray(var)

            if self.version >= vn1_7:
                # Additional conformance checks from CF-1.7 onwards
                self.chkActualRange(var)
                self.chkComputedStandardName(var)

            if self.version >= vn1_8:
                # Additional conformance checks from CF-1.8 onwards
                if var in geometryContainerVars:
                    self.chkGeometryContainerVar(var)
                self.chkNodesAttribute(var)

            if var in coordVars:
                self.chkMultiDimCoord(var, axes)
                self.chkValuesMonotonic(var)

            if var in gridMappingVars:
                self.chkGridMappingVar(var)

            if var in axes:
                if self.isTime(var):
                    # Time coordinate variable
                    self._add_debug("Time Axis.....")
                    self.chkTimeVariableAttributes(var)

                # Github Issue #13
                if var not in allCoordVars:
                    dimensions=list(map(str, self.f.variables[var].dimensions))

                    if len(dimensions) > 1 and var in dimensions:
                        # Variable name matches a dimension;
                        # This may be an unidentified multi-dimensional coordinate variable
                        self._add_warn('Possible incorrect declaration of a coordinate variable.', var, code='5')

        if self.version >= vn1_6:

            if self.raggedArrayFlag != 0 and not hasattr(self.f, 'featureType'):
                self._add_error("The global attribute 'featureType' must be present "
                                "(A ragged array representation has been used)",
                                code="9.4")

            if hasattr(self.f, 'featureType'):
                featureType = self.f.featureType

                if self.cf_roleCount == 0 and featureType != "point":
                    self._add_warn("A variable with the attribute cf_role should be included "
                                   "in a Discrete Geometry CF File",
                                   code="9.5")

                if re.match('^(timeSeries|trajectory|profile)$', featureType, re.I) and self.cf_roleCount != 1:
                    # Should only be a single occurrence of a cf_role attribute
                    self._add_warn("CF Files containing {} featureType should only include a single "
                                   "occurrence of a cf_role attribute".format(featureType))

                elif re.match('^(timeSeriesProfile|trajectoryProfile)$',featureType,re.I) and self.cf_roleCount > 2:
                    # May contain up to 2 occurrences of cf_roles attribute
                    self._add_error("CF Files containing {} featureType may contain 2 occurrences "
                                    "of a cf_role attribute".format(featureType))

        if not self.silent:
            print("")

        self.show_counts(append_to_all_messages=True)
        return self.results

    def setUpAttributeList(self):
        """Set up Dictionary of valid attributes, their corresponding
        Type; S(tring), N(umeric) D(ata variable type)  and Use C(oordinate),
        D(ata non-coordinate) or G(lobal) variable."""
    
        self.AttrList={}
        self.AttrList['add_offset'] = ['N', 'D']
        self.AttrList['ancillary_variables'] = ['S', 'D']
        self.AttrList['axis'] = ['S', 'C']
        self.AttrList['bounds'] = ['S', 'C']
        self.AttrList['calendar'] = ['S', 'C']
        self.AttrList['cell_measures'] = ['S', 'D']
        self.AttrList['cell_methods'] = ['S', 'D']
        self.AttrList['climatology'] = ['S', 'C']
        self.AttrList['comment'] = ['S', ('G', 'D')]
        self.AttrList['compress'] = ['S', 'C']
        self.AttrList['Conventions'] = ['S', 'G']
        self.AttrList['coordinates'] = ['S', 'D']
        self.AttrList['_FillValue'] = ['D', 'D']
        self.AttrList['flag_meanings'] = ['S', 'D']
        self.AttrList['flag_values'] = ['D', 'D']
        self.AttrList['formula_terms'] = ['S', 'C']
        self.AttrList['grid_mapping'] = ['S', 'D']
        self.AttrList['history'] = ['S', 'G']
        self.AttrList['institution'] = ['S', ('G', 'D')]
        self.AttrList['leap_month'] = ['N', 'C']
        self.AttrList['leap_year'] = ['N', 'C']
        self.AttrList['long_name'] = ['S', ('C', 'D')]
        self.AttrList['missing_value'] = ['D', 'D']
        self.AttrList['month_lengths'] = ['N', 'C']
        self.AttrList['positive'] = ['S', 'C']
        self.AttrList['references'] = ['S', ('G', 'D')]
        self.AttrList['scale_factor'] = ['N', 'D']
        self.AttrList['source'] = ['S', ('G', 'D')]
        self.AttrList['standard_error_multiplier'] = ['N', 'D']
        self.AttrList['standard_name'] = ['S', ('C', 'D')]
        self.AttrList['title'] = ['S', 'G']
        self.AttrList['units'] = ['S', ('C', 'D')]
        self.AttrList['valid_max'] = ['N', ('C', 'D')]
        self.AttrList['valid_min'] = ['N', ('C', 'D')]
        self.AttrList['valid_range'] = ['N', ('C', 'D')]

        if self.version >= vn1_3:
            self.AttrList['flag_masks'] = ['D', 'D']

        if self.version >= vn1_6:
            self.AttrList['cf_role'] = ['S', 'C']
            self.AttrList['_FillValue'] = ['D', ('C', 'D')]
            self.AttrList['featureType'] = ['S', 'G']
            self.AttrList['instance_dimension'] = ['S', 'D']
            self.AttrList['missing_value'] = ['D', ('C', 'D')]
            self.AttrList['sample_dimension'] = ['S', 'D']

        if self.version >= vn1_7:
            self.AttrList['actual_range'] = ['N', ('C', 'D')]
            self.AttrList['add_offset'] = ['N', ('C', 'D')]
            self.AttrList['comment'] = ['S', ('G', 'C', 'D')]
            self.AttrList['computed_standard_name'] = ['S', 'C']
            self.AttrList['external_variables'] = ['S', 'G']
            self.AttrList['instance_dimension'] = ['S', '-']
            self.AttrList['sample_dimension'] = ['S', '-']
            self.AttrList['scale_factor'] = ['N', ('C', 'D')]

        if self.version >= vn1_8:
            self.AttrList['coordinates'] = ['S', ('D', 'M')]
            self.AttrList['geometry'] = ['S', ('C', 'D')]
            self.AttrList['geometry_type'] = ['S', 'M']
            self.AttrList['grid_mapping'] = ['S', ('D', 'M')]
            self.AttrList['history'] = ['S', ('G', 'Gr')]
            self.AttrList['interior_ring'] = ['S', 'M']
            self.AttrList['node_coordinates'] = ['S', 'M']
            self.AttrList['node_count'] = ['S', 'M']
            self.AttrList['nodes'] = ['S', 'C']
            self.AttrList['part_node_count'] = ['S', 'M']
            self.AttrList['title'] = ['S', ('G', 'Gr')]
      
        return

    def uniqueList(self, list):
        """Determine if list has any repeated elements."""
        # Rewrite to allow list to be either a list or a Numeric array
        seen = []

        for x in list:
            if x in seen:
                return 0
            else:
                seen.append(x)
        return 1

    def isNumeric(self, var):
        """Determine if variable is of Numeric data type."""
        types = ['i', 'f', 'd']
        rc = 1
        if self.getTypeCode(self.f.variables[var]) not in types:
            rc = 0
        return rc

    def isTime(self, var):
        """Variable is a time axis coordinate if it has one or more of the following:
        1) The axis attribute has the value 'T'
        2) Units of reference time
        3) The standard_name attribute is one of 'time' or 'forecast_reference_time'"""

        variable = self.f.variables[var]

        # Does it have a reference time?
        if hasattr(variable, 'units'):
            try:
                u = Units(variable.units)
                if u.isreftime:
                    return 1
            except TypeError:
                # No need to indicate error here as picked up in chkUnits
                pass
      
        # Axis attribute has the value 'T'
        if hasattr(variable, 'axis'):
            if variable.axis == 'T':
                return 1

        # Standard name is one of 'time' or 'forecast_reference_time'
        if hasattr(variable, 'standard_name'):
            if variable.standard_name == 'time' or variable.standard_name == 'forecast_reference_time':
                return 1

        return 0


    def getStdName(self, var):
        """Get standard_name of variable.  Return it as 2 parts - the standard name and the modifier, if present."""
        attName = 'standard_name'
        attDict = var.__dict__

        if attName not in list(attDict.keys()):
            return None

        bits = attDict[attName].split()
      
        if len(bits) == 1:
            # Only standard_name part present
            return bits[0], ""

        elif len(bits) == 0:
            # Standard Name is blank
            return "", ""

        else:
            # At least 2 elements so return the first 2.
            # If there are more than 2, which is invalid syntax, this will have been picked up by chkDescription()
            return bits[0], bits[1]

    def getInterpretation(self, units, positive=None):
        """Determine the interpretation (time - T, height or depth - Z,
        latitude - Y or longitude - X) of a dimension."""

        try:
            u = Units(units)
        except:
            # Don't catch invalid units here as already caught in a previous check
            return None

        if u.islongitude:
            return "X"

        if u.islatitude:
            return "Y"

        if u.ispressure:
            return "Z"

        # Dimensionless vertical coordinate
        if units in ['level', 'layer', 'sigma_level']:
            return "Z"

        if positive and re.match('(up|down)',positive,re.I):
            return "Z"

        if u.istime or u.isreftime:
            return "T"

        # Not possible to deduce interpretation
        return None

    def getCoordinateDataVars(self):
        """Obtain list of coordinate data variables, boundary
        variables, climatology variables and grid_mapping variables."""

        allVariables = list(map(str, self.f.variables))   # List of all vars, including coord vars
        axes = list(map(str, self.f.dimensions))

        coordVars = []
        variables = []
        boundaryVars = []
        climatologyVars = []
        gridMappingVars = []
        auxCoordVars = []
        geometryContainerVars = {}
        nodeCoordinateVars = []

        # Split each variable in allVariables into either coordVars or variables (data vars)
        for varname, var in list(self.f.variables.items()):
            if len(var.shape) == 1 and len(var.dimensions) == 1 and var.dimensions[0] == varname:
                # 1D and dimension is same name as variable
                coordVars.append(varname)
            else:
                variables.append(varname)

        for var in allVariables:

            # ------------------------
            # Auxilliary Coord Checks
            # ------------------------
            if hasattr(self.f.variables[var], 'coordinates'):
                # Check syntax of 'coordinates' attribute
                if not self.parseBlankSeparatedList(self.f.variables[var].coordinates):
                    self._add_error("Invalid syntax for 'coordinates' attribute", var, code="5.3")
                else:
                    coordinates=self.f.variables[var].coordinates.split()
                    for dataVar in coordinates:
                        if dataVar in variables:
                            self._add_debug(dataVar)

                            # Has Auxillary Coordinate already been identified and checked?
                            if dataVar not in auxCoordVars:
                                auxCoordVars.append(dataVar)

                                # Is the auxillary coordinate var actually a label?
                                if self.getTypeCode(self.f.variables[dataVar]) == 'S':
                                    # Label variable
                                    num_dimensions = len(self.f.variables[dataVar].dimensions)
                                    if self.version < vn1_4:
                                        if not num_dimensions == 2:
                                            self._add_error("Label variable must have 2 dimensions only",
                                                            dataVar, code="6.1")

                                    if self.version >= vn1_4:
                                        if num_dimensions != 1 and num_dimensions != 2:
                                            self._add_error("Label variable must have 1 or 2 dimensions",
                                                            dataVar, code="6.1")

                                    if num_dimensions == 2:
                                        if self.f.variables[dataVar].dimensions[0] not in self.f.variables[var].dimensions:
                                            if self.version >= vn1_6 and hasattr(self.f, 'featureType'):
                                                # This file contains Discrete Sampling Geometries
                                                self._add_info("File contains a Discrete Sampling Geometry. Skipping check on dimensions",
                                                               dataVar, code="6.1")
                                            else:
                                                self._add_error("Leading dimension must match one of those for %s" % var,
                                                                dataVar,
                                                                code="6.1")
                                else:
                                    # Not a label variable

                                    # 31.05.13 The other exception is a ragged array (chapter 9 - Discrete sampling geometries
                                    # Todo - implement exception
                                    # A ragged array is identified by the presence of either the attribute sample_dimension
                                    # or instance_dimension. Need to check that the sample dimension is the dimension of
                                    # the variable to which the aux coord var is attached.
                                    self._add_debug("Not a label variable. Dimensions are: %s" % list(map(str, self.f.variables[dataVar].dimensions)),
                                                    dataVar)

                                    for dim in self.f.variables[dataVar].dimensions:
                                        if dim not in self.f.variables[var].dimensions:
                                            if self.version >= vn1_6 and hasattr(self.f, 'featureType'):
                                                # This file contains Discrete Sampling Geometries
                                                self._add_info("File contains a Discrete Sampling Geometry. Skipping check on dimensions",
                                                               dataVar,
                                                               code="5")
                                            else:
                                                self._add_error("Dimensions must be a subset of dimensions of %s" % var,
                                                                dataVar,
                                                                code="5")
                                            break

                        elif dataVar not in allVariables:
                            self._add_error("coordinates attribute referencing non-existent variable",
                                            dataVar,
                                            code="5")

            # -------------------------
            # Boundary Variable Checks
            # -------------------------
            if hasattr(self.f.variables[var], 'bounds'):
                bounds=self.f.variables[var].bounds
                # Check syntax of 'bounds' attribute
                if not re.search("^[a-zA-Z0-9_]*$",bounds):
                    self._add_error("Invalid syntax for 'bounds' attribute",
                                    var,
                                    code="7.1")
                else:
                    if bounds in variables:
                        boundaryVars.append(bounds)

                        if not self.isNumeric(bounds):
                            self._add_error("boundary variable with non-numeric data type", var, code="7.1")
                        if len(self.f.variables[var].shape) + 1 == len(self.f.variables[bounds].shape):
                            if var in axes:
                                varDimensions=[var]
                            else:
                                varDimensions=self.f.variables[var].dimensions

                            for dim in varDimensions:
                                if dim not in self.f.variables[bounds].dimensions:
                                    self._add_error("Incorrect dimensions for boundary variable: %s" % bounds,
                                                    bounds,
                                                    code="7.1")
                        else:
                            self._add_error("Incorrect number of dimensions for boundary variable: %s" % bounds,
                                            bounds,
                                            code="7.1")

                        l = ['units', 'standard_name']
                        if self.version >= vn1_7:
                            l[len(l):] = ['axis', 'positive', 'calendar', 'leap_month', 'leap_year', 'month_lengths']
                        for x in l:
                            if hasattr(self.f.variables[bounds], x):
                                if self.version >= vn1_7:
                                    self._add_warn("Boundary var %s should not have attribute %s" % (bounds, x),
                                                   bounds, code="7.1")
                                if (hasattr(self.f.variables[var], x)
                                    and self.f.variables[bounds].getncattr(x) != self.f.variables[var].getncattr(x)):
                                    self._add_error("Boundary var %s has inconsistent %s to %s" % (bounds, x, var),
                                                    bounds, code="7.1")

                        if hasattr(self.f.variables[bounds], 'bounds'):
                            self._add_error("Boundary var {} must not have attribute bounds".format(bounds),
                                            bounds, code="7.1")

                    else:
                        self._add_error("bounds attribute referencing non-existent variable %s" % bounds,
                                        bounds, code="7.1")

                # Check that points specified by a coordinate or auxilliary coordinate
                # variable should lie within, or on the boundary, of the cells specified by
                # the associated boundary variable.
                if bounds in variables:
                    # Is boundary variable 2 dimensional?  If so can check that points
                    # lie within, or on the boundary.
                    if len(self.f.variables[bounds].dimensions) <= 2:
                        varData = self.f.variables[var][:]
                        boundsData = self.f.variables[bounds][:]

                        # Convert 1d array (scalar coordinate variable) to 2d to check cell boundaries
                        if len(boundsData.shape) == 1:
                            boundsData = [boundsData]

                        for i, value in (enumerate(varData) if len(varData.shape) else enumerate([varData])):
                            try:
                                if not (boundsData[i][0] <= value <= boundsData[i][1]) \
                                        and not (boundsData[i][0] >= value >= boundsData[i][1]):
                                    self._add_warn("Data for variable %s lies outside cell boundaries" % var,
                                                   var,
                                                   code="7.1")
                                    break
                            except IndexError as e:
                                self._add_warn("Failed to check data lies within/on bounds for variable %s. Problem with bounds variable: %s" % (var, bounds),
                                               var,
                                               code="7.1")
                                self._add_debug("%s" % e, bounds)
                                break
                            except ValueError as e:
                                self._add_error("Problem with variable: {} \n(Python Error: {})".format(var, e),
                                                var,
                                                code="7.1")
                                break

            # ----------------------------
            # Climatology Variable Checks
            # ----------------------------
            if hasattr(self.f.variables[var], 'climatology'):
                climatology=self.f.variables[var].climatology
                # Check syntax of 'climatology' attribute
                if not re.search("^[a-zA-Z0-9_]*$", climatology):
                    self._add_error("Invalid syntax for 'climatology' attribute", var, code="7.4")
                else:
                    if climatology in variables:
                        climatologyVars.append(climatology)
                        if not self.isNumeric(climatology):
                            self._add_error("climatology variable with non-numeric data type", climatology, code="7.4")

                        if hasattr(self.f.variables[climatology], 'units'):
                            if self.f.variables[climatology].units != self.f.variables[var].units:
                                self._add_error("Climatology variable has inconsistent units to %s" % var,
                                                climatology, code="7.4")

                        if hasattr(self.f.variables[climatology], 'standard_name'):
                            if self.f.variables[climatology].standard_name != self.f.variables[var].standard_name:
                                self._add_error("Climatology variable has inconsistent std_name to %s" % var,
                                                climatology, code="7.4")

                        if hasattr(self.f.variables[climatology], 'calendar'):
                            if self.f.variables[climatology].calendar != self.f.variables[var].calendar:
                                self._add_error("Climatology variable has inconsistent calendar to %s" % var,
                                                climatology, code="7.4")
                    else:
                        self._add_error("Climatology attribute referencing non-existent variable",
                                        var, code="7.4")

            # -----------------------------
            # Geometry Container Variables
            # -----------------------------
            if self.version >= vn1_8:
                if hasattr(self.f.variables[var], 'geometry'):
                    geometry = self.f.variables[var].geometry
                    if not re.search("^[a-zA-Z0-9_]*$", geometry):
                        self._add_error("Invalid syntax for 'geometry' attribute", var, code="7.5")
                    else:
                        if geometry in variables:
                            # geometryContainerVars.append(geometry)
                            # Add geometry and associated data variable to dictionary
                            if geometryContainerVars.get(geometry) is None:
                                geometryContainerVars[geometry] = []

                            geometryContainerVars[geometry].append(var)
                        else:
                            self._add_error("Geometry attribute referencing non-existent variable",
                                            var, code="7.5")

                if hasattr(self.f.variables[var], 'node_coordinates'):
                    if self.parseBlankSeparatedList(self.f.variables[var].node_coordinates):
                        node_coordinates = self.f.variables[var].node_coordinates.split()
                        for coord in node_coordinates:
                            if coord in allVariables:
                                # Add coordinate to auxillary coordinate and node coordinate lists
                                auxCoordVars.append(coord)
                                nodeCoordinateVars.append(coord)
        
            # ----------------------
            # Grid_mapping variables
            # ----------------------
            if hasattr(self.f.variables[var], 'grid_mapping'):
                grid_mapping = self.f.variables[var].grid_mapping

                (grid_mapping_vars, coord_vars) = self.chkGridMappingAttribute(var, grid_mapping)

                for gmv in grid_mapping_vars:
                    if gmv in variables:
                        gridMappingVars.append(gmv)
                    else:
                        self._add_error("grid_mapping attribute referencing non-existent variable %s" % gmv,
                                        var, code="5.6")

                for cv in coord_vars:
                    # cv must be the name of a coordinate variable or auxiliary coordinate variable
                    if cv not in self.f.variables[var].dimensions and cv not in coordinates:
                        self._add_error("{} must be the name of a coordinate variable or auxiliary "
                                        "coordinate variable of {}".format(cv, var),
                                        var,
                                        code="5.6")

                    if cv not in allVariables:
                        self._add_error("grid_mapping attribute referencing non-existent coordinate variable {}".format(cv),
                                        var,
                                        code="5.6")

        # Make sure lists are unique
        gridMappingVars = self.unique(gridMappingVars)
        auxCoordVars = self.unique(auxCoordVars)
        nodeCoordinateVars = self.unique(nodeCoordinateVars)

        return (coordVars, auxCoordVars, boundaryVars, climatologyVars,
                geometryContainerVars, gridMappingVars, nodeCoordinateVars)

    def unique(self, list):
        """Get a unique values from list"""
        x = numpy.array(list)
        return numpy.unique(x).tolist()

    def subst(self, s):
        """substitute tokens for WORD and SEP (space or end of string)"""
        return s.replace('WORD', r'[A-Za-z0-9_]+').replace('SEP', r'(\s+|$)')

    def get_variable_attributes(self, varName):
        """Get all attributes of this variable and store in a dictionary"""
        variable = self.f.variables[varName]
        attributes = {}

        for attr in map(str, variable.ncattrs()):
            try:
                attributes[attr] = variable.getncattr(attr)
                if isinstance(attributes[attr], basestring):
                    try:
                        attributes[attr] = str(attributes[attr])
                    except:
                        attributes[attr] = attributes[attr].encode(errors='ignore')
            except UnicodeDecodeError:
                pass

        self._add_debug("attributes - {}".format(attributes), varName)
        return attributes

    def chkGeometryContainerVar(self, varName):
        """Section 7.5: Geometry Container Variable Checks"""
       
        # Get all attributes for this variable
        attributes = self.get_variable_attributes(varName)

        node_coordinates = attributes.get('node_coordinates')
        geometry_type = attributes.get('geometry_type')
        node_count = attributes.get('node_count')
        coordinates = attributes.get('coordinates')
        part_node_count = attributes.get('part_node_count')
        interior_ring = attributes.get('interior_ring')
        grid_mapping = attributes.get('grid_mapping')

        node_coord_axes = []
        node_coord_dimensions = []

        if node_coordinates is None:
            self._add_error("No node_coordinates attribute set", varName, code="7.5")
        else:
            if not self.parseBlankSeparatedList(node_coordinates):
                  self._add_error("Invalid syntax for 'node_coordinates' attribute", varName, code="7.5")
            else:
                for var in node_coordinates.split():
                    if var not in list(map(str, self.f.variables)):
                        self._add_error("Node_coordinates attribute referencing non-existent variable: {}".format(var),
                                        varName,
                                        code="7.5")
                    else:
                        # Check node_coordinate variable has an axis attribute
                        if hasattr(self.f.variables[var], 'axis'):
                            # Keep details of axis
                            node_coord_axes.append(self.f.variables[var].axis)
                        else:
                            self._add_error("Node_coordinates variable '{}' must have an axis attribute ".format(var),
                                            varName,
                                            code="7.5")

                        if len(self.f.variables[var].dimensions) != 1:
                            self._add_error("Node coordinate variable '{}' must only have a single dimension".format(var),
                                            var,
                                            code="7.5")
                        else:
                            if self.f.variables[var].dimensions[0] not in node_coord_dimensions:
                                node_coord_dimensions.append(self.f.variables[var].dimensions[0])

                if not self.uniqueList(node_coord_axes):
                    self._add_error("Multiple node coordinate variables with same value of axis attribute",
                                    varName,
                                    code="7.5")

                if len(node_coord_dimensions) != 1:
                    self._add_error("All node coordinate variables ({}) must have the "
                                    "same single dimension".format(node_coordinates),
                                    varName,
                                    code="7.5")

                elif node_count is not None:
                    # Same single dimension on all node coordinate variables
                    d = self.f.dimensions[node_coord_dimensions[0]].size
                    total_nodes = self.f.variables[node_count][:].sum()
                    if d != total_nodes:
                        self._add_error("Dimension '{}' must equal the total number of nodes "
                                        "in all the geometries".format(node_coord_dimensions[0]),
                                        varName,
                                        code="7.5")

        if geometry_type is None:
            self._add_error("No geometry_type attribute set", varName, code="7.5")
        else:
            geometry_type = geometry_type.lower()
            valid_geometry_types=['point', 'line', 'polygon']

            if geometry_type in valid_geometry_types:
                # Valid geometry_type
                if geometry_type == 'line' and not numpy.all(self.f.variables[node_count][:] >= 2):
                    # Each geometry must have a minimum of 2 nodes
                    self._add_error("For 'line' geometry_type, each geometry must have a minimum of two nodes",
                                    varName,
                                    code="7.5")
                  
                elif geometry_type == 'polygon' and not numpy.all(self.f.variables[node_count][:] >= 3):
                    # Each geometry must have a minimum of 3 nodes
                    self._add_error("For 'polygon' geometry_type, each geometry must have a minimum of three nodes",
                                    varName,
                                    code="7.5")
            else:
                self._add_error("Invalid geometry_type: {}".format(geometry_type), varName, code="7.5")

        if node_count is None:
            # There is no node_count variable, so all geometries must be single part point geometries
            try:
                if self.f.dimensions[node_coord_dimensions[0]].size > 1:
                    if geometry_type != 'point':
                        self._add_error("Geometry type must be 'point' as no node_count attribute is present",
                                        varName,
                                        code="7.5")
                    for data_var in self.geometryContainerVars[varName]:
                        if node_coord_dimensions[0] not in self.f.variables[data_var].dimensions:
                            self._add_error("Dimension {} of node coordinate variable must be one of "
                                            "the dimensions of {}".format(node_coord_dimensions[0], data_var),
                                            varName,
                                            code="7.5")
            except:
                pass

        else:
            # Find the netCDF dimension for the total number of geometries for each
            # data variable the geometry applies to
            geometry_dimension = self.f.variables[node_count].dimensions[0]

            for data_var in self.geometryContainerVars[varName]:
                if geometry_dimension not in self.f.variables[data_var].dimensions:
                    self._add_error('One of the dimensions of {} must be the number of geometries '
                                    'to which the data applies'.format(data_var),
                                    data_var,
                                    code="7.5")

        if part_node_count is not None and node_count is not None:
            if self.f.variables[part_node_count][:].sum() != self.f.variables[node_count][:].sum():
                self._add_error("Sum of part_node_count values must equal sum of node_count values", varName, code="7.5")
              
        if interior_ring is not None and part_node_count is None:
            self._add_error("No part_node_count attribute set", varName, code="7.5")

        if interior_ring is not None:
            interior_ring_variable = self.f.variables[interior_ring]
          
            for value in interior_ring_variable[:]:
                if value != 0 and value != 1:
                    self._add_error("Values of interior ring variable '{}' must be either 0 or 1".format(interior_ring),
                                    interior_ring,
                                    code="7.5")

            if len(interior_ring_variable.dimensions) != 1:
                self._add_error("Interior ring variable '{}' must only have 1 dimension".format(interior_ring),
                                interior_ring,
                                code="7.5")
              
            if part_node_count is not None:
                part_node_count_variable = self.f.variables[part_node_count]
              
                if len(part_node_count_variable.dimensions) != 1:
                    self._add_error("Part node count variable: '{}' must only have 1 dimension".format(part_node_count),
                                    part_node_count,
                                    code="7.5")

                if len(interior_ring_variable.dimensions) == 1 and len(part_node_count_variable.dimensions) == 1:
                  
                    if interior_ring_variable.dimensions[0] != part_node_count_variable.dimensions[0]:
                        self._add_error("Interior ring variable {} and part node count variable {} must have "
                                        "the same single dimension.".format(interior_ring, part_node_count),
                                        varName,
                                        code="7.5")
                  
        if grid_mapping is not None:
            # Associated data variable(s) must also carry a grid_mapping attribute
            for data_var in self.geometryContainerVars[varName]:
                if not hasattr(self.f.variables[data_var], 'grid_mapping'):
                    self._add_error('Variable {} must have a grid_mapping attribute'.format(data_var),
                                    data_var,
                                    code='7.5')

        if coordinates is not None:
            # Associated data variable(s) must also carry a coordinates attribute
            for data_var in self.geometryContainerVars[varName]:
                if not hasattr(self.f.variables[data_var], 'coordinates'):
                    self._add_error('Variable {} must have a coordinates attribute'.format(data_var),
                                    data_var,
                                    code='7.5')

    def chkNodesAttribute(self, varName):
        """Validate nodes attribute"""
        var = self.f.variables[varName]

        if hasattr(var, 'nodes'):
            # Syntax: a string whose value is a single variable name
            if not self.validName(var.nodes):
                self._add_error("'nodes' attribute must be a string whose value is a single variable name",
                                varName,
                                code='7.5')
            else:
                # Check that variable is a node coordinate variable and exists in the file
                node_coordinate = var.nodes
                if node_coordinate not in self.nodeCoordinateVars:
                    self._add_error("Variable referenced by 'nodes' attribute not identified as a node coordinate variable",
                                    varName,
                                    code='7.5')

                if node_coordinate not in list(map(str, self.f.variables)):
                    self._add_error("'nodes' attribute referencing non-existent variable",
                                    varName,
                                    code='7.5')

    def chkGridMappingAttribute(self, varName, grid_mapping):
        """Validate syntax of grid_mapping attribute"""

        grid_mapping_vars = []
        coord_vars = []

        if self.version < vn1_7:
            # Syntax: a string whose value is a single variable name
            pat_sole = self.subst('(?P<sole_mapping>WORD)$')
            m = re.match(pat_sole, grid_mapping)
              
        else:
            # Syntax: a string whose value is a single variable name or of the form:
            # grid_mapping_var: coord_var [coord_var ...] [grid_mapping_var: coord_var [coord_var ...]]

            pat_coord = self.subst('(?P<coord>WORD)SEP')
            pat_coord_list = '({})+'.format(pat_coord)

            pat_mapping = self.subst('(?P<mapping_name>WORD):SEP(?P<coord_list>{})'.format(pat_coord_list))
            pat_mapping_list = '({})+'.format(pat_mapping)

            pat_all = self.subst('((?P<sole_mapping>WORD)|(?P<mapping_list>{}))$'.format(pat_mapping_list))

            m = re.match(pat_all, grid_mapping)

        if not m:
            self._add_error("{} - Invalid syntax for 'grid_mapping' attribute".format(varName), varName, code="5.6")
            return [], []

        # Parse grid_mapping attribute to obtain a list of grid_mapping_vars and a list of coord_vars
        sole_mapping = m.group('sole_mapping')
        if sole_mapping:
            # Contains only a single variable name
            grid_mapping_vars.append(sole_mapping)
    
        else:
            # Complex form, split into lists of grid_mapping_vars and coord_vars
            mapping_list = m.group('mapping_list')
            for mapping in re.finditer(pat_mapping, mapping_list):
                mapping_name = mapping.group('mapping_name')
                coord_list = mapping.group('coord_list')

                grid_mapping_vars.append(mapping_name)
                for coord in re.finditer(pat_coord, coord_list):
                    coord_vars.append(coord.group('coord'))

        return list(map(str,grid_mapping_vars)), list(map(str,coord_vars))

    def validGridMappingAttributes(self):
        """Setup dictionary of valid grid mapping attributes and their types"""

        self.grid_mapping_attrs = dict([('azimuth_of_central_line', 'N'),
                                        ('crs_wkt', 'S'),
                                        ('earth_radius', 'N'),
                                        ('false_easting', 'N'),
                                        ('false_northing', 'N'),
                                        ('geographic_crs_name', 'S'),
                                        ('geoid_name', 'S'),
                                        ('geopotential_datum_name', 'S'),
                                        ('grid_mapping_name', 'S'),
                                        ('grid_north_pole_latitude', 'N'),
                                        ('grid_north_pole_longitude', 'N'),
                                        ('horizontal_datum_name', 'S'),
                                        ('inverse_flattening', 'N'),
                                        ('latitude_of_projection_origin', 'N'),
                                        ('longitude_of_central_meridian', 'N'),
                                        ('longitude_of_prime_meridian', 'N'),
                                        ('longitude_of_projection_origin', 'N'),
                                        ('north_pole_grid_longitude', 'N'),
                                        ('perspective_point_height', 'N'),
                                        ('prime_meridian_name', 'S'),
                                        ('projected_crs_name', 'S'),
                                        ('reference_ellipsoid_name', 'S'),
                                        ('scale_factor_at_central_meridian', 'N'),
                                        ('scale_factor_at_projection_origin', 'N'),
                                        ('semi_major_axis', 'N'),
                                        ('semi_minor_axis', 'N'),
                                        ('standard_parallel', 'N'),
                                        ('straight_vertical_longitude_from_pole', 'N'),
                                        ('towgs84', 'N')])
        return

    def chkGridMappingVar(self, varName):
        """Section 5.6: Grid Mapping Variable Checks"""
        var=self.f.variables[varName]
      
        if hasattr(var, 'grid_mapping_name'):
            # Check grid_mapping_name is valid
            validNames = ['albers_conical_equal_area',
                          'azimuthal_equidistant',
                          'lambert_azimuthal_equal_area',
                          'lambert_conformal_conic',
                          'polar_stereographic',
                          'rotated_latitude_longitude',
                          'stereographic',
                          'transverse_mercator']
          
            if self.version >= vn1_2:
                # Extra grid_mapping_names at vn1.2
                validNames[len(validNames):] = ['latitude_longitude', 'vertical_perspective']

            if self.version >= vn1_4:
                # Extra grid_mapping_names at vn1.4
                validNames[len(validNames):] = ['lambert_cylindrical_equal_area', 'mercator', 'orthographic']

            if self.version >= vn1_7:
                # Extra grid_mapping_names at vn1.7
                validNames[len(validNames):] = ['geostationary', 'oblique_mercator', 'sinusoidal']
              
            if var.grid_mapping_name not in validNames:
                self._add_error("Invalid grid_mapping_name: %s" % var.grid_mapping_name,
                                varName, code="5.6")
        else:
            self._add_error("No grid_mapping_name attribute set: %s" % var.grid_mapping_name,
                            varName, code="5.6")
              
        if len(var.dimensions) != 0:
            self._add_warn("A grid mapping variable should have 0 dimensions",
                           varName, code="5.6")

        for attribute in map(str, var.ncattrs()):

            # Check type of attribute matches that specified in Appendix F: Table 1
            attr_type = type(var.getncattr(attribute))

            if is_str_or_basestring(var.getncattr(attribute)):
                attr_type = 'S'
          
            elif (numpy.issubdtype(attr_type, numpy.integer) or
                  numpy.issubdtype(attr_type, numpy.floating) or
                  attr_type == numpy.ndarray):
                attr_type = 'N'

            else:
                self._add_info("Invalid Type for attribute: %s %s" % (attribute, attr_type))
                continue
          
            if (attribute in list(self.grid_mapping_attrs.keys()) and
                    attr_type != self.grid_mapping_attrs[attribute]):
                self._add_error("Attribute %s of incorrect data type (Appendix F)" % attribute,
                                varName, code="5.6")
              
        if self.version >= vn1_7:
            if hasattr(var, 'crs_wkt'):
                msg = "CF checker currently does not verify the syntax of the crs_wkt attribute " \
                      "which must conform to the CRS WKT specification"
                self._add_info(msg, varName, code="5.6")

            # If any of these attributes are present then they all must be
            l = ['reference_ellipsoid_name', 'prime_meridian_name', 'horizontal_datum_name', 'geographic_crs_name']
            if any(hasattr(var, x) for x in l) and not all(hasattr(var, x) for x in l):
                msg = "reference_ellipsoid_name, prime_meridian_name, horizontal_datum_name " \
                      "and geographic_crs_name must all be definied if any one is defined"
                self._add_error(msg, varName, code="5.6")

            if hasattr(var, 'projected_crs_name') and not hasattr(var, 'geographic_crs_name'):
                self._add_error("projected_crs_name is defined therefore geographic_crs_name must be also",
                                varName, code="5.6")

    def setUpFormulas(self):
        """Set up dictionary of all valid formulas"""
        self.formulas = {}
        self.alias = {}

        self.alias['atmosphere_ln_pressure_coordinate'] = 'atmosphere_ln_pressure_coordinate'
        self.alias['atmosphere_sigma_coordinate'] = 'sigma'
        self.alias['sigma'] = 'sigma'
        self.alias['atmosphere_hybrid_sigma_pressure_coordinate'] = 'hybrid_sigma_pressure'
        self.alias['hybrid_sigma_pressure'] = 'hybrid_sigma_pressure'
        self.alias['atmosphere_hybrid_height_coordinate'] = 'atmosphere_hybrid_height_coordinate'
        self.alias['atmosphere_sleve_coordinate'] = 'atmosphere_sleve_coordinate'
        self.alias['ocean_sigma_coordinate'] = 'ocean_sigma_coordinate'
        self.alias['ocean_s_coordinate'] = 'ocean_s_coordinate'
        self.alias['ocean_s_coordinate_g1'] = 'ocean_s_coordinate_g1'
        self.alias['ocean_s_coordinate_g2'] = 'ocean_s_coordinate_g2'
        self.alias['ocean_sigma_z_coordinate'] = 'ocean_sigma_z_coordinate'
        self.alias['ocean_double_sigma_coordinate'] = 'ocean_double_sigma_coordinate'

        self.formulas['atmosphere_ln_pressure_coordinate'] = ['p(k)=p0*exp(-lev(k))']
        self.formulas['sigma'] = ['p(n,k,j,i)=ptop+sigma(k)*(ps(n,j,i)-ptop)']

        self.formulas['hybrid_sigma_pressure'] = ['p(n,k,j,i)=a(k)*p0+b(k)*ps(n,j,i)',
                                                  'p(n,k,j,i)=ap(k)+b(k)*ps(n,j,i)']

        self.formulas['atmosphere_hybrid_height_coordinate'] = ['z(n,k,j,i)=a(k)+b(k)*orog(n,j,i)']

        self.formulas['atmosphere_sleve_coordinate'] = ['z(n,k,j,i) = a(k)*ztop + b1(k)*zsurf1(n,j,i) + b2(k)*zsurf2(n,j,i)']

        self.formulas['ocean_sigma_coordinate'] = ['z(n,k,j,i)=eta(n,j,i)+sigma(k)*(depth(j,i)+eta(n,j,i))']
      
        self.formulas['ocean_s_coordinate'] = ['z(n,k,j,i)=eta(n,j,i)*(1+s(k))+depth_c*s(k)+(depth(j,i)-depth_c)*C(k)',
                                               'C(k)=(1-b)*sinh(a*s(k))/sinh(a)+b*[tanh(a*(s(k)+0.5))/(2*tanh(0.5*a))-0.5]']

        self.formulas['ocean_s_coordinate_g1'] = ['z(n,k,j,i) = S(k,j,i) + eta(n,j,i) * (1 + S(k,j,i) / depth(j,i))',
                                                  'z(n,k,j,i) = S(k,j,i) + eta(n,j,i) * (1 + S(k,j,i) / depth(j,i))']

        self.formulas['ocean_s_coordinate_g2'] = ['z(n,k,j,i) = eta(n,j,i) + (eta(n,j,i) + depth(j,i)) * S(k,j,i)',
                                                  'S(k,j,i) = (depth_c * s(k) + depth(j,i) * C(k)) / (depth_c + depth(j,i))']

        self.formulas['ocean_sigma_z_coordinate'] = ['z(n,k,j,i)=eta(n,j,i)+sigma(k)*(min(depth_c,depth(j,i))+eta(n,j,i))',
                                                     'z(n,k,j,i)=zlev(k)']

        self.formulas['ocean_double_sigma_coordinate'] = ['z(k,j,i)=sigma(k)*f(j,i)',
                                                          'z(k,j,i)=f(j,i)+(sigma(k)-1)*(depth(j,i)-f(j,i))',
                                                          'f(j,i)=0.5*(z1+z2)+0.5*(z1-z2)*tanh(2*a/(z1-z2)*(depth(j,i)-href))']

        # Set up nested dictionary of:
        # 1) valid standard_names for variables named by the formula_terms attribute
        # 2) computed_standard_names (csn) for the variable specifying the formula_terms attribute

        self.ft_var_stdnames=defaultdict(dict)

        self.ft_var_stdnames['atmosphere_ln_pressure_coordinate'] = {'p0': ['reference_air_pressure_for_atmosphere_vertical_coordinate'],
                                                                     'csn': ['air_pressure']}

        self.ft_var_stdnames['sigma'] = {'ptop': ['air_pressure_at_top_of_atmosphere_model'],
                                         'ps': ['surface_air_pressure'],
                                         'csn': ['air_pressure']}

        self.ft_var_stdnames['hybrid_sigma_pressure'] = {'p0': ['reference_air_pressure_for_atmosphere_vertical_coordinate'],
                                                         'ps': ['surface_air_pressure'],
                                                         'csn': ['air_pressure']}

        self.ft_var_stdnames['atmosphere_hybrid_height_coordinate'] = {'orog': ['surface_altitude', 'surface_height_above_geopotential_datum'],
                                                                       'a': ['atmosphere_hybrid_height_coordinate'],
                                                                       'csn': ['altitude', 'height_above_geopotential_datum']}

        self.ft_var_stdnames['atmosphere_sleve_coordinate'] = {'ztop': ['altitude_at_top_of_atmosphere_model', 'height_above_geopotential_datum_at_top_of_atmosphere_model'],
                                                               'csn': ['altitude', 'height_above_geopotential_datum']}

        self.ft_var_stdnames['ocean_sigma_coordinate'] = {'eta': ['set'], 'depth': ['set'], 'csn': ['set']}
        self.ft_var_stdnames['ocean_s_coordinate'] = {'eta': ['set'], 'depth': ['set'], 'csn': ['set']}
        self.ft_var_stdnames['ocean_s_coordinate_g1'] = {'eta': ['set'], 'depth': ['set'], 'csn': ['set']}
        self.ft_var_stdnames['ocean_s_coordinate_g2'] = {'eta': ['set'], 'depth': ['set'], 'csn': ['set']}
        self.ft_var_stdnames['ocean_sigma_z_coordinate'] = {'eta': ['set'], 'depth': ['set'], 'zlev': ['set'], 'csn': ['set']}
        self.ft_var_stdnames['ocean_double_sigma_coordinate'] = {'depth': ['set'], 'csn': ['set']}

        self.ft_stdname_sets = defaultdict(dict)
        self.ft_stdname_sets[0] = {'zlev': ['altitude'],
                                   'eta': ['sea_surface_height_above_geoid'],
                                   'depth': ['sea_floor_depth_below_geoid'],
                                   'csn': ['altitude']}

        self.ft_stdname_sets[1] = {'zlev': ['height_above_geopotential_datum'],
                                   'eta': ['sea_surface_height_above_geopotential_datum'],
                                   'depth': ['sea_floor_depth_below_geopotential_datum'],
                                   'csn': ['height_above_geopotential_datum']}

        self.ft_stdname_sets[2] ={'zlev': ['height_above_reference_ellipsoid'],
                                  'eta': ['sea_surface_height_above_reference_ellipsoid'],
                                  'depth': ['sea_floor_depth_below_reference_ellipsoid'],
                                  'csn': ['height_above_reference_ellipsoid']}

        self.ft_stdname_sets[3] = {'zlev': ['height_above_mean_sea_level'],
                                   'eta': ['sea_surface_height_above_mean_ sea_level'],
                                   'depth': ['sea_floor_depth_below_mean_ sea_level'],
                                   'csn': ['height_above_mean_sea_level']}

    def parseBlankSeparatedList(self, list):
        """Parse blank separated list"""
        if re.match("^[a-zA-Z0-9_ ]*$",list):
            return 1
        else:
            return 0

    def extendedBlankSeparatedList(self, list):
        """Check list is a blank separated list of words containing alphanumeric characters
        plus underscore '_', period '.', plus '+', hyphen '-', or "at" sign '@'."""
        if re.match("^[a-zA-Z0-9_ @\-\+\.]*$", list):
            return 1
        else:
            return 0

    def commaOrBlankSeparatedList(self, list):
        """Check list is a blank or comma separated list of words containing alphanumeric
        characters plus underscore '_', period '.', plus '+', hyphen '-', or "at" sign '@'."""
        if re.match("^[a-zA-Z0-9_ @\-\+\.,]*$", list):
            return 1
        else:
            return 0

    def chkGlobalAttributes(self):
        """Check validity of global attributes."""
        for attribute in self.f.ncattrs():
            if not self.validName(attribute):
                self._add_warn("Global attribute {}: Attribute names should begin with a letter and be composed "
                               "of letters, digits and underscores".format(attribute),
                               code='2.3')

            # If this is a standard CF attribute check that it is a global attribute
            try:
                uses = self.AttrList[attribute][1]
                if 'G' not in uses:
                    self._add_info("Attribute {} is being used in a non-standard way; as a global attribute. "
                                   "(See Appendix A)".format(attribute))
            except KeyError:
                pass

        if hasattr(self.f, 'Conventions'):
            conventions = self.f.Conventions

            # Conventions attribute can be a blank separated (or comma separated) list of conforming conventions
            if not self.commaOrBlankSeparatedList(conventions):
                self._add_error("Conventions attribute must be a blank (or comma) separated list of convention names",
                                code="2.6.1")
            else:
                # Split string up into component parts
                # If a comma is present we assume a comma separated list as names cannot contain commas
                if re.match("^.*,.*$", conventions):
                    conventionList = conventions.split(",")
                else:
                    conventionList = conventions.split()

                found = 0
                for convention in conventionList:
                    if convention.strip() in list(map(str, cfVersions)):
                        found = 1
                        break

                if found != 1:
                    self._add_error("This netCDF file does not appear to contain CF Convention data.",
                                    code="2.6.1")
                else:
                    if convention.strip() != str(self.version):
                        self._add_warn("Inconsistency - This netCDF file appears to contain %s data, "
                                       "but you've requested a validity check against %s" % (convention, self.version),
                                       code="2.6.1")
        else:
            self._add_warn("No 'Conventions' attribute present", code="2.6.1")

        # Discrete geometries
        if self.version >= vn1_6 and hasattr(self.f, 'featureType'):
            featureType = self.f.featureType

            if not re.match('^(point|timeSeries|trajectory|profile|timeSeriesProfile|trajectoryProfile)$', featureType, re.I):
                self._add_error("Global attribute 'featureType' contains invalid value",
                                code="9.4")

        # External variables
        if self.version >= vn1_7 and hasattr(self.f, 'external_variables'):
            external_vars = self.f.external_variables
            if is_str_or_basestring(external_vars):
                if not self.parseBlankSeparatedList(external_vars):
                    self._add_error("external_variables attribute must be a blank separated list of variable names",
                                    code="2.6.3")
                else:
                    # Split string up into component parts
                    external_vars_list = external_vars.split()
                    for var in external_vars_list:
                        if var.strip() in list(map(str, self.f.variables)):
                            self._add_error("Variable %s named as an external variable must not be present in this file" % var,
                                            code="2.6.3")

        # Global attributes that must be of type string
        str_global_attrs = ['title', 'history', 'institution', 'source', 'references', 'comment']
        if self.version >= vn1_6:
            str_global_attrs.append('featureType')
        if self.version >= vn1_7:
            str_global_attrs.append('external_variables')

        for attribute in str_global_attrs:
            if hasattr(self.f, attribute):
                if isnt_str_or_basestring(self.f.getncattr(attribute)):
                    self._add_error("Global attribute %s must be of type 'String'" % attribute,
                                    code="2.6.2")

    def getFileCFVersion(self):
        """Return CF version of file, used for auto version option. If Conventions is COARDS return CF-1.0,
        else a valid version based on Conventions else an empty version (for auto version)"""
        rc = CFVersion()

        if "Conventions" in list(map(str, self.f.ncattrs())):
            value = self.f.getncattr('Conventions')

            if is_str_or_basestring(value):
                try:
                    conventions = str(value)
                except UnicodeEncodeError:
                    conventions = value.encode(errors='ignore')
            else:
                conventions = value

            # Split string up into component parts
            # If a comma is present we assume a comma separated list as names cannot contain commas
            if re.match("^.*,.*$", conventions):
                conventionList = conventions.split(",")
            else:
                conventionList = conventions.split()

            found = 0
            coards = 0
            for convention in conventionList:
                if convention.strip() in list(map(str, cfVersions)):
                    found = 1
                    rc = CFVersion(convention.strip())
                    break
                elif convention.strip() == 'COARDS':
                    coards = 1

            if not found and coards:
                self._add_warn("The conventions attribute specifies COARDS, assuming CF-1.0")
                rc = CFVersion((1, 0))

        return rc

    def validName(self, name):
        """ Check for valid name.  They should begin with a
        letter and be composed of letters, digits and underscores."""

        nameSyntax = re.compile('^[a-zA-Z][a-zA-Z0-9_]*$')
        if not nameSyntax.match(name):
            return 0

        return 1

    def chkDimensions(self, varName, allcoordVars):
        """Check variable has non-repeated dimensions, that space/time dimensions are listed in the order T,Z,Y,X
        and that any non space/time dimensions are added to the left of the space/time dimensions, unless it
        is a boundary variable or climatology variable, where 1 trailing dimension is allowed.
        """

        var = self.f.variables[varName]
        dimensions = list(map(str, var.dimensions))
        trailingVars = []
    
        if len(list(dimensions)) > 1:
            order = ['T', 'Z', 'Y', 'X']
            axesFound = [0, 0, 0, 0]    # Holding array to record whether a dimension with an axis value has been found.
            i = -1
            lastPos = -1

            # Flags to hold positions of first space/time dimension and
            # last Non-space/time dimension in variable declaration.
            firstST = -1
            lastNonST = -1
            nonSpaceDimensions = []

            for dim in dimensions:
                if not self.validName(dim):
                    self._add_warn("Dimension names should begin with a letter and be composed "
                               "of letters, digits and underscores: {}".format(dim),
                               code='2.3')
                i = i+1
                try:
                    if hasattr(self.f.variables[dim], 'axis'):
                        pos = order.index(self.f.variables[dim].axis)

                        # Is there already a dimension with this axis attribute specified.
                        if axesFound[pos] == 1:
                            self._add_error("Variable has more than 1 coordinate variable with same axis value",
                                            varName)
                        else:
                            axesFound[pos] = 1
                    elif hasattr(self.f.variables[dim], 'units') and self.f.variables[dim].units != "":
                        # Determine interpretation of variable by units attribute
                        if hasattr(self.f.variables[dim], 'positive'):
                            interp = self.getInterpretation(self.f.variables[dim].units, self.f.variables[dim].positive)
                        else:
                            interp = self.getInterpretation(self.f.variables[dim].units)

                        if not interp: raise ValueError
                        pos = order.index(interp)
                    else:
                        # No axis or units attribute so can't determine interpretation of variable
                        raise ValueError

                    if firstST == -1:
                        firstST = pos
                except KeyError:
                    pass
                except ValueError:
                    # Dimension is not T,Z,Y or X axis
                    nonSpaceDimensions.append(dim)
                    trailingVars.append(dim)
                    lastNonST = i
                else:
                    # Is the dimensional position of this dimension further to the right than the previous dim?
                    if pos >= lastPos:
                        lastPos = pos
                        trailingVars = []
                    else:
                        self._add_warn("space/time dimensions appear in incorrect order", varName, code="2.4")

            # As per CRM #022
            # This check should only be applied for COARDS conformance.
            if self.coards:
                validTrailing = self.boundsVars[:]
                validTrailing[len(validTrailing):] = self.climatologyVars[:]
                if lastNonST > firstST and firstST != -1:
                    if len(trailingVars) == 1:
                        if varName not in validTrailing:
                            self._add_warn("dimensions %s should appear to left of space/time dimensions" % nonSpaceDimensions,
                                           varName, code="2.4")
                    else:
                        self._add_warn("dimensions %s should appear to left of space/time dimensions" % nonSpaceDimensions,
                                       varName, code="2.4")

            sorted(dimensions)
            if not self.uniqueList(dimensions):
                self._add_error("variable has repeated dimensions", varName, code="2.4")

    def getTypeCode(self, obj):
        """
        Get the type, as a 1-character code
        """
        if isinstance(obj, netCDF4.Variable):
            # Variable object
            if isinstance(obj.datatype, netCDF4.VLType):
                # VLEN types not supported
                return 'vlen'
          
            try:
                typecode = obj.dtype.char
            except AttributeError as e:
                self._add_warn("Problem getting typecode: {}".format(e), obj.name)
        else:
            # Attribute object
            if isinstance(obj, bytes):
                # Bytestring
                typecode='S'
            else:
                typecode = obj.dtype.char
          
        return typecode

    def chkAttribute(self, attribute, varName, allCoordVars, geometryContainerVars):
        """Check the syntax of the attribute name, that the attribute
        is of the correct type and that it is attached to the right
        kind of variable."""
        var = self.f.variables[varName]

        # https://www.unidata.ucar.edu/software/netcdf/docs/file_format_specifications.html
        reserved_attributes = ["_FillValue", "_Encoding", "_Unsigned"]

        if not self.validName(attribute) and attribute not in reserved_attributes:
            self._add_error("Invalid attribute name: {}".format(attribute),
                            varName)
            return

        try:
            value = var.getncattr(attribute)
        except KeyError as e:
            self._add_error("{} - {}".format(attribute, e), varName, code="2.2")
            if attribute in self.AttrList:
                # This is a standard attribute so inform user no further checks being made on it
                self._add_info("No further checks made on attribute: {}".format(attribute), varName)
            return

        self._add_debug("chkAttribute: Checking attribute - {}".format(attribute), varName)
 
        # ------------------------------------------------------------
        # Attribute of wrong 'type' in the sense numeric/non-numeric
        # ------------------------------------------------------------
        if attribute in self.AttrList:
            # Standard Attribute, therefore check type

            attrType = type(value)

            if isinstance(value, bytes):
                # Bytestring
                value = value.decode('utf-8')

            if is_str_or_basestring(value):
                attrType = 'S'
            elif numpy.issubdtype(attrType, numpy.integer) or numpy.issubdtype(attrType, numpy.floating):
                attrType = 'N'
            elif attrType == numpy.ndarray:
                attrType = 'N'
            elif attrType == type(None):
                attrType = 'NoneType'
            else:
                self._add_info("Invalid Type for attribute: %s %s" % (attribute, attrType))

            # If attrType = 'NoneType' then it has been automatically created e.g. missing_value
            typeError = 0
            if attrType != 'NoneType':
                if self.AttrList[attribute][0] == 'D':
                    # Special case for 'D' as these attributes will always be caught
                    # by one of the above cases.
                    # Attributes of type 'D' should be the same type as the data variable
                    # they are attached to.
                    if attrType == 'S':
                        # Note: A string is an array of chars
                        if self.getTypeCode(var) != 'S':
                            typeError = 1
                    else:
                        if self.getTypeCode(var) != self.getTypeCode(var.getncattr(attribute)):
                                typeError = 1

                elif self.AttrList[attribute][0] != attrType:
                    typeError = 1

                if typeError:

                    attrLookup = {"D": "Data Variable",
                                  "N": "Numeric",
                                  "S": "String"}

                    self._add_error("Attribute %s of incorrect type (expecting '%s' type, got '%s' type)" %
                                    (attribute,
                                     attrLookup[self.AttrList[attribute][0]],
                                     attrLookup[attrType]),
                                    varName)

            # Attribute attached to the wrong kind of variable
            uses = self.AttrList[attribute][1]
            usesLen = len(uses)
            i = 1
            for use in uses:
                if use == "C" and varName in allCoordVars:
                    # Valid association
                    break
                elif use == "D" and varName not in allCoordVars:
                    # Valid association
                    break
                elif use == "M" and varName in geometryContainerVars.keys():
                    # Variable is a geometry container variable - valid association
                    break
                elif i == usesLen:
                    if attribute == "missing_value":
                        # Special case since missing_value attribute is present for all
                        # variables whether set explicitly or not. Is this a cdms thing?
                        # Using var.missing_value is null then missing_value not set in the file
                        if var.missing_value:
                            self._add_warn("attribute %s attached to wrong kind of variable" % attribute,
                                           varName)
                    else:
                        self._add_info("attribute %s is being used in a non-standard way" % attribute,
                                       varName)
                else:
                    i = i+1

            # Check no time variable attributes. E.g. calendar, month_lengths etc.
            TimeAttributes = ['calendar', 'month_lengths', 'leap_year', 'leap_month', 'climatology']
            if attribute in TimeAttributes:

                if hasattr(var, 'units'):
                    varUnits = Units(var.units)
                    secsSinceEpoch = Units('seconds since 1970-01-01')

                    if not varUnits.equivalent(secsSinceEpoch):
                        self._add_error("Attribute %s may only be attached to time coordinate variable" % attribute,
                                        varName, code="4.4.1")
                else:
                    self._add_error("Attribute %s may only be attached to time coordinate variable" % attribute,
                                    varName, code="4.4.1")

    def chkCFRole(self, varName):
        """Validate cf_role attribute"""
        var = self.f.variables[varName]

        if hasattr(var, 'cf_role'):
            cf_role = var.cf_role

            # Keep a tally of how many variables have the cf_role attribute set
            self.cf_roleCount = self.cf_roleCount + 1

            if not cf_role in ['timeseries_id', 'profile_id', 'trajectory_id']:
                self._add_error("Invalid value for cf_role attribute", varName, code="9.5")

    def chkRaggedArray(self, varName):
        """Validate count/index variable"""
        var=self.f.variables[varName]
  
        if hasattr(var, 'sample_dimension'):

            self._add_debug("is a count variable (Discrete Geometries)", varName)
            self.raggedArrayFlag = 1
          
            if self.getTypeCode(var) != 'i':
                self._add_error("count variable must be of type integer", varName, code="9.3")

        if hasattr(var, 'instance_dimension'):

            self._add_debug("is an index variable (Discrete Geometries)", varName)
            self.raggedArrayFlag = 1

            if self.getTypeCode(var) != 'i':
                self._add_error("index variable must be of type integer", varName, code="9.3")

    def isValidCellMethodTypeValue(self, type, value, varName):
        """
        Is <type1> or <type2> in the cell_methods attribute a valid value
        (method may have side-effect of logging additional errors,
        and for this purpose the variable name is also passed in)
        """
        rc = 1

        # Is it a string-valued aux coord var with standard_name of area_type?
        if value in self.auxCoordVars:
            if self.f.variables[value].dtype.char != 'c':
                rc = 0
            elif type == "type2":
                # <type2> has the additional requirement that it is not allowed a leading dimension of more than one
                leadingDim = self.f.variables[value].dimensions[0]
                # Must not be a value of more than one
                if self.f.dimensions[leadingDim] > 1:
                    self._add_error("%s is not allowed a leading dimension of more than one." % value,
                                    varName)

            if hasattr(self.f.variables[value], 'standard_name'):
                if self.f.variables[value].standard_name != 'area_type':
                   rc = 0
                  
        # Is type a valid area_type according to the area_type table
        elif value not in self.area_type_lh.list:
            rc = 0

        return rc

    def chkCellMethods(self, varName):
        """Checks on cell_methods attribute
           dim1: [dim2: [dim3: ...]] method [where type1 [over type2]] [ (comment) ]
           where comment is of the form:  ([interval: value unit [interval: ...] comment:] remainder)
        """
        varDimensions = {}
        var = self.f.variables[varName]
    
        if hasattr(var, 'cell_methods'):
            cellMethods = var.cell_methods

    #        cellMethods="lat: area: maximum (interval: 1 hours interval: 3 hours comment: fred)"

            pr1 = re.compile(r'^'
                             r'(\s*\S+\s*:\s*(\S+\s*:\s*)*'
                             r'([a-z_]+)'
                             r'(\s+where\s+\S+(\s+over\s+\S+)?)?'
                             r'(\s+(over|within)\s+(days|years))?\s*'
                             r'(\((interval:\s+\d+\s+\S+\s*)*(comment: .+)?.*\))?)'
                             r'+$')

            # Validate the entire string
            m = pr1.match(cellMethods)
            if not m:
                self._add_error("Invalid syntax for cell_methods attribute", varName, code="7.3")

            # Grab each word-list
            # dim1: [dim2: [dim3: ...]] method [where type1 [over type2]] [within|over days|years] [(comment)]
            pr2 = re.compile(r'(?P<dimensions>\s*\S+\s*:\s*(\S+\s*:\s*)*'
                             r'(?P<method>[a-z_]+)'
                             r'(?:\s+where\s+(?P<type1>\S+)(?:\s+over\s+(?P<type2>\S+))?)?'
                             r'(?:\s+(?:over|within)\s+(?:days|years))?\s*)'
                             r'(?P<comment>\([^)]+\))?')

            substr_iter = pr2.finditer(cellMethods)

            # Validate each substring
            for s in substr_iter:
                if not re.match(r'point|sum|maximum|median|mid_range|minimum|mean|mode|standard_deviation|variance',
                                s.group('method')):
                    self._add_error("Invalid cell_method: %s" %s.group('method'),
                                    varName, code="7.3")

                if self.version >= vn1_4:
                    if s.group('type1'):
                        if not self.isValidCellMethodTypeValue('type1', s.group('type1'), varName):
                            self._add_error("Invalid type1: %s - must be a variable name or valid area_type" % s.group('type1'),
                                            varName, code="7.3")

                    if s.group('type2'):
                        if not self.isValidCellMethodTypeValue('type2', s.group('type2'), varName):
                            self._add_error("Invalid type2: %s - must be a variable name or valid area_type" % s.group('type2'),
                                            varName, code="7.3")

                # Validate dim and check that it only appears once unless it is 'time'
                allDims = re.findall(r'\S+\s*:',s.group('dimensions'))
                dc = 0          # Number of dims

                for part in allDims:
                    dims = re.split(':',part)

                    for d in dims:
                        if d:
                            dc = dc+1
                            if d not in var.dimensions and d not in list(self.std_name_dh.dict.keys()):
                                if self.version >= vn1_4:
                                    # Extra constraints at CF-1.4 and above
                                    if d != "area":
                                        self._add_error("Invalid 'name' in cell_methods attribute: %s" % d,
                                                        varName,
                                                        code="7.3")
                                else:
                                    self._add_error("Invalid 'name' in cell_methods attribute: %s" % d,
                                                    varName,
                                                    code="7.3")
                            else:
                                # dim is a variable dimension
                                if d != "time" and d in varDimensions:
                                    self._add_error("Multiple cell_methods entries for dimension: %s" % d,
                                                    varName,
                                                    code="7.3")
                                else:
                                    varDimensions[d] = 1

                                if self.version >= vn1_4:
                                    # If dim is a coordinate variable and cell_method is not 'point' check
                                    # if the coordinate variable has either bounds or climatology attributes
                                    if d in self.coordVars and s.group('method') != 'point':
                                        if not hasattr(self.f.variables[d], 'bounds') \
                                                and not hasattr(self.f.variables[d], 'climatology'):
                                            self._add_warn("Coordinate variable {} should have bounds or "
                                                           "climatology attribute".format(d),
                                                           varName,
                                                           code="7.3")
                                                
                # Validate the comment associated with this method, if present
                comment = s.group('comment')
                if comment:
                    getIntervals = re.compile(r'(?P<interval>interval:\s+\d+\s+(?P<unit>\S+)\s*)')
                    allIntervals = getIntervals.finditer(comment)

                    # There must be zero, one or exactly as many interval clauses as there are dims
                    i = 0   # Number of intervals present
                    for m in allIntervals:
                        i = i+1
                        unit = m.group('unit')
                        if not Units(unit).isvalid:
                            self._add_error("Invalid unit %s in cell_methods comment" % unit, varName, code="7.3")

                    if i > 1 and i != dc:
                        self._add_error("Incorrect number or interval clauses in cell_methods attribute",
                                        varName,
                                        code="7.3")

    def chkCellMeasures(self, varName):
        """Checks on cell_measures attribute:
        1) Correct syntax
        2) Reference valid variable
        3) Valid measure"""
        var = self.f.variables[varName]
    
        if hasattr(var, 'cell_measures'):
            cellMeasures = var.cell_measures
            if not re.search("^([a-zA-Z0-9]+: +([a-zA-Z0-9_ ]+:?)*( +[a-zA-Z0-9_]+)?)$", cellMeasures):
                self._add_error("Invalid cell_measures syntax", varName, code="7.2")
            else:
                # Need to validate the measure + name
                split = cellMeasures.split()
                splitIter = iter(split)
                try:
                    while 1:
                        measure = next(splitIter)
                        variable = next(splitIter)

                        if variable not in self.f.variables:
                            if self.version >= vn1_7:
                                # Variable must exist in the file or be named by the external_variables attribute
                                msg = "cell_measures variable %s must either exist in this netCDF file " \
                                    "or be named by the external_variables attribute" % variable
                                if not hasattr(self.f, 'external_variables'):
                                    self._add_error(msg, varName, code="7.2")
                                elif variable not in self.f.external_variables.split():
                                    self._add_error(msg, varName, code="7.2")
                            else:
                                self._add_warn("cell_measures refers to variable {} that doesn't exist in this "
                                               "netCDF file. This is strictly an error if the cell_measures "
                                               "variable is not included in the dataset.".format(variable),
                                               varName, code="7.2")

                        else:
                            # Valid variable name in cell_measures so carry on with tests.
                            if len(self.f.variables[variable].dimensions) > len(var.dimensions):
                                self._add_error("Dimensions of {} must be same or a subset of {}".
                                                format(variable, list(map(str, var.dimensions))),
                                                varName, code="7.2")
                            else:
                                # If cell_measures variable has more dims than var then this check automatically will fail
                                # Put in else so as not to duplicate ERROR messages.
                                for dim in self.f.variables[variable].dimensions:
                                    if dim not in var.dimensions:
                                        self._add_error("Dimensions of %s must be same or a subset of %s" % (variable, list(map(str, var.dimensions))),
                                                        varName, code="7.2")

                            measure = re.sub(':', '', measure)
                            if not re.match("^(area|volume)$", measure):
                                self._add_error("Invalid measure in attribute cell_measures", varName, code="7.2")

                            if measure == "area" and Units(self.f.variables[variable].units) != Units('m2'):
                                self._add_error("Must have square meters for area measure", varName, code="7.2")

                            if measure == "volume" and Units(self.f.variables[variable].units) != Units('m3'):
                                self._add_error("Must have cubic meters for volume measure", varName, code="7.2")

                except StopIteration:
                    pass

    def chkFormulaTerms(self, varName, allCoordVars):
        """Checks on formula_terms attribute (CF Section 4.3.3):
        formula_terms = var: term var: term ...
        1) No standard_name present
        2) No formula defined for std_name
        3) Invalid formula_terms syntax
        4) Var referenced, not declared"""
        var = self.f.variables[varName]
    
        if hasattr(var, 'formula_terms'):

            if self.version >= vn1_7:
                # CF conventions document reorganised - section no. has changed
                scode = "4.3.3"
            else:
                scode = "4.3.2"

            if varName not in allCoordVars:
                self._add_error("formula_terms attribute only allowed on coordinate variables", varName, code=scode)

            # Get standard_name to determine which formula is to be used
            if not hasattr(var, 'standard_name'):
                self._add_error("Cannot get formula definition as no standard_name", varName, code=scode)
                # No sense in carrying on as can't validate formula_terms without valid standard name
                return

            (stdName, modifier) = self.getStdName(var)

            if stdName not in self.alias:
                self._add_error("No formula defined for standard name: %s" % stdName, varName, code=scode)
                # No formula available so can't validate formula_terms
                return

            index=self.alias[stdName]

            if self.version >= vn1_7:
                # Check computed_standard_name is valid
                setname = None
                if hasattr(var, 'computed_standard_name'):
                    csn = var.computed_standard_name
                    if self.ft_var_stdnames[index]['csn'][0] == 'set':
                        # Check which set
                        for key in list(self.ft_stdname_sets.keys()):
                            if csn in self.ft_stdname_sets[key]['csn']:
                                # Found
                                setname = key

                    elif csn not in self.ft_var_stdnames[index]['csn']:
                        self._add_error("Invalid computed_standard_name: %s" % csn, varName, code=scode)

            formulaTerms = var.formula_terms
            if not re.search("^([a-zA-Z0-9_]+: +[a-zA-Z0-9_]+( +)?)*$",formulaTerms):
                self._add_error("Invalid formula_terms syntax", varName, code=scode)
            else:
                # Need to validate the term & var
                iter_obj=iter(formulaTerms.split())
                while True:
                    try:
                        term = next(iter_obj)
                        term=re.sub(':', '', term)

                        ftvar = next(iter_obj)

                        # Term - Should be present in formula
                        found = 'false'
                        for formula in self.formulas[index]:
                            if re.search(term,formula):
                                found = 'true'
                                break

                        if found == 'false':
                            self._add_error("Formula term {} not present in formula for {}".format(term, stdName),
                                            varName, code=scode)

                        # Variable - should be declared in netCDF file
                        if ftvar not in list(self.f.variables.keys()):
                            self._add_error("%s is not declared as a variable" % ftvar, varName, code=scode)
                        elif ftvar == varName:
                            # var is the variable specifying the formula_terms attribute
                            pass
                        else:
                            if self.version >= vn1_7:
                                # Check that standard_name of formula term is consistent with that
                                # of the coordinate variable
                                if hasattr(self.f.variables[ftvar], 'standard_name'):
                                    try:
                                        valid_stdnames = self.ft_var_stdnames[index][term]
                                    except KeyError:
                                        # No standard_name specified for this formula_term
                                        continue

                                    if valid_stdnames[0] == 'set':
                                        if setname is None:
                                            for key in list(self.ft_stdname_sets.keys()):
                                                if self.f.variables[ftvar].standard_name in self.ft_stdname_sets[key][term]:
                                                    # Found
                                                    if not setname:
                                                        setname = key
                                                    elif setname != key:
                                                        # standard_names of formula_terms vars are inconsistent
                                                        self._add_error("Standard names of formula_terms variables "
                                                                        "are inconsistent/invalid", varName, code=scode)
                                                        break
                                        else:
                                            if not self.f.variables[ftvar].standard_name in self.ft_stdname_sets[setname][term]:
                                                self._add_error("Standard names of formula_terms variables are "
                                                                "inconsistent/invalid", varName, code=scode)

                                    elif self.f.variables[ftvar].standard_name not in valid_stdnames:
                                        self._add_error("Standard name of variable {} inconsistent with "
                                                        "that of {}".format(ftvar, varName),
                                                        varName, code=scode)

                    except StopIteration:
                        break

    def chkUnits(self, varName, allCoordVars):
        """Check units attribute"""

        var = self.f.variables[varName]

        if self.badc:
            # If unit is a BADC unit then no need to check via udunits
            if self.chkBADCUnits(var):
                return

        # Test for blank since coordinate variables have 'units' defined even if not specifically defined in the file
        if hasattr(var, 'units') and var.units != '':
            # Type of units is a string
            units = var.units

            if isnt_str_or_basestring(units):
                self._add_error("units attribute must be of type 'String'", varName, code="3.1")
                # units not a string so no point carrying out further tests
                return
            
            # units - level, layer and sigma_level are deprecated
            if units in ['level', 'layer', 'sigma_level']:
                self._add_warn("units %s is deprecated" % units, varName, code="3.1")
            elif units == 'month':
                self._add_warn("The unit 'month', defined by udunits to be exactly year/12, "
                               "should be used with caution",
                               varName, code="4.4")
            elif units == 'year':
                self._add_warn("The unit 'year', defined by udunits to be exactly 365.242198781 days, should be "
                               "used with caution. It is not a calendar year.",
                               varName, code="4.4")
            else:
                # units must be recognizable by udunits package
                try:
                    varUnit = Units(units)
                except TypeError:
                    varUnit = Units('error')

                if not varUnit.isvalid:
                    self._add_error("Invalid units: %s" % units,  varName, code="3.1")
                    # Invalid unit so no point continuing with further unit checks
                    return

                # units of a variable that specifies a standard_name must
                # be consistent with units given in standard_name table
                if hasattr(var, 'standard_name'):
                    (stdName,modifier) = self.getStdName(var)

                    # Is the Standard Name modifier number_of_observations being used.
                    if modifier == 'number_of_observations':
                        # Standard Name modifier is number_of_observations therefore units should be "1". See Appendix C
                        if not units == "1":
                            self._add_error("Standard Name modifier 'number_of_observations' present therefore "
                                            "units must be set to 1.",
                                            varName, code="3.3")
                  
                    elif stdName in list(self.std_name_dh.dict.keys()):
                        # Get canonical units from standard name table
                        stdNameUnits = self.std_name_dh.dict[stdName]

                        canonicalUnit = Units(stdNameUnits)
                        # To compare units we need to remove the reference time from the variable units
                        if re.search("since", units):
                            # unit attribute contains a reference time - remove it
                            varUnit = Units(units.split()[0])

                        # If variable has cell_methods=variance we need to square standard_name table units
                        if hasattr(var, 'cell_methods'):
                            # Remove comments from the cell_methods string - no need to search these
                            getComments = re.compile(r'\([^)]+\)')
                            noComments = getComments.sub('%5A', var.cell_methods)

                            if re.search(r'(\s+|:)variance', noComments):
                                # Variance method so standard_name units need to be squared.
                                unit1 = canonicalUnit
                                canonicalUnit = unit1 * unit1

                        if not varUnit.equivalent(canonicalUnit):
                            # Conversion unsuccessful
                            self._add_error("Units are not consistent with those given in the standard_name table.",
                                             varName, code="3.1")
        else:

            # No units attribute - is this a coordinate variable or
            # dimensionless vertical coordinate var
            if varName in allCoordVars:
              
                # Label variables do not require units attribute
                try:
                    if self.f.variables[varName].dtype.char != 'S':
                        if hasattr(var, 'axis'):
                            if not var.axis == 'Z':
                                self._add_warn("units attribute should be present", varName, code="3.1")
                        elif not hasattr(var,'positive') \
                                and not hasattr(var, 'formula_terms') \
                                and not hasattr(var, 'compress'):
                            self._add_warn("units attribute should be present", varName, code="3.1")
                except:
                    pass

            elif varName not in self.boundsVars \
                    and varName not in self.climatologyVars \
                    and varName not in self.gridMappingVars:
                # Variable is not a boundary or climatology variable

                dimensions = self.f.variables[varName].dimensions

                if not (hasattr(var, 'flag_values')
                        or hasattr(var, 'flag_masks')) \
                        and len(dimensions) != 0:
                    try:
                        if self.f.variables[varName].dtype.char != 'S':
                            # Variable is not a flag variable or a scalar or a label
                            self._add_info("No units attribute set.  Please consider adding a units attribute "
                                           "for completeness.",
                                           varName, code="3.1")
                    except AttributeError:
                        typecodes = "char, byte, short, int, float, real, double"
                        self._add_warn("Could not get typecode of variable.  Variable types supported "
                                       "are: %s" % typecodes,
                                       varName,
                                       code="2.2")

    def chkBADCUnits(self, var):
        """Check units allowed by BADC"""
        units_lines = open("/usr/local/cf-checker/lib/badc_units.txt").readlines()
      
        # units must be recognizable by the BADC units file
        for line in units_lines:
            if hasattr(var, 'units') and var.attributes['units'] in string.split(line):
                self._add_info("Valid units in BADC list: %s" % var.attributes['units'], var.id)
                return 1
        return 0

    def chkValidMinMaxRange(self, varName):
        """Check that valid_range and valid_min/valid_max are not both specified"""
        var = self.f.variables[varName]
    
        if hasattr(var, 'valid_range'):
            if hasattr(var, 'valid_min') or hasattr(var, 'valid_max'):
                self._add_error("Illegal use of valid_range and valid_min/valid_max", varName, code="2.5.1")

    def chkComputedStandardName(self, varName):
        """Check if var computed_standard_name attribute that it also has formula_terms attribute"""
        var= self.f.variables[varName]
      
        if hasattr(var, 'computed_standard_name') and not hasattr(var, 'formula_terms'):
            self._add_error("computed_standard_name attribute is only allowed on a coordinate variable "
                            "which has a formula_terms attribute",
                            varName, code="4.3.3")

    def chkActualRange(self, varName):
        """Check that the actual_range:
        1) is the same type as its associated variable or scale_factor/add_offset if set
        2) has 2 elements where the first equals the min non-missing value and the second the max
        after any scale_factor/add_offset applied
        3) is not present if all data values are equal to missing value
        4) is valid if valid_range/valid_min/valid_max are specified
        """
        var = self.f.variables[varName]

        if hasattr(var, 'actual_range'):
            actual_range = var.actual_range

            if len(actual_range) != 2:
                self._add_error("actual_range attribute must contain only 2 elements",
                                varName, code="2.5.1")

            actual_range_type = var.actual_range.dtype.char

            # actual_range must be of same type as scale_factor/add_offset, if present otherwise the associated variable
            if hasattr(var, 'scale_factor') or hasattr(var, 'add_offset'):

                if hasattr(var, 'scale_factor') and actual_range_type != var.scale_factor.dtype.char:
                        self._add_error("actual_range attribute must be of same type as scale_factor",
                                        varName, code="2.5.1")

                if hasattr(var, 'add_offset') and actual_range_type != var.add_offset.dtype.char:
                        self._add_error("actual_range attribute must be of same type as add_offset",
                                        varName, code="2.5.1")
            else:
                if actual_range_type != var.dtype.char:
                    self._add_error("actual_range attribute must be of same type as variable %s" % varName,
                                    varName, code="2.5.1")

            # actual_range values must lie within valid_range, if specified
            min_v = None
            max_v = None
            if hasattr(var, 'valid_range'):
                min_v = var.valid_range[0]
                max_v = var.valid_range[1]
            elif hasattr(var, 'valid_min') or hasattr(var, 'valid_max'):
                try:
                    min_v = var.valid_min
                except AttributeError:
                    pass
                try:
                    max_v = var.valid_max
                except AttributeError:
                    pass

            if min_v and max_v:
                if not ((min_v <= actual_range[0] <= max_v) and (min_v <= actual_range[1] <= max_v)):
                    self._add_error("actual_range values must lie between %s and %s (valid_range)" %(min_v, max_v),
                                    varName, code="2.5.1")

            elif min_v and not ((min_v <= actual_range[0]) and (min_v <= actual_range[1])):
                self._add_error("actual_range values must be greater than or equal to %s (valid_min)" % min_v,
                                varName, code="2.5.1")

            elif max_v and not ((actual_range[0] <= max_v) and (actual_range[1] <= max_v)):
                self._add_error("actual_range values must be less than or equal to %s (valid_max)" % max_v,
                                varName, code="2.5.1")

            varData = self.f.variables[varName][:]
            # Note: scale_factor & add_offset is automatically applied to data values.
            if varData.count() == 0:
                # All data values equal the missing value
                self._add_error("There must be no actual_range attribute when all data values equal the missing value",
                                varName, code="2.5.1")
            else:
                # Data values present
                missing_value = None
          
                if hasattr(var, '_FillValue'):
                    missing_value = var._FillValue
                elif hasattr(var, 'missing_value'):
                    missing_value = var.missing_value

                if missing_value:
                    # Find minimum and maximum data value.
                    # varData doesn't include values that are missing data
                    min_dv=varData.min()
                    max_dv=varData.max()

                    if min_dv and actual_range[0] != min_dv:
                        self._add_error("First element of actual_range must equal minimum data value of variable "
                                        "after scale_factor/add_offset applied ({})".format(min_dv),
                                        varName, code="2.5.1")
                    if max_dv and actual_range[1] != max_dv:
                        self._add_error("Second element of actual_range must equal maximum data value of variable "
                                        "after scale_factor/add_offset applied ({})".format(max_dv),
                                        varName, code="2.5.1")

    def chk_FillValue(self, varName):
        """Check 1) type of _FillValue
        2) _FillValue lies outside of valid_range
        3) type of missing_value
        """
        var = self.f.variables[varName]

        if hasattr(var, '_FillValue'):
            fillValue = var._FillValue

            if hasattr(var, 'valid_range'):
                # Check _FillValue is outside valid_range
                validRange = var.valid_range
                if validRange[0] < fillValue < validRange[1]:
                    self._add_warn("_FillValue should be outside valid_range", varName, code="2.5.1")

            if varName in self.boundsVars:
                self._add_warn("Boundary Variable {} should not have _FillValue attribute".format(varName),
                               varName, code="7.1")
            elif varName in self.climatologyVars:
                self._add_error("Climatology Variable {} must not have _FillValue attribute".format(varName),
                                varName, code="7.4")

        if hasattr(var, 'missing_value'):
            missingValue = var.missing_value
            try:
                if missingValue:
                    if hasattr(var, '_FillValue'):

                        if isinstance(fillValue, bytes):
                            fillValue = fillValue.decode('utf-8')

                        if fillValue != missingValue:
                            # Special case: NaN == NaN is not detected as NaN does not compare equal to anything else
                            if not (numpy.isnan(fillValue) and numpy.isnan(missingValue)):
                                self._add_warn("missing_value and _FillValue set to differing values",
                                               varName, code="2.5.1")

                    if varName in self.boundsVars:
                        self._add_warn("Boundary Variable %s should not have missing_value attribute" % varName,
                                       varName, code="7.1")

                    elif var in self.climatologyVars:
                        self._add_error("Climatology Variable %s must not have missing_value attribute" % varName,
                                        varName, code="7.4")

            except ValueError:
                self._add_info("Could not complete tests on missing_value attribute: %s" % sys.exc_info()[1], varName)

    def chkAxisAttribute(self, varName):
        """Check validity of axis attribute"""
        var = self.f.variables[varName]
      
        if hasattr(var, 'axis'):
            if not re.match('^(X|Y|Z|T)$', var.axis, re.I):
                self._add_error("Invalid value for axis attribute", varName, code="4")
                return

            # axis attribute is allowed on an aux coord var as of CF-1.6
            if self.version >= vn1_1 and self.version < vn1_6 and varName in self.auxCoordVars:
                self._add_error("Axis attribute is not allowed for auxillary coordinate variables.",
                                varName, code="4")
                return
          
            # Check that axis attribute is consistent with the coordinate type
            # deduced from units and positive.
            if hasattr(var, 'units'):
                if hasattr(var, 'positive'):
                    interp = self.getInterpretation(var.units,var.positive)
                else:
                    interp = self.getInterpretation(var.units)
            else:
                # Variable does not have a units attribute so a consistency check cannot be made
                interp = None

            if interp != None:
                # It was possible to deduce axis interpretation from units/positive
                if interp != var.axis:
                    self._add_error("axis attribute inconsistent with coordinate type as deduced from "
                                    "units and/or positive",
                                    varName, code="4")
                    return

    def chkPositiveAttribute(self, varName):
        var = self.f.variables[varName]
        if hasattr(var, 'positive'):
            if not re.match('^(down|up)$', var.positive, re.I):
                self._add_error("Invalid value for positive attribute", varName, code="4.3")

    def chkTimeVariableAttributes(self, varName):
        var = self.f.variables[varName]

        if hasattr(var, 'calendar'):
            if not re.match('(gregorian|standard|proleptic_gregorian|noleap|365_day|all_leap|'
                            '366_day|360_day|julian|none)', var.calendar, re.I):
                # Non-standardized calendar so month_lengths should be present
                if not hasattr(var, 'month_lengths'):
                    self._add_error("Non-standard calendar, so month_lengths attribute must be present",
                                    varName,
                                    code="4.4.1")
            else:
                if hasattr(var, 'month_lengths') or \
                   hasattr(var, 'leap_year') or \
                   hasattr(var, 'leap_month'):
                    self._add_error("The attributes 'month_lengths', 'leap_year' and 'leap_month' must not appear "
                                    "when 'calendar' is present.",
                                    varName,
                                    code="4.4.1")

        if not hasattr(var, 'calendar') and not hasattr(var, 'month_lengths'):
            self._add_warn("Use of the calendar and/or month_lengths attributes is recommended for time "
                           "coordinate variables", varName, code="4.4.1")

        if hasattr(var, 'month_lengths'):
            if len(var.month_lengths) != 12 and \
               self.getTypeCode(var.month_lengths) != 'i':
                self._add_error("Attribute 'month_lengths' should be an integer array of size 12",
                                varName, code="4.4.1")

        if hasattr(var, 'leap_year'):
            if self.getTypeCode(var.leap_year) != 'i' and \
               len(var.leap_year) != 1:
                self._add_error("leap_year should be a scalar value", varName, code="4.4.1")

        if hasattr(var, 'leap_month'):
            if not re.match("^(1|2|3|4|5|6|7|8|9|10|11|12)$",
                            str(var.leap_month[0])):
                self._add_error("leap_month should be between 1 and 12", varName, code="4.4.1")

            if not hasattr(var, 'leap_year'):
                self._add_warn("leap_month is ignored as leap_year NOT specified", varName, code="4.4.1")

        # Time units must contain a reference time
        try:
            varUnits = Units(var.units)
        except TypeError:
            varUnits = Units('error')

        if not varUnits.isreftime:
            self._add_error("Invalid units and/or reference time", varName, code="4.4")

    def chkDescription(self, varName):
        """Check 1) standard_name & long_name attributes are present
                 2) for a valid standard_name as listed in the standard name table."""
        var = self.f.variables[varName]

        if not hasattr(var, 'standard_name') and \
           not hasattr(var, 'long_name'):

            exceptions = self.boundsVars + self.climatologyVars + self.gridMappingVars + \
                         list(map(str, self.geometryContainerVars.keys()))
            if varName not in exceptions:
                self._add_warn("No standard_name or long_name attribute specified", varName, code="3")
              
        if hasattr(var, 'standard_name'):
            # Check if valid by the standard_name table and allowed modifiers
            std_name = var.standard_name

            # standard_name attribute can comprise a standard_name only or a standard_name
            # followed by a modifier (E.g. atmosphere_cloud_liquid_water_content status_flag)
            std_name_el = std_name.split()
            if not std_name_el:
                self._add_error("Empty string for 'standard_name' attribute", varName, code="3.3")
              
            elif not self.parseBlankSeparatedList(std_name) or len(std_name_el) > 2:
                self._add_error("Invalid syntax for 'standard_name' attribute: '%s'" % std_name, varName, code="3.3")

            else:
                # Validate standard_name
                name = std_name_el[0]
                if not name in list(self.std_name_dh.dict.keys()):
                    if check_derived_name(name):
                        self._add_error("Invalid standard_name: %s" % name, varName, code="3.3")

                if len(std_name_el) == 2:
                    # Validate modifier
                    modifier = std_name_el[1]
                    if not modifier in ['detection_minimum', 'number_of_observations', 'standard_error', 'status_flag']:
                        self._add_error("Invalid standard_name modifier: %s" % modifier, varName, code="3.3")

                    if self.version >= vn1_7:
                        if modifier in ['status_flag', 'number_of_observations']:
                            self._add_warn("Use of standard_name modifier %s is deprecated" % modifier,
                                           varName, code="3.3")

                if name == "region":
                    # Check values are from the permitted list
                    region_names = self.getStringValue(varName)
                  
                    if len(region_names) == 1 and region_names[0] == None:
                        # Not a char variable so getStringValue couldn't be applied

                        # Does variable have flag_meanings attribute
                        if hasattr(var, 'flag_meanings'):
                            # Check values are from the region names permitted list
                            meanings = var.flag_meanings

                            if is_str_or_basestring(meanings):
                                region_names = meanings.split()
                                for region in region_names:
                                    if not region in list(self.region_name_lh.list):
                                        self._add_error("Invalid region name: {}".format(region), varName, code="3.3")

                            else:
                                self._add_error("Invalid syntax for 'flag_meanings' attribute.", varName, code="3.5")

                        else:
                            self._add_error("Variable {} of invalid type. Region variable should be of type char."
                                            .format(varName),
                                            varName,
                                            code="3.3")

                    elif len(region_names):
                        for region in region_names:

                            if not region.decode('utf-8') in list(self.region_name_lh.list):
                                self._add_error("Invalid region name: {}".format(region.decode('utf-8')),
                                                varName,
                                                code="3.3")
                    else:
                        self._add_error("No region names specified", varName, code="3.3")

                if self.version >= vn1_4 and name == "area_type":
                    # Check values from the permitted list
                    area_types = self.getStringValue(varName)

                    if len(area_types) == 1 and area_types[0] == None:
                        # Not a char variable
                        if hasattr(var, 'flag_meanings'):
                            # Check values are from the region names permitted list
                            meanings = var.flag_meanings

                            if is_str_or_basestring(meanings):
                                area_types = meanings.split()
                                for area in area_types:
                                    if not area in list(self.area_type_lh.list):
                                        self._add_error("Invalid area_type: {}".format(area), varName, code="3.3")
                            else:
                                self._add_error("Invalid syntax for 'flag_meanings' attribute.", varName, code="3.5")

                        else:
                            self._add_error("Variable {} of invalid type. Area Types variable should be of type char."
                                            .format(varName), varName, code="3.3")

                    elif len(area_types):
                        for area in area_types:
                            if not area.decode('utf-8') in list(self.area_type_lh.list):
                                self._add_error("Invalid area_type: {}".format(area.decode('utf-8')),
                                                varName, code="3.3")

                    else:
                        self._add_error("No area types specified", varName, code="3.3")

                if hasattr(var, 'positive'):
                    # Check that positive attribute is consistent with sign implied by standard_name
                    if (re.match("height", name, re.I) and not re.match("up", var.positive, re.I)) or \
                            (re.match("depth", name, re.I) and not re.match("down", var.positive, re.I)):
                        self._add_warn("Positive attribute inconsistent with sign conventions implied by "
                                       "the standard_name", varName, code="4.3")

    def getStringValue(self, varName):
        """
        Collapse (by concatenation) the outermost (fastest varying) dimension of string valued array into
        memory. E.g. [['a','b','c']] becomes ['abc']
        """
        array = self.f.variables[varName][:]
        ndim = array.ndim

        if array.dtype.kind in ('S', 'U'):
            if array.dtype.kind == 'U':
                array = array.astype('S')
            
            array = netCDF4.chartostring(array)
            shape = array.shape
            array = numpy.array([x.rstrip() for x in array.flat], dtype='S') #array.dtype)
            array = numpy.reshape(array, shape)
            array = numpy.ma.masked_where(array == b'', array)

            # If varName is one dimension convert result of join from a string into an array
            if ndim == 1:
                array = [array]
        else:
            # Variable not of char type
            return [None]

        return array

    def chkCompressAttr(self, varName):
        """Check Compress Attribute"""
        var = self.f.variables[varName]
        if hasattr(var, 'compress'):
            compress = var.compress

            if var.dtype.char != 'i':
                self._add_error("compress attribute can only be attached to variable of type int.", varName, code="8.2")
                return
            if not re.search("^[a-zA-Z0-9_ ]*$",compress):
                self._add_error("Invalid syntax for 'compress' attribute", varName, code="8.2")
            else:
                dimensions = compress.split()
                dimProduct = 1
                for x in dimensions:
                    found = 'false'
                    if x in self.f.dimensions:
                        # Get product of compressed dimension sizes for use later
                        dimProduct = dimProduct*len(self.f.dimensions[x])
                        found = 'true'

                    if found != 'true':
                        self._add_error("compress attribute naming non-existent dimension: %s" % x,
                                        varName, code="8.2")

                # Check all non-masked values are within the range 0 to product of compressed dimensions
                if var[:].count() != 0:
                    if var[:].compressed().min() < 0 or var[:].compressed().max() > dimProduct-1:
                        self._add_error("values of %s must be in the range 0 to %s" % (varName, dimProduct - 1),
                                        varName, code="8.2")

    def chkPackedData(self, varName):
        var = self.f.variables[varName]
        if hasattr(var, 'scale_factor') and hasattr(var, 'add_offset'):
            if var.scale_factor.dtype.char != var.add_offset.dtype.char:
                self._add_error("scale_factor and add_offset must be the same numeric data type", varName, code="8.1")
                # No point running rest of packed data tests
                return

        if hasattr(var, 'scale_factor'):
            type = var.scale_factor.dtype.char
        elif hasattr(var, 'add_offset'):
            type = var.add_offset.dtype.char
        else:
            # No packed Data attributes present
            return

        varType = var.dtype.char
   
        # One or other attributes present; run remaining checks
        if varType != type:
            if type != 'f' and type != 'd':
                self._add_error("scale_factor and add_offset must be of type float or double", varName, code="8.1")

            if varType != 'b' and  varType != 'h' and varType != 'i':
                self._add_error("must be of type byte, short or int", varName, code="8.1")

            if type == 'f' and varType == 'i':
                self._add_warn("scale_factor/add_offset are type float, therefore variable should not be of type int",
                               varName, code="8.1")

    def chkFlags(self, varName):
        var = self.f.variables[varName]

        if hasattr(var, 'flag_meanings'):
            # Flag to indicate whether one of flag_values or flag_masks present
            values_or_masks = 0
            meanings = var.flag_meanings

            if not self.extendedBlankSeparatedList(meanings):
                self._add_error("Invalid syntax for 'flag_meanings' attribute", varName, code="3.5")
          
            if hasattr(var, 'flag_values'):
                values_or_masks = 1
                values = var.flag_values
              
                retcode = self.equalNumOfValues(values,meanings)
                if retcode == -1:
                    self._add_error("Problem in subroutine equalNumOfValues", varName, code="3.5")
                elif not retcode:
                    self._add_error("Number of flag_values values must equal the number or words/phrases "
                                    "in flag_meanings", varName, code="3.5")
                  
                # flag_values values must be mutually exclusive
                if is_str_or_basestring(values):
                    values = values.split()

                try:
                    iterator = iter(values)
                except TypeError:
                    iterator = [values]

                if not self.uniqueList(iterator):
                    self._add_error("flag_values attribute must contain a list of unique values", varName, code="3.5")
                  
            if hasattr(var, 'flag_masks'):
                values_or_masks = 1
                masks = var.flag_masks

                retcode = self.equalNumOfValues(masks,meanings)
                if retcode == -1:
                    self._add_error("Problem in subroutine equalNumOfValues", varName, code="3.5")
                elif not retcode:
                    self._add_error("Number of flag_masks values must equal the number or words/phrases "
                                    "in flag_meanings", varName, code="3.5")
                  
                # flag_masks values must be non-zero
                try:
                    iterator = iter(masks)
                except TypeError:
                    iterator = [masks]

                for v in iterator:
                    if v == 0:
                        self._add_error("flag_masks values must be non-zero", varName, code="3.5")
                      
            # Doesn't make sense to do bitwise comparison for char variable
            if var.dtype.char != 'c':
                if hasattr(var, 'flag_values') and hasattr(var, 'flag_masks'):
                    # Both flag_values and flag_masks present
                    # Do a bitwise AND of each flag_value and its corresponding flag_mask value,
                    # the result must be equal to the flag_values entry
                    i=0
                    for v in values:
                        bitwise_AND = v & masks[i]

                        if bitwise_AND != v:
                            self._add_warn("Bitwise AND of flag_value {} and corresponding flag_mask {} "
                                           "doesn't match flag_value.".format(v, masks[i]),
                                           varName,
                                           code="3.5")
                        i = i+1
                 
            if values_or_masks == 0:
                # flag_meanings attribute present, but no flag_values or flag_masks
                self._add_error("flag_meanings present, but no flag_values or flag_masks specified",
                                varName,
                                code="3.5")

            if hasattr(var, 'flag_values') and not hasattr(var, 'flag_meanings'):
                self._add_error("flag_meanings attribute is missing", varName, code="3.5")

    def equalNumOfValues(self, arg1, arg2):
        """ Check that arg1 and arg2 contain the same number elements."""

        # Determine if args are strings. Strings need to be split up into elements.
        if isinstance(arg1, basestring):
            arg1 = arg1.split()

        if isinstance(arg2, basestring):
            arg2 = arg2.split()

        if numpy.size(arg1) != numpy.size(arg2):
            return 0

        return 1

    def chkMultiDimCoord(self, varName, axes):
        """If a coordinate variable is multi-dimensional, then it is recommended
        that the variable name should not match the name of any of its dimensions."""
        var = self.f.variables[varName]
    
        if varName in axes and len(var.dimensions) > 1:
            # Multi-dimensional coordinate var
            if varName in var.dimensions:
                self._add_warn("The name of a multi-dimensional coordinate variable should not match "
                               "the name of any of its dimensions.",
                               varName,
                               code="5")

    def chkValuesMonotonic(self, varName):
        """A coordinate variable must have values that are strictly monotonic
        (increasing or decreasing)."""
        values = self.f.variables[varName][:]

        if not self.isStrictlyMonotonic(values):
            self._add_error("co-ordinate variable not monotonic", varName, code="5")

    def isStrictlyMonotonic(self, values):
        """Is array strictly monotonic increasing or decreasing"""

        if numpy.all(numpy.diff(values) > 0):
            # monotonic increasing
            return 1
        elif numpy.all(numpy.diff(values) < 0):
            # monotonic decreasing
            return 2
        else:
            # not monotonic
            return 0


def getargs(arglist):
    """getargs(arglist): parse command line options and environment variables"""

    from getopt import getopt, GetoptError
    from os import environ
    from sys import stderr, exit

    standardnamekey = 'CF_STANDARD_NAMES'
    areatypeskey = 'CF_AREA_TYPES'
    regionnameskey = 'CF_REGION_NAMES'

    # set defaults
    standardname = STANDARDNAME
    areatypes = AREATYPES
    regionnames = REGIONNAMES
    uploader = None
    useFileName = "yes"
    badc = None
    coards = None
    version = newest_version
    debug = False

    # cacheTables : introduced to enable caching of CF standard name, area type and region name tables.
    cacheTables = False

    # default cache longevity is 1 day
    cacheTime = 24*3600

    # default directory to store cached tables
    cacheDir = '/tmp'
    
    # set to environment variables
    if standardnamekey in environ:
        standardname = environ[standardnamekey]
    if areatypeskey in environ:
        areatypes = environ[areatypeskey]
    if regionnameskey in environ:
        regionnames = environ[regionnameskey]

    try:
        (opts, args) = getopt(arglist[1:], 'a:bcdhlnr:s:t:v:x',
                           ['area_types=', 'badc', 'coards', 'debug', 'help', 'uploader',
                            'noname', 'region_names=', 'cf_standard_names=',
                            'cache_time_days=', 'version=', 'cache_tables', 'cache_dir='])
    except GetoptError:
        stderr.write('%s\n' % __doc__)
        exit(1)
    
    for a, v in opts:
        if a in ('-a', '--area_types'):
            areatypes = v.strip()
            continue
        if a in ('-b', '--badc'):
            badc = "yes"
            continue
        if a in ('-c', '--coards'):
            coards = "yes"
            continue
        if a in ('--cache_dir'):
            cacheDir = v.strip()
        if a in ('-d', '--debug'):
            debug = True
            continue
        if a in ('-h', '--help'):
            print(__doc__)
            exit(0)
        if a in ('-l', '--uploader'):
            uploader = "yes"
            continue
        if a in ('-n', '--noname'):
            useFileName = "no"
            continue
        if a in ('-r', '--region_names'):
            regionnames = v.strip()
            continue
        if a in ('-s', '--cf_standard_names'):
            standardname = v.strip()
            continue
        if a in ('-t', '--cache_time_days'):
            cacheTime = float(v)*24*3600
            continue
        if a in ('-v', '--version'):
            if v == 'auto':
                version = CFVersion()
            else:
                try:
                    version = CFVersion(v)
                except ValueError:
                    print("WARNING: '%s' cannot be parsed as a version number." % v)
                    print("Performing check against newest version: %s" % newest_version)
                if version not in cfVersions:
                    print("WARNING: %s is not a valid CF version." % version)
                    print("Performing check against newest version: %s" % newest_version)
                    version = newest_version
            continue
        if a in ('-x', '--cache_tables'):
            cacheTables = True
            continue
            
    if len(args) == 0:
        stderr.write('ERROR in command line\n\nusage:\n%s\n' % __doc__)
        exit(1)

    return badc, coards, debug, uploader, useFileName, regionnames, standardname, areatypes, cacheDir, cacheTables, \
           cacheTime, version, args


def main():

    (badc, coards, debug, uploader, useFileName, regionnames, standardName, areaTypes, cacheDir, cacheTables, cacheTime,
     version, files) = getargs(sys.argv)
    
    inst = CFChecker(uploader=uploader,
                     useFileName=useFileName,
                     badc=badc,
                     coards=coards,
                     cfRegionNamesXML=regionnames,
                     cfStandardNamesXML=standardName,
                     cfAreaTypesXML=areaTypes,
                     cacheDir=cacheDir,
                     cacheTables=cacheTables,
                     cacheTime=cacheTime,
                     version=version,
                     debug=debug)
    for file in files:
        try:
            inst.checker(file)
        except FatalCheckerError:
            print("Checking of file %s aborted due to error" % file)

    totals = inst.get_total_counts()

    if debug:
        print("")
        print("Results dictionary: %s" % inst.all_results)
        print("")
        print("Messages that were printed: %s" % inst.all_messages)

    errs = totals["FATAL"] + totals["ERROR"]
    if errs:
        sys.exit(errs)
    
    warns = totals["WARN"]
    if warns:
        sys.exit(-warns)

    sys.exit(0)


# --------------------------
# Main Program
# --------------------------
if __name__ == '__main__':

    main()
