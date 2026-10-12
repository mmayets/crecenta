from django.template import Context, Template


def render(text, **ctx):
    return Template(text).render(Context(ctx))


def test_icono_decorativo_y_con_etiqueta():
    html = render('{% load icons %}{% icon "wallet" %}')
    assert '<use href="#i-wallet">' in html and 'aria-hidden="true"' in html
    html = render('{% load icons %}{% icon "bell" "h-6 w-6" "Alertas" %}')
    assert 'role="img"' in html and 'aria-label="Alertas"' in html and 'class="h-6 w-6"' in html


def test_filtro_de_dinero():
    assert render("{% load money %}{{ v|money }}", v="50000") == "RD$50,000.00"
    assert render('{% load money %}{{ v|money:"USD" }}', v=12) == "US$12.00"
    assert render("{% load money %}{{ v|money }}", v=None) == "—"
    assert render("{% load money %}{{ v|money }}", v="abc") == "abc"
