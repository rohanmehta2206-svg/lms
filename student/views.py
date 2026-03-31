import os
from django.http import FileResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from teacher.models import Course, Section, Module
from .models import StudentModuleProgress


# =====================================
# HELPER: FIND REAL FILE PATH SAFELY
# =====================================
def get_real_material_path(field_file):
    if not field_file:
        return None

    relative_path = str(field_file).replace("/", os.sep)

    possible_paths = [
        os.path.join(r"C:\lms_storage", relative_path),
        os.path.join(r"C:\Users\rohan\OneDrive\Documents\teacher\instructor\media", relative_path),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None


# =====================================
# HELPER: COURSE PROGRESS DATA
# =====================================
def get_course_progress_data(user, course, sections):
    module_ids = []

    for section in sections:
        module_ids.extend(section.modules.values_list("id", flat=True))

    total_modules = len(module_ids)

    completed_module_ids = set(
        StudentModuleProgress.objects.filter(
            student=user,
            module_id__in=module_ids,
            is_completed=True
        ).values_list("module_id", flat=True)
    )

    completed_modules = len(completed_module_ids)
    pending_modules = total_modules - completed_modules

    progress_percent = 0
    if total_modules > 0:
        progress_percent = int((completed_modules / total_modules) * 100)

    return {
        "total_modules": total_modules,
        "completed_modules": completed_modules,
        "pending_modules": pending_modules,
        "progress_percent": progress_percent,
        "completed_module_ids": completed_module_ids,
    }


# =====================================
# HELPER: MARK SINGLE MODULE COMPLETED
# =====================================
def complete_module_for_user(user, module):
    progress_obj, created = StudentModuleProgress.objects.get_or_create(
        student=user,
        module=module,
        defaults={
            "is_completed": True,
            "completed_at": timezone.now()
        }
    )

    if not created and not progress_obj.is_completed:
        progress_obj.is_completed = True
        progress_obj.completed_at = timezone.now()
        progress_obj.save()

    return progress_obj


# =====================================
# DASHBOARD
# =====================================
@login_required
def student_dashboard(request):
    return render(request, 'student/student_dashboard.html')


# =====================================
# MY COURSES
# =====================================
@login_required
def my_courses(request):
    courses = Course.objects.filter(is_published=True).order_by('-created_at')

    context = {
        'courses': courses
    }
    return render(request, 'student/my_courses.html', context)


# =====================================
# PROGRESS
# =====================================
@login_required
def progress_tracker(request):
    return render(request, 'student/progress.html')


# =====================================
# CERTIFICATES
# =====================================
@login_required
def certificates(request):
    return render(request, 'student/certificates.html')


# =====================================
# COURSE DETAIL
# =====================================
@login_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)
    sections = Section.objects.filter(course=course).prefetch_related('modules').order_by('order')

    progress_data = get_course_progress_data(request.user, course, sections)
    completed_module_ids = progress_data["completed_module_ids"]

    for section in sections:
        for module in section.modules.all():
            module.is_completed = module.id in completed_module_ids

    context = {
        'course': course,
        'sections': sections,
        'total_modules': progress_data["total_modules"],
        'completed_modules': progress_data["completed_modules"],
        'pending_modules': progress_data["pending_modules"],
        'progress_percent': progress_data["progress_percent"],
    }
    return render(request, 'student/course_detail.html', context)


# =====================================
# PLAY VIDEO
# =====================================
@login_required
def play_video(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='video')

    mpd_url = None
    if module.video_mpd:
        mpd_url = f"/stream/{str(module.video_mpd).replace(os.sep, '/')}"

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        'module': module,
        'course': module.section.course,
        'section': module.section,
        'mpd_url': mpd_url,
        'is_completed': is_completed,
    }
    return render(request, 'student/play_video.html', context)


# =====================================
# READ THEORY
# =====================================
@login_required
def read_theory(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='theory')

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        'module': module,
        'course': module.section.course,
        'section': module.section,
        'is_completed': is_completed,
    }
    return render(request, 'student/read_theory.html', context)


# =====================================
# TAKE QUIZ
# =====================================
@login_required
def take_quiz(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='quiz')

    if request.method == "POST":
        # For now, submitting the quiz marks this quiz module as completed.
        # Real score calculation can be added later.
        complete_module_for_user(request.user, module)
        return redirect('student:take_quiz', module_id=module.id)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        'module': module,
        'course': module.section.course,
        'section': module.section,
        'questions': module.questions.all(),
        'is_completed': is_completed,
    }
    return render(request, 'student/take_quiz.html', context)


# =====================================
# MATERIAL PAGE
# =====================================
@login_required
def material_page(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='material')

    real_file_path = get_real_material_path(module.material_file)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        'module': module,
        'course': module.section.course,
        'section': module.section,
        'material_file': f"/student/material-file/{module.id}/" if real_file_path else None,
        'is_completed': is_completed,
    }
    return render(request, 'student/material.html', context)


# =====================================
# MARK MODULE AS COMPLETED
# =====================================
@login_required
def mark_module_complete(request, module_id):
    module = get_object_or_404(Module, id=module_id)

    # Quiz should be completed only through quiz submit, not direct button
    if module.type == 'quiz':
        return redirect('student:take_quiz', module_id=module.id)

    complete_module_for_user(request.user, module)

    next_url = request.GET.get("next")

    if next_url:
        return redirect(next_url)

    return redirect("student:course_detail", course_id=module.section.course.id)


# =====================================
# SERVE MATERIAL FILE FROM LMS STORAGE
# =====================================
@login_required
def serve_material_file(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='material')

    real_file_path = get_real_material_path(module.material_file)

    if not real_file_path:
        raise Http404("Material file not found.")

    return FileResponse(open(real_file_path, "rb"), as_attachment=False)