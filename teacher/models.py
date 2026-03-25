from django.db import models


# ==========================================
# CATEGORY MODEL
# ==========================================

class Category(models.Model):

    name = models.CharField(
        max_length=200,
        unique=True
    )

    position = models.PositiveIntegerField(
        default=0
    )

    moodle_category_id = models.IntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return self.name


# ==========================================
# COURSE MODEL
# ==========================================

class Course(models.Model):

    title = models.CharField(max_length=200)

    short_name = models.CharField(
        max_length=100,
        blank=True,
        unique=True
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses"
    )

    description = models.TextField(blank=True)

    course_code = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    is_published = models.BooleanField(default=True)

    start_date = models.DateField(
        blank=True,
        null=True
    )

    end_date = models.DateField(
        blank=True,
        null=True
    )

    completion_tracking = models.BooleanField(default=True)

    number_of_sections = models.PositiveIntegerField(default=10)

    image = models.ImageField(
        upload_to="course_images/",
        blank=True,
        null=True
    )

    moodle_course_id = models.IntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.short_name:
            self.short_name = self.title.replace(" ", "_")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.short_name})"


# ==========================================
# SECTION MODEL
# ==========================================

class Section(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="sections"
    )

    title = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    order = models.PositiveIntegerField(
        default=1,
        db_index=True
    )

    moodle_section_id = models.IntegerField(
        null=True,
        blank=True
    )

    moodle_section_number = models.PositiveIntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        unique_together = ("course", "order")

    def __str__(self):
        return f"{self.course.title} → Section {self.order}: {self.title}"


# ==========================================
# MODULE MODEL
# ==========================================

class Module(models.Model):

    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="modules"
    )

    title = models.CharField(max_length=255)

    type = models.CharField(
        max_length=20,
        default="video"
    )

    # Video
    video_mp4 = models.FileField(
        upload_to="videos/",
        blank=True,
        null=True
    )

    video_mpd = models.FileField(
        upload_to="dash/",
        blank=True,
        null=True
    )

    # Theory
    theory = models.TextField(
        blank=True,
        null=True
    )

    # Quiz
    quiz_question = models.TextField(
        blank=True,
        null=True
    )

    quiz_options = models.TextField(
        blank=True,
        null=True
    )

    quiz_answer = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    order = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.section.title} → {self.title}"