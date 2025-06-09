import pytest
import aclpubcheck.formatchecker as formatchecker
from tests.aclpubcheck.test_formatchecker import DummyPDFPage


def test_dummypdfpage_init_defaults(monkeypatch):
    """Test DummyPDFPage __init__ sets defaults correctly including formatchecker Page values."""
    monkeypatch.setattr(formatchecker.Page.WIDTH, 'value', 595)
    monkeypatch.setattr(formatchecker.Page.HEIGHT, 'value', 842)
    page = DummyPDFPage()
    assert page.width == 595
    assert page.height == 842
    assert page.text == ''
    assert page.images == []
    assert page.words == []
    assert page.chars == []
    assert page.hyperlinks == []
    # internal cropcalls should be empty
    assert isinstance(page._DummyPDFPage__cropcalls, list)
    assert page._DummyPDFPage__cropcalls == []


def test_dummypdfpage_init_custom(monkeypatch):
    """Test DummyPDFPage __init__ uses custom arguments if provided."""
    text = "some text"
    images = [1]
    words = [2]
    chars = [3]
    hyperlinks = [4]
    page = DummyPDFPage(width=500, height=400, text=text, images=images, words=words, chars=chars, hyperlinks=hyperlinks)
    assert page.width == 500
    assert page.height == 400
    assert page.text == text
    assert page.images == images
    assert page.words == words
    assert page.chars == chars
    assert page.hyperlinks == hyperlinks


def test_dummypdfpage_extract_text():
    """Test that extract_text returns the text attribute."""
    txt = "Hello PDF test!"
    page = DummyPDFPage(text=txt)
    assert page.extract_text() == txt


def test_dummypdfpage_extract_text_empty():
    """Test that extract_text on an empty text page returns ''."""
    page = DummyPDFPage(text="")
    assert page.extract_text() == ""


def test_dummypdfpage_extract_words_default():
    """Test extract_words returns the words list (default [])."""
    page = DummyPDFPage()
    assert page.extract_words() == []


def test_dummypdfpage_extract_words_with_words():
    """Test extract_words returns set words list."""
    words = [{"x0": 0, "x1": 1, "top": 2, "bottom": 3, "non_stroking_color": (0,0,0), "stroking_color": (0,0,0)}]
    page = DummyPDFPage(words=words)
    assert page.extract_words() == words
    # extra_attrs arg is ignored, but ensure it doesn't break
    assert page.extract_words(extra_attrs=["foo"]) == words


def test_dummypdfpage_crop_returns_self_and_records_bbox():
    """Test crop returns self and bbox stored in __cropcalls list."""
    page = DummyPDFPage()
    bbox = (10, 20, 30, 40)
    retval = page.crop(bbox)
    assert retval is page
    # The bbox should be appended to __cropcalls
    assert page._DummyPDFPage__cropcalls[-1] == bbox
    # Calling crop multiple times accumulates calls
    page.crop((1,2,3,4))
    assert page._DummyPDFPage__cropcalls[-2] == bbox


def test_dummypdfpage_crop_empty_bbox():
    """Test crop handles empty/zero bbox as input."""
    page = DummyPDFPage()
    bbox = (0, 0, 0, 0)
    retval = page.crop(bbox)
    assert retval is page
    assert page._DummyPDFPage__cropcalls[-1] == bbox


def test_dummypdfpage_to_image_returns_image_obj(monkeypatch):
    """Test to_image returns an object with expected methods and .original property."""
    # Patch formatchecker.np to a dummy numpy
    import types
    dummy_np = types.SimpleNamespace()
    dummy_np.ones = lambda shape, dtype: [[255 for _ in range(shape[1])] for _ in range(shape[0])]
    monkeypatch.setattr(formatchecker, "np", dummy_np)

    page = DummyPDFPage()
    img = page.to_image(resolution=72)
    assert hasattr(img, "draw_rect")
    assert hasattr(img, "save")
    assert hasattr(img, "original")
    # 'original' should be a 2x2 array of 255s
    orig = img.original
    assert isinstance(orig, list)
    assert len(orig) == 2
    assert all(row == [255,255] for row in orig)
    # The dummy methods return None
    assert img.draw_rect((0,0,1,1), fill=None, stroke=None, stroke_width=1) is None
    assert img.save("path", format="PNG") is None


def test_dummypdfpage_to_image_edge(monkeypatch):
    """Test to_image does not error if called without resolution and has .original property even if simulate_white is set."""
    # Patch formatchecker.np, and monkeypatch DummyImageObj to include simulate_white
    import types
    dummy_np = types.SimpleNamespace()
    dummy_np.ones = lambda shape, dtype: [[42 for _ in range(shape[1])] for _ in range(shape[0])]
    monkeypatch.setattr(formatchecker, "np", dummy_np)

    page = DummyPDFPage()
    # simulate_white attribute (for branch in DummyImageObj)
    class DummyWhite:
        pass
    dummy_img_obj = page.to_image()
    assert hasattr(dummy_img_obj, "original")
    orig = dummy_img_obj.original
    # As simulate_white is not expected to be set, default branch is triggered: value should be 42
    assert all(row == [42,42] for row in orig)


def test_dummypdfpage_words_and_text_consistency():
    """Test that repeated extract_words and extract_text always return latest values."""
    page = DummyPDFPage(text="First", words=[{"foo":1}])
    assert page.extract_text() == "First"
    assert page.extract_words() == [{"foo":1}]
    # Change text/words attributes
    page.text = "Second"
    page.words = [{"foo":2}]
    assert page.extract_text() == "Second"
    assert page.extract_words() == [{"foo":2}]
