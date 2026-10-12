import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.cache import SessionStore
from django.http import Http404, HttpResponse
from django.test import RequestFactory
from django.views.generic import TemplateView

from apps.workspaces.managers import WorkspaceScopedQuerySet
from apps.workspaces.mixins import WorkspaceRequiredMixin, workspace_required
from apps.workspaces.models import Membership, Workspace

pytestmark = pytest.mark.django_db


class SoloNegocio(WorkspaceRequiredMixin, TemplateView):
    template_name = "workspaces/dashboard.html"
    workspace_kind = "business"

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        ids = list(self.scoped(Membership).values_list("workspace_id", flat=True))
        return HttpResponse(f"{context['workspace'].pk}|{ids}")


@workspace_required(kind="personal")
def solo_personal(request, workspace):
    return HttpResponse(str(workspace.pk))


def make_request(user):
    request = RequestFactory().get("/")
    request.user = user
    request.session = SessionStore()
    return request


def test_mixin_inyecta_espacio_y_filtra(user, business_ws):
    response = SoloNegocio.as_view()(make_request(user), ws=business_ws.pk)
    assert response.content.decode() == f"{business_ws.pk}|[UUID('{business_ws.pk}')]"


def test_mixin_rechaza_tipo_distinto(user, personal_ws):
    with pytest.raises(Http404):
        SoloNegocio.as_view()(make_request(user), ws=personal_ws.pk)


def test_mixin_anonimo_redirige(business_ws):
    response = SoloNegocio.as_view()(make_request(AnonymousUser()), ws=business_ws.pk)
    assert response.status_code == 302


def test_mixin_espacio_ajeno_404(user, other_ws):
    with pytest.raises(Http404):
        SoloNegocio.as_view()(make_request(user), ws=other_ws.pk)


def test_decorador(user, personal_ws, business_ws):
    assert solo_personal(make_request(user), ws=personal_ws.pk).content.decode() == str(
        personal_ws.pk
    )
    with pytest.raises(Http404):
        solo_personal(make_request(user), ws=business_ws.pk)
    with pytest.raises(Http404):
        solo_personal(make_request(user), ws=uuid.uuid4())
    assert solo_personal(make_request(AnonymousUser()), ws=personal_ws.pk).status_code == 302


def test_for_workspace_filtra_y_exige_espacio(user, personal_ws, other_ws):
    qs = Membership.objects.all()
    assert isinstance(qs, WorkspaceScopedQuerySet)
    assert list(qs.for_workspace(personal_ws).values_list("user", flat=True)) == [user.pk]
    with pytest.raises(ValueError):
        qs.for_workspace(None)
    with pytest.raises(ValueError):
        qs.for_workspace(Workspace())


def test_for_user_anonimo(personal_ws):
    assert not Workspace.objects.for_user(AnonymousUser()).exists()
