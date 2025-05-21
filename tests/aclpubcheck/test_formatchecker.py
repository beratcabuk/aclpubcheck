import builtins
import io
import json
import os
import types
from argparse import Namespace
import pytest
from unittest import mock

import aclpubcheck.formatchecker as formatchecker

class DummyPDFPage:
    def __init__(self, width=None, height=None, text='', images=None, words=None, chars=None, hyperlinks=None):
        self.width = width if width is not None else formatchecker.Page.WIDTH.value
        self.height = height if height is not None else formatchecker.Page.HEIGHT.value
        self.text = text
        self.images = images or []
        self.words = words or []
        self.chars = chars or []
        self.hyperlinks = hyperlinks or []
        self.__cropcalls = []
    def extract_text(self):
        return self.text
    def extract_words(self, extra_attrs=None):
        return self.words
    def crop(self, bbox):
        # support chaining for to_image
        self.__cropcalls.append(bbox)
        return self
    def to_image(self, resolution=None):
        class DummyImageObj:
            def __init__(self):
                self.original = 0 if hasattr(self, "simulate_white") else 255 * formatchecker.np.ones((2,2), dtype=int)
            def draw_rect(self, bbox, fill, stroke, stroke_width):
                return None
            def save(self, path, format=None):
                return None
        img = DummyImageObj()
        return img


class DummyPDF:
    def __init__(self, pages):
        self.pages = pages
    def close(self):
        pass

@pytest.fixture
def dummy_pdf_basic(monkeypatch):
    page1 = DummyPDFPage(
        width=formatchecker.Page.WIDTH.value,
        height=formatchecker.Page.HEIGHT.value,
        text='This is a test.\\nReferences',
        words=[{"x0": 0, "x1": 50, "top": 55, "bottom": 60, "non_stroking_color": (0, 0, 0), "stroking_color": (0, 0, 0)}],
        images=[],
        chars=[{"fontname": "NimbusRomNo9L-Regu"}]
    )
    pdf = DummyPDF([page1])
    monkeypatch.setattr(formatchecker.pdfplumber, "open", lambda path: pdf)
    return pdf

@pytest.fixture
def dummy_pdf_multiple(monkeypatch):
    # Two pages, one wrong size, and one with margin violation
    page1 = DummyPDFPage(
        width=600, height=842, # wrong width
        text="This is the first page",
        words=[],
        images=[],
        chars=[{"fontname": "SomeFont"}, {"fontname": "NimbusRomNo9L-Regu"}]
    )
    # Simulate a left margin violation in images
    page2 = DummyPDFPage(
        width=formatchecker.Page.WIDTH.value, height=formatchecker.Page.HEIGHT.value,
        text="Second page\\nReferences", images=[{"x0": 0, "x1": 60, "top": 10, "bottom": 20}],
        words=[{"x0": 0, "x1": 10, "top": 10, "bottom": 20, "non_stroking_color": 1, "stroking_color": 1}],
        chars=[{"fontname": "NimbusRomNo9L-Regu"}, {"fontname": "NimbusRomNo9L-Regu"}],
        hyperlinks=[{"uri": "https://arxiv.org/abs/1234.56789"}]
    )
    pdf = DummyPDF([page1, page2])
    monkeypatch.setattr(formatchecker.pdfplumber, "open", lambda path: pdf)
    return pdf

@pytest.fixture(autouse=True)
def patch_termcolor(monkeypatch):
    # No color in printing (stub out)
    monkeypatch.setattr(formatchecker, "colored", lambda x, color: x)

@pytest.fixture(autouse=True)
def patch_json_dump(monkeypatch):
    # Prevent actually writing out JSON files
    monkeypatch.setattr(json, "dump", lambda obj, fp, **kwargs: None)

@pytest.fixture(autouse=True)
def patch_os_path_join(monkeypatch):
    # Always return the file name itself
    monkeypatch.setattr(os.path, "join", lambda *args: args[-1])

@pytest.fixture(autouse=True)
def patch_draw_and_save(monkeypatch):
    # Patch the image draw_rect/save
    dummy_draw_rect = lambda *args, **kwargs: None
    dummy_save = lambda *args, **kwargs: None
    class DummyImageObj:
        def draw_rect(self, *a, **kw):
            return None
        def save(self, *a, **kw):
            return None
        @property
        def original(self):
            return 255*formatchecker.np.ones((2,2), dtype=int)
    monkeypatch.setattr(DummyPDFPage, "to_image", lambda self, resolution=None: DummyImageObj())
    

def test_formatter_init():
    """Test that Formatter initializes all properties correctly"""
    fmt = formatchecker.Formatter()
    assert fmt.right_offset == 4.5
    assert fmt.left_offset == 2
    assert fmt.top_offset == 1
    assert fmt.bottom_offset == 1
    assert fmt.background_color == 255
    assert hasattr(fmt, "pdf_namecheck")


def test_format_check_all_clear(dummy_pdf_basic, monkeypatch):
    """Test format_check returns logs for a non-error PDF (all clear case)"""
    fmt = formatchecker.Formatter()
    # Also patch formatchecker.args used in check_page_margin and check_references
    monkeypatch.setattr(formatchecker, "args", Namespace(disable_bottom_check=False, disable_name_check=False))
    # Should trigger all clear path
    logs = fmt.format_check("dummy.pdf", paper_type="long", check_references=False)
    assert isinstance(logs, dict)
    assert all(isinstance(k, str) for k in logs.keys())


def test_format_check_with_errors(dummy_pdf_multiple, monkeypatch):
    """Test format_check returns logs that include errors for size, margin, font, and references"""
    fmt = formatchecker.Formatter()
    monkeypatch.setattr(formatchecker, "args", Namespace(disable_bottom_check=False, disable_name_check=True))
    # This PDF triggers size error and margin error
    logs = fmt.format_check("dummy.pdf", paper_type="long", check_references=True)
    # Should have error strings for SIZE, MARGIN, FONT (possibly)
    assert any("Size" in k for k in logs.keys())
    assert any("Margin" in k for k in logs.keys())
    assert any("Font" in k for k in logs.keys()) or any("Page Limit" in k for k in logs.keys()) or any("Bibliography" in k for k in logs.keys())


def test_check_page_size_marks_non_a4(dummy_pdf_multiple):
    """Test check_page_size logs error when page size is not A4"""
    fmt = formatchecker.Formatter()
    fmt.pdf = dummy_pdf_multiple
    fmt.logs = {}
    fmt.page_errors = set()
    fmt.logs = formatchecker.defaultdict(list)
    fmt.check_page_size()
    assert formatchecker.Error.SIZE in fmt.logs
    assert "Page #1 is not A4." in fmt.logs[formatchecker.Error.SIZE]
    assert 1 in fmt.page_errors


def test_check_page_num_limit(dummy_pdf_basic):
    """Test check_page_num does not log error if under threshold, but does above threshold"""
    fmt = formatchecker.Formatter()
    pdf = DummyPDF([DummyPDFPage(text="Hello") for _ in range(4)])
    fmt.pdf = pdf
    fmt.logs = formatchecker.defaultdict(list)
    fmt.page_errors = set()
    fmt.check_page_num("short")
    # Should not log anything since for 4 pages threshold is 5 for short
    assert not fmt.logs

    # Now test above page limit: 6 pages and 'References' in page 6
    pages = [DummyPDFPage(text="Body") for _ in range(5)] + [DummyPDFPage(text="References\nlist")]  # total 6 pages
    fmt.pdf = DummyPDF(pages)
    fmt.logs.clear()
    fmt.page_errors.clear()
    fmt.check_page_num("short")
    assert formatchecker.Error.PAGELIMIT in fmt.logs
    # There should be some reference to page 6, line 1
    assert any("page 6, line 1" in m for m in fmt.logs[formatchecker.Error.PAGELIMIT])


def test_check_page_margin_text_and_image_violations(monkeypatch):
    """Test check_page_margin logs margin errors for both text and image violations"""
    fmt = formatchecker.Formatter()
    # Simulate a PDF with one ordinary page and one margin breaking image/text
    violations = [
        DummyPDFPage(
            text="Normal",
            images=[],
            words=[],
            chars=[]
        ),
        DummyPDFPage(
            text="This is bad",
            images=[{"x0": 0, "x1": 60, "top": 10, "bottom": 20}],
            words=[{"x0":0, "x1":10, "top":10, "bottom":20, "non_stroking_color":1, "stroking_color":1}],
            chars=[]
        ),
    ]
    fmt.pdf = DummyPDF(violations)
    fmt.page_errors = set()
    fmt.number = '666'
    fmt.logs = formatchecker.defaultdict(list)
    # Patch global args used inside check_page_margin
    monkeypatch.setattr(formatchecker, "args", Namespace(disable_bottom_check=False, disable_name_check=False))
    fmt.check_page_margin("output_dir")
    assert formatchecker.Error.MARGIN in fmt.logs
    margin_msgs = fmt.logs[formatchecker.Error.MARGIN]
    assert any("image" in m.lower() or "text" in m.lower() for m in margin_msgs)


def test_check_font_logs_wrong_font():
    """Test check_font logs error when most used font is not one of the allowed set or too few matches"""
    fmt = formatchecker.Formatter()
    # Simulate a dummy PDF with odd fonts
    fmt.pdf = DummyPDF([
        DummyPDFPage(chars=[{"fontname":"NotAllowedFont"} for _ in range(100)], text="Text1"),
        DummyPDFPage(chars=[{"fontname":"AnotherFont"} for _ in range(50)], text="Text2"),
    ])
    fmt.logs = formatchecker.defaultdict(list)
    fmt.check_font()
    assert formatchecker.Error.FONT in fmt.logs
    # Should have a message about wrong font
    assert any("Wrong font" in s or "Can't find the main font" in s for s in fmt.logs[formatchecker.Error.FONT])


def test_make_name_check_config_sets_expected_keys():
    """Test make_name_check_config returns a Namespace with all expected attributes"""
    fmt = formatchecker.Formatter()
    fmt.pdfpath = "dummy.pdf"
    config = fmt.make_name_check_config()
    assert isinstance(config, Namespace)
    expected = ["file", "show_names", "whole_name", "first_name", "last_name", "ref_string", "mode", "initials"]
    for k in expected:
        assert hasattr(config, k)
    assert config.file == "dummy.pdf"
    assert config.ref_string == "References"
    assert config.mode == "ensemble"
    assert config.initials is True


def test_check_references_warnings(monkeypatch):
    """Test check_references logs appropriate warnings for missing/insufficient DOIs, too many arXiv links, too few URLs, etc."""
    fmt = formatchecker.Formatter()

    # Page with 'References', more than 10 arxiv, <3 dois, <5 links
    page1 = DummyPDFPage(
        text="References\nThis is a ref to arxiv arXiv arxiv arxiv arxiv arxiv arxiv arxiv arxiv arxiv arxiv arxiv",  # 11 'arxiv's
        hyperlinks=[{"uri": "https://arxiv.org/abs/1"}, {"uri": "https://arxiv.org/abs/2"}, {"uri": "https://doi.org/10.1234/doix"}]
    )
    fmt.pdf = DummyPDF([page1])
    fmt.logs = formatchecker.defaultdict(list)
    fmt.pdfpath = "dummy.pdf"
    # Patch PDFNameCheck.execute to not raise (and simulate name_check active)
    monkeypatch.setattr(formatchecker, "args", Namespace(disable_name_check=True, disable_bottom_check=False))
    monkeypatch.setattr(fmt.pdf_namecheck, "execute", lambda config: ["Output From NameCheck!"])  # simulate output
    fmt.make_name_check_config = lambda: Namespace(**{"file":"dummy.pdf", "show_names":False, "whole_name":False, "first_name":True, "last_name":True, "ref_string":"References", "mode":"ensemble", "initials": True})
    fmt.check_references()
    bib_msgs = fmt.logs[formatchecker.Warn.BIB]
    # Should have warnings about arxiv count, insufficient link use, and namecheck
    assert any("arxiv" in s.lower() for s in bib_msgs)
    assert any("doi" in s.lower() for s in bib_msgs)
    assert any("links found" in s or "not using paper links" in s for s in bib_msgs)
    assert any("Output From NameCheck" in s for s in bib_msgs)


def test_worker_and_main_dispatch(monkeypatch, tmp_path):
    """Test the worker function and 'main' dispatch, patching all filesystem and PDF dependencies"""
    # Patch Formatter.format_check to test worker dispatch and main
    called_with = {}
    def fake_format_check(self, submission, paper_type, **kwargs):
        called_with["submission"] = submission
        called_with["paper_type"] = paper_type
        return {"ok": True}
    monkeypatch.setattr(formatchecker.Formatter, "format_check", fake_format_check)
    
    # worker
    result = formatchecker.worker("/some/fake.pdf", "long")
    assert result == {"ok": True}
    assert called_with["submission"] == "/some/fake.pdf"
    assert called_with["paper_type"] == "long"

    # main - we need to mock sys.argv and argparse.ArgumentParser
    # We'll simulate discovery of 1 file
    fake_args = Namespace(
        submission_paths=[str(tmp_path)],
        paper_type='long',
        num_workers=1,
        disable_name_check=False,
        disable_bottom_check=False
    )
    class FakeArgParser:
        def __init__(self):
            pass
        def add_argument(self, *a, **kw):
            return None
        def parse_args(self):
            return fake_args
    # Patch walk and isfile
    monkeypatch.setattr(formatchecker, "walk", lambda path: [(str(tmp_path), [], ["test.pdf"])] )
    monkeypatch.setattr(formatchecker, "isfile", lambda p: True)
    monkeypatch.setattr(formatchecker, "join", lambda *a: str(tmp_path/"test.pdf"))
    monkeypatch.setattr(formatchecker, "tqdm", lambda x, **kw: x)
    monkeypatch.setattr(formatchecker, "argparse", types.SimpleNamespace(ArgumentParser=lambda : FakeArgParser()))
    # patch print to capture
    print_calls = []
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: print_calls.append(args))
    formatchecker.main()
    # Should have called the fake format_check
    assert any("test.pdf" in v for v in called_with.values())
    # Should print something about no pdfs only if fileset is empty; else not
