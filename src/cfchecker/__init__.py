import sys
import os
import os.path as op


__version__ = '2.0.9'

from cfchecker.cfchecks import getargs, CFChecker

def cfchecks_main():
    """cfchecks_main is based on the main program block in cfchecks.py
    """

    (badc,coards,uploader,useFileName,standardName,areaTypes,udunitsDat,version,files)=getargs(sys.argv)
    
    inst = CFChecker(uploader=uploader, useFileName=useFileName, badc=badc, coards=coards, cfStandardNamesXML=standardName, cfAreaTypesXML=areaTypes, udunitsDat=udunitsDat, version=version)
    for file in files:
        rc = inst.checker(file)
        sys.exit (rc)


