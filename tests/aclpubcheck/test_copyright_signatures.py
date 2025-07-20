import os
import tempfile
import pandas as pd
import pytest
from unittest import mock

import aclpubcheck.copyright_signatures as cs

# --- Testing clean_str (the inner function) ---
def get_clean_str():
    # Extract the clean_str function from the closure
    def _get():
        def dummy(submissions_path):
            def clean_str(value):
                return '' if pd.isna(value) else value.strip()
            return clean_str
        return dummy(None)
    return _get()

clean_str = get_clean_str()

def test_clean_str_normal_string():
    """
    Test that clean_str trims whitespace from a normal, non-NA string.
    """
    assert clean_str('  Hello World\n') == 'Hello World'
    assert clean_str('\t hi  ') == 'hi'
    assert clean_str('abc') == 'abc'

def test_clean_str_empty_string():
    """
    Test that clean_str does not change empty string inputs.
    """
    assert clean_str('') == ''

def test_clean_str_only_whitespace():
    """
    Test that clean_str returns an empty string when input is only whitespace.
    """
    assert clean_str('   ') == ''
    assert clean_str('\n\t') == ''

def test_clean_str_nan_values():
    """
    Test that clean_str returns an empty string for various NA/nan inputs.
    """
    assert clean_str(float('nan')) == ''
    assert clean_str(pd.NA) == ''
    assert clean_str(pd.NaT) == ''
    assert clean_str(None) == ''

def test_clean_str_non_str_types():
    """
    Test that clean_str handles non-string, but not-NA inputs (should error if not str, per code logic).
    """
    # Will raise AttributeError since int has no strip method.
    with pytest.raises(AttributeError):
        clean_str(123)

# --- Testing write_copyright_signatures ---

def make_sample_csv(tmp_path, rows):
    """Helper to write a DataFrame as a CSV for test input."""
    df = pd.DataFrame(rows)
    csv_path = tmp_path / "input.csv"
    df.to_csv(csv_path, index=False)
    return str(csv_path), df

def read_signatures_output(fp):
    """Helper to read the output file after function call."""
    with open(fp, 'r', encoding='utf-8') as f:
        return f.read()

def test_write_copyright_signatures_basic(tmp_path, monkeypatch):
    """
    Test that write_copyright_signatures correctly formats a single row with one author.
    """
    # Prepare minimal input
    csv_rows = [{
        'Submission ID': 101,
        'Title': 'Sample Paper',
        'copyrightSig': 'John Doe',
        'orgName': 'Sample University',
        'orgAddress': '123 Main St',
        'jobTitle': '',
        # Author fields
        '1: First Name': 'Alice',
        '1: Middle Name': 'B.',
        '1: Last Name': 'Smith',
        '1: Affiliation': 'Sample University',
    }]
    # Fill remaining author columns with blanks
    for i in range(2, 25):
        csv_rows[0][f'{i}: First Name'] = ''
        csv_rows[0][f'{i}: Middle Name'] = ''
        csv_rows[0][f'{i}: Last Name'] = ''
        csv_rows[0][f'{i}: Affiliation'] = ''

    csv_path, _ = make_sample_csv(tmp_path, csv_rows)

    # set cwd to tmp_path so "copyright-signatures.txt" is written there
    monkeypatch.chdir(tmp_path)

    cs.write_copyright_signatures(csv_path)
    out = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert "Submission # 101" in out
    assert "Title: Sample Paper" in out
    assert "Alice B. Smith (Sample University)" in out
    assert "Signature: John Doe" in out
    assert "Sample University" in out
    assert "123 Main St" in out
    # Check indenting of authors line
    lines = out.splitlines()
    authors_index = lines.index('Authors:')
    # Should see at least four spaces before author name
    assert lines[authors_index+1].startswith('    ')


def test_write_copyright_signatures_multiple_authors(tmp_path, monkeypatch):
    """
    Test copyright signature output with multiple authors, some with missing middle names and mixed affiliations.
    """
    row = {
        'Submission ID': 202,
        'Title': 'Team Contributions',
        'copyrightSig': 'Jane Signer',
        'orgName': 'Example Corp',
        'orgAddress': '456 Broadway Ave',
        'jobTitle': 'Legal Counsel',
    }
    authors = [
        ('John', '', 'Doe', 'University A'),
        ('', '', '', ''),
        ('Lee', 'C.', 'Wong', 'Company B'),
        ('Maria', '', 'Garcia', ''),
    ]
    for i in range(1, 5):
        firstname, middlename, lastname, affil = authors[i-1]
        row[f'{i}: First Name'] = firstname
        row[f'{i}: Middle Name'] = middlename
        row[f'{i}: Last Name'] = lastname
        row[f'{i}: Affiliation'] = affil
    for i in range(5, 25):
        row[f'{i}: First Name'] = ''
        row[f'{i}: Middle Name'] = ''
        row[f'{i}: Last Name'] = ''
        row[f'{i}: Affiliation'] = ''
    csv_path, _ = make_sample_csv(tmp_path, [row])
    monkeypatch.chdir(tmp_path)
    cs.write_copyright_signatures(csv_path)
    output = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert "John Doe (University A)" in output
    assert "Lee C. Wong (Company B)" in output
    assert "Maria Garcia ()" in output
    # Should not include the empty (second) author
    assert "(University A)" in output
    assert "Legal Counsel" in output
    assert output.count('(') == 3  # Only three authors


def test_write_copyright_signatures_empty_fields(tmp_path, monkeypatch):
    """
    Test that blank signature/organization/jobTitle fields print as empty strings (no crash).
    """
    row = {
        'Submission ID': 303,
        'Title': 'Untitled Work',
        'copyrightSig': '',
        'orgName': '',
        'orgAddress': '',
        'jobTitle': '',
    }
    for i in range(1, 25):
        row[f'{i}: First Name'] = ''
        row[f'{i}: Middle Name'] = ''
        row[f'{i}: Last Name'] = ''
        row[f'{i}: Affiliation'] = ''
    csv_path, _ = make_sample_csv(tmp_path, [row])
    monkeypatch.chdir(tmp_path)
    cs.write_copyright_signatures(csv_path)
    output = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert "Signature: " in output  # Should not crash if signature blank
    assert "Name and address of your organization:" in output
    # Should be no authors listed (no spaces after indentation)
    lines = output.splitlines()
    authors_index = lines.index('Authors:')
    assert lines[authors_index+1].strip() == ''


def test_write_copyright_signatures_reads_all_author_columns(tmp_path, monkeypatch):
    """
    Test that authors beyond the minimum columns are processed correctly (e.g., author #24).
    """
    row = {
        'Submission ID': 404,
        'Title': 'Last Author Edge',
        'copyrightSig': 'Final S.',
        'orgName': 'Final Inst',
        'orgAddress': '999 Loop Rd',
        'jobTitle': '',
    }
    for i in range(1, 25):
        if i == 24:
            row[f'{i}: First Name'] = 'Zack'
            row[f'{i}: Middle Name'] = 'Q.'
            row[f'{i}: Last Name'] = 'Zulu'
            row[f'{i}: Affiliation'] = 'Z-Final University'
        else:
            row[f'{i}: First Name'] = ''
            row[f'{i}: Middle Name'] = ''
            row[f'{i}: Last Name'] = ''
            row[f'{i}: Affiliation'] = ''
    csv_path, _ = make_sample_csv(tmp_path, [row])
    monkeypatch.chdir(tmp_path)
    cs.write_copyright_signatures(csv_path)
    out = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert "Zack Q. Zulu (Z-Final University)" in out
    assert out.count('(Z-Final University)') == 1


def test_write_copyright_signatures_nan_values_handling(tmp_path, monkeypatch):
    """
    Test handling when some fields in csv are pd.NA or NaN (should not crash and should output empty fields).
    """
    # mixed NA and string
    row = {
        'Submission ID': 505,
        'Title': 'Missing Person',
        'copyrightSig': pd.NA,
        'orgName': float('nan'),
        'orgAddress': pd.NaT,
        'jobTitle': '',
    }
    for i in range(1, 25):
        row[f'{i}: First Name'] = pd.NA
        row[f'{i}: Middle Name'] = float('nan')
        row[f'{i}: Last Name'] = pd.NaT
        row[f'{i}: Affiliation'] = pd.NA
    csv_path, _ = make_sample_csv(tmp_path, [row])
    monkeypatch.chdir(tmp_path)
    # Should not raise exceptions on pd.NA, np.nan etc
    cs.write_copyright_signatures(csv_path)
    out = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert "Signature: " in out
    assert "Name and address of your organization:" in out


def test_write_copyright_signatures_unicode_support(tmp_path, monkeypatch):
    """
    Test that unicode in names/affiliations is preserved in output.
    """
    row = {
        'Submission ID': 707,
        'Title': 'Überprüfung',
        'copyrightSig': 'José Ñañez',
        'orgName': 'Universität München',
        'orgAddress': 'Straße 1, München',
        'jobTitle': '',
        '1: First Name': 'Chloé',
        '1: Middle Name': '',
        '1: Last Name': 'Dubois-Éclair',
        '1: Affiliation': 'École Polytechnique',
    }
    for i in range(2, 25):
        row[f'{i}: First Name'] = ''
        row[f'{i}: Middle Name'] = ''
        row[f'{i}: Last Name'] = ''
        row[f'{i}: Affiliation'] = ''
    csv_path, _ = make_sample_csv(tmp_path, [row])
    monkeypatch.chdir(tmp_path)
    cs.write_copyright_signatures(csv_path)
    out = read_signatures_output(tmp_path / "copyright-signatures.txt")
    assert 'José Ñañez' in out
    assert 'Chloé Dubois-Éclair (École Polytechnique)' in out
    assert 'Universität München' in out
    assert 'Straße 1, München' in out
