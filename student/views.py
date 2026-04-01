import os
from django.http import FileResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages

from teacher.models import Course, Section, Module
from teacher.moodle_api import enroll_student_to_course
from .models import Enrollment, StudentModuleProgress, QuizAttempt


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
# HELPER: ENROLLMENT CHECK
# =====================================
def is_student_enrolled(user, course):
    return Enrollment.objects.filter(
        student=user,
        course=course,
        is_active=True
    ).exists()


def get_active_enrollment(user, course):
    return Enrollment.objects.filter(
        student=user,
        course=course,
        is_active=True
    ).first()


# =====================================
# HELPER: LOCK / UNLOCK MODULE FLOW
# =====================================
def get_ordered_course_modules(course):
    """
    Full course order:
    Section 1 Module 1 -> Section 1 Module 2 -> Section 2 Module 1 -> ...
    """
    return list(
        Module.objects.filter(section__course=course)
        .select_related("section", "section__course")
        .order_by("section__order", "order", "id")
    )


def get_completed_module_ids(user, course):
    course_module_ids = Module.objects.filter(
        section__course=course
    ).values_list("id", flat=True)

    return set(
        StudentModuleProgress.objects.filter(
            student=user,
            module_id__in=course_module_ids,
            is_completed=True
        ).values_list("module_id", flat=True)
    )


def get_next_unlocked_module_id(user, course):
    """
    Exact guided flow:
    - if nothing is completed -> unlock first module only
    - after each completion -> unlock next module only
    - completed modules remain accessible
    """
    ordered_modules = get_ordered_course_modules(course)
    completed_module_ids = get_completed_module_ids(user, course)

    if not ordered_modules:
        return None

    for module in ordered_modules:
        if module.id not in completed_module_ids:
            return module.id

    return None


def get_locked_module_ids(user, course):
    """
    Only one next pending module is unlocked.
    All completed modules remain open.
    All future modules remain locked.
    """
    ordered_modules = get_ordered_course_modules(course)
    completed_module_ids = get_completed_module_ids(user, course)
    next_unlocked_module_id = get_next_unlocked_module_id(user, course)

    locked_module_ids = set()

    for module in ordered_modules:
        if module.id in completed_module_ids:
            continue

        if module.id == next_unlocked_module_id:
            continue

        locked_module_ids.add(module.id)

    return locked_module_ids


def is_module_locked(user, module):
    course = module.section.course
    locked_module_ids = get_locked_module_ids(user, course)
    return module.id in locked_module_ids


# =====================================
# HELPER: COURSE ACCESS CHECK
# =====================================
def ensure_course_access(request, course):
    if not is_student_enrolled(request.user, course):
        messages.error(request, "You are not enrolled in this course.")
        return False
    return True


def ensure_module_access(request, module):
    course = module.section.course

    if not is_student_enrolled(request.user, course):
        messages.error(request, "You are not enrolled in this course.")
        return False

    if is_module_locked(request.user, module):
        messages.warning(request, "This module is locked. Please complete the current unlocked module first.")
        return False

    return True


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
# HELPER: QUIZ SCORING
# =====================================
def normalize_answer_text(value):
    return (value or "").strip().lower()


def build_quiz_result(module, post_data):
    questions = list(module.questions.all())
    total_questions = len(questions)
    correct_answers = 0

    for question in questions:
        selected_answer = (post_data.get(f"question_{question.id}") or "").strip()
        correct_answer = (question.answer or "").strip()

        question.selected_answer = selected_answer
        question.correct_answer = correct_answer
        question.is_correct = (
            normalize_answer_text(selected_answer) == normalize_answer_text(correct_answer)
            and selected_answer != ""
        )

        if question.is_correct:
            correct_answers += 1

    score_percent = 0
    if total_questions > 0:
        score_percent = int((correct_answers / total_questions) * 100)

    return {
        "questions": questions,
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "score_percent": score_percent,
    }


def save_quiz_attempt(user, module, quiz_result):
    return QuizAttempt.objects.create(
        student=user,
        module=module,
        total_questions=quiz_result["total_questions"],
        correct_answers=quiz_result["correct_answers"],
        score_percent=quiz_result["score_percent"],
    )


def get_latest_quiz_attempt(user, module):
    return QuizAttempt.objects.filter(
        student=user,
        module=module
    ).order_by("-submitted_at").first()


# =====================================
# DASHBOARD
# =====================================
@login_required
def student_dashboard(request):
    enrolled_courses_count = Enrollment.objects.filter(
        student=request.user,
        is_active=True
    ).count()

    context = {
        "enrolled_courses_count": enrolled_courses_count
    }
    return render(request, 'student/student_dashboard.html', context)


# =====================================
# ENROLL COURSE
# =====================================
@login_required
def enroll_course(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)

    existing_enrollment = Enrollment.objects.filter(
        student=request.user,
        course=course,
        is_active=True
    ).first()

    if existing_enrollment:
        messages.info(request, "You are already enrolled in this course.")
        return redirect("student:course_detail", course_id=course.id)

    student_profile = getattr(request.user, "student_profile", None)
    moodle_user_id = getattr(student_profile, "moodle_user_id", None)
    moodle_course_id = getattr(course, "moodle_course_id", None)

    if not student_profile:
        messages.error(request, "Student profile not found.")
        return redirect("student:my_courses")

    if not moodle_user_id:
        messages.error(request, "Your Moodle account is not linked yet. Please login again or contact admin.")
        return redirect("student:my_courses")

    if not moodle_course_id:
        messages.error(request, "This course is not synced with Moodle yet.")
        return redirect("student:my_courses")

    moodle_ok, moodle_error = enroll_student_to_course(
        moodle_user_id=moodle_user_id,
        moodle_course_id=moodle_course_id
    )

    if not moodle_ok:
        messages.error(request, f"Moodle enrollment failed: {moodle_error}")
        return redirect("student:my_courses")

    enrollment, created = Enrollment.objects.get_or_create(
        student=request.user,
        course=course,
        defaults={"is_active": True}
    )

    if not created and not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save(update_fields=["is_active"])

    messages.success(request, "You have enrolled in this course successfully.")
    return redirect("student:course_detail", course_id=course.id)


# =====================================
# VIEW COURSE PREVIEW
# =====================================
@login_required
def view_course(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)
    sections = list(Section.objects.filter(course=course).order_by('order'))

    for section in sections:
        section.modules_list = list(section.modules.all().order_by("order", "id"))

    already_enrolled = is_student_enrolled(request.user, course)

    context = {
        'course': course,
        'sections': sections,
        'already_enrolled': already_enrolled,
    }
    return render(request, 'student/view_course.html', context)


# =====================================
# MY COURSES
# =====================================
@login_required
def my_courses(request):
    enrollments = Enrollment.objects.filter(
        student=request.user,
        is_active=True,
        course__is_published=True
    ).select_related("course").order_by("-enrolled_at")

    enrolled_course_ids = enrollments.values_list("course_id", flat=True)

    enrolled_courses = Course.objects.filter(
        id__in=enrolled_course_ids,
        is_published=True
    ).order_by('-created_at')

    available_courses = Course.objects.filter(
        is_published=True
    ).exclude(
        id__in=enrolled_course_ids
    ).order_by('-created_at')

    context = {
        'courses': enrolled_courses,
        'available_courses': available_courses,
        'enrollments': enrollments,
    }
    return render(request, 'student/my_courses.html', context)


# =====================================
# PROGRESS
# =====================================
@login_required
def progress_tracker(request):
    enrollments = Enrollment.objects.filter(
        student=request.user,
        is_active=True,
        course__is_published=True
    ).select_related("course").order_by("-enrolled_at")

    progress_rows = []

    for enrollment in enrollments:
        course = enrollment.course
        sections = Section.objects.filter(course=course).order_by('order')
        progress_data = get_course_progress_data(request.user, course, sections)

        progress_rows.append({
            "course": course,
            "total_modules": progress_data["total_modules"],
            "completed_modules": progress_data["completed_modules"],
            "pending_modules": progress_data["pending_modules"],
            "progress_percent": progress_data["progress_percent"],
        })

    context = {
        "progress_rows": progress_rows
    }
    return render(request, 'student/progress.html', context)


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

    enrollment = get_active_enrollment(request.user, course)
    if not enrollment:
        messages.warning(request, "Please enroll in this course first.")
        return redirect("student:my_courses")

    sections = list(Section.objects.filter(course=course).order_by('order'))

    progress_data = get_course_progress_data(request.user, course, sections)
    completed_module_ids = progress_data["completed_module_ids"]
    locked_module_ids = get_locked_module_ids(request.user, course)
    next_unlocked_module_id = get_next_unlocked_module_id(request.user, course)

    for section in sections:
        ordered_modules = list(section.modules.all().order_by("order", "id"))

        for module in ordered_modules:
            module.is_completed = module.id in completed_module_ids
            module.is_locked = module.id in locked_module_ids
            module.is_available = not module.is_locked
            module.is_current = module.id == next_unlocked_module_id

            if module.type == "quiz":
                latest_attempt = get_latest_quiz_attempt(request.user, module)
                module.latest_quiz_score = latest_attempt.score_percent if latest_attempt else None
            else:
                module.latest_quiz_score = None

        section.modules_list = ordered_modules

        if not hasattr(section, "_prefetched_objects_cache"):
            section._prefetched_objects_cache = {}
        section._prefetched_objects_cache["modules"] = ordered_modules

    context = {
        'course': course,
        'sections': sections,
        'enrollment': enrollment,
        'total_modules': progress_data["total_modules"],
        'completed_modules': progress_data["completed_modules"],
        'pending_modules': progress_data["pending_modules"],
        'progress_percent': progress_data["progress_percent"],
        'next_unlocked_module_id': next_unlocked_module_id,
    }
    return render(request, 'student/course_detail.html', context)


# =====================================
# PLAY VIDEO
# =====================================
@login_required
def play_video(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='video')

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

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

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

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

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

    questions = list(module.questions.all())

    if request.method == "POST":
        if not questions:
            messages.error(request, "No quiz questions are available for this module.")
            return redirect('student:course_detail', course_id=module.section.course.id)

        quiz_result = build_quiz_result(module, request.POST)

        save_quiz_attempt(request.user, module, quiz_result)
        complete_module_for_user(request.user, module)

        messages.success(
            request,
            f"Quiz submitted successfully. Your score is {quiz_result['correct_answers']}/{quiz_result['total_questions']} ({quiz_result['score_percent']}%)."
        )

        context = {
            'module': module,
            'course': module.section.course,
            'section': module.section,
            'questions': quiz_result["questions"],
            'is_completed': True,
            'quiz_result': {
                "correct_answers": quiz_result["correct_answers"],
                "total_questions": quiz_result["total_questions"],
                "score_percent": quiz_result["score_percent"],
            },
        }
        return render(request, 'student/take_quiz.html', context)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    latest_attempt = get_latest_quiz_attempt(request.user, module)

    for question in questions:
        question.selected_answer = ""
        question.correct_answer = (question.answer or "").strip()
        question.is_correct = False

    context = {
        'module': module,
        'course': module.section.course,
        'section': module.section,
        'questions': questions,
        'is_completed': is_completed,
        'quiz_result': {
            "correct_answers": latest_attempt.correct_answers,
            "total_questions": latest_attempt.total_questions,
            "score_percent": latest_attempt.score_percent,
        } if latest_attempt else None,
    }
    return render(request, 'student/take_quiz.html', context)


# =====================================
# MATERIAL PAGE
# =====================================
@login_required
def material_page(request, module_id):
    module = get_object_or_404(Module, id=module_id, type='material')

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

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

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

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

    if not ensure_module_access(request, module):
        return redirect('student:course_detail', course_id=module.section.course.id)

    real_file_path = get_real_material_path(module.material_file)

    if not real_file_path:
        raise Http404("Material file not found.")

    return FileResponse(open(real_file_path, "rb"), as_attachment=False)