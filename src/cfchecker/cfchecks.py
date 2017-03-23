#!/usr/bin/env python
#-------------------------------------------------------------
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
#-------------------------------------------------------------
''' cfchecker [-a|--area_types area_types.xml] [-s|--cf_standard_names standard_names.xml] [-v|--version CFVersion] file1 [file2...]

Description:
 The cfchecker checks NetCDF files for compliance to the CF standard.
 
Options:
 -a or --area_types:
       the location of the CF area types table (xml)
       
 -s or --cf_standard_names:
       the location of the CF standard name table (xml)

 -h or --help: Prints this help text.

 -v or --version: CF version to check against, use auto to auto-detect the file version.

'''

import sys

if sys.version_info[:2] < (2,7):
    from ordereddict import OrderedDict
else:
    from collections import OrderedDict

import re, string, types, numpy

from netCDF4 import Dataset as netCDF4_Dataset
from netCDF4 import Variable as netCDF4_Variable
from cfunits import Units

# Version is imported from the package module cfchecker/__init__.py
from cfchecker import __version__

STANDARDNAME = 'http://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml'
AREATYPES = 'http://cfconventions.org/Data/area-type-table/current/src/area-type-table.xml'

#-----------------------------------------------------------
from xml.sax import ContentHandler
from xml.sax import make_parser
from xml.sax.handler import feature_namespaces


def normalize_whitespace(text):
    "Remove redundant whitespace from a string."
    return ' '.join(text.split())


class CFVersion(object):
    """A CF version number, stored as a tuple, that can be instantiated with 
    a tuple or a string, written out as a string, and compared with another version"""

    def __init__(self, value=()):
        "Instantiate CFVersion with a string or with a tuple of ints"
        if isinstance(value, str):
            if value.startswith("CF-"):
                value = value[3:]
            self.tuple = map(int, value.split("."))
        else:
            self.tuple = value

    def __nonzero__(self):
        if self.tuple:
            return True
        else:
            return False

    def __str__(self):
        return "CF-%s" % string.join(map(str, self.tuple), ".")

    def __cmp__(self, other):
        # maybe overkill but allow for different lengths in future e.g. 3.2 and 3.2.1
        pos = 0
        while True:
            in_s = (pos < len(self.tuple))
            in_o = (pos < len(other.tuple))
            if in_s:
                if in_o:
                    c = cmp(self.tuple[pos], other.tuple[pos])
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

vn1_0 = CFVersion((1, 0))
vn1_1 = CFVersion((1, 1))
vn1_2 = CFVersion((1, 2))
vn1_3 = CFVersion((1, 3))
vn1_4 = CFVersion((1, 4))
vn1_5 = CFVersion((1, 5))
vn1_6 = CFVersion((1, 6))
cfVersions = [vn1_0, vn1_1, vn1_2, vn1_3, vn1_4, vn1_5, vn1_6]
newest_version = max(cfVersions)


class ConstructDict(ContentHandler):
    """Parse the xml standard_name table, reading all entries
       into a dictionary; storing standard_name and units.
    """
    def __init__(self):
        self.inUnitsContent = 0
        self.inEntryIdContent = 0
        self.inVersionNoContent = 0
        self.inLastModifiedContent = 0
        self.dict = {}
        
    def startElement(self, name, attrs):
        # If it's an entry element, save the id
        if name == 'entry':
            id = normalize_whitespace(attrs.get('id', ""))
            self.this_id = id

        # If it's the start of a canonical_units element
        elif name == 'canonical_units':
            self.inUnitsContent = 1
            self.units = ""

        elif name == 'alias':
            id = normalize_whitespace(attrs.get('id', ""))
            self.this_id = id

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
            self.entry_id = normalize_whitespace(self.entry_id)
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
    def __init__(self):
        self.inVersionNoContent = 0
        self.inLastModifiedContent = 0
        self.list = []
        
    def startElement(self, name, attrs):
        # If it's an entry element, save the id
        if name == 'entry':
            id = normalize_whitespace(attrs.get('id', ""))
            self.list.append(id)

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

            
def chkDerivedName(name):
    """Checks whether name is a derived standard name and adheres
       to the transformation rules. See CF standard names document
       for more information.
    """
    if re.search("^(direction|magnitude|square|divergence)_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^rate_of_change_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^(grid_)?(northward|southward|eastward|westward)_derivative_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^product_of_[a-zA-Z][a-zA-Z0-9_]*_and_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^ratio_of_[a-zA-Z][a-zA-Z0-9_]*_to_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^derivative_of_[a-zA-Z][a-zA-Z0-9_]*_wrt_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^(correlation|covariance)_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*_and_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^histogram_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^probability_distribution_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0

    if re.search("^probability_density_function_over_[a-zA-Z][a-zA-Z0-9_]*_of_[a-zA-Z][a-zA-Z0-9_]*$",name):
        return 0
    
    # Not a valid derived name
    return 1


class FatalCheckerError(Exception):
    pass

#======================
# Checking class
#======================
class CFChecker:
    
  def __init__(self, uploader=None, useFileName="yes", badc=None, coards=None, cfStandardNamesXML=STANDARDNAME, cfAreaTypesXML=AREATYPES, version=newest_version, debug=False, silent=False):
      self.uploader = uploader
      self.useFileName = useFileName
      self.badc = badc
      self.coards = coards
      self.standardNames = cfStandardNamesXML
      self.areaTypes = cfAreaTypesXML
      self.version = version
      self.all_results = OrderedDict()  # dictonary of results sorted by file and then by globals / variable 
                                        # and then by category
      self.all_messages = []  # list of all messages in the order they were printed
      self.cf_roleCount = 0          # Number of occurences of the cf_role attribute in the file
      self.raggedArrayFlag = 0       # Flag to indicate if file contains any ragged array representations
      self.debug = debug
      self.silent = silent

      self.categories = ("FATAL", "ERROR", "WARN", "INFO", "VERSION")
      if debug:
          self.categories += ("DEBUG",)


  def checker(self, file):

    self._init_results(file)
    fileSuffix = re.compile('^\S+\.nc$')

    if self.uploader:
        realfile = string.split(file,".nc")[0]+".nc"
        self._add_version("CHECKING NetCDF FILE: %s" % realfile)
    elif self.useFileName=="no":
        self._add_version("CHECKING NetCDF FILE")
    else:
        self._add_version("CHECKING NetCDF FILE: %s" % file)
    
    if not self.silent:
        print "====================="

    # Check for valid filename
    if not fileSuffix.match(file):
        self._fatal("Filename must have .nc suffix", code="2.1")

    # Read in netCDF file
    try:
        self.f=netCDF4_Dataset(file,"r")
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

    # Set up dictionary of standard_names and their assoc. units
    parser = make_parser()
    parser.setFeature(feature_namespaces, 0)
    self.std_name_dh = ConstructDict()
    parser.setContentHandler(self.std_name_dh)
    parser.parse(self.standardNames)

    if self.version >= vn1_4:
        # Set up list of valid area_types
        self.area_type_lh = ConstructList()
        parser.setContentHandler(self.area_type_lh)
        parser.parse(self.areaTypes)
    
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
    
    if not self.silent:
        print ""

    try:
        return self._checker()
    finally:
        self.f.close()

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
        "as _add_error but for warnings"
        self._add_message("WARN", *args, **kwargs)

  def _add_info(self, *args, **kwargs):
        "as _add_error but for informational messages"
        self._add_message("INFO", *args, **kwargs)

  def _add_version(self, *args, **kwargs):
        "as _add_error but for informational messages"
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
                print self._join_strings([code_report, msg])
            else:
                print self._join_strings([category, code_report, msg])

        self.all_messages.append(msg_print)

  def _join_strings(self, list_):
      """
      filter out None from lists and join the rest
      """
      return string.join(filter(lambda x: x is not None, list_), ": ")

  def get_total_counts(self):
        """
        Get counts totalled over all files checked.
        """
        grand_totals = self._get_zero_counts()
        for results in self.all_results.values():
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
        for res in results["variables"].values():
            self._update_counts(counts, res)
        return counts

  def _update_counts(self, counts, results):
        "helper for _get_counts()"
        for category in self.categories:
            counts[category] += len(results[category])

  def show_counts(self, results=None, append_to_all_messages=False):
        descriptions = {"FATAL": "FATAL ERRORS",
                        "ERROR": "ERRORS detected",
                        "WARN": "WARNINGS given",
                        "INFO": "INFORMATION messages",
                        "DEBUG": "DEBUG messages",
                        "VERSION": "VERSION information"}
        for category, count in self.get_counts(results).iteritems():
            # A FATAL error is really the inability of the checker to perform the checks.
            # Only show this if it actually occurred.
            if category == "FATAL" and count == 0:
                continue
            if category == "VERSION":
                continue
            line = "%s: %s" % (descriptions[category], count)
            if not self.silent:
                print line
            if append_to_all_messages:
                self.all_messages.append(line)
  
  def _checker(self):
    """
    Main implementation of checker assuming self.f exists.
    """
    lowerVars=[]
    for var in map(str, self.f.variables.keys()):
        self._init_var_results(var)

    # Check global attributes
    self.chkGlobalAttributes()
        
    (coordVars,auxCoordVars,boundsVars,climatologyVars,gridMappingVars)=self.getCoordinateDataVars()
    self.coordVars = coordVars
    self.auxCoordVars = auxCoordVars
    self.boundsVars = boundsVars
    self.climatologyVars = climatologyVars
    self.gridMappingVars = gridMappingVars

    self._add_debug("Auxillary Coordinate Vars: %s" % map(str,auxCoordVars))
    self._add_debug("Coordinate Vars: %s" % map(str,coordVars))
    self._add_debug("Boundary Vars: %s" % map(str,boundsVars))
    self._add_debug("Climatology Vars: %s" % map(str,climatologyVars))
    self._add_debug("Grid Mapping Vars: %s" % map(str,gridMappingVars))

    allCoordVars=coordVars[:]
    allCoordVars[len(allCoordVars):]=auxCoordVars[:]

    self.setUpFormulas()
    
    axes=self.f.dimensions.keys()

    self._add_debug("Axes: %s" % axes)

    # Check each variable
    for var in self.f.variables.keys():

        if not self.silent:
            print ""
            print "------------------"
            print "Checking variable:",var
            print "------------------"


        if not self.validName(var):
            self._add_error("Invalid variable name", var, code='2.3')

        # Check to see if a variable with this name already exists (case-insensitive)
        lowerVar=var.lower()
        if lowerVar in lowerVars:
            self._add_warn("variable clash", var, code='2.3')
        else:
            lowerVars.append(lowerVar)

        if var not in axes:
            # Non-coordinate variable
            self.chkDimensions(var,allCoordVars)
            
        self.chkDescription(var)

        for attribute in map(str, self.f.variables[var].ncattrs()):
            self.chkAttribute(attribute,var,allCoordVars)

        self.chkUnits(var,allCoordVars)
        self.chkValidMinMaxRange(var)
        self.chk_FillValue(var)
        self.chkAxisAttribute(var)
        self.chkPositiveAttribute(var)
        self.chkCellMethods(var)
        self.chkCellMeasures(var)
        self.chkFormulaTerms(var,allCoordVars)
        self.chkCompressAttr(var)
        self.chkPackedData(var)

        if self.version >= vn1_3:
            # Additional conformance checks from CF-1.3 onwards
            self.chkFlags(var)

        if self.version >= vn1_6:
            # Additional conformance checks from CF-1.6 onwards
            self.chkCFRole(var)
            self.chkRaggedArray(var)

        if var in coordVars:
            self.chkMultiDimCoord(var, axes)
            self.chkValuesMonotonic(var)

        if var in gridMappingVars:
            self.chkGridMappingVar(var)

        if var in axes:

            if self.isTime(var):
                self._add_debug("Time Axis.....")
                self.chkTimeVariableAttributes(var)

            # Github Issue #13
            if var not in allCoordVars:
                dimensions=map(str,self.f.variables[var].dimensions)

                if len(dimensions) > 1 and var in dimensions:
                    # Variable name matches a dimension; this may be an unidentified multi-dimensional coordinate variable
                    self._add_warn('Possible incorrect declaration of a coordinate variable.', var, code='5')


    #self._add_info("%s variable(s) have the cf_role attribute set" % self.cf_roleCount)
    if self.version >= vn1_6:
   
        if self.raggedArrayFlag != 0 and not hasattr(self.f, 'featureType'):
            self._add_error("The global attribute 'featureType' must be present (A ragged array representation has been used)",
                            code="9.4")

        if hasattr(self.f, 'featureType'):
            featureType = self.f.featureType

            if self.cf_roleCount == 0 and featureType != "point":
                self._add_warn("A variable with the attribute cf_role should be included in a Discrete Geometry CF File",
                               code="9.5")
                    
            if re.match('^(timeSeries|trajectory|profile)$',featureType,re.I) and self.cf_roleCount != 1:
                # Should only be a single occurence of a cf_role attribute
                self._add_warn("CF Files containing %s featureType should only include a single occurrence of a cf_role attribute" % featureType)
            elif re.match('^(timeSeriesProfile|trajectoryProfile)$',featureType,re.I) and self.cf_roleCount > 2:
                # May contain up to 2 occurences of cf_roles attribute
                self._add_error("CF Files containing %s featureType may contain 2 occurrences of a cf_role attribute" % featureType)

    if not self.silent:
        print
    self.show_counts(append_to_all_messages=True)
    return self.results


  #-----------------------------
  def setUpAttributeList(self):
  #-----------------------------
      """Set up Dictionary of valid attributes, their corresponding
      Type; S(tring), N(umeric) D(ata variable type)  and Use C(oordinate),
      D(ata non-coordinate) or G(lobal) variable."""
    
      self.AttrList={}
      self.AttrList['add_offset']=['N','D']
      self.AttrList['ancillary_variables']=['S','D']
      self.AttrList['axis']=['S','C']
      self.AttrList['bounds']=['S','C']
      self.AttrList['calendar']=['S','C']
      self.AttrList['cell_measures']=['S','D']
      self.AttrList['cell_methods']=['S','D']
      self.AttrList['climatology']=['S','C']
      self.AttrList['comment']=['S',('G','D')]
      self.AttrList['compress']=['S','C']
      self.AttrList['Conventions']=['S','G']
      self.AttrList['coordinates']=['S','D']
      self.AttrList['_FillValue']=['D','D']
      self.AttrList['flag_meanings']=['S','D']
      self.AttrList['flag_values']=['D','D']
      self.AttrList['formula_terms']=['S','C']
      self.AttrList['grid_mapping']=['S','D']
      self.AttrList['history']=['S','G']
      self.AttrList['institution']=['S',('G','D')]
      self.AttrList['leap_month']=['N','C']
      self.AttrList['leap_year']=['N','C']
      self.AttrList['long_name']=['S',('C','D')]
      self.AttrList['missing_value']=['D','D']
      self.AttrList['month_lengths']=['N','C']
      self.AttrList['positive']=['S','C']
      self.AttrList['references']=['S',('G','D')]
      self.AttrList['scale_factor']=['N','D']
      self.AttrList['source']=['S',('G','D')]
      self.AttrList['standard_error_multiplier']=['N','D']
      self.AttrList['standard_name']=['S',('C','D')]
      self.AttrList['title']=['S','G']
      self.AttrList['units']=['S',('C','D')]
      self.AttrList['valid_max']=['N',('C','D')]
      self.AttrList['valid_min']=['N',('C','D')]
      self.AttrList['valid_range']=['N',('C','D')]

      if self.version >= vn1_3:
          self.AttrList['flag_masks']=['D','D']

      if self.version >= vn1_6:
          self.AttrList['cf_role']=['S','C']
          self.AttrList['featureType']=['S','G']
          self.AttrList['instance_dimension']=['S','D']
          self.AttrList['sample_dimension']=['S','D']
      
      return


  #---------------------------
  def uniqueList(self, list):
  #---------------------------
      """Determine if list has any repeated elements."""
      # Rewrite to allow list to be either a list or a Numeric array
      seen=[]

      for x in list:
          if x in seen:
              return 0
          else:
              seen.append(x)        
      return 1


  #-------------------------
  def isNumeric(self, var):
  #-------------------------
      """Determine if variable is of Numeric data type."""
      types=['i','f','d']
      rc=1 
      if self.getTypeCode(self.f.variables[var]) not in types:
          rc=0
      return rc

  #----------------------
  def isTime(self, var):
  #----------------------
      """Is variable a time axis."""

      variable = self.f.variables[var]

      if hasattr(variable, 'units'):
          if self.getInterpretation(variable.units) == 'T':
              return 1
      
      if hasattr(variable, 'axis'):
          if variable.axis == 'T':
              return 1

      if hasattr(variable, 'standard_name'):
          if variable.standard_name == 'time' or variable.standard_name == 'forecast_reference_time':
              return 1

      return 0






  #-------------------------
  def getStdName(self, var):
  #-------------------------
      """Get standard_name of variable.  Return it as 2 parts - the standard name and the modifier, if present."""
      attName = 'standard_name'
      attDict = var.__dict__

      if attName not in attDict.keys():
          return None

      bits = string.split(attDict[attName])
      
      if len(bits) == 1:
          # Only standard_name part present
          return (bits[0],"")
      elif len(bits) == 0:
          # Standard Name is blank
          return ("","")
      else:
          # At least 2 elements so return the first 2.  
          # If there are more than 2, which is invalid syntax, this will have been picked up by chkDescription()
          return (bits[0],bits[1])
    
  #--------------------------------------------------
  def getInterpretation(self, units, positive=None):
  #--------------------------------------------------
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
    if units in ['level','layer','sigma_level']:
        return "Z"
    
    if positive and re.match('(up|down)',positive,re.I):
        return "Z"

    
    if u.istime or u.isreftime:
        return "T"

    # Not possible to deduce interpretation
    return None


  #--------------------------------
  def getCoordinateDataVars(self):
  #--------------------------------
    """Obtain list of coordinate data variables, boundary
    variables, climatology variables and grid_mapping variables."""
    
    allVariables = map(str, self.f.variables)   # List of all vars, including coord vars
    axes = map(str, self.f.dimensions)
    
    coordVars = []
    variables = []
    boundaryVars = []
    climatologyVars = []
    gridMappingVars = []
    auxCoordVars = []

    # Split each variable in allVariables into either coordVars or variables (data vars)
    for varname, var in self.f.variables.items():
        if len(var.shape) == 1 and len(var.dimensions) == 1 and var.dimensions[0] == varname: # 1D and dimension is same name as variable
            coordVars.append(varname)
        else:
            variables.append(varname)

    for var in allVariables:

        #------------------------
        # Auxilliary Coord Checks
        #------------------------
        if hasattr(self.f.variables[var], 'coordinates'):
            # Check syntax of 'coordinates' attribute
            if not self.parseBlankSeparatedList(self.f.variables[var].coordinates):
                self._add_error("Invalid syntax for 'coordinates' attribute", var, code="5.3")
            else:
                coordinates=string.split(self.f.variables[var].coordinates)
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
                                self._add_debug("Not a label variable. Dimensions are: %s" % map(str, self.f.variables[dataVar].dimensions),
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
                                        code = "5")

        #-------------------------
        # Boundary Variable Checks
        #-------------------------
        if hasattr(self.f.variables[var], 'bounds'):
            bounds=self.f.variables[var].bounds
            # Check syntax of 'bounds' attribute
            if not re.search("^[a-zA-Z0-9_]*$",bounds):
                self._add_error("Invalid syntax for 'bounds' attribute", var,
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
                                self._add_error("Incorrect dimensions for boundary variable: %s" % bounds, bounds, code="7.1")
                    else:
                        self._add_error("Incorrect number of dimensions for boundary variable: %s" % bounds, bounds, code="7.1")

                    if hasattr(self.f.variables[bounds], 'units'):
                        if self.f.variables[bounds].units != self.f.variables[var].units:
                            self._add_error("Boundary var %s has inconsistent units to %s" % (bounds, var),
                                            bounds, code="7.1")
                    if hasattr(self.f.variables[bounds], 'standard_name') and hasattr(self.f.variables[var], 'standard_name'):
                        if self.f.variables[bounds].standard_name != self.f.variables[var].standard_name:
                            self._add_error("Boundary var %s has inconsistent std_name to %s" % (bounds, var),
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
                    varData=self.f.variables[var][:]
                    boundsData=self.f.variables[bounds][:]

# RSH TODO - Remove this as all tests pass                    
#                    print "RSH: boundsData -",boundsData
#
#                    try:
#                        length = len(varData)
#                        print "RSH: length:",length
#                    except TypeError:
#                        length = 1  # scalar (no len); treat as length 1
#                        print "RSH: length 1"
#
#                    if length == 0:
#                        self._add_warn("Problem with variable - Skipping check that data lies within cell boundaries.", var)
#                  
#                    elif length == 1:
#                        # Variable contains only one value
#                        # Bounds array will be 1-dimensional
#                        if not (boundsData[0] <= varData <= boundsData[1]):
#                            self._add_warn("Data for variable %s lies outside cell boundaries" % var,
#                                           var, code="7.1")
#                    else:
                    for i, value in enumerate(varData):
                        try:
                            if not (boundsData[i][0] <= value <= boundsData[i][1]):
                                self._add_warn("Data for variable %s lies outside cell boundaries" % var,
                                               var, code="7.1")
                                break
                        except IndexError as e:
                            self._add_warn("Failed to check data lies within/on bounds for variable %s. Problem with bounds data: %s" % (var, bounds),
                                           var, code="7.1")
                            #self._add_info("%s" % e, bounds)
                            break


        #----------------------------
        # Climatology Variable Checks
        #----------------------------
        if hasattr(self.f.variables[var],'climatology'):
            climatology=self.f.variables[var].climatology
            # Check syntax of 'climatology' attribute
            if not re.search("^[a-zA-Z0-9_]*$",climatology):
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

        #------------------------------------------
        # Is there a grid_mapping variable?
        #------------------------------------------
        if hasattr(self.f.variables[var], 'grid_mapping'):
            grid_mapping = self.f.variables[var].grid_mapping
            # Check syntax of grid_mapping attribute: a string whose value is a single variable name.
            if not re.search("^[a-zA-Z0-9_]*$",grid_mapping):
                self._add_error("%s - Invalid syntax for 'grid_mapping' attribute" % var, var, code="5.6")
            else:
                if grid_mapping in variables:
                    gridMappingVars.append(grid_mapping)
                else:
                    self._add_error("grid_mapping attribute referencing non-existent variable %s" % grid_mapping,
                                    var)
                    
    return (coordVars, auxCoordVars, boundaryVars, climatologyVars, gridMappingVars)


  #-------------------------------------
  def chkGridMappingVar(self, varName):
  #-------------------------------------
      """Section 5.6: Grid Mapping Variable Checks"""
      var=self.f.variables[varName]
      
      if hasattr(var, 'grid_mapping_name'):
          # Check grid_mapping_name is valid
          validNames = ['albers_conical_equal_area','azimuthal_equidistant','lambert_azimuthal_equal_area',
                        'lambert_conformal_conic','polar_stereographic','rotated_latitude_longitude',
                        'stereographic','transverse_mercator']
          
          if self.version >= vn1_2:
              # Extra grid_mapping_names at vn1.2
              validNames[len(validNames):] = ['latitude_longitude','vertical_perspective']

          if self.version >= vn1_4:
              # Extra grid_mapping_names at vn1.4
              validNames[len(validNames):] = ['lambert_cylindrical_equal_area','mercator','orthographic']
              
          if var.grid_mapping_name not in validNames:
              self._add_error("Invalid grid_mapping_name: %s" % var.grid_mapping_name,
                              varName, code="5.6")
      else:
          self._add_error("No grid_mapping_name attribute set: %s" % var.grid_mapping_name,
                          varName, code="5.6")
              
      if len(var.dimensions) != 0:
          self._add_warn("A grid mapping variable should have 0 dimensions",
                         varName, code="5.6")

  #------------------------
  def setUpFormulas(self):
  #------------------------
      """Set up dictionary of all valid formulas"""
      self.formulas={}
      self.alias={}
      self.alias['atmosphere_ln_pressure_coordinate']='atmosphere_ln_pressure_coordinate'
      self.alias['atmosphere_sigma_coordinate']='sigma'
      self.alias['sigma']='sigma'
      self.alias['atmosphere_hybrid_sigma_pressure_coordinate']='hybrid_sigma_pressure'
      self.alias['hybrid_sigma_pressure']='hybrid_sigma_pressure'
      self.alias['atmosphere_hybrid_height_coordinate']='atmosphere_hybrid_height_coordinate'
      self.alias['ocean_sigma_coordinate']='ocean_sigma_coordinate'
      self.alias['ocean_s_coordinate']='ocean_s_coordinate'
      self.alias['ocean_sigma_z_coordinate']='ocean_sigma_z_coordinate'
      self.alias['ocean_double_sigma_coordinate']='ocean_double_sigma_coordinate'
      

      self.formulas['atmosphere_ln_pressure_coordinate']=['p(k)=p0*exp(-lev(k))']
      self.formulas['sigma']=['p(n,k,j,i)=ptop+sigma(k)*(ps(n,j,i)-ptop)']

      self.formulas['hybrid_sigma_pressure']=['p(n,k,j,i)=a(k)*p0+b(k)*ps(n,j,i)'
                                              ,'p(n,k,j,i)=ap(k)+b(k)*ps(n,j,i)']

      self.formulas['atmosphere_hybrid_height_coordinate']=['z(n,k,j,i)=a(k)+b(k)*orog(n,j,i)']

      self.formulas['ocean_sigma_coordinate']=['z(n,k,j,i)=eta(n,j,i)+sigma(k)*(depth(j,i)+eta(n,j,i))']
      
      self.formulas['ocean_s_coordinate']=['z(n,k,j,i)=eta(n,j,i)*(1+s(k))+depth_c*s(k)+(depth(j,i)-depth_c)*C(k)'
                                           ,'C(k)=(1-b)*sinh(a*s(k))/sinh(a)+b*[tanh(a*(s(k)+0.5))/(2*tanh(0.5*a))-0.5]']

      self.formulas['ocean_sigma_z_coordinate']=['z(n,k,j,i)=eta(n,j,i)+sigma(k)*(min(depth_c,depth(j,i))+eta(n,j,i))'
                                                 ,'z(n,k,j,i)=zlev(k)']

      self.formulas['ocean_double_sigma_coordinate']=['z(k,j,i)=sigma(k)*f(j,i)'
                                                      ,'z(k,j,i)=f(j,i)+(sigma(k)-1)*(depth(j,i)-f(j,i))'
                                                      ,'f(j,i)=0.5*(z1+z2)+0.5*(z1-z2)*tanh(2*a/(z1-z2)*(depth(j,i)-href))']

      
  #----------------------------------------
  def parseBlankSeparatedList(self, list):
  #----------------------------------------
      """Parse blank separated list"""
      if re.match("^[a-zA-Z0-9_ ]*$",list):
          return 1
      else:
          return 0


  #-------------------------------------------
  def extendedBlankSeparatedList(self, list):
  #-------------------------------------------
      """Check list is a blank separated list of words containing alphanumeric characters
      plus underscore '_', period '.', plus '+', hyphen '-', or "at" sign '@'."""
      if re.match("^[a-zA-Z0-9_ @\-\+\.]*$",list):
          return 1
      else:
          return 0

  #-------------------------------------------
  def commaOrBlankSeparatedList(self, list):
  #-------------------------------------------
      """Check list is a blank or comma separated list of words containing alphanumeric 
      characters plus underscore '_', period '.', plus '+', hyphen '-', or "at" sign '@'."""
      if re.match("^[a-zA-Z0-9_ @\-\+\.,]*$",list):
          return 1
      else:
          return 0
         
  
  #------------------------------
  def chkGlobalAttributes(self):
  #------------------------------
    """Check validity of global attributes."""
    if hasattr(self.f, 'Conventions'):
        conventions = self.f.Conventions
        
        # Conventions attribute can be a blank separated (or comma separated) list of conforming conventions
        if not self.commaOrBlankSeparatedList(conventions):
            self._add_error("Conventions attribute must be a blank (or comma) separated list of convention names",
                            code="2.6.1")
        else:
            # Split string up into component parts
            # If a comma is present we assume a comma separated list as names cannot contain commas
            if re.match("^.*,.*$",conventions):
                conventionList = string.split(conventions,",")
            else:
                conventionList = string.split(conventions)
            
            found = 0
            for convention in conventionList:
                if convention.strip() in map(str, cfVersions):
                    found = 1
                    break
        
            if found != 1:
                self._add_error("This netCDF file does not appear to contain CF Convention data.",
                                code="2.6.1")
            else:
                if convention.strip() != str(self.version):
                    self._add_warn("Inconsistency - This netCDF file appears to contain %s data, but you've requested a validity check against %s" % (convention, self.version), code="2.6.1")

    else:
        self._add_warn("No 'Conventions' attribute present", code="2.6.1")

    # Discrete geometries
    if self.version >= vn1_6 and hasattr(self.f, 'featureType'):
        featureType = self.f.featureType

        if not re.match('^(point|timeSeries|trajectory|profile|timeSeriesProfile|trajectoryProfile)$',featureType,re.I):
            self._add_error("Global attribute 'featureType' contains invalid value",
                            code="9.4")

    for attribute in ['title','history','institution','source','reference','comment']:
        if hasattr(self.f, attribute):
            if not isinstance(self.f.getncattr(attribute), basestring):
                self._add_error("Global attribute %s must be of type 'String'" % attribute,
                                code="2.6.2")

  #------------------------------
  def getFileCFVersion(self):
  #------------------------------
    """Return CF version of file, used for auto version option. If Conventions is COARDS return CF-1.0, 
    else a valid version based on Conventions else an empty version (for auto version)"""
    rc = CFVersion()

    if "Conventions" in map(str, self.f.ncattrs()):
        value = self.f.getncattr('Conventions')
        if isinstance(value, basestring):
            try:
                conventions = str(value)
            except UnicodeEncodeError:
                conventions = value.encode(errors='ignore') 
        else:
            conventions = value
        
        # Split string up into component parts
        # If a comma is present we assume a comma separated list as names cannot contain commas
        if re.match("^.*,.*$",conventions):
            conventionList = string.split(conventions,",")
        else:
            conventionList = string.split(conventions)

        found = 0
        coards = 0
        for convention in conventionList:
            if convention.strip() in map(str, cfVersions):
                found = 1
                rc = CFVersion(convention.strip())
                break
            elif convention.strip() == 'COARDS':
                coards = 1

        if not found and coards:
            self._add_warn("The conventions attribute specifies COARDS, assuming CF-1.0")
            rc = CFVersion((1, 0))

            #print "RSH - rc is ",rc
                
    return rc

  #--------------------------
  def validName(self, name):
  #--------------------------
    """ Check for valid name.  They must begin with a
    letter and be composed of letters, digits and underscores."""

    nameSyntax = re.compile('^[a-zA-Z][a-zA-Z0-9_]*$')
    if not nameSyntax.match(name):
        return 0

    return 1


  #---------------------------------------------
  def chkDimensions(self,varName,allcoordVars):
  #---------------------------------------------
    """Check variable has non-repeated dimensions, that
       space/time dimensions are listed in the order T,Z,Y,X
       and that any non space/time dimensions are added to
       the left of the space/time dimensions, unless it
       is a boundary variable or climatology variable, where
       1 trailing dimension is allowed."""

    var=self.f.variables[varName]
    dimensions=map(str,var.dimensions)
    trailingVars=[]
    
    if len(dimensions) > 1:
        order=['T','Z','Y','X']
        axesFound=[0,0,0,0] # Holding array to record whether a dimension with an axis value has been found.
        i=-1
        lastPos=-1
        trailing=0   # Flag to indicate trailing dimension
        
        # Flags to hold positions of first space/time dimension and
        # last Non-space/time dimension in variable declaration.
        firstST=-1
        lastNonST=-1
        nonSpaceDimensions=[]

        for dim in dimensions:
            i=i+1
            try:
                if hasattr(self.f.variables[dim],'axis'):
                    pos=order.index(self.f.variables[dim].axis)

                    # Is there already a dimension with this axis attribute specified.
                    if axesFound[pos] == 1:
                        self._add_error("Variable has more than 1 coordinate variable with same axis value",
                                        varName)
                    else:
                        axesFound[pos] = 1
                elif hasattr(self.f.variables[dim],'units') and self.f.variables[dim].units != "":
                    # Determine interpretation of variable by units attribute
                    if hasattr(self.f.variables[dim],'positive'):
                        interp=self.getInterpretation(self.f.variables[dim].units,self.f.variables[dim].positive)
                    else:
                        interp=self.getInterpretation(self.f.variables[dim].units)

                    if not interp: raise ValueError
                    pos=order.index(interp)
                else:
                    # No axis or units attribute so can't determine interpretation of variable
                    raise ValueError

                if firstST == -1:
                    firstST=pos
            except KeyError:
                pass
            except ValueError:
                # Dimension is not T,Z,Y or X axis
                nonSpaceDimensions.append(dim)
                trailingVars.append(dim)
                lastNonST=i
            else:
                # Is the dimensional position of this dimension further to the right than the previous dim?
                if pos >= lastPos:
                    lastPos=pos
                    trailingVars=[]
                else:
                    self._add_warn("space/time dimensions appear in incorrect order", varName, code="2.4")

        # As per CRM #022 
        # This check should only be applied for COARDS conformance.
        if self.coards:
            validTrailing=self.boundsVars[:]
            validTrailing[len(validTrailing):]=self.climatologyVars[:]
            if lastNonST > firstST and firstST != -1:
                if len(trailingVars) == 1:
                    if varName not in validTrailing:
                        self._add_warn("dimensions %s should appear to left of space/time dimensions" % nonSpaceDimensions,
                                       varName, code="2.4")
                else:                    
                    self._add_warn("dimensions %s should appear to left of space/time dimensions" % nonSpaceDimensions,
                                   varName, code="2.4")

                
        dimensions.sort()
        if not self.uniqueList(dimensions):
            self._add_error("variable has repeated dimensions", varName, code="2.4")

  #-------------------------------------------------------
  def getTypeCode(self, obj):
  #-------------------------------------------------------
      """
      Get the type, as a 1-character code
      """
  #     self._add_debug("getTypeCode: Object - %s" % obj)

 #     if isinstance(obj, netCDF4_Variable) or isinstance(obj, numpy.ndarray):
 #         print "RSH: netcdf4.Variable or numpy.ndarray"
 #         return obj.dtype.char

 #     print "RSH: type ", obj.dtype.char
 
      return obj.dtype.char


  #-------------------------------------------------------
  def chkAttribute(self, attribute,varName,allCoordVars):
  #-------------------------------------------------------
    """Check the syntax of the attribute name, that the attribute
    is of the correct type and that it is attached to the right
    kind of variable."""
    var=self.f.variables[varName]

    if not self.validName(attribute) and attribute != "_FillValue":
        self._add_error("Invalid attribute name: %s",attribute,
                        varName)
        return

    value=var.getncattr(attribute)

    self._add_debug("chkAttribute: Checking attribute - %s" % attribute, varName)
 
    #------------------------------------------------------------
    # Attribute of wrong 'type' in the sense numeric/non-numeric
    #------------------------------------------------------------
    if self.AttrList.has_key(attribute):
        # Standard Attribute, therefore check type

        attrType=type(value)

        if isinstance(value, basestring):
            attrType='S'
        elif numpy.issubdtype(attrType, numpy.int) or numpy.issubdtype(attrType, numpy.float):
            attrType='N'
        elif attrType == numpy.ndarray:
            attrType='N'
        elif attrType == types.NoneType:
            attrType='NoneType'
        else:
            self._add_info("Unknown Type for attribute: %s %s" % (attribute, attrType))

        # If attrType = 'NoneType' then it has been automatically created e.g. missing_value
        typeError=0
        if attrType != 'NoneType':
            if self.AttrList[attribute][0] == 'D':
                # Special case for 'D' as these attributes will always be caught
                # by one of the above cases.
                # Attributes of type 'D' should be the same type as the data variable
                # they are attached to.
                if attrType == 'S':
                    # Note: A string is an array of chars
                    if self.getTypeCode(var) != 'S':
                        typeError=1
                else:
                    if self.getTypeCode(var) != self.getTypeCode(var.getncattr(attribute)):
                            typeError=1
                    
            elif self.AttrList[attribute][0] != attrType:
                typeError=1

            if typeError:
                self._add_error("Attribute %s of incorrect type" % attribute,
                                varName)
            
        # Attribute attached to the wrong kind of variable
        uses=self.AttrList[attribute][1]
        usesLen=len(uses)
        i=1
        for use in uses:
            if use == "C" and varName in allCoordVars:
                # Valid association
                break
            elif use == "D" and varName not in allCoordVars:
                # Valid association
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
                i=i+1

        # Check no time variable attributes. E.g. calendar, month_lengths etc.
        TimeAttributes=['calendar','month_lengths','leap_year','leap_month','climatology']
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


  #----------------------------
  def chkCFRole(self,varName):
  #----------------------------
      # Validate cf_role attribute
      var=self.f.variables[varName]

      if hasattr(var, 'cf_role'):
          cf_role=var.cf_role

          # Keep a tally of how many variables have the cf_role attribute set
          self.cf_roleCount = self.cf_roleCount + 1

          if not cf_role in ['timeseries_id','profile_id','trajectory_id']:
              self._add_error("Invalid value for cf_role attribute", varName, code="9.5")

  #---------------------------------
  def chkRaggedArray(self,varName):
  #---------------------------------
      # Validate count/index variable
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
                
  #----------------------------------
  def isValidUdunitsUnit(self,unit):
  #----------------------------------
      # units must be recognizable by udunits package
      rc=1
      try:
          u = Units(unit)
      except:
          rc=0

      return rc


  #---------------------------------------------------
  def isValidCellMethodTypeValue(self, type, value, varName):
  #---------------------------------------------------
      """ 
      Is <type1> or <type2> in the cell_methods attribute a valid value
      (method may have side-effect of logging additional errors,
      and for this purpose the variable name is also passed in)
      """
      rc=1
      # Is it a string-valued aux coord var with standard_name of area_type?
      if value in self.auxCoordVars:
          if self.f.variables[value].dtype.char != 'c':
              rc=0
          elif type == "type2":
              # <type2> has the additional requirement that it is not allowed a leading dimension of more than one
              leadingDim = self.f.variables[value].dimensions[0]
              # Must not be a value of more than one
              if self.f.dimensions[leadingDim] > 1:
                  self._add_error("%s is not allowed a leading dimension of more than one." % value,
                                  varName)

          if hasattr(self.f.variables[value], 'standard_name'):
              if self.f.variables[value].standard_name != 'area_type':
                  rc=0
                  
      # Is type a valid area_type according to the area_type table
      elif value not in self.area_type_lh.list:
          rc=0

      return rc


  #----------------------------------
  def chkCellMethods(self,varName):
  #----------------------------------
    """Checks on cell_methods attribute
       dim1: [dim2: [dim3: ...]] method [where type1 [over type2]] [ (comment) ]
       where comment is of the form:  ([interval: value unit [interval: ...] comment:] remainder)
    """
    
    error = 0  # Flag to indicate validity of cell_methods string syntax
    varDimensions={}
    var=self.f.variables[varName]
    
    if hasattr(var, 'cell_methods'):
        cellMethods=var.cell_methods

#        cellMethods="lat: area: maximum (interval: 1 hours interval: 3 hours comment: fred)"

        pr1=re.compile(r'^'
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

        # Grab each word-list - dim1: [dim2: [dim3: ...]] method [where type1 [over type2]] [within|over days|years] [(comment)]
        pr2=re.compile(r'(?P<dimensions>\s*\S+\s*:\s*(\S+\s*:\s*)*'
                      r'(?P<method>[a-z_]+)'
                      r'(?:\s+where\s+(?P<type1>\S+)(?:\s+over\s+(?P<type2>\S+))?)?'
                      r'(?:\s+(?:over|within)\s+(?:days|years))?\s*)'
                      r'(?P<comment>\([^)]+\))?')

        substr_iter=pr2.finditer(cellMethods)
        
        # Validate each substring
        for s in substr_iter:
            if not re.match(r'point|sum|maximum|median|mid_range|minimum|mean|mode|standard_deviation|variance',s.group('method')):
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
            allDims=re.findall(r'\S+\s*:',s.group('dimensions'))
            dc=0          # Number of dims
            
            for part in allDims:
                dims=re.split(':',part)

                for d in dims:
                    if d:
                        dc=dc+1
                        if d not in var.dimensions and d not in self.std_name_dh.dict.keys():
                            if self.version >= vn1_4:
                                # Extra constraints at CF-1.4 and above
                                if d != "area":
                                    self._add_error("Invalid 'name' in cell_methods attribute: %s" % d, varName, code="7.3")
                            else:
                                self._add_error("Invalid 'name' in cell_methods attribute: %s" % d, varName, code="7.3")
                                
                        else:
                            # dim is a variable dimension
                            if varDimensions.has_key(d) and d != "time":
                                self._add_error("Multiple cell_methods entries for dimension: %s" % d, varName, code="7.3")
                            else:
                                varDimensions[d]=1
                                
                            if self.version >= vn1_4:
                                # If dim is a coordinate variable and cell_method is not 'point' check
                                # if the coordinate variable has either bounds or climatology attributes
                                if d in self.coordVars and s.group('method') != 'point':
                                    if not hasattr(self.f.variables[d], 'bounds') and not hasattr(self.f.variables[d], 'climatology'):
                                        self._add_warn("Coordinate variable %s should have bounds or climatology attribute" %d,
                                                       varName, code="7.3")
                                                
            # Validate the comment associated with this method, if present
            comment = s.group('comment')
            if comment:
                getIntervals = re.compile(r'(?P<interval>interval:\s+\d+\s+(?P<unit>\S+)\s*)')
                allIntervals = getIntervals.finditer(comment)

                # There must be zero, one or exactly as many interval clauses as there are dims
                i=0   # Number of intervals present
                for m in allIntervals:
                    i=i+1
                    unit=m.group('unit')
                    if not self.isValidUdunitsUnit(unit):
                        self._add_error("Invalid unit %s in cell_methods comment" % unit, varName, code="7.3")

                if i > 1 and i != dc:
                    self._add_error("Incorrect number or interval clauses in cell_methods attribute", varName, code="7.3")
                    

  #----------------------------------
  def chkCellMeasures(self,varName):
  #----------------------------------
    """Checks on cell_measures attribute:
    1) Correct syntax
    2) Reference valid variable
    3) Valid measure"""
    var=self.f.variables[varName]
    
    if hasattr(var, 'cell_measures'):
        cellMeasures=var.cell_measures
        if not re.search("^([a-zA-Z0-9]+: +([a-zA-Z0-9_ ]+:?)*( +[a-zA-Z0-9_]+)?)$",cellMeasures):
            self._add_error("Invalid cell_measures syntax", varName, code="7.2")
        else:
            # Need to validate the measure + name
            split=string.split(cellMeasures)
            splitIter=iter(split)
            try:
                while 1:
                    measure=splitIter.next()
                    variable=splitIter.next()

                    if variable not in self.f.variables:
                        self._add_warn("cell_measures refers to variable %s that doesn't exist in this netCDF file. " % variable + 
                                       "This is strictly an error if the cell_measures variable is not included in the dataset.", 
                                       varName, code="7.2")
                        
                    else:
                        # Valid variable name in cell_measures so carry on with tests.    
                        if len(self.f.variables[variable].dimensions) > len(var.dimensions):
                            self._add_error("Dimensions of %s must be same or a subset of %s" % (variable, map(str,var.dimensions)),
                                            varName, code="7.2")
                        else:
                            # If cell_measures variable has more dims than var then this check automatically will fail
                            # Put in else so as not to duplicate ERROR messages.
                            for dim in self.f.variables[variable].dimensions:
                                if dim not in var.dimensions:
                                    self._add_error("Dimensions of %s must be same or a subset of %s" % (variable, map(str,var.dimensions)),
                                                    varName, code="7.2")
                    
                        measure=re.sub(':','',measure)
                        if not re.match("^(area|volume)$",measure):
                            self._add_error("Invalid measure in attribute cell_measures", varName, code="7.2")

                        if measure == "area" and Units(self.f.variables[variable].units) != Units('m2'):
                            self._add_error("Must have square meters for area measure", varName, code="7.2")

                        if measure == "volume" and Units(self.f.variables[variable].units) != Units('m3'):
                            self._add_error("Must have cubic meters for volume measure", varName, code="7.2")
                        
            except StopIteration:
                pass
            

  #----------------------------------
  def chkFormulaTerms(self,varName,allCoordVars):
  #----------------------------------
    """Checks on formula_terms attribute (CF Section 4.3.2):
    formula_terms = var: term var: term ...
    1) No standard_name present
    2) No formula defined for std_name
    3) Invalid formula_terms syntax
    4) Var referenced, not declared"""
    var=self.f.variables[varName]
    
    if hasattr(var, 'formula_terms'):

        if varName not in allCoordVars:
            self._add_error("formula_terms attribute only allowed on coordinate variables", varName, code="4.3.2")
            
        # Get standard_name to determine which formula is to be used
        if not hasattr(var, 'standard_name'):
            self._add_error("Cannot get formula definition as no standard_name", varName, code="4.3.2")
            # No sense in carrying on as can't validate formula_terms without valid standard name
            return


        (stdName,modifier) = self.getStdName(var)
        
        if not self.alias.has_key(stdName):
            self._add_error("No formula defined for standard name: %s" % stdName, varName, code="4.3.2")
            # No formula available so can't validate formula_terms
            return

        index=self.alias[stdName]

        formulaTerms=var.formula_terms
        if not re.search("^([a-zA-Z0-9_]+: +[a-zA-Z0-9_]+( +)?)*$",formulaTerms):
            self._add_error("Invalid formula_terms syntax", varName, code="4.3.2")
        else:
            # Need to validate the term & var
            split=string.split(formulaTerms)
            for x in split[:]:
                if not re.search("^[a-zA-Z0-9_]+:$", x):
                    # Variable - should be declared in netCDF file
                    if x not in self.f.variables.keys():
                        self._add_error("%s is not declared as a variable" % x, varName, code="4.3.2")
                else:
                    # Term - Should be present in formula
                    x=re.sub(':','',x)
                    found='false'
                    for formula in self.formulas[index]:
                        if re.search(x,formula):
                            found='true'
                            break

                    if found == 'false':
                        self._add_error("term %s not present in formula" % x, varName, code="4.3.2")

  #----------------------------------------
  def chkUnits(self,varName,allCoordVars):
  #----------------------------------------
      """Check units attribute"""

      var=self.f.variables[varName]

      if self.badc:
          # If unit is a BADC unit then no need to check via udunits
          if self.chkBADCUnits(var):
              return

      # Test for blank since coordinate variables have 'units' defined even if not specifically defined in the file
      if hasattr(var, 'units') and var.units != '':
          # Type of units is a string
          units = var.units
          if not isinstance(units, basestring):
              self._add_error("units attribute must be of type 'String'", varName, code="3.1")
              # units not a string so no point carrying out further tests
              return
            
          # units - level, layer and sigma_level are deprecated
          if units in ['level','layer','sigma_level']:
              self._add_warn("units %s is deprecated" % units, varName, code="3.1")
          elif units == 'month':
              self._add_warn("The unit 'month', defined by udunits to be exactly year/12, should be used with caution",
                             varName, code="4.4")
          elif units == 'year':
              self._add_warn("The unit 'year', defined by udunits to be exactly 365.242198781 days, should be used with caution. It is not a calendar year.",
                             varName, code="4.4")
          else:
              # units must be recognizable by udunits package
              try:
                  varUnit = Units(units)
              except ValueError:
                  self._add_error("Invalid units: %s" % units,  varName, code="3.1")
                  # Invalid unit so no point continuing with further unit checks
                  return

              # units of a variable that specifies a standard_name must
              # be consistent with units given in standard_name table
              if hasattr(var, 'standard_name'):
                  (stdName,modifier) = self.getStdName(var)

                  # Is the Standard Name modifier number_of_observations being used.
                  if modifier == 'number_of_observations':
                      # Standard Name modifier is number_of_observations therefore units should be "1".  See Appendix C
                      if not units == "1":
                          self._add_error("Standard Name modifier 'number_of_observations' present therefore units must be set to 1.",
                                          varName, code="3.3")
                  
                  elif stdName in self.std_name_dh.dict.keys():
                      # Get canonical units from standard name table
                      stdNameUnits = self.std_name_dh.dict[stdName]

                      # stdNameUnits is unicode which udunits can't deal with.  Explicity convert it to ASCII
                      stdNameUnits=stdNameUnits.encode('ascii')

                      canonicalUnit = Units(stdNameUnits)
                      # To compare units we need to remove the reference time from the variable units
                      if re.search("since", units):
                          # unit attribute contains a reference time - remove it
                          varUnit = Units(units.split()[0])

                      # If variable has cell_methods=variance we need to square standard_name table units
                      if hasattr(var, 'cell_methods'):
                          # Remove comments from the cell_methods string - no need to search these
                          getComments=re.compile(r'\([^)]+\)')
                          noComments=getComments.sub('%5A',var.cell_methods)

                          if re.search(r'(\s+|:)variance',noComments):
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
              
              #print "RSH: in allCoordVars"
              # Label variables do not require units attribute
              if self.f.variables[varName].dtype.char != 'S':
                  if hasattr(var, 'axis'):
                      if not var.axis == 'Z':
                          self._add_warn("units attribute should be present", varName, code="3.1")
                  elif not hasattr(var,'positive') and not hasattr(var,'formula_terms') and not hasattr(var,'compress'):
                      self._add_warn("units attribute should be present", varName, code="3.1")

          elif varName not in self.boundsVars and varName not in self.climatologyVars and varName not in self.gridMappingVars:
              # Variable is not a boundary or climatology variable

              dimensions = self.f.variables[varName].dimensions

              if not hasattr(var,'flag_values') and len(dimensions) != 0:
                  try:
                      if self.f.variables[varName].dtype.char != 'S':
                          # Variable is not a flag variable or a scalar or a label
                          self._add_info("No units attribute set.  Please consider adding a units attribute for completeness.",
                                     varName, code="3.1")
                  except AttributeError:
                      typecodes = "char, byte, short, int, float, real, double"
                      self._add_warn("Could not get typecode of variable.  Variable types supported are: %s" % typecodes, varName, code="2.2")
                  


  #----------------------------
  def chkBADCUnits(self, var):
  #----------------------------
      """Check units allowed by BADC"""
      units_lines=open("/usr/local/cf-checker/lib/badc_units.txt").readlines()

      # badc_units test case
      #units_lines=open("/home/ros/SRCE_projects/CF_Checker_W/main/Test_Files/badc_units.txt").readlines()
      
      # units must be recognizable by the BADC units file
      for line in units_lines:
          if hasattr(var, 'units') and var.attributes['units'] in string.split(line):
              self._add_info("Valid units in BADC list: %s" % var.attributes['units'], var.id)
              return 1
      return 0
  

  #---------------------------------------
  def chkValidMinMaxRange(self, varName):
  #---------------------------------------
      """Check that valid_range and valid_min/valid_max are not both specified"""
      var=self.f.variables[varName]
    
      if hasattr(var, 'valid_range'):
          if hasattr(var, 'valid_min') or hasattr(var, 'valid_max'):
              self._add_error("Illegal use of valid_range and valid_min/valid_max", varName, code="2.5.1")

  #---------------------------------
  def chk_FillValue(self, varName):
  #---------------------------------
    """Check 1) type of _FillValue
    2) _FillValue lies outside of valid_range
    3) type of missing_value
    4) flag use of missing_value as deprecated"""
    var=self.f.variables[varName]

    if hasattr(var, '_FillValue'):
        fillValue=var._FillValue
            
        if hasattr(var, 'valid_range'):
            # Check _FillValue is outside valid_range
            validRange=var.valid_range
            if validRange[0] < fillValue < validRange[1]:
                self._add_warn("_FillValue should be outside valid_range", varName, code="2.5.1")

        if varName in self.boundsVars:
            self._add_warn("Boundary Variable %s should not have _FillValue attribute"% varName, varName, code="7.1")
        elif varName in self.climatologyVars:
            self._add_error("Climatology Variable %s must not have _FillValue attribute" % varName, varName, code="7.4")

    if hasattr(var, 'missing_value'):
        missingValue=var.missing_value
        try:
            if missingValue:
                if hasattr(var, '_FillValue'):
                    if fillValue != missingValue:
                        # Special case: NaN == NaN is not detected as NaN does not compare equal to anything else
                        if not (numpy.isnan(fillValue) and numpy.isnan(missingValue)):
                            self._add_warn("missing_value and _FillValue set to differing values", varName, code="2.5.1")

                if varName in self.boundsVars:
                    self._add_warn("Boundary Variable %s should not have missing_value attribute" % varName, 
                                   varName, code="7.1")
                elif var in self.climatologyVars:
                    self._add_error("Climatology Variable %s must not have missing_value attribute" % varName, 
                                    varName, code="7.4")

        except ValueError:
            self._add_info("Could not complete tests on missing_value attribute: %s" % sys.exc_info()[1], varName)
        

  #------------------------------------
  def chkAxisAttribute(self, varName):
  #------------------------------------
      """Check validity of axis attribute"""
      var=self.f.variables[varName]
      
      if hasattr(var, 'axis'):
          if not re.match('^(X|Y|Z|T)$',var.axis,re.I):
              self._add_error("Invalid value for axis attribute", varName, code="4")
              return

          # axis attribute is allowed on an aux coord var as of CF-1.6
          if self.version >= vn1_1 and self.version < vn1_6 and varName in self.auxCoordVars:
              self._add_error("Axis attribute is not allowed for auxillary coordinate variables.",
                              varName, code="4")
              return
          
          # Check that axis attribute is consistent with the coordinate type
          # deduced from units and positive.
          if hasattr(var,'units'):
              if hasattr(var,'positive'): 
                  interp=self.getInterpretation(var.units,var.positive)
              else:
                  interp=self.getInterpretation(var.units)
          else:
              # Variable does not have a units attribute so a consistency check cannot be made
              interp=None

          if interp != None:
              # It was possible to deduce axis interpretation from units/positive
              if interp != var.axis:
                  self._add_error("axis attribute inconsistent with coordinate type as deduced from units and/or positive", 
                                  varName, code="4")
                  return


  #----------------------------------------
  def chkPositiveAttribute(self, varName):
  #----------------------------------------
      var=self.f.variables[varName]
      if hasattr(var, 'positive'):
          if not re.match('^(down|up)$',var.positive,re.I):
              self._add_error("Invalid value for positive attribute", varName, code="4.3")


  #-----------------------------------------
  def chkTimeVariableAttributes(self, varName):
  #-----------------------------------------
    var=self.f.variables[varName]
    
    if hasattr(var, 'calendar'):
        if not re.match('(gregorian|standard|proleptic_gregorian|noleap|365_day|all_leap|366_day|360_day|julian|none)',
                        var.calendar,re.I):
            # Non-standardized calendar so month_lengths should be present
            if not hasattr(var, 'month_lengths'):
                self._add_error("Non-standard calendar, so month_lengths attribute must be present", varName, code="4.4.1")
        else:   
            if hasattr(var, 'month_lengths') or \
               hasattr(var, 'leap_year') or \
               hasattr(var, 'leap_month'):
                self._add_error("The attributes 'month_lengths', 'leap_year' and 'leap_month' must not appear when 'calendar' is present.",
                                varName, code="4.4.1")

    if not hasattr(var, 'calendar') and not hasattr(var, 'month_lengths'):
        self._add_warn("Use of the calendar and/or month_lengths attributes is recommended for time coordinate variables",
                       varName, code="4.4.1")
        
    if hasattr(var, 'month_lengths'):
        if len(var.month_lengths) != 12 and \
           self.getTypeCode(var.month_lengths) != 'i':
            self._add_error("Attribute 'month_lengths' should be an integer array of size 12", varName, code="4.4.1")

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
    varUnits = Units(var.units)
    if not varUnits.isreftime:
        self._add_error("Invalid units and/or reference time", varName, code="4.4")

    
  #----------------------------------
  def chkDescription(self, varName):
  #----------------------------------
      """Check 1) standard_name & long_name attributes are present
               2) for a valid standard_name as listed in the standard name table."""
      var=self.f.variables[varName]

      if not hasattr(var, 'standard_name') and \
         not hasattr(var, 'long_name'):

          exceptions=self.boundsVars+self.climatologyVars+self.gridMappingVars
          if varName not in exceptions:
              self._add_warn("No standard_name or long_name attribute specified", varName, code="3")
              
      if hasattr(var, 'standard_name'):
          # Check if valid by the standard_name table and allowed modifiers
          std_name=var.standard_name

          # standard_name attribute can comprise a standard_name only or a standard_name
          # followed by a modifier (E.g. atmosphere_cloud_liquid_water_content status_flag)
          std_name_el=string.split(std_name)
          if not std_name_el:
              self._add_error("Empty string for 'standard_name' attribute", varName, code="3.3")
              
          elif not self.parseBlankSeparatedList(std_name) or len(std_name_el) > 2:
              self._add_error("Invalid syntax for 'standard_name' attribute: '%s'" % std_name, varName, code="3.3")

          else:
              # Validate standard_name
              name=std_name_el[0]
              if not name in self.std_name_dh.dict.keys():
                  if chkDerivedName(name):
                      self._add_error("Invalid standard_name: %s" % name, varName, code="3.3")

              if len(std_name_el) == 2:
                  # Validate modifier
                  modifier=std_name_el[1]
                  if not modifier in ['detection_minimum','number_of_observations','standard_error','status_flag']:
                      self._add_error("Invalid standard_name modifier: %s" % modifier, varName, code="3.3")
                      

  #-----------------------------------
  def chkCompressAttr(self, varName):
  #-----------------------------------
    var=self.f.variables[varName]
    if hasattr(var, 'compress'):
        compress=var.compress

        if var.dtype.char != 'i':
            self._add_error("compress attribute can only be attached to variable of type int.", varName, code="8.2")
            return
        if not re.search("^[a-zA-Z0-9_ ]*$",compress):
            self._add_error("Invalid syntax for 'compress' attribute", varName, code="8.2")
        else:
            dimensions=string.split(compress)
            dimProduct=1
            for x in dimensions:
                found='false'
                if x in self.f.dimensions:
                    # Get product of compressed dimension sizes for use later
                    #dimProduct=dimProduct*self.f.dimensions[x]
                    dimProduct=dimProduct*len(self.f.dimensions[x])
                    found='true'

                if found != 'true':
                    self._add_error("compress attribute naming non-existent dimension: %s" % x,
                                    varName, code="8.2")

            outOfRange=0
            for val in var[:]:
                if val < 0 or val > dimProduct-1:
                    outOfRange=1
                    break;
                
            if outOfRange:
                self._add_error("values of %s must be in the range 0 to %s" % (varName, dimProduct - 1),
                                varName, code="8.2")

  #---------------------------------
  def chkPackedData(self, varName):
  #---------------------------------
    var=self.f.variables[varName]
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
            self._add_warn("scale_factor/add_offset are type float, therefore should not be of type int", varName, code="8.1")
            
  #----------------------------
  def chkFlags(self, varName):
  #----------------------------
      var=self.f.variables[varName]

      if hasattr(var, 'flag_meanings'):
          # Flag to indicate whether one of flag_values or flag_masks present
          values_or_masks=0
          meanings = var.flag_meanings

#          if not self.parseBlankSeparatedList(meanings):
          if not self.extendedBlankSeparatedList(meanings):
              self._add_error("Invalid syntax for 'flag_meanings' attribute", varName, code="3.5")
          
          if hasattr(var, 'flag_values'):
              values_or_masks=1
              values = var.flag_values
              
              retcode = self.equalNumOfValues(values,meanings)
              if retcode == -1:
                  self._add_error("Problem in subroutine equalNumOfValues", varName, code="3.5")
              elif not retcode:
                  self._add_error("Number of flag_values values must equal the number or words/phrases in flag_meanings",
                                  varName, code="3.5")
                  
              # flag_values values must be mutually exclusive
              if type(values) == str:
                  values = values.split()

              if not self.uniqueList(values):
                  self._add_error("flag_values attribute must contain a list of unique values", varName, code="3.5")
                  
          if hasattr(var, 'flag_masks'):
              values_or_masks=1
              masks = var.flag_masks

              retcode = self.equalNumOfValues(masks,meanings)
              if retcode == -1:
                  self._add_error("Problem in subroutine equalNumOfValues", varName, code="3.5")
              elif not retcode:
                  self._add_error("Number of flag_masks values must equal the number or words/phrases in flag_meanings",
                                  varName, code="3.5")
                  
              # flag_values values must be non-zero
              for v in masks:
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
                          self._add_warn("Bitwise AND of flag_value %s and corresponding flag_mask %s doesn't match flag_value." % (v, masks[i]),  
                                         varName, code="3.5")
                      i=i+1
                 
          if values_or_masks == 0:
              # flag_meanings attribute present, but no flag_values or flag_masks
              self._add_error("flag_meanings present, but no flag_values or flag_masks specified", varName, code="3.5")

          if hasattr(var, 'flag_values') and not hasattr(var, 'flag_meanings'):
              self._add_error("flag_meanings attribute is missing", varName, code="3.5")
              

  #-----------------------
  def getType(self, arg):
  #-----------------------

#      if type(arg) == type(numpy.array([])):
      if isinstance(arg, numpy.ndarray):
          return "array"

      elif isinstance(arg, basestring):
          return "str"

      elif type(arg) == list:
          return "list"

      else:
          print "<cfchecker> ERROR: Unknown Type in getType("+arg+")"
          return 0
  
  
  
  #----------------------------------------    
  def equalNumOfValues(self, arg1, arg2):
  #----------------------------------------
      """ Check that arg1 and arg2 contain the same number of blank-separated elements."""

      # Determine the type of both arguments.  strings and arrays need to be handled differently
      type_arg1 = self.getType(arg1)
      type_arg2 = self.getType(arg2)
      
      if not type_arg1 or not type_arg2:
          return -1
          
      if type_arg1 == "str":
          len_arg1 = len(arg1.split())
      else:
          len_arg1 = len(arg1)

      if type_arg2 == "str":
          len_arg2 = len(arg2.split())
      else:
          len_arg2 = len(arg2)
      
      
      if len_arg1 != len_arg2:
          return 0

      return 1

      
  #------------------------------------------
  def chkMultiDimCoord(self, varName, axes):
  #------------------------------------------
      """If a coordinate variable is multi-dimensional, then it is recommended
      that the variable name should not match the name of any of its dimensions."""
      var=self.f.variables[varName]
    
      if varName in axes and len(var.dimensions) > 1:
          # Multi-dimensional coordinate var
          if varName in var.dimensions:
              self._add_warn("The name of a multi-dimensional coordinate variable should not match the name of any of its dimensions.",
                             varName, code="5")

  #--------------------------------------
  def chkValuesMonotonic(self, varName):
  #--------------------------------------
    """A coordinate variable must have values that are strictly monotonic
    (increasing or decreasing)."""
    var=self.f.variables[varName]
    i=0

    if len(var) == 0 or len(var) == 1:
        # nothing to check
        return
    
    for i, value in enumerate(var):
        if i == 0:
            # First value - no comparison to do
            lastVal=value
            continue
        elif i == 1:
            if value < lastVal:
                # Decreasing sequence
                type='decr'
            elif value > lastVal:
                # Increasing sequence
                type='incr'
            else:
                # Same value - ERROR
                self._add_error("co-ordinate variable not monotonic", varName, code="5")
                return

            lastVal=value
        else:
            if value < lastVal and type != 'decr':
                # ERROR - should be increasing value
                self._add_error("co-ordinate variable not monotonic", varName, code="5")
                return
            elif value > lastVal and type != 'incr':
                # ERROR - should be decreasing value
                self._add_error("co-ordinate variable not monotonic", varName, code="5")
                return

            lastVal=value


def getargs(arglist):
    
    '''getargs(arglist): parse command line options and environment variables'''

    from getopt import getopt, GetoptError
    from os import environ
    from sys import stderr, exit

    standardnamekey='CF_STANDARD_NAMES'
    areatypeskey='CF_AREA_TYPES'
    # set defaults
    standardname=STANDARDNAME
    areatypes=AREATYPES
    uploader=None
    useFileName="yes"
    badc=None
    coards=None
    version=newest_version
    debug = False
    
    # set to environment variables
    if environ.has_key(standardnamekey):
        standardname=environ[standardnamekey]
    if environ.has_key(areatypeskey):
        areatypes=environ[areatypeskey]

    try:
        (opts,args)=getopt(arglist[1:],'a:bcdhlns:v:',['area_types=','badc','coards','help','uploader','noname','cf_standard_names=','version=', 'debug'])
    except GetoptError:
        stderr.write('%s\n'%__doc__)
        exit(1)
    
    for a, v in opts:
        if a in ('-a','--area_types'):
            areatypes=v.strip()
            continue
        if a in ('-b','--badc'):
            badc="yes"
            continue
        if a in ('-c','--coards'):
            coards="yes"
            continue
        if a in ('-d','--debug'):
            debug=True
            continue
        if a in ('-h','--help'):
            print __doc__
            exit(0)
        if a in ('-l','--uploader'):
            uploader="yes"
            continue
        if a in ('-n','--noname'):
            useFileName="no"
            continue
        if a in ('-s','--cf_standard_names'):
            standardname=v.strip()
            continue
        if a in ('-v','--version'):
            if v == 'auto':
                version = CFVersion()
            else:
                try:
                    version = CFVersion(v)
                except ValueError:
                    print "WARNING: '%s' cannot be parsed as a version number." % v
                    print "Performing check against newest version", newest_version                    
                if version not in cfVersions:
                    print "WARNING: %s is not a valid CF version." % version
                    print "Performing check against newest version", newest_version
                    version = newest_version
            continue
            
    if len(args) == 0:
        stderr.write('ERROR in command line\n\nusage:\n%s\n'%__doc__)
        exit(1)

    return (badc,coards,uploader,useFileName,standardname,areatypes,version,args,debug)


def main():

    (badc,coards,uploader,useFileName,standardName,areaTypes,version,files,debug)=getargs(sys.argv)
    
    inst = CFChecker(uploader=uploader, useFileName=useFileName, badc=badc, coards=coards, cfStandardNamesXML=standardName, cfAreaTypesXML=areaTypes, version=version, debug=debug)
    for file in files:
        #print
        try:
            inst.checker(file)
        except FatalCheckerError:
            print "Checking of file %s aborted due to error" % file
        #print

    totals = inst.get_total_counts()

    if debug:
        print
        print "Results dictionary:", inst.all_results
        print
        print "Messages that were printed", inst.all_messages

    errs = totals["FATAL"] + totals["ERROR"]
    if errs:
        sys.exit(errs)
    
    warns = totals["WARN"]
    if warns:
        sys.exit(-warns)

    sys.exit(0)


#--------------------------
# Main Program
#--------------------------

if __name__ == '__main__':

    main()
