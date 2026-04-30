def test_repo_is_importable():
    from app.main import app
    assert app is not None
