#!/bin/ksh

# Note that you may need to change the $cfchecker variable in this file to
# point to the full path location of your "cfchecks" script

outdir=tests_output.$$
mkdir $outdir

std_name_table=http://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml
area_table=http://cfconventions.org/Data/area-type-table/current/src/area-type-table.xml

cfchecker="/home/ros/software/dev/bin/cfchecks"
cfchecker="/home/ros/software/dev-python3/bin/cfchecks"

failed=0

echo "Unzipping input netcdf files..."
gzip -d *.gz

cache_opts="-x --cache_dir /home/ros/temp/cfcache-files-py3"

for file in `ls *.nc`
do
  if test $file == "badc_units.nc"
  then
    # Check --badc option (Note:  Need to set path to badc_units.txt in cfchecks.py)
    $cfchecker $cache_opts --badc $file -s $std_name_table > $outdir/$file.out 2>&1
  elif test $file == "stdName_test.nc"
  then
    # Check --cf_standard_names option
    # Test uses an older version of standard_name table so don't use table caching
    $cfchecker -s ./stdName_test_table.xml -a $area_table $file > $outdir/$file.out 2>&1
  elif test $file == "CF_1_2.nc"
  then
    # CF-1.2
    $cfchecker $cache_opts -s $std_name_table -v 1.2 $file > $outdir/$file.out 2>&1
  elif test $file == "flag_tests.nc"
  then
    # CF-1.3
    $cfchecker $cache_opts -s $std_name_table -v 1.3 $file > $outdir/$file.out 2>&1
  elif [[ $file == "Trac049_test1.nc" || $file == "Trac049_test2.nc" ]]
  then 
    # CF-1.4
    $cfchecker $cache_opts -s $std_name_table -a $area_table -v 1.4 $file > $outdir/$file.out 2>&1
  elif [[ $file == "CF_1_7.nc" || $file == "example_6.2.nc" || $file == "example_5.10.nc" || $file = "issue27.nc" ]]
  then
    # Run checker using the CF version specified in the conventions attribute of the file
    $cfchecker $cache_opts -s $std_name_table -v auto $file > $outdir/$file.out 2>&1
  else
    # Run the checker on the file
    $cfchecker $cache_opts -s $std_name_table -v 1.0 $file > $outdir/$file.out 2>&1
  fi
  # Check the output against what is expected
  result=${file%.nc}.check
  diff $outdir/$file.out $result >/dev/null
  if test $? == 0
  then
    echo $file: Success
    rm $outdir/$file.out
  else
    echo $file: Failed
    failed=`expr $failed + 1`
  fi
done

# Print Test Results Summary
echo ""
if [[ $failed != 0 ]]
then
  echo "****************************"
  echo "***    $failed Tests Failed    ***"
  echo "****************************"
else
  echo "****************************"
  echo "*** All Tests Successful ***"
  echo "****************************"
fi

# Check that the script options

# --cf_standard_names

# --udunits

# --coards


