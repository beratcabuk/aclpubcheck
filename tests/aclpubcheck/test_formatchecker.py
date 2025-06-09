import pytest
from types import SimpleNamespace
from collections import defaultdict
from unittest.mock import patch, MagicMock
from aclpubcheck.formatchecker import Formatter, Error, Warn, Margin, Page
import argparse

class DummyPage:
    def __init__(self, width=None, height=None, extract_text_result=None, images=None, words=None, hyperlinks=None, chars=None):
        self.width = width or Page.WIDTH.value
        self.height = height or Page.HEIGHT.value
        self.extract_text_result = extract_text_result
        self.images = images or []
        self.hyperlinks = hyperlinks or []
        self.chars = chars or []
        self._words = words or []
    def extract_text(self):
        return self.extract_text_result or ''
    def extract_words(self, extra_attrs=None):
        return self._words
    def crop(self, bbox):
        im = MagicMock()
        im.to_image.return_value.original = 255 * (1,)
        # The test can set .to_image to raise or return an object as needed
        return im
    def to_image(self, resolution=None):
        im = MagicMock()
        im.draw_rect.return_value = None
        im.save.return_value = None
        im.original = 0  # so np.mean is not 255
        return im


def make_pdf_mock(pages):
    pdf_mock = MagicMock()
    pdf_mock.pages = pages
    return pdf_mock


def test_formatter_init_sets_defaults():
    """Test Formatter.__init__ sets the expected default values."""
    f = Formatter()
    assert f.right_offset == 4.5
    assert f.left_offset == 2
    assert f.top_offset == 1
    assert f.bottom_offset == 1
    assert f.background_color == 255
    assert hasattr(f, 'pdf_namecheck')


def test_make_name_check_config_fields():
    """Test make_name_check_config returns an argparse.Namespace with correct fields."""
    f = Formatter()
    f.pdfpath = '/tmp/sample.pdf'
    cfg = f.make_name_check_config()
    assert isinstance(cfg, argparse.Namespace)
    assert cfg.file == '/tmp/sample.pdf'
    assert cfg.show_names is False
    assert cfg.whole_name is False
    assert cfg.first_name is True
    assert cfg.last_name is True
    assert cfg.ref_string == 'References'
    assert cfg.mode == 'ensemble'
    assert cfg.initials is True


def test_check_page_size_good_pages():
    """Test check_page_size does not log errors with A4-sized pages."""
    f = Formatter()
    f.logs = defaultdict(list)
    f.page_errors = set()
    f.pdf = make_pdf_mock([DummyPage() for _ in range(3)])
    f.check_page_size()
    assert Error.SIZE not in f.logs
    assert len(f.page_errors) == 0


def test_check_page_size_bad_pages():
    """Test check_page_size logs errors if page sizes are incorrect."""
    f = Formatter()
    f.logs = defaultdict(list)
    f.page_errors = set()
    pages = [DummyPage(width=Page.WIDTH.value+5, height=Page.HEIGHT.value), DummyPage(), DummyPage(height=Page.HEIGHT.value-10)]
    f.pdf = make_pdf_mock(pages)
    f.check_page_size()
    # Should log for page 1 and 3
    assert Error.SIZE in f.logs
    assert any('Page #1 is not A4.' in err for err in f.logs[Error.SIZE])
    assert any('Page #3 is not A4.' in err for err in f.logs[Error.SIZE])
    assert 1 in f.page_errors and 3 in f.page_errors


def test_check_page_margin_text_and_image_violations(monkeypatch, tmp_path):
    """Test check_page_margin logs margin errors for text and image violations."""
    # Patch args.disable_bottom_check to False, as if not set
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_bottom_check=False))
    f = Formatter()
    f.page_errors = set()
    f.logs = defaultdict(list)
    # Word in left margin violation
    words = [{
        "non_stroking_color": (10,10,10),
        "stroking_color": None,
        "x0": 0,
        "x1": 30,
        "top": 10,
        "bottom": 20,
    }]
    images = [{
        "x0": 0,
        "x1": 30,
        "top": 10,
        "bottom": 20
    }]
    page = DummyPage(words=words, images=images, extract_text_result='Some text')
    # Make crop().to_image().original be a value different from 255
    def crop_override(bbox):
        im = MagicMock()
        image_mock = MagicMock()
        image_mock.original = [0, 0, 0]
        im.to_image.return_value = image_mock
        return im
    page.crop = crop_override
    def page_to_image(resolution=None):
        im = MagicMock()
        im.draw_rect.return_value = None
        im.save.return_value = None
        im.original = [0,0,0]
        return im
    page.to_image = page_to_image
    f.pdf = make_pdf_mock([page])
    f.number = "0001"
    f.check_page_margin(str(tmp_path))
    assert Error.MARGIN in f.logs
    assert any("Text on page 1 bleeds into the left margin." in msg or "An image on page 1 bleeds into the margin." in msg for msg in f.logs[Error.MARGIN])


def test_check_page_margin_catches_parsing_errors(monkeypatch, tmp_path):
    """Test check_page_margin logs parsing errors when exception occurs."""
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_bottom_check=False))
    f = Formatter()
    f.page_errors = set()
    f.logs = defaultdict(list)
    bad_page = MagicMock()
    def raise_error(*a, **kw):
        raise Exception("Parse error!")
    bad_page.images = []
    bad_page.extract_words.side_effect = raise_error
    bad_page.crop = lambda bbox: MagicMock()
    bad_page.to_image = lambda resolution=None: MagicMock()
    f.pdf = make_pdf_mock([bad_page])
    f.number = "xyz"
    f.check_page_margin(str(tmp_path))
    assert Error.PARSING in f.logs
    assert f.page_errors == {1}


def test_check_font_correct_font():
    """Test check_font does not log errors when majority font is correct."""
    f = Formatter()
    f.logs = defaultdict(list)
    correct_font = "TimesNewRomanPSMT"
    chars = [dict(fontname=correct_font)] * 10 + [dict(fontname="WrongFont")] * 2
    page = DummyPage(chars=chars)
    f.pdf = make_pdf_mock([page])
    f.check_font()
    assert Error.FONT not in f.logs


def test_check_font_low_ratio_logs():
    """Test check_font logs error if dominant font is not used enough."""
    f = Formatter()
    f.logs = defaultdict(list)
    correct_font = "TimesNewRomanPSMT"
    # Mix of fonts, with correct below 35%
    chars = [dict(fontname=correct_font)] * 2 + [dict(fontname="WrongFont")] * 5
    page = DummyPage(chars=chars)
    f.pdf = make_pdf_mock([page])
    f.check_font()
    assert Error.FONT in f.logs
    assert any('main font' in msg for msg in f.logs[Error.FONT])


def test_check_font_wrong_font_logs():
    """Test check_font logs error if dominant font is not valid."""
    f = Formatter()
    f.logs = defaultdict(list)
    chars = [dict(fontname="NotAllowedFont")] * 10
    page = DummyPage(chars=chars)
    f.pdf = make_pdf_mock([page])
    f.check_font()
    assert Error.FONT in f.logs
    msgs = ' '.join(f.logs[Error.FONT])
    assert 'Wrong font' in msgs


def test_check_page_num_below_threshold():
    """Test check_page_num does not log errors if under page count."""
    f = Formatter()
    f.logs = defaultdict(list)
    f.page_errors = set()
    # 5 pages for 'short' type (limit is 5)
    pages = [DummyPage(extract_text_result='AAA')] * 5
    f.pdf = make_pdf_mock(pages)
    f.check_page_num("short")
    assert Error.PAGELIMIT not in f.logs


def test_check_page_num_exceeds_threshold_and_adds_log():
    """Test check_page_num logs error if marker occurs after threshold page."""
    f = Formatter()
    f.logs = defaultdict(list)
    f.page_errors = set()
    # 10 pages for 'short' type
    marks = [DummyPage(extract_text_result='Nothing') for _ in range(6)] + [DummyPage(extract_text_result='References\nMore')] + [DummyPage(extract_text_result='Nothing')]*3
    f.pdf = make_pdf_mock(marks)
    f.check_page_num("short")
    assert Error.PAGELIMIT in f.logs
    # The message should mention page 7 (after page 5 threshold)
    log_msg = f.logs[Error.PAGELIMIT][0]
    assert "page 7" in log_msg
    assert "References" in log_msg


def test_check_page_num_with_all_pages_in_page_errors():
    """Test check_page_num does not log if all pages have errors."""
    f = Formatter()
    f.logs = defaultdict(list)
    # Mark all as errored
    f.page_errors = {i+1 for i in range(10)}
    pages = [DummyPage(extract_text_result='References\nEtc')] * 10
    f.pdf = make_pdf_mock(pages)
    f.check_page_num("short")
    assert Error.PAGELIMIT not in f.logs


def test_check_references_all_warnings(monkeypatch):
    """Test check_references logs correct warnings in absence of references and links."""
    # Patch args to have disable_name_check=True
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_name_check=True))
    f = Formatter()
    f.logs = defaultdict(list)
    f.pdf_namecheck = MagicMock()
    f.pdf_namecheck.execute.return_value = ["Name check warning."]
    # Pages have no 'References', no hyperlinks
    page1 = DummyPage(extract_text_result="No references present.", hyperlinks=[])
    page2 = DummyPage(extract_text_result="Still no references.", hyperlinks=[])
    f.pdf = make_pdf_mock([page1, page2])
    f.check_references()
    # Should contain at least: not enough DOIs, not enough links, and couldn't find references
    msgs = sum((v for v in f.logs[Warn.BIB]), []) if isinstance(f.logs[Warn.BIB][0], list) else f.logs[Warn.BIB]
    flat_msgs = ' '.join(str(m) for m in msgs)
    assert "Bibliography should use ACL Anthology DOIs" in flat_msgs
    assert "not using paper links" in flat_msgs or "Only 0 links found" in flat_msgs
    assert "couldn't find any references".lower() in flat_msgs.lower()
    assert f.pdf_namecheck.execute.called


def test_check_references_found_references_with_links(monkeypatch):
    """Test check_references does not warn about missing references when present and enough links."""
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_name_check=False))
    f = Formatter()
    f.logs = defaultdict(list)
    # Page with enough DOIs and 0.2 arxiv ratio, and ref
    hyperlinks = [{'uri':"https://doi.org/10.X/1"}, {'uri':'https://doi.org/10.X/2'}, {'uri':'https://doi.org/10.X/3'}, {'uri':'https://arxiv.org/abs/1'}]
    page_text = "References\n[1]..."
    page = DummyPage(extract_text_result=page_text, hyperlinks=hyperlinks)
    f.pdf = make_pdf_mock([page])
    f.check_references()
    assert not any("couldn't find any references".lower() in m.lower() for m in f.logs[Warn.BIB])
    # Should no 'only 0 links' or 'not using paper links'
    assert not any("not using paper links" in str(m) or "Only 0 links found" in str(m) for m in f.logs[Warn.BIB])


def test_format_check_runs_all(monkeypatch, tmp_path):
    """Test format_check runs and aggregates logs when errors exist."""
    monkeypatch.setattr('aclpubcheck.formatchecker.pdfplumber.open', lambda x: make_pdf_mock([DummyPage()]))
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_name_check=True, disable_bottom_check=False))
    f = Formatter()
    # Patch all checks to inject one error
    f.check_page_size = lambda: f.logs.setdefault(Error.SIZE, []).append('error-size')
    f.check_page_margin = lambda output_dir: f.logs.setdefault(Error.MARGIN, []).append('error-margin')
    f.check_page_num = lambda paper_type: f.logs.setdefault(Error.PAGELIMIT, []).append('error-pagelimit')
    f.check_font = lambda: f.logs.setdefault(Error.FONT, []).append('error-font')
    f.check_references = lambda: f.logs.setdefault(Warn.BIB, []).append('warn-bib')
    # Patch json.dump to avoid filesystem
    with patch('aclpubcheck.formatchecker.json.dump') as json_dump:
        result = f.format_check('some/path/1234_testpaper.pdf', 'long', output_dir=str(tmp_path), print_only_errors=False, check_references=True)
        assert Error.SIZE.name in result
        assert Error.MARGIN.name in result
        assert Error.PAGELIMIT.name in result
        assert Error.FONT.name in result
        assert Warn.BIB.name in result
        assert json_dump.called


def test_format_check_returns_empty_when_no_logs(monkeypatch, tmp_path):
    """Test format_check returns empty result and prints all clear if no issues."""
    monkeypatch.setattr('aclpubcheck.formatchecker.pdfplumber.open', lambda x: make_pdf_mock([DummyPage()]))
    monkeypatch.setattr('aclpubcheck.formatchecker.json.dump', lambda *a, **kw: None)
    monkeypatch.setattr('aclpubcheck.formatchecker.args', SimpleNamespace(disable_name_check=True, disable_bottom_check=False))
    f = Formatter()
    f.check_page_size = lambda: None
    f.check_page_margin = lambda out: None
    f.check_page_num = lambda paper_type: None
    f.check_font = lambda: None
    f.check_references = lambda: None
    result = f.format_check('xx/456_testpaper.pdf', 'short', output_dir=str(tmp_path), print_only_errors=False, check_references=True)
    assert result == {}
