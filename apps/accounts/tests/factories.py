import factory

from apps.accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"usuario{n}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "Clave-Segura-2026")

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):  # noqa: N805
        if create:
            obj.save()
