from reactive import canal


def test_series_upgrade():
    assert canal.status_set.call_count == 0
    canal.pre_series_upgrade()
    assert canal.status_set.call_count == 1
