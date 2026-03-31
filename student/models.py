from django.db import models
from django.contrib.auth.models import User
from teacher.models import Course, Module


class Student(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    moodle_user_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


class Enrollment(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    is_active = models.BooleanField(default=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.student.username} - {self.course.title} - {status}"


class StudentModuleProgress(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='student_module_progress'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'module')

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"{self.student.username} - {self.module.title} - {status}"


class QuizAttempt(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    total_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    score_percent = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - {self.score_percent}%"