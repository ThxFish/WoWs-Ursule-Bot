from ursule_bot.integrations.collectors import third_party_totals


def test_third_party_totals_only_reads_explicit_counters():
    payload = {"shipInfo": [{"shipId": 1, "pvp": {"battles": 3, "xp": 900}}, {"shipId": 2, "battle_count": 2, "total_xp": 500}]}
    assert third_party_totals(payload) == {"battles": 5, "xp": 1400}
