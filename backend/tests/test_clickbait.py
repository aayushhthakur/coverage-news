import pytest

from app.clickbait import is_clickbait, reasons


@pytest.mark.parametrize("title,why", [
    ("Can you guess which phone is fastest?", "question bait"),
    ("Should you buy a new iPhone this year?", "question bait"),
    ("You won't believe what Apple just did", "withheld subject"),
    ("Here's why everyone is selling Nvidia", "withheld subject"),
    ("This is why the Fed will cut rates", "withheld subject"),
    ("Arsenal win again!!", "excessive punctuation"),
    ("Brighton?!", "excessive punctuation"),
    ("SHOCKING DEFEAT FOR ENGLAND at home", "excessive capitals"),
])
def test_flags(title, why):
    assert why in reasons(title)


@pytest.mark.parametrize("title", [
    "Jensen Huang resigns as Nvidia CEO",
    "Who is Colette Kress, interim Nvidia CEO?",
    "Will the Fed cut rates in December?",
    "NATO and EU leaders meet in Brussels",
    "India vs New Zealand LIVE Score, 4th ODI",
    "UK economy grows 0.7% as AI boosts output",
])
def test_does_not_flag_plain_news(title):
    assert not is_clickbait(title)
