from setuptools import setup, find_packages
import sys, os

sys.path.append(os.path.abspath(os.path.dirname(__file__))+'/src/')
__version__ = __import__('cfchecker').__version__
__description__ = "\n"+open(os.path.join(os.path.dirname(__file__), 'README')).read()

setup(name='cfchecker',
      version=__version__,
      description="The NetCDF Climate Forcast Conventions compliance checker",
      long_description=__description__,
      
      classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Topic :: Software Development :: Libraries',
        'Topic :: Scientific/Engineering :: Atmospheric Science',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: BSD License',
        ], 

      keywords='',
      author='Rosalyn Hatcher',
      author_email='r.s.hatcher@reading.ac.uk',

      #!TODO: Maintainer becomes author in PKG-INFO so disable this for now
      #       This is a known Python issue that may be fixed in the future.
      #maintainer='Stephen Pascoe',
      #maintainer_email='Stephen.Pascoe@stfc.ac.uk',

      url='http://cf-pcmdi.llnl.gov/conformance/compliance-checker/',
      package_dir = {'': 'src'},
      packages=find_packages('src'),
      include_package_data=True,
      zip_safe=False,
      install_requires=[
        # -*- Extra requirements: -*-
        #!NOTE: although CDAT is required we may want to use full CDAT or
        #       cdat_lite.  Therefore don't use dependency management.
      ],
      entry_points= {
        'console_scripts': ['cfchecks = cfchecker:cfchecks_main'],
        },
      test_suite='nose.collector',
      )
