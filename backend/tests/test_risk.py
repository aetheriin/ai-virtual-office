import pytest

from app.risk import idx_tick, position_size, round_price, rr


@pytest.mark.parametrize("price,tick", [(150, 1), (350, 2), (1500, 5), (4500, 10), (9000, 25)])
def test_idx_tick(price, tick):
    assert idx_tick(price) == tick


def test_round_price_idx_respects_tick():
    assert round_price(9013, "idx_stock", "down") == 9000
    assert round_price(9013, "idx_stock", "up") == 9025


def test_rr():
    assert rr(100, 90, 115) == pytest.approx(1.5)
    assert rr(100, 100, 115) == 0


def test_idx_position_size_by_risk():
    # 10jt capital, 1% risk = 100k; SL distance 100 -> 100k / (100*100) = 10 lot
    ps = position_size(capital=10_000_000, risk_pct=1, entry=9000, stop=8900, asset_class="idx_stock")
    assert ps.quantity == 10
    assert ps.max_loss == pytest.approx(100_000)


def test_idx_position_capped_by_capital():
    ps = position_size(capital=1_000_000, risk_pct=5, entry=9000, stop=8990, asset_class="idx_stock")
    assert ps.quantity == 1  # 1 lot = 900k, cannot afford 2
    assert "modal" in ps.note.lower()


def test_gold_lots_usd_account():
    # $10k, 1% = $100; SL 5 USD * 100 oz = $500/lot -> 0.2 lot
    ps = position_size(capital=10_000, risk_pct=1, entry=2400, stop=2395, asset_class="gold",
                       account_currency="USD", quote_currency="USD")
    assert ps.quantity == pytest.approx(0.2)


def test_forex_too_small_account_flags():
    ps = position_size(capital=100, risk_pct=1, entry=1.1, stop=1.09, asset_class="forex",
                       account_currency="USD", quote_currency="USD")
    assert ps.quantity == 0
    assert ps.note
