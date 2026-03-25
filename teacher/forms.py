from django import forms
from .models import Course, Category


class CourseForm(forms.ModelForm):

    # ==========================================
    # NUMBER OF SECTIONS
    # ==========================================

    number_of_sections = forms.IntegerField(
        min_value=1,
        max_value=50,
        initial=10,
        label="Number of Sections",
        help_text="Enter how many sections should be created automatically (Max 50).",
        widget=forms.NumberInput(attrs={"class": "form-control"})
    )

    # ==========================================
    # COURSE VISIBILITY
    # ==========================================

    is_published = forms.ChoiceField(
        choices=[
            ("True", "Show"),
            ("False", "Hide"),
        ],
        initial="True",   # 🔥 default
        label="Course Visibility",
        widget=forms.Select(attrs={"class": "form-control"})
    )

    # ==========================================
    # COMPLETION TRACKING
    # ==========================================

    completion_tracking = forms.ChoiceField(
        choices=[
            ("True", "Yes"),
            ("False", "No"),
        ],
        initial="True",   # 🔥 default
        label="Enable Completion Tracking",
        widget=forms.Select(attrs={"class": "form-control"})
    )

    class Meta:

        model = Course

        fields = [
            "title",
            "short_name",
            "category",
            "course_code",
            "is_published",
            "start_date",
            "end_date",
            "completion_tracking",
            "image",
            "description",
        ]

        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),

            # 🔥 short_name optional UI
            "short_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Auto generated if empty"
            }),

            "category": forms.Select(attrs={"class": "form-control"}),

            "course_code": forms.TextInput(attrs={"class": "form-control"}),

            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),

            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),

            "description": forms.Textarea(
                attrs={"rows": 4, "class": "form-control"}
            ),
        }

    # ==========================================
    # INITIALIZATION
    # ==========================================

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Order categories nicely
        self.fields["category"].queryset = Category.objects.all().order_by("name")

        # Better labels
        self.fields["title"].label = "Course Name"
        self.fields["short_name"].label = "Short Name"

        # 🔥 make short_name optional
        self.fields["short_name"].required = False

    # ==========================================
    # CLEAN BOOLEAN FIELDS
    # ==========================================

    def clean_is_published(self):
        return self.cleaned_data["is_published"] == "True"

    def clean_completion_tracking(self):
        return self.cleaned_data["completion_tracking"] == "True"

    # ==========================================
    # SAVE COURSE
    # ==========================================

    def save(self, commit=True):

        course = super().save(commit=False)

        # 🔥 Save number_of_sections
        course.number_of_sections = self.cleaned_data.get("number_of_sections", 10)

        if commit:
            course.save()

        return course