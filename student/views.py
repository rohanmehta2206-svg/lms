from django.shortcuts import render, get_object_or_404
from teacher.models import Course


def student_dashboard(request):
    return render(request, 'student/student_dashboard.html')


def my_courses(request):
    courses = Course.objects.filter(is_published=True).order_by('-created_at')

    context = {
        'courses': courses
    }
    return render(request, 'student/my_courses.html', context)


def progress_tracker(request):
    return render(request, 'student/progress.html')


def certificates(request):
    return render(request, 'student/certificates.html')


def course_detail(request, course_id=None):
    course = None

    if course_id is not None:
        course = get_object_or_404(Course, id=course_id)

    context = {
        'course': course
    }
    return render(request, 'student/course_detail.html', context)


def play_video(request):
    return render(request, 'student/play_video.html')


def read_theory(request):
    return render(request, 'student/read_theory.html')


def take_quiz(request):
    return render(request, 'student/take_quiz.html')


def material_page(request):
    return render(request, 'student/material.html')