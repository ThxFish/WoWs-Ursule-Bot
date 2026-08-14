from tracker.collectors import parse_account_balance, parse_armory_inventory


def test_parse_armory_inventory_nested_payload():
    payload = {"data": {"inventory": [{"name": "coal", "amount": 12345}, {"id": "steel", "count": 456}, {"currency": "paragon_xp", "value": 7890}, {"name": "holiday_convoy_token", "quantity": 111}, {"id": "economic_booster_t3", "count": 9}]}}
    result = parse_armory_inventory(payload)
    assert result.coal == 12345
    assert result.steel == 456
    assert result.research_points == 7890
    assert result.holiday_tokens == 111
    assert result.boosters["economic_booster_t3"] == 9


def test_parse_known_rare_booster_ids():
    payload = {"data": {"items_storage": {"4281331632": 132, "4270845872": 48, "4260360112": 151, "4249874352": 125}}}
    assert parse_armory_inventory(payload).boosters == {
        "rare_credits": 132,
        "rare_ship_xp": 48,
        "rare_commander_xp": 151,
        "rare_free_xp": 125,
    }


def test_parse_account_balance_currency_codes():
    payload = {"balance": [{"currency": "eventum_10", "value": 1200}, {"currency": "gold", "value": 2906}, {"currency": "coal", "value": 256940}, {"currency": "steel", "value": 8303}, {"currency": "paragon_xp", "value": 518}, {"currency": "free_xp", "value": 128288}, {"currency": "elite_xp", "value": 268205}]}
    result = parse_account_balance(payload)
    assert (result.holiday_tokens, result.gold, result.coal, result.steel, result.research_points) == (1200, 2906, 256940, 8303, 518)
    assert (result.free_xp, result.elite_commander_xp) == (128288, 268205)
