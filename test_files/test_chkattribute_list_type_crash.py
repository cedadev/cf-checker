"""
Regression test for: chkAttribute raises an uncaught KeyError when a
standard CF attribute value is a Python list (e.g. a malformed
'comment' attribute) rather than a single string.

Before the fix, this crashed with:
    KeyError: <class 'list'>
raised from the attrLookup[attrType] lookup in chkAttribute().

After the fix, the checker should complete and report a normal ERROR
message for the malformed attribute instead of raising.

Note: this test deliberately uses the 'comment' attribute rather than
'flag_meanings'. A list-valued 'flag_meanings' also crashes, but in a
*different* function (chkFlags -> extendedBlankSeparatedList), which is
a separate bug from the one being fixed here. Using 'comment' keeps
this test scoped to chkAttribute only.

Run with:
    pytest test_chkattribute_list_type_crash.py -v
"""
import os
import tempfile

import netCDF4
import pytest

from cfchecker.cfchecks import CFChecker


@pytest.fixture
def bad_comment_file():
    """
    Create a minimal netCDF file where 'comment' is written as multiple
    separate string values instead of a single string. netCDF4 reads
    this back as a Python list, which previously crashed chkAttribute().
    """
    fd, path = tempfile.mkstemp(suffix=".nc")
    os.close(fd)

    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("x", 4)
        var = ds.createVariable("some_var", "i4", ("x",))
        # CF expects a single string here -- this is deliberately
        # malformed to reproduce the reported bug.
        var.setncattr("comment", ["first note", "second note"])

    yield path

    os.remove(path)


def test_list_valued_comment_does_not_crash(bad_comment_file):
    """
    The checker must not raise an unhandled exception when a standard
    CF attribute's value is a list. It should complete and record an
    ERROR against the offending variable/attribute instead.
    """
    checker = CFChecker(silent=True)

    # This previously raised: KeyError: <class 'list'>
    results = checker.checker(bad_comment_file)

    var_results = results["variables"]["some_var"]
    errors = var_results["ERROR"]

    assert errors, (
        "Expected an ERROR to be reported for the malformed "
        "'comment' attribute, but none was recorded."
    )
    assert any("comment" in msg for msg in errors), (
        f"Expected an error mentioning 'comment', got: {errors}"
    )


if __name__ == "__main__":
    # Allow running directly with `python test_flag_meanings_list_crash.py`
    # without pytest, for quick manual reproduction.
    import contextlib

    fd, path = tempfile.mkstemp(suffix=".nc")
    os.close(fd)
    try:
        with netCDF4.Dataset(path, "w") as ds:
            ds.createDimension("x", 4)
            var = ds.createVariable("some_var", "i4", ("x",))
            var.setncattr("comment", ["first note", "second note"])

        checker = CFChecker(silent=True)
        results = checker.checker(path)
        print("OK - no crash. Results for some_var:")
        print(results["variables"]["some_var"])
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)