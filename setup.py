from setuptools import setup, find_packages
import sys, os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + '/src')
__version__ = __import__('cfchecker').__version__

# Need to try/except this because pip install unpacks to a different dir and
# relative path lookup fails. Should still work where needed.
try:
    __description__ = "\n" + open(os.path.join(os.path.dirname(__file__), 'README.md')).read()
except:
    __description__ = ""


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

      url='http://cfconventions.org/compliance-checker.html',
      package_dir = {'': 'src'},
      packages=find_packages('src'),

      include_package_data=True,
      zip_safe=False,
      install_requires=['netCDF4', 'numpy', 'cfunits'],
      entry_points= {
        'console_scripts': ['cfchecks = cfchecker.cfchecks:main'],
        },
      )
