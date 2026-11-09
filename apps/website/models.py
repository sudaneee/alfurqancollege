from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.validators import validate_image


class HeroSlide(models.Model):
    title = models.CharField(max_length=160)
    subtitle = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="slides/", blank=True, validators=[validate_image])
    static_image = models.CharField(max_length=200, blank=True, help_text="Bundled image path (used when no upload)")
    button_text = models.CharField(max_length=40, blank=True)
    button_url = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


class Post(models.Model):
    NEWS, ANNOUNCEMENT, EVENT, ADMISSION = "news", "announcement", "event", "admission"
    CATEGORY_CHOICES = [(NEWS, "News"), (ANNOUNCEMENT, "Announcement"), (EVENT, "Event"), (ADMISSION, "Admission notice")]
    AUDIENCE_CHOICES = [("public", "Everyone (website & portals)"), ("students", "Students only"),
                        ("staff", "Staff only"), ("applicants", "Applicants only")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=NEWS)
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="public")
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    image = models.ImageField(upload_to="posts/", blank=True, validators=[validate_image])
    event_date = models.DateTimeField(null=True, blank=True)
    event_venue = models.CharField(max_length=200, blank=True)
    is_published = models.BooleanField(default=True)
    is_pinned = models.BooleanField(default=False, help_text="Highlight as an important update")
    published_at = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    is_sample = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_pinned", "-published_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "post"
            slug, n = base, 2
            while Post.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("website:post_detail", args=[self.slug])

    @classmethod
    def visible(cls, audiences=("public",)):
        return cls.objects.filter(is_published=True, published_at__lte=timezone.now(), audience__in=audiences)


class Highlight(models.Model):
    """'Why choose Alfurqan' items."""

    title = models.CharField(max_length=120)
    text = models.CharField(max_length=300)
    icon = models.CharField(max_length=40, default="bi-check2-circle")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


class LeadershipMember(models.Model):
    name = models.CharField(max_length=150)
    position = models.CharField(max_length=150)
    photo = models.ImageField(upload_to="leadership/", blank=True, validators=[validate_image])
    bio = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.name} — {self.position}"


class GalleryImage(models.Model):
    title = models.CharField(max_length=150)
    image = models.ImageField(upload_to="gallery/", blank=True, validators=[validate_image])
    static_image = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.title


class ContactMessage(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=200)
    message = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    response_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} — {self.name}"
