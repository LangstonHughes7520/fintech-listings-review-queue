from src.fintech_pipeline import assess_listing


def test_sensitive_listing_enters_review_queue():
    assert assess_listing("Instant credit platform", "offers instant credit") == ("review", True)


def test_plain_listing_can_follow_standard_path():
    assert assess_listing("Invoice payments", "monthly reconciliation") == ("standard", False)
