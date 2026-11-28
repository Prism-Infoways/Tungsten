"""The page kit: bigger UI blocks (payment cards, invoices, pricing, chat...) and two new widgets."""

from __future__ import annotations

import pytest
from tungsten import Item, StatStripWidget, TransactionsWidget


@pytest.fixture()
def ui(panel):
    """Draw one ui.html macro call: ui('rating(4.5)')."""
    env = panel.renderer.env

    def draw(call: str, **ctx) -> str:
        src = '{% import "tungsten/components/ui.html" as ui %}{{ ui.' + call + ' }}'
        return str(env.from_string(src).render(**ctx))

    return draw


def test_ui_kit_page_shows_the_page_kit(admin):
    page = admin.get("/admin/ui-kit").text
    for kind in ("media-card", "payment-card", "payment-method", "stat-tile", "stat-strip", "metric", "toggle-tile",
                 "transaction", "description-list", "invoice", "profile-header", "pricing-card", "steps",
                 "copy-field", "chat-bubble", "rating", "progress-steps"):
        assert f'data-tw-ui="{kind}"' in page, kind
    assert "Page kit" in page


def test_rating_is_clamped_and_draws_half_stars(ui):
    html = ui("rating(9)")
    assert 'aria-label="5 / 5"' in html
    half = ui("rating(3.5, count=12)")
    assert "width: 50%" in half and "(12)" in half


def test_progress_steps_marks_done_and_current(ui):
    html = ui("progress_steps([{'label': 'A'}, {'label': 'B'}, {'label': 'C'}], 1)")
    assert html.count('aria-current="step"') == 1
    assert html.index('aria-current="step"') > html.index(">A<")


def test_transaction_row_signs_and_pending(ui):
    assert "+ ₹5" in ui("transaction_row('x', none, '₹5', 'in')")
    assert "− ₹5" in ui("transaction_row('x', none, '₹5', 'out')")
    assert "Pending" in ui("transaction_row('x', none, none, 'pending')")


def test_description_list_takes_pairs_and_dicts(ui):
    html = ui("description_list([('Tax', '₹1'), {'label': 'Fee', 'value': '₹2'}], '₹3')")
    assert "Tax" in html and "Fee" in html and "₹3" in html and "Total" in html


def test_payment_card_shows_only_last_four(ui):
    html = ui("payment_card('7852', 'Jack', '11/27')")
    assert "•••• •••• •••• 7852" in html and "Jack" in html


def test_copy_field_escapes_text_for_alpine(ui):
    html = ui("copy_field('a\"b', 'Code')")
    assert 'value="a&#34;b"' in html or 'value="a&quot;b"' in html
    assert "navigator.clipboard.writeText" in html


def test_toggle_tile_is_a_real_checkbox(ui):
    html = ui("toggle_tile('wifi', 'Wi-Fi', 'wifi', true)")
    assert 'type="checkbox" name="wifi"' in html and "checked" in html


def test_stat_strip_and_transactions_widgets(panel):
    class Strip(StatStripWidget):
        heading = "Referral program"

        @classmethod
        def items(cls):
            return [Item("Earnings", "₹23,980", badge="12%"), Item("Refunds", "4%", badge="1%", color="danger")]

    class Money(TransactionsWidget):
        heading = "Your transactions"

        @classmethod
        def items(cls):
            return [Item("Netflix", "₹2,500", time="27 Mar", color="danger", description="Newest"),
                    Item("Apple", "₹2,000", color="success"), Item("Webflow", color="gray")]

    for w in (Strip, Money):
        assert w.template.startswith("tungsten/widgets/")
    html = str(panel.renderer.render(Strip.template, w=Strip, entries=Strip.items(), link=None))
    assert 'data-tw-widget="stat-strip"' in html and "₹23,980" in html
    assert "Referral program" in html and "Earnings" in html
    html = str(panel.renderer.render(Money.template, w=Money, entries=Money.items(), link=None))
    assert 'data-tw-widget="transactions"' in html
    assert "Newest" in html and "− ₹2,500" in html and "+ ₹2,000" in html and "Pending" in html

    class Empty(TransactionsWidget):
        pass

    html = str(panel.renderer.render(Empty.template, w=Empty, entries=[], link=None))
    assert "Nothing here yet." in html
